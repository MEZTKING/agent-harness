package com.meztking.roundtable.runtime

import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.File
import java.io.InputStream
import java.net.Proxy
import java.util.concurrent.TimeUnit
import com.meztking.roundtable.Brand

/** Where Roundtable on this phone stands, for the screens and the notification. */
sealed interface RuntimeState {
    /** Nothing installed yet. */
    data object NotInstalled : RuntimeState
    data object Checking : RuntimeState
    data class Downloading(val done: Long, val total: Long) : RuntimeState
    data object Verifying : RuntimeState
    data class Unpacking(val entries: Int, val totalEntries: Int) : RuntimeState
    data class Stopped(val record: InstalledRecord) : RuntimeState
    data class Starting(val record: InstalledRecord) : RuntimeState
    data class Running(val record: InstalledRecord, val port: Int) : RuntimeState
    data object Stopping : RuntimeState
    data class Failed(val failure: RuntimeFailure, val record: InstalledRecord?) : RuntimeState

    val busy: Boolean get() = this is Checking || this is Downloading || this is Verifying || this is Unpacking || this is Starting || this is Stopping

    /** The foreground service covers these (an install, a start, a running Roundtable). */
    val needsService: Boolean get() = this is Downloading || this is Verifying || this is Unpacking || this is Starting || this is Running
}

/**
 * Sets up, starts and stops Roundtable on this phone. One per app process ([com.meztking.roundtable.RoundtableApp]).
 *
 * The launch token lives in memory only: it is made at each start, handed to Roundtable in its environment
 * ([ProotCommand]) and to the app's own "This phone" client ([token]); it is never written down or logged.
 */
