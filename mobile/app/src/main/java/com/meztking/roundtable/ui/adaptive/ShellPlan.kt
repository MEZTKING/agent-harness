package com.meztking.roundtable.ui.adaptive

/** Where the main places (Table, Letters, Settings) are reached from. */
enum class ShellNav { BOTTOM_BAR, RAIL }

/**
 * How the app sits on the screen it has: a phone gets the bottom bar; a phone on its side, a small tablet or an
 * open foldable gets a rail on the left; a big screen (or a foldable open like a book) gets the rail and two
 * panes, the Table beside what waits for the owner. Pure, so it is tested at every size.
 */
data class ShellPlan(
    val nav: ShellNav,
    /** 1 or 2 panes side by side. */
    val panes: Int,
    /** The first pane's share of the width when there are two. */
    val firstShare: Float = 1f,
    /** The widest one pane is drawn, in dp, so lines stay readable on a big screen (0 = the whole width). */
    val maxPaneDp: Int = 0,
) {
    val twoPanes: Boolean get() = panes == 2

    companion object {
        /** The compact width class ends here (Android's window size classes). */
        const val MEDIUM_DP = 600
        /** The expanded width class starts here. */
        const val EXPANDED_DP = 840
        /** Below this height a phone lying on its side has no room for a bottom bar or a second pane. */
        const val SHORT_DP = 480

        /**
         * [widthDp] and [heightDp] are the window's size; [folded] is true when a hinge runs down the middle of
         * the screen (a foldable half open like a book), which splits it into two panes at the fold.
         */
        fun plan(widthDp: Int, heightDp: Int, folded: Boolean = false): ShellPlan {
            val w = widthDp.coerceAtLeast(0)
            val h = heightDp.coerceAtLeast(0)
            return when {
                w < MEDIUM_DP -> ShellPlan(ShellNav.BOTTOM_BAR, 1)
                folded -> ShellPlan(ShellNav.RAIL, 2, firstShare = 0.5f)
                w >= EXPANDED_DP && h >= SHORT_DP -> ShellPlan(ShellNav.RAIL, 2, firstShare = if (w >= 1200) 0.6f else 0.55f)
                else -> ShellPlan(ShellNav.RAIL, 1, maxPaneDp = 720)
            }
        }
    }
}
