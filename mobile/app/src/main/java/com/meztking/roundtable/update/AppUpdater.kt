package com.meztking.roundtable.update

import android.content.Context
import android.content.Intent
import android.content.SharedPreferences
import android.content.pm.PackageInstaller
import android.net.ConnectivityManager
import com.meztking.roundtable.BuildConfig
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.Json
import okhttp3.Interceptor
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.File
import java.io.FileOutputStream
import java.io.IOException
import java.net.SocketTimeoutException
import java.net.UnknownHostException
import java.util.concurrent.TimeUnit
import kotlin.coroutines.coroutineContext

/** What the update card and the Table's banner show. */
data class UpdateUi(
    val enabled: Boolean = true,
    val current: String = BuildConfig.VERSION_NAME,
    /** The newest phone build found on GitHub (may be this one), or null before the first check. */
    val latest: AppRelease? = null,
    val checkedAt: Long = 0,
    val checking: Boolean = false,
    val phase: Phase = Phase.IDLE,
    val done: Long = 0,
    val total: Long = -1,
    /** What went wrong, in plain words that say what to do next. */
    val error: String? = null,
    /** The version whose banner the owner closed. */
    val dismissed: String = "",
    /** The owner has seen the one line about Android's "allow installs" question. */
    val explained: Boolean = false,
) {
    val available: AppRelease? get() = latest?.takeIf { isNewerVersion(it.version, current) }
    val showBanner: Boolean get() = available != null && available?.version != dismissed

    enum class Phase { IDLE, ASK_DATA, DOWNLOADING, NEED_PERMISSION, INSTALLING }
}

/** Android's answer to a download or a check that failed, in the owner's words. */
class UpdateProblem(message: String) : IOException(message)

/**
 * The phone's own updater: finds the newest `v<version>` release of Roundtable Hold that carries the
 * phone's APK, downloads it (resuming after a cut), checks its size and SHA-256 and hands it to Android's
 * installer. One per app ([get]). The ideas, and the download and install steps, follow DSH Mobile's
 * in-app updater (InAppUpdater, ResumableDownloader, PackageInstallerGateway); see THIRD_PARTY_NOTICES.md.
 */
