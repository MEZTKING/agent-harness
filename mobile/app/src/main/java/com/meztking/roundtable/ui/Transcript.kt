package com.meztking.roundtable.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

/**
 * Where the reader is in a transcript (DS-82): the item at the top of the screen and how far into it, as a share of
 * its height, so the same paragraph stays at the top when the width changes (a rotation, a fold, split screen) and
 * every item's height with it. [following] means the reader was at the end: then the end stays in view instead.
 */
data class TranscriptPlace(val key: Any?, val index: Int, val share: Float, val following: Boolean) {
    companion object {
        /** The place [state] shows now. */
        fun of(state: LazyListState): TranscriptPlace {
            val info = state.layoutInfo
            val first = info.visibleItemsInfo.firstOrNull() ?: return TranscriptPlace(null, 0, 0f, true)
            val last = info.visibleItemsInfo.last()
            val atEnd = last.index == info.totalItemsCount - 1 && last.offset + last.size <= info.viewportEndOffset + 1
            val share = if (first.size > 0) (state.firstVisibleItemScrollOffset.toFloat() / first.size).coerceIn(0f, 1f) else 0f
            return TranscriptPlace(first.key, first.index, share, atEnd)
        }

        /** The scroll offset that puts [share] of an item now [newHeight] high at the top (the same line, near enough). */
        fun offsetFor(share: Float, newHeight: Int): Int = (share.coerceIn(0f, 1f) * newHeight.coerceAtLeast(0)).toInt()

        /** Where [key] now is among [keys] (it may have moved as items came in), else the old [index] clamped. */
        fun indexFor(key: Any?, index: Int, keys: List<Any?>): Int =
            keys.indexOf(key).takeIf { it >= 0 } ?: index.coerceIn(0, (keys.size - 1).coerceAtLeast(0))
    }
}

/**
 * A transcript with its composer: the list takes the room above, the composer its own row below (never drawn over the
 * newest line), lifted over the keyboard. [keys] are the items' keys in order, as the list's `items(key=)` gives them.
 */
@Composable
fun Transcript(
    keys: List<Any?>,
    modifier: Modifier = Modifier,
    state: LazyListState = rememberLazyListState(),
    contentPadding: PaddingValues = PaddingValues(16.dp),
    spacing: Dp = 14.dp,
    /** Start at the end and stay there while the reader is (a chat); false: start at the top (the Live tab). */
    followEnd: Boolean = true,
    composer: (@Composable () -> Unit)? = null,
    content: LazyListScope.() -> Unit,
) {
    var place by remember { mutableStateOf<TranscriptPlace?>(null) }
    // keep the place up to date while the reader scrolls, so a width change knows where they were
    LaunchedEffect(state) {
        snapshotFlow { state.firstVisibleItemIndex to state.firstVisibleItemScrollOffset }.collect { place = TranscriptPlace.of(state) }
    }
    // the newest line comes in, or the composer grows: a reader at the end stays at the end
    LaunchedEffect(keys.size, keys.lastOrNull()) {
        if (followEnd && place?.following != false && keys.isNotEmpty()) state.scrollToItem(keys.size - 1, Int.MAX_VALUE / 2)
    }
    Column(modifier.fillMaxSize().imePadding()) {
        BoxWithConstraints(Modifier.weight(1f).fillMaxWidth()) {
            val width = maxWidth
            LaunchedEffect(width) {
                val p = place ?: return@LaunchedEffect
                if (followEnd && p.following && keys.isNotEmpty()) { state.scrollToItem(keys.size - 1, Int.MAX_VALUE / 2); return@LaunchedEffect }
                val i = TranscriptPlace.indexFor(p.key, p.index, keys)
                state.scrollToItem(i)
                val h = state.layoutInfo.visibleItemsInfo.firstOrNull { it.index == i }?.size ?: 0
                state.scrollToItem(i, TranscriptPlace.offsetFor(p.share, h))
            }
            LazyColumn(Modifier.fillMaxSize(), state = state, contentPadding = contentPadding, verticalArrangement = Arrangement.spacedBy(spacing), content = content)
        }
        composer?.invoke()
    }
}
