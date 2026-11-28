package com.meztking.roundtable

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.verticalScroll
import androidx.compose.ui.unit.dp
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.MenuBook
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.TripOrigin
import androidx.compose.material3.Badge
import androidx.compose.material3.BadgedBox
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.core.content.ContextCompat
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.NavHostController
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import com.meztking.roundtable.data.Mode
import com.meztking.roundtable.ui.GalleryScreen
import com.meztking.roundtable.ui.LettersScreen
import com.meztking.roundtable.ui.NotesScreen
import com.meztking.roundtable.ui.MainViewModel
import com.meztking.roundtable.ui.ProjectActions
import com.meztking.roundtable.ui.ProjectScreen
import com.meztking.roundtable.ui.ProjectUi
import com.meztking.roundtable.ui.ProjectViewModel
import com.meztking.roundtable.ui.HarnessScreen
import com.meztking.roundtable.ui.ConnectionsScreen
import com.meztking.roundtable.ui.SharedSettingsContent
import com.meztking.roundtable.ui.SharedSettingsViewModel
import com.meztking.roundtable.ui.ProjectSettingsContent
import com.meztking.roundtable.ui.ProjectSettingsViewModel
import com.meztking.roundtable.ui.SettingsScreen
import com.meztking.roundtable.ui.ThisPhoneSetupScreen
import com.meztking.roundtable.ui.SetupScreen
import com.meztking.roundtable.ui.TableScreen
import com.meztking.roundtable.ui.NewIdeaScreen
import com.meztking.roundtable.ui.FilesScreen
import com.meztking.roundtable.ui.ApiFiles
import com.meztking.roundtable.ui.SearchScreen
import com.meztking.roundtable.ui.composerSender
import com.meztking.roundtable.ui.ComfortScreen
import com.meztking.roundtable.ui.NeedsList
import com.meztking.roundtable.ui.TablePins
import com.meztking.roundtable.ui.adaptive.AdaptiveShell
import com.meztking.roundtable.ui.adaptive.LocalShellPlan
import com.meztking.roundtable.ui.adaptive.ShellPlace
import com.meztking.roundtable.data.Comfort
import com.meztking.roundtable.ui.theme.Hall
import com.meztking.roundtable.ui.theme.RoundtableTheme
import com.meztking.roundtable.ui.theme.hallBackground
import com.meztking.roundtable.update.AppUpdater
import com.meztking.roundtable.work.Watch
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.map
import androidx.compose.runtime.CompositionLocalProvider
import androidx.window.layout.FoldingFeature
import androidx.window.layout.WindowInfoTracker
import com.meztking.roundtable.data.FailureAction
import com.meztking.roundtable.data.browser.BrowserConnection
import com.meztking.roundtable.data.browser.mentionedLocalAddresses
import com.meztking.roundtable.ui.LocalFailureActions
import com.meztking.roundtable.ui.adaptive.Hinge
import com.meztking.roundtable.ui.adaptive.HingeSource
import com.meztking.roundtable.ui.adaptive.LocalHingeSource
import com.meztking.roundtable.ui.adaptive.rememberFolded
import com.meztking.roundtable.ui.browser.BrowserScreen
import com.meztking.roundtable.ui.browser.ProvideBrowserTab

class MainActivity : ComponentActivity() {
    /** A project to open, from a tapped notification. */
    private val openProject = MutableStateFlow<String?>(null)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        if (savedInstanceState == null) openProject.value = intent?.getStringExtra(Watch.EXTRA_PROJECT)
        // the window's folds, from Jetpack WindowManager (a foldable opened like a book splits the shell there)
        val hinges = HingeSource {
            WindowInfoTracker.getOrCreate(this).windowLayoutInfo(this).map { info ->
                info.displayFeatures.filterIsInstance<FoldingFeature>().map { f ->
                    Hinge(vertical = f.orientation == FoldingFeature.Orientation.VERTICAL,
                        halfOpen = f.state == FoldingFeature.State.HALF_OPENED, separating = f.isSeparating)
                }
            }
        }
        setContent {
            RoundtableTheme {
                CompositionLocalProvider(LocalHingeSource provides hinges) { Root(openProject) }
            }
        }
    }

    override fun onStart() {
        super.onStart()
        runCatching { AppUpdater.get(this).checkOnOpen() } // at most every 4 hours
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        openProject.value = intent.getStringExtra(Watch.EXTRA_PROJECT)
    }
}

