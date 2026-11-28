package com.meztking.roundtable.ui

import android.graphics.BitmapFactory
import androidx.compose.foundation.Image
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import com.meztking.roundtable.data.Looks
import com.meztking.roundtable.data.Words
import com.meztking.roundtable.ui.theme.Hall

/**
 * The look's pictures on its card, two a row, each with its look's name under it; tap one to see it bigger. Only data
 * addresses are drawn (Looks.safe): a picture is never fetched from anywhere.
 */
@Composable
fun LookPictureGrid(pictures: List<Pair<String, String>>) {
    val shown = remember(pictures) { pictures.filter { Looks.safe(it.second) } }
    if (shown.isEmpty()) return
    var big by rememberSaveable { mutableStateOf(-1) }
    Column(Modifier.fillMaxWidth().padding(vertical = 6.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        shown.chunked(2).forEachIndexed { row, pair ->
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                pair.forEachIndexed { i, (label, address) ->
                    val at = row * 2 + i
                    Column(Modifier.weight(1f).clickable(role = Role.Image, onClickLabel = Words.t("See it bigger")) { big = at }) {
                        LookPicture(address, label, Modifier.fillMaxWidth().aspectRatio(16f / 10f))
                        Text(label, color = Hall.ink, style = MaterialTheme.typography.bodySmall, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    }
                }
                if (pair.size == 1) Spacer(Modifier.weight(1f))
            }
        }
        Text(Words.t("Tap a picture to see it bigger."), color = Hall.inkSoft, style = MaterialTheme.typography.bodySmall)
    }
    shown.getOrNull(big)?.let { (label, address) ->
        Dialog(onDismissRequest = { big = -1 }) {
            Column(Modifier.fillMaxWidth()) {
                LookPicture(address, label, Modifier.fillMaxWidth(), fit = true)
                TextButton({ big = -1 }) { Text(Words.t("Close") + " · " + label, color = Hall.text) }
            }
        }
    }
}

@Composable
private fun LookPicture(address: String, label: String, modifier: Modifier, fit: Boolean = false) {
    val img = remember(address) {
        Looks.bytes(address)?.let { b -> runCatching { BitmapFactory.decodeByteArray(b, 0, b.size)?.asImageBitmap() }.getOrNull() }
    }
    val shape = RoundedCornerShape(8.dp)
    if (img != null) Image(img, Words.t("How {look} looks", "look" to label), modifier.clip(shape).border(1.dp, Hall.line, shape),
        contentScale = if (fit) ContentScale.FillWidth else ContentScale.Crop)
    else Text(Words.t("This picture can't be shown."), modifier, color = Hall.inkSoft, style = MaterialTheme.typography.bodySmall)
}
