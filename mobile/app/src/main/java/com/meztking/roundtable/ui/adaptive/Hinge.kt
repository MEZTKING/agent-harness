package com.meztking.roundtable.ui.adaptive

import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.staticCompositionLocalOf
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.flow.map

/**
 * A fold or hinge on the screen as Jetpack WindowManager's `FoldingFeature` describes it, in plain values, so the
 * rule below is tested without a device or the library (DS-69).
 */
data class Hinge(
    /** The fold runs top to bottom (a book), not across (a laptop). */
    val vertical: Boolean,
    /** Half open (bent) rather than flat. */
    val halfOpen: Boolean,
    /** It splits the screen into two parts (a real hinge, or any fold that is bent). */
    val separating: Boolean,
)

/** Where the window's folds come from. The device's one reads `WindowInfoTracker`; the default has none. */
fun interface HingeSource {
    fun hinges(): Flow<List<Hinge>>
}

/** No fold anywhere: a phone, a tablet, or a build without Jetpack WindowManager. */
val NoHinge = HingeSource { flowOf(emptyList()) }

/** The source the app uses (MainActivity provides the device's one once `androidx.window` is a dependency). */
val LocalHingeSource = staticCompositionLocalOf { NoHinge }

object Fold {
    /**
     * Whether the shell splits at a fold: a top-to-bottom fold that separates the screen, or one bent half open
     * like a book. A flat fold that doesn't separate (a foldable lying open) is one big screen.
     */
    fun folded(hinges: List<Hinge>): Boolean = hinges.any { it.vertical && (it.separating || it.halfOpen) }
}

/** `folded` for [AdaptiveShell], following the window as it opens and bends. */
@Composable
fun rememberFolded(source: HingeSource = LocalHingeSource.current): Boolean {
    val flow = remember(source) { source.hinges().map(Fold::folded) }
    val folded by flow.collectAsState(initial = false)
    return folded
}