@Composable
private fun Root(openProject: MutableStateFlow<String?>) {
    val ctx = LocalContext.current
    val app = ctx.applicationContext as RoundtableApp
    val nav = rememberNavController()
    val start = remember { if (app.store.configured) "home" else "setup" }
    val main: MainViewModel = viewModel()
    val pending by openProject.collectAsState()
    LaunchedEffect(pending) {
        val p = pending ?: return@LaunchedEffect
        if (app.store.configured) nav.navigate("project/${android.net.Uri.encode(p)}")
        openProject.value = null
    }
    // a failure's button does what it says (pair again, a new key, the phone's clock), wherever it shows
    val failureActions: (FailureAction) -> Boolean = { a ->
        when (a) {
            FailureAction.PAIR_AGAIN -> { nav.navigate("setup"); true }
            FailureAction.NEW_KEY, FailureAction.FIX_KEY_ACCESS, FailureAction.CHECK_REPO -> { nav.navigate("connect"); true }
            FailureAction.RESTART_PHONE -> { nav.navigate("harness"); true }
            FailureAction.CHECK_TIME -> runCatching { ctx.startActivity(Intent(android.provider.Settings.ACTION_DATE_SETTINGS)) }.isSuccess
            else -> false
        }
    }
    Box(Modifier.fillMaxSize().hallBackground()) {
      CompositionLocalProvider(LocalFailureActions provides failureActions) {
      // a local address an agent printed opens in the Browser tab (DS-81), anything else in the phone's browser
      ProvideBrowserTab({ u -> nav.navigate("browser?url=" + android.net.Uri.encode(u)) }) {
        NavHost(nav, startDestination = start) {
            composable("browser?url={url}", arguments = listOf(navArgument("url") { type = NavType.StringType; nullable = true; defaultValue = null })) { entry ->
                val hall by main.hall.collectAsState()
                val connection = remember(hall.data) { browserConnection(app) }
                val texts = hall.data?.seats.orEmpty().flatMap { listOf(it.statusText, it.leftOff) + it.nextSteps }
                BrowserScreen(entry.arguments?.getString("url"), connection, mentionedLocalAddresses(texts),
                    onBack = { nav.popBackStack() })
            }
            composable("setup") {
                SetupScreen(onDone = {
                    main.reset()
                    nav.navigate("home") { popUpTo(0) { inclusive = true } }
                }, onBack = null, onThisPhone = { nav.navigate("thisphone") })
            }
            composable("connect") {
                SetupScreen(onDone = { main.reset(); nav.popBackStack() }, onBack = { nav.popBackStack() },
                    onThisPhone = { nav.navigate("thisphone") })
            }
            composable("thisphone") {
                ThisPhoneSetupScreen(onDone = {
                    main.reset()
                    nav.navigate("home") { popUpTo(0) { inclusive = true } }
                }, onBack = { nav.popBackStack() })
            }
            composable("connections") {
                ConnectionsScreen(onBack = { nav.popBackStack() }, onPhoneSetup = { nav.navigate("thisphone") }, onHarness = { nav.navigate("harness") },
                    onHub = { nav.navigate("connect") }, onChanged = {
                        if (!app.store.configured) nav.navigate("setup") { popUpTo(0) { inclusive = true } } else main.reset()
                    })
            }
            composable("shared") {
                val vm: SharedSettingsViewModel = viewModel()
                LaunchedEffect(Unit) { vm.load() }
                val st by vm.settings.collectAsState()
                val from by vm.from.collectAsState()
                val saving by vm.saving.collectAsState()
                Snacked(vm.notice.collectAsState().value, vm::noticeShown) {
                    SharedSettingsContent(st, from, saving, onBack = { nav.popBackStack() }, onRefresh = vm::load, onSave = vm::save)
                }
            }
            composable("projectsettings/{id}", arguments = listOf(navArgument("id") { type = NavType.StringType })) {
                val vm: ProjectSettingsViewModel = viewModel()
                val hall by main.hall.collectAsState()
                val seat = hall.data?.seats?.firstOrNull { it.id == vm.id }
                LaunchedEffect(vm.id) { vm.start(seat) }
                val view by vm.view.collectAsState()
                val saving by vm.saving.collectAsState()
                Snacked(vm.notice.collectAsState().value, vm::noticeShown) {
                    ProjectSettingsContent(vm.id, view, saving, onBack = { nav.popBackStack() }, onRefresh = vm::load, onSave = vm::save)
                }
            }
            composable("comfort") { ComfortScreen(Comfort.get(ctx), onBack = { nav.popBackStack() }) }
            composable("harness") { HarnessScreen(onBack = { nav.popBackStack() }, onSetUp = { nav.navigate("thisphone") }) }
            composable("home") { Home(main, nav) }
            composable("notes") { NotesScreen(onBack = { nav.popBackStack() }) }
            composable("gallery") {
                // everything finished, and what Roundtable can make; read from the PC (or this phone's Roundtable)
                GalleryScreen(onBack = { nav.popBackStack() }, onOpenProject = { path ->
                    val seat = main.hall.value.data?.seats?.firstOrNull { it.path == path }
                    if (seat != null) nav.navigate("project/${android.net.Uri.encode(seat.id)}")
                }, onStart = { _, _ -> nav.navigate("newidea") })
            }
            composable("newidea") {
                NewIdeaScreen(onBack = { nav.popBackStack() }, onStarted = { _ -> nav.popBackStack(); main.reset() })
            }
            composable("files/{id}", arguments = listOf(navArgument("id") { type = NavType.StringType })) { entry ->
                val id = entry.arguments?.getString("id").orEmpty()
                val hall by main.hall.collectAsState()
                val seat = hall.data?.seats?.firstOrNull { it.id == id }
                val api = remember(seat) { machineApi(app, seat) }
                FilesScreen(title = id, source = api?.let { a -> seat?.path?.let { ApiFiles(a, it) } },
                    elsewhere = "These files are on your PC. Connect this phone to it (Settings, Your PC) to see them.",
                    onBack = { nav.popBackStack() })
            }
            composable(
                "project/{id}?tab={tab}",
                arguments = listOf(navArgument("id") { type = NavType.StringType }, navArgument("tab") { type = NavType.IntType; defaultValue = 0 }),
            ) { entry ->
                val vm: ProjectViewModel = viewModel()
                val hall by main.hall.collectAsState()
                val seat = hall.data?.seats?.firstOrNull { it.id == vm.id }
                LaunchedEffect(vm.id, seat) { vm.start(seat) }
                val status by vm.status.collectAsState()
                val plan by vm.plan.collectAsState()
                val inbox by vm.inbox.collectAsState()
                val sent by vm.sent.collectAsState()
                val asks by vm.asks.collectAsState()
                val live by vm.live.collectAsState()
                val notice by vm.notice.collectAsState()
                val snack = remember { SnackbarHostState() }
                LaunchedEffect(notice) { notice?.let { snack.showSnackbar(it); vm.noticeShown() } }
                val backend = app.backend()
                Scaffold(containerColor = Color.Transparent, snackbarHost = { SnackbarHost(snack) }) { pad ->
                    Box(Modifier.padding(pad)) {
                        ProjectScreen(
                            ProjectUi(vm.id, seat, backend?.modeFor(seat), backend?.identity ?: app.store.identity, status, plan, inbox, sent, asks, live),
                            ProjectActions(
                                back = { nav.popBackStack() }, refresh = vm::refresh, command = vm::command, act = vm::act,
                                opened = vm::opened, reply = vm::reply, send = vm::send, answer = vm::answer,
                                settings = if (seat?.holder?.isNotBlank() == true) ({ nav.navigate("projectsettings/${android.net.Uri.encode(vm.id)}") }) else null,
                                files = { nav.navigate("files/${android.net.Uri.encode(vm.id)}") },
                                composer = remember(seat) { machineApi(app, seat)?.let { composerSender(it) } },
                                path = seat?.path,
                                machine = remember(seat) { machineApi(app, seat) },
                            ),
                            initialTab = entry.arguments?.getInt("tab") ?: 0,
                        )
                    }
                }
            }
        }
      }
      }
    }
}

