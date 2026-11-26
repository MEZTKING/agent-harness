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
import com.meztking.roundtable.ui.LettersScreen
import com.meztking.roundtable.ui.MainViewModel
import com.meztking.roundtable.ui.ProjectActions
import com.meztking.roundtable.ui.ProjectScreen
import com.meztking.roundtable.ui.ProjectUi
import com.meztking.roundtable.ui.ProjectViewModel
import com.meztking.roundtable.ui.SettingsScreen
import com.meztking.roundtable.ui.SetupScreen
import com.meztking.roundtable.ui.TableScreen
import com.meztking.roundtable.ui.theme.Hall
import com.meztking.roundtable.ui.theme.RoundtableTheme
import com.meztking.roundtable.ui.theme.hallBackground
import com.meztking.roundtable.work.Watch
import kotlinx.coroutines.flow.MutableStateFlow

class MainActivity : ComponentActivity() {
    /** A project to open, from a tapped notification. */
    private val openProject = MutableStateFlow<String?>(null)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        if (savedInstanceState == null) openProject.value = intent?.getStringExtra(Watch.EXTRA_PROJECT)
        setContent { RoundtableTheme { Root(openProject) } }
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
    Box(Modifier.fillMaxSize().hallBackground()) {
        NavHost(nav, startDestination = start) {
            composable("setup") {
                SetupScreen(onDone = {
                    main.reset()
                    nav.navigate("home") { popUpTo(0) { inclusive = true } }
                }, onBack = null)
            }
            composable("connect") {
                SetupScreen(onDone = { main.reset(); nav.popBackStack() }, onBack = { nav.popBackStack() })
            }
            composable("home") { Home(main, nav) }
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
                val notice by vm.notice.collectAsState()
                val snack = remember { SnackbarHostState() }
                LaunchedEffect(notice) { notice?.let { snack.showSnackbar(it); vm.noticeShown() } }
                val backend = app.backend()
                Scaffold(containerColor = Color.Transparent, snackbarHost = { SnackbarHost(snack) }) { pad ->
                    Box(Modifier.padding(pad)) {
                        ProjectScreen(
                            ProjectUi(vm.id, seat, backend?.mode, backend?.identity ?: app.store.identity, status, plan, inbox, sent, asks),
                            ProjectActions(
                                back = { nav.popBackStack() }, refresh = vm::refresh, command = vm::command, act = vm::act,
                                opened = vm::opened, reply = vm::reply, send = vm::send, answer = vm::answer,
                            ),
                            initialTab = entry.arguments?.getInt("tab") ?: 0,
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun Home(main: MainViewModel, nav: NavHostController) {
    val ctx = LocalContext.current
    val app = ctx.applicationContext as RoundtableApp
    var tab by rememberSaveable { mutableIntStateOf(0) }
    var showNeeds by rememberSaveable { mutableStateOf(false) }
    val hall by main.hall.collectAsState()
    val letters by main.letters.collectAsState()
    val busy by main.busy.collectAsState()
    val notice by main.notice.collectAsState()
    val snack = remember { SnackbarHostState() }
    var settingsTick by remember { mutableIntStateOf(0) }
    val backend = remember(settingsTick) { app.backend() }

    LaunchedEffect(notice) { notice?.let { snack.showSnackbar(it); main.noticeShown() } }
    LaunchedEffect(backend) { if (backend != null) main.refresh() }
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
    val where = when (backend?.mode) {
        Mode.HUB -> "Hub on GitHub · ${app.store.hubRepo}"
        Mode.PC -> "Paired PC · ${app.store.link?.name ?: "PC"}"
        null -> "Not connected"
    }
    Scaffold(
        containerColor = Color.Transparent,
        snackbarHost = { SnackbarHost(snack) },
        bottomBar = {
            NavigationBar(containerColor = Hall.panel) {
                val colors = NavigationBarItemDefaults.colors(selectedIconColor = Hall.ink, indicatorColor = Hall.gold, selectedTextColor = Hall.goldBright,
                    unselectedIconColor = Hall.muted, unselectedTextColor = Hall.muted)
                NavigationBarItem(tab == 0, { tab = 0 }, icon = {
                    BadgedBox(badge = { if (needCount > 0) Badge(containerColor = Hall.ember) { Text("$needCount") } }) { Icon(Icons.Filled.TripOrigin, null) }
                }, label = { Text("Table") }, colors = colors)
                NavigationBarItem(tab == 1, { tab = 1 }, icon = {
                    BadgedBox(badge = { if (myUnread > 0) Badge(containerColor = Hall.ember) { Text("$myUnread") } }) { Icon(Icons.AutoMirrored.Filled.MenuBook, null) }
                }, label = { Text("Letters") }, colors = colors)
                NavigationBarItem(tab == 2, { tab = 2 }, icon = { Icon(Icons.Filled.Settings, null) }, label = { Text("Settings") }, colors = colors)
            }
        },
    ) { pad ->
        Box(Modifier.padding(pad)) {
            when (tab) {
                0 -> TableScreen(
                    hall, backend?.mode, where, busy, onRefresh = main::refresh,
                    onOpen = { s -> nav.navigate("project/${android.net.Uri.encode(s.id)}") },
                    onAct = main::act,
                    onOpenNeed = { n ->
                        showNeeds = false
                        when {
                            n.kind == "message" -> { tab = 1; main.loadLetters() }
                            n.ask != null -> nav.navigate("project/${android.net.Uri.encode(n.project)}?tab=1")
                            n.actions.contains("approve") -> nav.navigate("project/${android.net.Uri.encode(n.project)}?tab=1")
                            else -> nav.navigate("project/${android.net.Uri.encode(n.project)}")
                        }
                    },
                    showNeeds = showNeeds, onShowNeeds = { showNeeds = it },
                    onAnswer = main::answer,
                )
                1 -> LettersScreen(
                    letters, identity, hall.data?.seats?.map { it.id }.orEmpty(),
                    onRefresh = main::loadLetters, onOpened = main::opened, onSend = main::send, onReply = main::reply,
                )
                else -> SettingsScreen(onConnect = { nav.navigate("connect") }, onChanged = {
                    settingsTick++
                    if (!app.store.configured) nav.navigate("setup") { popUpTo(0) { inclusive = true } } else main.reset()
                })
            }
        }
    }
}