class AppUpdater(
    private val ctx: Context,
    private val releasesUrl: String = RELEASES_URL,
    client: OkHttpClient = OkHttpClient(),
    private val now: () -> Long = System::currentTimeMillis,
    /** The hosts a release check or a download may reach (every redirect is checked). */
    private val allowedHosts: (String) -> Boolean = ::isGitHubHost,
) {
    private val prefs: SharedPreferences = ctx.getSharedPreferences("roundtable.update", Context.MODE_PRIVATE)
    private val json = Json { ignoreUnknownKeys = true; coerceInputValues = true; explicitNulls = false }
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val checkLock = Mutex()
    private var download: Job? = null
    private var pendingApk: File? = null

    private val client: OkHttpClient = client.newBuilder()
        .connectTimeout(15, TimeUnit.SECONDS).readTimeout(30, TimeUnit.SECONDS)
        .addNetworkInterceptor(Interceptor { chain ->
            val host = chain.request().url.host
            if (!allowedHosts(host)) throw UpdateProblem("The update tried to come from $host, which isn't GitHub, so it was stopped.")
            chain.proceed(chain.request())
        })
        .build()

    private val _state = MutableStateFlow(
        UpdateUi(
            enabled = prefs.getBoolean(K_ENABLED, true),
            latest = prefs.getString(K_LATEST, null)?.let { runCatching { json.decodeFromString(AppRelease.serializer(), it) }.getOrNull() },
            checkedAt = prefs.getLong(K_CHECKED, 0),
            dismissed = prefs.getString(K_DISMISSED, "").orEmpty(),
            explained = prefs.getBoolean(K_EXPLAINED, false),
        ),
    )
    val state: StateFlow<UpdateUi> = _state.asStateFlow()

    private val dir: File get() = File(ctx.cacheDir, "updates").apply { mkdirs() }

    init {
        // a build that is now installed (or older) has done its job: free the space
        runCatching {
            dir.listFiles()?.forEach { f ->
                val v = f.name.removePrefix("RoundtableMobile-").substringBefore("-test.apk")
                if (!isNewerVersion(v, _state.value.current)) f.delete()
            }
        }
    }

    var enabled: Boolean
        get() = _state.value.enabled
        set(v) {
            prefs.edit().putBoolean(K_ENABLED, v).apply()
            _state.update { it.copy(enabled = v) }
        }

    fun dismissBanner() {
        val v = _state.value.available?.version ?: return
        prefs.edit().putString(K_DISMISSED, v).apply()
        _state.update { it.copy(dismissed = v) }
    }

    /** When the app opens: check if it's on and the last check was 4 hours ago or more. */
    fun checkOnOpen() {
        val s = _state.value
        if (!s.enabled || !checkDue(now(), s.checkedAt)) return
        // seen on the banner straight away, so the daily check doesn't announce it again
        scope.launch { runCatching { check(quiet = true)?.let { markNotified(it.version) } } }
    }

    /** "Check now" in Settings. */
    fun checkNow() { scope.launch { runCatching { check(quiet = false) } } }

    /**
     * Ask GitHub for the releases and keep the newest phone build. A quiet check (on open, in the
     * background) shows no error; a check the owner asked for does. Returns the newer release, if any.
     */
    suspend fun check(quiet: Boolean): AppRelease? = checkLock.withLock {
        _state.update { it.copy(checking = true, error = if (quiet) it.error else null) }
        try {
            val body = withContext(Dispatchers.IO) {
                val req = Request.Builder().url(releasesUrl).header("Accept", "application/vnd.github+json")
                    .header("X-GitHub-Api-Version", "2022-11-28").build()
                try {
                    client.newCall(req).execute().use { r ->
                        if (!r.isSuccessful) throw UpdateProblem(httpText(r.code, checking = true))
                        r.body?.string().orEmpty()
                    }
                } catch (e: UpdateProblem) {
                    throw e
                } catch (e: IOException) {
                    throw UpdateProblem(networkText(e, checking = true))
                }
            }
            val releases = runCatching { json.decodeFromString(ListSerializer(GhRelease.serializer()), body) }
                .getOrElse { throw UpdateProblem("GitHub's answer couldn't be read. Try again later.") }
            val latest = pickRelease(releases)
            val at = now()
            prefs.edit().putLong(K_CHECKED, at)
                .putString(K_LATEST, latest?.let { json.encodeToString(AppRelease.serializer(), it) }).apply()
            _state.update { it.copy(latest = latest, checkedAt = at, checking = false, error = null) }
            _state.value.available
        } catch (e: UpdateProblem) {
            _state.update { it.copy(checking = false, error = if (quiet) it.error else e.message) }
            if (quiet) null else throw e
        }
    }

    /** The version the last notification was about, so each new version is announced once. */
    fun shouldNotify(version: String): Boolean = prefs.getString(K_NOTIFIED, "") != version
    fun markNotified(version: String) = prefs.edit().putString(K_NOTIFIED, version).apply()

    /** The owner has read the line about Android's question. */
    fun explained() {
        prefs.edit().putBoolean(K_EXPLAINED, true).apply()
        _state.update { it.copy(explained = true) }
    }

    /** Download and install. On mobile data it asks first, unless [overMobileData]. */
    fun downloadAndInstall(overMobileData: Boolean = false) {
        val release = _state.value.available ?: return
        if (download?.isActive == true) return
        if (!overMobileData && isMetered()) {
            _state.update { it.copy(phase = UpdateUi.Phase.ASK_DATA, error = null) }
            return
        }
        explained()
        _state.update { it.copy(phase = UpdateUi.Phase.DOWNLOADING, done = 0, total = release.size, error = null) }
        download = scope.launch {
            try {
                val apk = fetch(release)
                verifyDownload(apk, release)?.let { apk.delete(); throw UpdateProblem(it) }
                withContext(Dispatchers.Main) { install(apk) }
            } catch (e: UpdateProblem) {
                fail(e.message)
            } catch (e: kotlinx.coroutines.CancellationException) {
                _state.update { it.copy(phase = UpdateUi.Phase.IDLE) }
            } catch (e: Exception) {
                fail("Something went wrong with the update (${e.message ?: e.javaClass.simpleName}). Tap Download and install to try again.")
            }
        }
    }

    fun cancelAsk() = _state.update { it.copy(phase = UpdateUi.Phase.IDLE) }

    fun cancelDownload() { download?.cancel() }

    /** Back from Android's settings: carry on if installs are now allowed. */
    fun onResumed() {
        val apk = pendingApk
        if (_state.value.phase == UpdateUi.Phase.NEED_PERMISSION && apk != null && Installer.canInstall(ctx)) install(apk)
    }

    /** Opens the "Install unknown apps" page for Roundtable Mobile. */
    fun openPermission() { runCatching { ctx.startActivity(Installer.permissionIntent(ctx)) } }

    private fun install(apk: File) {
        pendingApk = apk
        if (!Installer.canInstall(ctx)) {
            _state.update { it.copy(phase = UpdateUi.Phase.NEED_PERMISSION, error = null) }
            return
        }
        _state.update { it.copy(phase = UpdateUi.Phase.INSTALLING, error = null) }
        try {
            Installer.commit(ctx, apk)
        } catch (e: IOException) {
            fail(if (isNoSpace(e)) "Not enough space to install. Free some space, then tap Download and install again."
                else "Android couldn't start the install. Tap Download and install to try again.")
        } catch (e: SecurityException) {
            _state.update { it.copy(phase = UpdateUi.Phase.NEED_PERMISSION) }
        }
    }

    /** From [InstallReceiver]: show Android's prompt, or say what went wrong. */
    fun onInstallStatus(status: Int, message: String?, confirm: Intent?) {
        when (status) {
            PackageInstaller.STATUS_PENDING_USER_ACTION -> {
                if (confirm != null) runCatching { ctx.startActivity(confirm.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }
                    .onFailure { fail("Android's install prompt didn't open. Tap Download and install to try again.") }
            }
            PackageInstaller.STATUS_SUCCESS -> _state.update { it.copy(phase = UpdateUi.Phase.IDLE) }
            else -> {
                if (status == PackageInstaller.STATUS_FAILURE_INVALID) pendingApk?.delete()
                fail(installFailureText(status, message))
            }
        }
    }

    private fun fail(text: String?) = _state.update { it.copy(phase = UpdateUi.Phase.IDLE, error = text) }

    private fun isMetered(): Boolean = runCatching {
        (ctx.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager).isActiveNetworkMetered
    }.getOrDefault(false)

    /**
     * Fetch the APK into the cache, carrying on from a partial file when GitHub agrees (Range), and trying
     * again by itself twice after a cut. (The resume rules follow DSH Mobile's ResumableDownloader.)
     */
    internal suspend fun fetch(release: AppRelease): File = withContext(Dispatchers.IO) {
        val target = File(dir, release.apkName)
        if (target.isFile && verifyDownload(target, release) == null) return@withContext target
        target.delete()
        val part = File(dir, release.apkName + ".part")
        dir.listFiles()?.filter { it != part }?.forEach { it.delete() } // only one update kept at a time
        var attempt = 0
        while (true) {
            coroutineContext.ensureActive()
            val have = if (part.isFile) part.length() else 0L
            val need = (if (release.size > 0) release.size - have else 50L * 1024 * 1024) + 20L * 1024 * 1024
            if (dir.usableSpace in 1 until need) {
                throw UpdateProblem("Not enough space on the phone: the update needs about ${mb(need)} free. " +
                    "Free some space, then tap Download and install again.")
            }
            try {
                fetchOnce(release, part, have)
                if (!part.renameTo(target)) throw UpdateProblem("The download couldn't be saved. Tap Download and install to try again.")
                return@withContext target
            } catch (e: UpdateProblem) {
                throw e
            } catch (e: IOException) {
                if (isNoSpace(e)) throw UpdateProblem("Not enough space on the phone. Free some space, then tap Download and install again.")
                attempt++
                if (attempt > 2) throw UpdateProblem(networkText(e, checking = false))
                delay(2000L * attempt)
            }
        }
        @Suppress("UNREACHABLE_CODE") target
    }

    private suspend fun fetchOnce(release: AppRelease, part: File, have: Long) {
        val req = Request.Builder().url(release.apkUrl).header("Accept", "application/octet-stream").apply {
            if (have > 0) header("Range", "bytes=$have-")
        }.build()
        client.newCall(req).execute().use { r ->
            val append = when {
                r.code == 206 && contentRangeStart(r.header("Content-Range")) == have -> true
                r.code == 200 -> false
                r.code == 416 && release.size > 0 && have == release.size -> return
                r.code == 206 || r.code == 416 -> { part.delete(); throw IOException("range refused") }
                else -> throw UpdateProblem(httpText(r.code, checking = false))
            }
            val body = r.body ?: throw IOException("empty answer")
            val total = if (append) have + body.contentLength().coerceAtLeast(0) else body.contentLength()
            val expected = if (release.size > 0) release.size else total
            if (release.size > 0 && total > 0 && total != release.size) {
                part.delete()
                throw UpdateProblem("GitHub sent a file of the wrong size. Tap Download and install to try again.")
            }
            var done = if (append) have else 0L
            var shown = -1L
            _state.update { it.copy(done = done, total = expected) }
            FileOutputStream(part, append).use { out ->
                val input = body.byteStream()
                val buffer = ByteArray(64 * 1024)
                while (true) {
                    coroutineContext.ensureActive()
                    val read = input.read(buffer)
                    if (read < 0) break
                    out.write(buffer, 0, read)
                    done += read
                    val step = if (expected > 0) done * 100 / expected else done / (256 * 1024)
                    if (step != shown) { shown = step; _state.update { it.copy(done = done) } }
                }
                out.fd.sync()
            }
            _state.update { it.copy(done = done) }
            if (expected > 0 && done < expected) throw IOException("cut off at $done of $expected")
        }
    }

    companion object {
        private const val K_ENABLED = "enabled"
        private const val K_LATEST = "latest"
        private const val K_CHECKED = "checked_at"
        private const val K_DISMISSED = "dismissed"
        private const val K_NOTIFIED = "notified"
        private const val K_EXPLAINED = "explained"

        @Volatile private var instance: AppUpdater? = null

        fun get(ctx: Context): AppUpdater =
            instance ?: synchronized(this) { instance ?: AppUpdater(ctx.applicationContext).also { instance = it } }

        fun isGitHubHost(host: String): Boolean =
            host == "api.github.com" || host == "github.com" || host.endsWith(".githubusercontent.com")

        fun mb(bytes: Long): String = if (bytes < 1024 * 1024) "${(bytes / 1024).coerceAtLeast(1)} KB" else "%.1f MB".format(bytes / 1048576.0)

        internal fun contentRangeStart(header: String?): Long? =
            header?.trim()?.removePrefix("bytes")?.trim()?.substringBefore('-')?.trim()?.toLongOrNull()

        internal fun isNoSpace(e: Throwable): Boolean =
            generateSequence(e) { it.cause }.mapNotNull { it.message }.any { it.contains("ENOSPC") || it.contains("No space left", true) }

        internal fun networkText(e: IOException, checking: Boolean): String = when (e) {
            is UnknownHostException -> "No internet connection. Connect to Wi-Fi or mobile data, then " +
                (if (checking) "tap Check now." else "tap Download and install again.")
            is SocketTimeoutException -> if (checking) "GitHub didn't answer in time. Tap Check now to try again."
                else "The download was cut off. Tap Download and install to carry on from where it stopped."
            else -> if (checking) "Couldn't reach GitHub. Check the internet connection and tap Check now."
                else "The download was cut off. Tap Download and install to carry on from where it stopped."
        }

        internal fun httpText(code: Int, checking: Boolean): String = when (code) {
            403, 429 -> "GitHub is busy right now. Try again in a few minutes."
            404 -> if (checking) "No releases found on GitHub yet. Try again later." else "The update file isn't on GitHub any more. Tap Check now."
            in 500..599 -> "GitHub is having trouble right now. Try again in a few minutes."
            else -> "GitHub answered with an error ($code). Try again later."
        }
    }
}