/** What `localhost` means in the Browser tab: this phone, the paired PC, or nothing known (Hub mode). */
private fun browserConnection(app: RoundtableApp): BrowserConnection {
    if (app.usingThisPhone()) return BrowserConnection.ThisPhone
    val pc = app.backend()?.parts?.values?.firstNotNullOfOrNull { it as? com.meztking.roundtable.data.PcBackend }
    return pc?.api?.let { BrowserConnection.Pc(it.activeHost, it.link.port) } ?: BrowserConnection.Hub
}

@Composable
private fun Home(main: MainViewModel, nav: NavHostController) {
    val ctx = LocalContext.current
    val app = ctx.applicationContext as RoundtableApp
    var tab by rememberSaveable { mutableIntStateOf(0) }
    var showNeeds by rememberSaveable { mutableStateOf(false) }
    var searching by rememberSaveable { mutableStateOf(false) }
    val hall by main.hall.collectAsState()
    val letters by main.letters.collectAsState()
    val busy by main.busy.collectAsState()
    val notice by main.notice.collectAsState()
    val crash by main.crash.collectAsState()
    val snack = remember { SnackbarHostState() }
    var settingsTick by remember { mutableIntStateOf(0) }
    val backend = remember(settingsTick) { app.backend() }

    LaunchedEffect(notice) { notice?.let { snack.showSnackbar(it); main.noticeShown() } }
    // This phone: start Roundtable here first, so the Table's first load waits for it
    LaunchedEffect(backend) { if (app.usingThisPhone()) app.runtime.startIfNeeded() }
    // while the app is open, the Table keeps itself fresh: often when a machine answers, gently through the hub
    LaunchedEffect(backend, crash) {
        if (backend == null || crash != null) return@LaunchedEffect
        while (true) {
            kotlinx.coroutines.delay(if (backend.connected.any { it != com.meztking.roundtable.data.Source.HUB }) 30_000 else 120_000)
            main.refresh()
        }
    }
    LaunchedEffect(backend, crash) { if (backend != null && crash == null) main.refresh() }
    LaunchedEffect(tab, backend) { if (tab == 1 && backend != null && letters.data == null) main.loadLetters() }

    // ask once for notifications (Android 13+)
    val ask = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { }
    LaunchedEffect(Unit) {
        if (Build.VERSION.SDK_INT >= 33 && ContextCompat.checkSelfPermission(ctx, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            ask.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
    }

    val identity = backend?.identity ?: app.store.identity
    val needCount = hall.data?.needs?.size ?: 0
    val myUnread = hall.data?.seats?.firstOrNull { it.id == identity }?.unread ?: 0
    val where = remember(hall.data, backend) { whereLabel(backend) }
    val comfort = remember(ctx) { Comfort.get(ctx) }
    val pins = TablePins(comfort.pinned, comfort.putAway, pin = comfort::pin, putAway = comfort::putAwayProject,
        order = comfort.order, reorder = comfort::reorder)
    val openNeed: (com.meztking.roundtable.data.NeedView) -> Unit = { n ->
        showNeeds = false
        when {
            n.kind == "message" -> { tab = 1; main.loadLetters() }
            n.ask != null -> nav.navigate("project/${android.net.Uri.encode(n.project)}?tab=1")
            n.actions.contains("approve") -> nav.navigate("project/${android.net.Uri.encode(n.project)}?tab=1")
            else -> nav.navigate("project/${android.net.Uri.encode(n.project)}")
        }
    }
    // on a big screen (or a foldable open like a book) what waits for the owner sits beside the Table
    val needsPane: (@Composable () -> Unit)? = if (tab == 0 && crash == null && !searching && hall.data != null) ({
        NeedsList(hall.data?.needs.orEmpty(), backend?.mode, busy, main::act, openNeed, Modifier.padding(horizontal = 16.dp, vertical = 12.dp),
            onAnswer = main::answer, onMarkAllRead = { ns -> main.markAllRead(ns.mapNotNull { it.message }) })
    }) else null
    AdaptiveShell(
        places = listOf(ShellPlace("Table", Icons.Filled.TripOrigin, needCount), ShellPlace("Letters", Icons.AutoMirrored.Filled.MenuBook, myUnread),
            ShellPlace("Settings", Icons.Filled.Settings)),
        selected = tab, onSelect = { tab = it },
        snackbarHost = { SnackbarHost(snack) },
        beside = needsPane,
        folded = rememberFolded(),
    ) {
        val twoPanes = LocalShellPlan.current.twoPanes
        Box {
            crash?.let { details ->
                // safe mode: the app closed last time; nothing loads until the owner says so
                CrashCard(details, onSend = main::sendCrash, onTryAgain = main::crashSeen)
                return@Box
            }
            if (searching) {
                androidx.activity.compose.BackHandler { searching = false }
                SearchScreen(onBack = { searching = false }, onOpen = { hit ->
                    val seats = hall.data?.seats.orEmpty()
                    val o = hit.open
                    val seat = when (o.room) {
                        "project" -> seats.firstOrNull { it.path != null && it.path == o.path }
                        "hub_plan" -> seats.firstOrNull { it.hubName == o.name || it.id == o.name }
                        "journal" -> seats.firstOrNull { it.id == o.agent }
                        else -> null
                    }
                    when {
                        o.room == "letter" -> { searching = false; tab = 1; main.loadLetters(); true }
                        seat != null -> {
                            searching = false
                            nav.navigate("project/${android.net.Uri.encode(seat.id)}" + if (o.room == "journal") "" else "?tab=1"); true
                        }
                        else -> false
                    }
                })
                return@Box
            }
            when (tab) {
                0 -> TableScreen(
                    hall, if (backend == null) null else backend.mode, where, busy, onRefresh = main::refresh,
                    onOpen = { s -> nav.navigate("project/${android.net.Uri.encode(s.id)}") },
                    onAct = main::act,
                    onOpenNeed = openNeed,
                    showNeeds = showNeeds && !twoPanes, onShowNeeds = { showNeeds = it && !twoPanes },
                    onAnswer = main::answer,
                    onMarkAllRead = { ns -> main.markAllRead(ns.mapNotNull { it.message }) },
                    onAutopilot = main::autopilot,
                    onNotes = if (backend != null) ({ nav.navigate("notes") }) else null,
                    onSearch = if (backend != null) ({ searching = true }) else null,
                    onNewIdea = if (backend != null) ({ nav.navigate("newidea") }) else null,
                    onGallery = if (backend != null) ({ nav.navigate("gallery") }) else null,
                    pins = pins, needsBeside = twoPanes,
                )
                1 -> LettersScreen(
                    letters, identity, hall.data?.seats?.map { it.id }.orEmpty(),
                    onRefresh = main::loadLetters, onOpened = main::opened, onSend = main::send, onReply = main::reply,
                    onMarkAllRead = main::markAllRead,
                )
                else -> SettingsScreen(onConnect = { nav.navigate("connect") }, onHarness = { nav.navigate("harness") },
                    onComputers = { nav.navigate("connections") }, onShared = { nav.navigate("shared") }, onComfort = { nav.navigate("comfort") }, onChanged = {
                    settingsTick++
                    if (!app.store.configured) nav.navigate("setup") { popUpTo(0) { inclusive = true } } else main.reset()
                })
            }
        }
    }
}

/** The PC's (or this phone's) API for a seat that lives there; null for a project only the hub has. */
fun machineApi(app: RoundtableApp, seat: com.meztking.roundtable.data.SeatView?): com.meztking.roundtable.net.Api? {
    val src = com.meztking.roundtable.data.Source.of(seat?.source) ?: return null
    if (src == com.meztking.roundtable.data.Source.HUB) return null
    return (app.backend()?.parts?.get(src) as? com.meztking.roundtable.data.PcBackend)?.api
}

/** The Table's header line: which connections answer ("This phone · your PC · the hub"), and which don't. */
fun whereLabel(b: com.meztking.roundtable.data.MultiBackend?): String {
    if (b == null) return "Not connected"
    val all = b.configured.sortedBy { it.ordinal }
    val on = all.filter { b.health(it).ok != false }
    val off = all - on.toSet()
    val words = on.joinToString(" · ") { it.words.replaceFirstChar { c -> c.uppercase() }.let { w -> if (it == com.meztking.roundtable.data.Source.HUB) "Hub" else w } }
    return words.ifBlank { "Nothing answers" } + off.joinToString("") { " · ${it.words} is off" }.let { if (it.isBlank()) "" else it }
}

/** A screen with its own snackbar for short notices. */
@Composable
private fun Snacked(notice: String?, shown: () -> Unit, content: @Composable () -> Unit) {
    val snack = remember { SnackbarHostState() }
    LaunchedEffect(notice) { notice?.let { snack.showSnackbar(it); shown() } }
    Scaffold(containerColor = Color.Transparent, snackbarHost = { SnackbarHost(snack) }) { pad ->
        Box(Modifier.padding(pad)) { content() }
    }
}

@Composable
private fun CrashCard(details: String, onSend: () -> Unit, onTryAgain: () -> Unit) {
    androidx.compose.foundation.layout.Column(
        Modifier.fillMaxSize().padding(20.dp).androidx_verticalScroll(),
        verticalArrangement = androidx.compose.foundation.layout.Arrangement.spacedBy(14.dp),
    ) {
        Text("${Brand.NAME} closed unexpectedly last time", color = Hall.text, style = androidx.compose.material3.MaterialTheme.typography.titleLarge)
        Text("Sorry about that. To stop it happening again straight away, nothing has loaded yet. " +
            "Send the details to your PC so it can be fixed, then try again.", color = Hall.muted)
        androidx.compose.material3.Button(onClick = onSend, modifier = Modifier.fillMaxWidth(),
            colors = androidx.compose.material3.ButtonDefaults.buttonColors(containerColor = Hall.gold, contentColor = Hall.onAccent)) {
            Text("Send the details to my PC")
        }
        androidx.compose.material3.OutlinedButton(onClick = onTryAgain, modifier = Modifier.fillMaxWidth()) { Text("Try loading again", color = Hall.text) }
        Text("What happened (for the fix)", color = Hall.muted, style = androidx.compose.material3.MaterialTheme.typography.labelLarge)
        Text(details.take(3000), color = Hall.muted, style = androidx.compose.material3.MaterialTheme.typography.bodySmall)
    }
}

@Composable
private fun Modifier.androidx_verticalScroll(): Modifier =
    this.then(Modifier.verticalScroll(androidx.compose.foundation.rememberScrollState()))
