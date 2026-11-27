package com.meztking.roundtable.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Computer
import androidx.compose.material.icons.filled.Wifi
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.PlainTooltip
import androidx.compose.material3.Text
import androidx.compose.material3.TooltipBox
import androidx.compose.material3.TooltipDefaults
import androidx.compose.material3.rememberTooltipState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import com.meztking.roundtable.net.Discovery
import com.meztking.roundtable.net.FoundPc
import com.meztking.roundtable.ui.theme.Hall
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.launch

/** Where a look on the Wi-Fi stands. */
data class FindPcState(val looking: Boolean = false, val found: List<FoundPc> = emptyList(), val problem: String? = null, val looked: Boolean = false)

/**
 * "Look for my PC": finds Roundtable Hold on this phone's Wi-Fi (only when pressed) and hands the one picked to
 * [onFound]. For a first pairing the owner then types the 8-letter code shown on the PC. [look] is for tests.
 */
@Composable
fun FindPcCard(onFound: (FoundPc) -> Unit, modifier: Modifier = Modifier, look: (suspend () -> Discovery.Look)? = null) {
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    var state by remember { mutableStateOf(FindPcState()) }
    val doLook: suspend () -> Discovery.Look = look ?: { Discovery.find(ctx) }
    FindPcContent(state, modifier, onLook = {
        if (!state.looking) {
            state = state.copy(looking = true, problem = null)
            scope.launch {
                state = try {
                    val r = doLook()
                    FindPcState(found = r.found, problem = r.problem, looked = true)
                } catch (e: CancellationException) {
                    throw e
                } catch (e: Exception) {
                    FindPcState(problem = Discovery.NOTHING, looked = true)
                }
            }
        }
    }, onPick = onFound)
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun FindPcContent(state: FindPcState, modifier: Modifier = Modifier, onLook: () -> Unit, onPick: (FoundPc) -> Unit) {
    Column(modifier.fillMaxWidth()) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("Find my PC on the Wi-Fi", style = MaterialTheme.typography.titleSmall, color = Hall.goldBright)
            Spacer(Modifier.width(8.dp))
            TooltipBox(TooltipDefaults.rememberPlainTooltipPositionProvider(),
                tooltip = { PlainTooltip { Text("New, and not yet tried on many home networks. If it finds nothing, scan the QR code instead.") } },
                state = rememberTooltipState()) {
                Text("Beta", style = MaterialTheme.typography.labelSmall, color = Hall.muted)
            }
        }
        Text("For when there's no QR code to scan, or your PC's address has changed.",
            style = MaterialTheme.typography.bodySmall, color = Hall.muted)
        Spacer(Modifier.height(8.dp))
        OutlinedButton(onClick = onLook, enabled = !state.looking, modifier = Modifier.fillMaxWidth()) {
            if (state.looking) CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp)
            else Icon(Icons.Filled.Wifi, null, Modifier.size(18.dp))
            Spacer(Modifier.width(8.dp))
            Text(if (state.looking) "Looking…" else if (state.looked) "Look again" else "Look for my PC")
        }
        state.problem?.let { Text(it, color = Hall.bad, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.padding(top = 6.dp)) }
        if (state.found.isNotEmpty()) {
            Spacer(Modifier.height(6.dp))
            Text(if (state.found.size == 1) "Found one. Tap it, then type the code shown on the PC."
                else "Found ${state.found.size}. Tap yours, then type the code shown on it.",
                style = MaterialTheme.typography.bodySmall, color = Hall.text)
            Column(verticalArrangement = Arrangement.spacedBy(4.dp), modifier = Modifier.padding(top = 4.dp)) {
                for (pc in state.found) {
                    Row(Modifier.fillMaxWidth().clickable { onPick(pc) }.padding(vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                        Icon(Icons.Filled.Computer, null, Modifier.size(20.dp), tint = Hall.goldBright)
                        Spacer(Modifier.width(10.dp))
                        Column(Modifier.weight(1f)) {
                            Text(pc.name.ifBlank { "A PC" }, style = MaterialTheme.typography.bodyLarge, color = Hall.text)
                            Text(pc.host, style = MaterialTheme.typography.bodySmall, color = Hall.muted)
                        }
                        Text("Use", style = MaterialTheme.typography.labelLarge, color = Hall.goldBright)
                    }
                }
            }
        }
    }
}
