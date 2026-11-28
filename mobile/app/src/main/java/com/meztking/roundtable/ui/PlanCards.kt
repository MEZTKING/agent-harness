package com.meztking.roundtable.ui

import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import com.meztking.roundtable.data.Ask
import com.meztking.roundtable.data.HoldThrottle
import com.meztking.roundtable.data.LookPictures
import com.meztking.roundtable.data.Looks
import com.meztking.roundtable.net.Api
import kotlinx.coroutines.launch

/**
 * What a question card needs from the machine that has the project: the hold sent while the owner types (at most once
 * every 20 seconds a card, HoldThrottle) and the look's pictures. Both are quiet when they fail: the card still works.
 */
interface CardHelp {
    /** Stop the clock of [ask] for a while; only a hold, never setting or clearing a timer. */
    suspend fun hold(path: String, id: String)
    /** The look's pictures of a project's plan, as data addresses. */
    suspend fun looks(path: String): Map<String, LookPictures>
}

class ApiCardHelp(private val api: Api) : CardHelp {
    override suspend fun hold(path: String, id: String) { api.holdTimer(path, id) }
    override suspend fun looks(path: String) = Looks.parse(api.planLooks(path))
}

/** A function to call while typing on [ask]'s card: it sends a hold through [help] at most once every 20 seconds. */
@Composable
fun rememberHold(help: CardHelp?, throttle: HoldThrottle = remember { HoldThrottle() }): ((Ask) -> Unit)? {
    if (help == null) return null
    val scope = rememberCoroutineScope()
    return remember(help, throttle) {
        { ask: Ask ->
            val path = ask.path.orEmpty()
            if (path.isNotBlank() && throttle.shouldSend("$path#${ask.id}")) scope.launch { runCatching { help.hold(path, ask.id) } }
        }
    }
}

/** The look's pictures for a project, read once when a look card shows; empty otherwise. */
@Composable
fun rememberLooks(help: CardHelp?, path: String?, cards: List<Ask>): Map<String, LookPictures> {
    var pics by remember(path) { mutableStateOf<Map<String, LookPictures>>(emptyMap()) }
    val wanted = cards.any { it.kind == "look" }
    LaunchedEffect(help, path, wanted) {
        if (help != null && !path.isNullOrBlank() && wanted) pics = runCatching { help.looks(path) }.getOrDefault(emptyMap())
    }
    return pics
}