class RuntimeController(
    private val layout: RuntimeLayout,
    private val installer: RuntimeInstaller,
    private val supervisor: HarnessSupervisor,
    private val log: RotatingLog,
    private val fs: FsOps,
    private val nativeLibraryDir: () -> File,
    private val dnsServers: () -> List<String>,
    private val cpuCount: () -> Int,
    private val scope: CoroutineScope,
    private val onActive: () -> Unit = {},
    private val inherited: () -> Set<String> = { System.getenv().keys },
    private val health: OkHttpClient = localHealthClient(),
    /** The owner's choices handed to Roundtable at each start ([ProotCommand.Inputs.extra]). */
    private val extraEnv: () -> Map<String, String> = { emptyMap() },
) {
    private val _state = MutableStateFlow<RuntimeState>(installer.installed()?.let { RuntimeState.Stopped(it) } ?: RuntimeState.NotInstalled)
    val state: StateFlow<RuntimeState> = _state.asStateFlow()

    /** The last check, so set-up can show the size and ask about mobile data before downloading. */
    @Volatile var lastCheck: RuntimeInstaller.CheckResult? = null
        private set

    @Volatile private var launchToken: String? = null
    @Volatile private var port: Int = FreePort.DEFAULT
    private var job: Job? = null

    val installed: InstalledRecord? get() = installer.installed()

    /** Fetch and check the newest download's description (small; no layer is fetched). */
    suspend fun check(): RuntimeInstaller.CheckResult {
        val before = _state.value
        _state.value = RuntimeState.Checking
        val result = installer.check()
        lastCheck = result
        _state.value = when (result) {
            is RuntimeInstaller.CheckResult.Refused -> RuntimeState.Failed(result.failure, installer.installed())
            else -> if (before is RuntimeState.Running) before else installer.installed()?.let { RuntimeState.Stopped(it) } ?: RuntimeState.NotInstalled
        }
        return result
    }

    /** Bytes still to download (less what a cut download already has), or null before a check. */
    fun remainingBytes(): Long? = (lastCheck as? RuntimeInstaller.CheckResult.Available)?.let { installer.remainingBytes(it) }

    /** Download, check and unpack (resuming a cut download), then start. */
    fun install() {
        if (_state.value.busy) return
        job = scope.launch {
            try {
                val result = (lastCheck as? RuntimeInstaller.CheckResult.Available) ?: check()
                val available = when (result) {
                    is RuntimeInstaller.CheckResult.Available -> result
                    is RuntimeInstaller.CheckResult.UpToDate -> { startNow(); return@launch }
                    is RuntimeInstaller.CheckResult.Refused -> return@launch
                }
                _state.value = RuntimeState.Downloading(0, available.downloadBytes)
                onActive()
                var fetchedBefore = 0L
                var lastLayer = -1
                installer.apply(available.manifest, available.decision, onEvent = { e ->
                    _state.value = when (e) {
                        InstallEvent.Checking -> RuntimeState.Checking
                        is InstallEvent.Downloading -> {
                            if (e.progress.index != lastLayer) {
                                fetchedBefore = available.decision.layers.take(e.progress.index).sumOf { it.size }
                                lastLayer = e.progress.index
                            }
                            RuntimeState.Downloading(fetchedBefore + e.progress.done, available.downloadBytes)
                        }
                        is InstallEvent.Verifying -> RuntimeState.Verifying
                        is InstallEvent.Unpacking -> RuntimeState.Unpacking(e.progress.entries, available.decision.layers.sumOf { it.entries })
                    }
                }, beforeCommit = { stopNow() })
                lastCheck = null
                startNow()
            } catch (e: CancellationException) {
                _state.value = installer.installed()?.let { RuntimeState.Stopped(it) } ?: RuntimeState.NotInstalled
                throw e
            } catch (e: InstallException) {
                _state.value = RuntimeState.Failed(e.failure, installer.installed())
            } catch (e: DownloadException) {
                _state.value = RuntimeState.Failed(e.failure, installer.installed())
            } catch (e: Exception) {
                _state.value = RuntimeState.Failed(RuntimeFailure.Storage(e.message ?: e.javaClass.simpleName), installer.installed())
            }
        }
    }

    /** Stop a download or unpack in progress; a cut download carries on next time. */
    fun cancel() {
        job?.cancel()
    }

    fun start() {
        val s = _state.value
        if (s.busy || s is RuntimeState.Running) return
        val record = installer.installed() ?: return
        // Set synchronously, so a call made right after this one waits for the start ([token]).
        _state.value = RuntimeState.Starting(record)
        job = scope.launch { startNow() }
    }

    /** Start it when it is installed and neither running nor on its way. */
    fun startIfNeeded() {
        val s = _state.value
        if (s is RuntimeState.Stopped || (s is RuntimeState.Failed && s.record != null)) start()
    }

    fun stop() {
        job = scope.launch { stopNow(); installer.installed()?.let { _state.value = RuntimeState.Stopped(it) } }
    }

    fun restart() {
        job = scope.launch {
            stopNow()
            startNow()
        }
    }

    /** Remove the Linux files. [keepProjects] keeps the projects and Roundtable's own settings (keys included). */
    fun remove(keepProjects: Boolean) {
        job = scope.launch {
            stopNow()
            withContext(Dispatchers.IO) { installer.uninstall(keepUserData = keepProjects) }
            lastCheck = null
            _state.value = RuntimeState.NotInstalled
        }
    }

    /** The port Roundtable listens on while it runs. */
    fun port(): Int = port

    /**
     * The current launch token, waiting for a start in progress. Throws [NotRunningException] when Roundtable
     * on this phone is not running and not starting.
     */
    suspend fun token(): String {
        val s = _state.value
        if (s is RuntimeState.Running) launchToken?.let { return it }
        if (s is RuntimeState.Starting) {
            val done = withTimeoutOrNull(START_WAIT_MS) { _state.first { it !is RuntimeState.Starting } }
            if (done is RuntimeState.Running) launchToken?.let { return it }
        }
        throw NotRunningException()
    }

    fun logTail(lines: Int = 200): String = runCatching { log.tail(lines) }.getOrDefault("")

    /** Bytes used on the phone: the Linux files, Roundtable's home and the projects. */
    suspend fun storageUsed(): Long = withContext(Dispatchers.IO) { runCatching { FsTree.size(fs, layout.root) }.getOrDefault(0L) }

    suspend fun projectsSize(): Long = withContext(Dispatchers.IO) { runCatching { FsTree.size(fs, layout.workspaces) }.getOrDefault(0L) }

    private suspend fun startNow() {
        val record = installer.installed() ?: run { _state.value = RuntimeState.NotInstalled; return }
        _state.value = RuntimeState.Starting(record)
        onActive()
        val outcome = try {
            withContext(Dispatchers.IO) {
                runCatching { supervisor.cleanupStale() }
                layout.home.mkdirs(); layout.workspaces.mkdirs(); layout.run.mkdirs(); layout.prootTmp.mkdirs()
                File(layout.run, ProotCommand.GENERATED_RESOLV).writeText(ProotCommand.resolvConf(dnsServers()))
                val shipped = record.fakeProc.firstOrNull { it.target == "/proc/stat" }
                    ?.let { File(File(layout.root, record.base.dir), it.source.removePrefix("/")) }?.takeIf { it.isFile }?.readText()
                File(layout.run, ProotCommand.GENERATED_PROC_STAT).writeText(ProotCommand.procStat(shipped, cpuCount()))
                port = FreePort.pick()
                val token = LaunchToken.next()
                launchToken = token
                val command = ProotCommand.build(ProotCommand.Inputs(nativeLibraryDir(), layout, record, port, token, inherited(), extraEnv()))
                supervisor.start(
                    command, layout.root, isReady = { healthy(port, record.healthPath) }, requestedPort = port, secrets = listOf(token),
                    readinessPrefix = record.readinessPrefix,
                ) { code, _ ->
                    launchToken = null
                    _state.value = RuntimeState.Failed(RuntimeFailure.StartFailed("it stopped by itself, code $code"), installer.installed())
                }
            }
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            HarnessSupervisor.StartOutcome.LaunchFailed(e.message ?: e.javaClass.simpleName)
        }
        _state.value = when (outcome) {
            is HarnessSupervisor.StartOutcome.Ready -> RuntimeState.Running(record, outcome.port)
            is HarnessSupervisor.StartOutcome.Exited -> fail(record, "it closed straight away, code ${outcome.exitCode}")
            is HarnessSupervisor.StartOutcome.TimedOut -> fail(record, "no answer after four minutes")
            is HarnessSupervisor.StartOutcome.LaunchFailed -> fail(record, outcome.detail)
        }
    }

    private fun fail(record: InstalledRecord, detail: String): RuntimeState {
        launchToken = null
        return RuntimeState.Failed(RuntimeFailure.StartFailed(detail), record)
    }

    private suspend fun stopNow() {
        if (!supervisor.isRunning) return
        _state.value = RuntimeState.Stopping
        launchToken = null
        runCatching { supervisor.stop() }
    }

    private suspend fun healthy(port: Int, path: String): Boolean = withContext(Dispatchers.IO) {
        runCatching {
            health.newCall(Request.Builder().url("http://127.0.0.1:$port$path").build()).execute().use { it.isSuccessful }
        }.getOrDefault(false)
    }

    class NotRunningException : java.io.IOException("${Brand.NAME} on this phone isn't running. Open Settings, Harness on this phone, and press Start.")

    companion object {
        const val START_WAIT_MS = 240_000L

        fun localHealthClient(): OkHttpClient = OkHttpClient.Builder()
            .proxy(Proxy.NO_PROXY)
            .connectTimeout(1, TimeUnit.SECONDS)
            .readTimeout(2, TimeUnit.SECONDS)
            .build()

        /** Everything wired for the device. */
        fun create(
            context: android.content.Context, scope: CoroutineScope = CoroutineScope(SupervisorJob() + Dispatchers.Default),
            extraEnv: () -> Map<String, String> = { emptyMap() }, onActive: () -> Unit,
        ): RuntimeController {
            val system = AndroidRuntimeSystem(context)
            val layout = RuntimeLayout(File(context.noBackupFilesDir, "runtime"), File(context.cacheDir, "runtime"))
            val client = OkHttpClient.Builder().connectTimeout(15, TimeUnit.SECONDS).readTimeout(60, TimeUnit.SECONDS).build()
            val verifier = ManifestVerifier(
                ManifestVerifier.decodeKeys(com.meztking.roundtable.BuildConfig.RUNTIME_TEST_KEY, com.meztking.roundtable.BuildConfig.RUNTIME_RELEASE_KEY),
            )
            val finder = ReleaseFinder(client, com.meztking.roundtable.BuildConfig.RUNTIME_REPO)
            val installer = RuntimeInstaller(
                layout, InstalledStore(layout), AndroidFsOps, client, LayerDownloader(client, layout.downloads), system.space,
                source = { finder.latest() },
                appVersion = { com.meztking.roundtable.BuildConfig.VERSION_NAME },
                deviceAbis = system.deviceAbis,
                verifier = verifier,
                allowTest = com.meztking.roundtable.BuildConfig.RUNTIME_ALLOW_TEST,
                decoder = ::xz,
            )
            val log = RotatingLog(File(layout.logs, "roundtable.log"))
            val supervisor = HarnessSupervisor(scope, JvmProcessLauncher, AndroidProcessTable, log)
            return RuntimeController(
                layout, installer, supervisor, log, AndroidFsOps,
                nativeLibraryDir = { system.nativeLibraryDir }, dnsServers = system::dnsServers, cpuCount = { system.cpuCount },
                scope = scope, onActive = onActive, extraEnv = extraEnv,
            )
        }

        fun xz(input: InputStream): InputStream = org.tukaani.xz.XZInputStream(input)
    }
}
