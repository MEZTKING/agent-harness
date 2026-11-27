package com.meztking.roundtable.ui.adaptive

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.material3.Badge
import androidx.compose.material3.BadgedBox
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.NavigationRail
import androidx.compose.material3.NavigationRailItem
import androidx.compose.material3.NavigationRailItemDefaults
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.compositionLocalOf
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.unit.dp
import com.meztking.roundtable.ui.theme.Hall

/** The plan the shell is drawn with now, for the screens inside it (two panes: what waits is already beside). */
val LocalShellPlan = compositionLocalOf { ShellPlan(ShellNav.BOTTOM_BAR, 1) }

/** One of the main places: its name, icon and how many things wait there (a badge when above 0). */
data class ShellPlace(val label: String, val icon: ImageVector, val badge: Int = 0)

/**
 * The app's frame on any screen, laid out by [ShellPlan]: the bottom bar on a phone, a rail on a wider screen,
 * and on a big one [beside] as a second pane next to [content]. [beside] null means one pane everywhere.
 * [folded] says a hinge runs down the screen (the caller knows; without it the size decides alone).
 */
@Composable
fun AdaptiveShell(
    places: List<ShellPlace>,
    selected: Int,
    onSelect: (Int) -> Unit,
    modifier: Modifier = Modifier,
    folded: Boolean = false,
    snackbarHost: @Composable () -> Unit = {},
    beside: (@Composable () -> Unit)? = null,
    content: @Composable () -> Unit,
) {
    BoxWithConstraints(modifier.fillMaxSize()) {
        val sized = ShellPlan.plan(maxWidth.value.toInt(), maxHeight.value.toInt(), folded)
        val plan = if (sized.twoPanes && beside == null) sized.copy(panes = 1, firstShare = 1f) else sized
        CompositionLocalProvider(LocalShellPlan provides plan) {
        when (plan.nav) {
            ShellNav.BOTTOM_BAR -> Scaffold(
                containerColor = Color.Transparent,
                snackbarHost = snackbarHost,
                bottomBar = { BottomBar(places, selected, onSelect) },
            ) { pad -> Box(Modifier.padding(pad)) { content() } }
            ShellNav.RAIL -> Scaffold(containerColor = Color.Transparent, snackbarHost = snackbarHost) { pad ->
                Row(Modifier.fillMaxSize().padding(pad)) {
                    Rail(places, selected, onSelect)
                    if (plan.twoPanes && beside != null) {
                        Box(Modifier.weight(plan.firstShare).fillMaxHeight()) { content() }
                        Box(Modifier.width(1.dp).fillMaxHeight().background(Hall.line))
                        Box(Modifier.weight(1f - plan.firstShare).fillMaxHeight()) { beside() }
                    } else {
                        Box(Modifier.weight(1f).fillMaxHeight(), contentAlignment = Alignment.TopCenter) {
                            // one pane on a wide screen: no wider than reads well
                            val max = if (plan.maxPaneDp > 0) plan.maxPaneDp else ShellPlan.EXPANDED_DP
                            Box(Modifier.widthIn(max = max.dp).fillMaxWidth().fillMaxHeight()) { content() }
                        }
                    }
                }
            }
        }
        }
    }
}

@Composable
private fun Badged(p: ShellPlace) {
    BadgedBox(badge = { if (p.badge > 0) Badge(containerColor = Hall.ember) { Text("${p.badge}") } }) { Icon(p.icon, null) }
}

@Composable
private fun BottomBar(places: List<ShellPlace>, selected: Int, onSelect: (Int) -> Unit) {
    NavigationBar(containerColor = Hall.panel) {
        val colors = NavigationBarItemDefaults.colors(selectedIconColor = Hall.onAccent, indicatorColor = Hall.gold, selectedTextColor = Hall.text,
            unselectedIconColor = Hall.muted, unselectedTextColor = Hall.muted)
        places.forEachIndexed { i, p ->
            NavigationBarItem(selected == i, { onSelect(i) }, icon = { Badged(p) }, label = { Text(p.label) }, colors = colors)
        }
    }
}

@Composable
private fun Rail(places: List<ShellPlace>, selected: Int, onSelect: (Int) -> Unit) {
    NavigationRail(containerColor = Hall.panel, contentColor = Hall.text) {
        val colors = NavigationRailItemDefaults.colors(selectedIconColor = Hall.onAccent, indicatorColor = Hall.gold, selectedTextColor = Hall.text,
            unselectedIconColor = Hall.muted, unselectedTextColor = Hall.muted)
        places.forEachIndexed { i, p ->
            NavigationRailItem(selected == i, { onSelect(i) }, icon = { Badged(p) }, label = { Text(p.label) }, colors = colors)
        }
    }
}
