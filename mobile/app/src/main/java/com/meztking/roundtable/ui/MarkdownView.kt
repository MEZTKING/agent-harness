package com.meztking.roundtable.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.LocalContentColor
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.LinkAnnotation
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.TextLinkStyles
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.withLink
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.meztking.roundtable.data.Inline
import com.meztking.roundtable.data.Markdown
import com.meztking.roundtable.data.Md
import com.meztking.roundtable.data.StatusDoc
import com.meztking.roundtable.ui.theme.Hall
import com.meztking.roundtable.ui.theme.Label
import com.meztking.roundtable.ui.theme.Serif

/** Inline markdown to styled text: bold, italic, `code` as a small dark chip, links in gold. */
fun styled(s: String, codeBg: Color = Hall.code, codeFg: Color = Hall.goldBright, link: Color = Hall.goldBright): AnnotatedString =
    buildAnnotatedString {
        for (span in Markdown.inline(s)) when (span) {
            is Inline.Plain -> append(span.text)
            is Inline.Bold -> withStyle(SpanStyle(fontWeight = FontWeight.Bold)) { append(span.text) }
            is Inline.Italic -> withStyle(SpanStyle(fontStyle = FontStyle.Italic)) { append(span.text) }
            is Inline.Code -> withStyle(SpanStyle(fontFamily = FontFamily.Monospace, fontSize = 12.sp, background = codeBg, color = codeFg)) {
                append(" ${span.text} ")
            }
            is Inline.Link -> withLink(LinkAnnotation.Url(span.url, TextLinkStyles(SpanStyle(color = link, textDecoration = TextDecoration.Underline)))) {
                append(span.text)
            }
        }
    }

/** The sections of a status page or plan, drawn natively. */
@Composable
fun SectionsView(sections: List<StatusDoc.Section>, modifier: Modifier = Modifier) {
    Column(modifier, verticalArrangement = Arrangement.spacedBy(6.dp)) {
        for (s in sections) {
            SectionTitle(s.title)
            MdBlocks(s.blocks)
        }
    }
}

@Composable
fun SectionTitle(title: String) {
    Column(Modifier.padding(top = 14.dp, bottom = 2.dp)) {
        Text(title.uppercase(), style = Label)
        Spacer(Modifier.height(4.dp))
        Box(Modifier.fillMaxWidth().height(1.dp).background(
            androidx.compose.ui.graphics.Brush.horizontalGradient(listOf(Hall.gold, Hall.gold.copy(alpha = 0.2f), Color.Transparent))))
    }
}

@Composable
fun MdBlocks(blocks: List<Md>, modifier: Modifier = Modifier) {
    val text = LocalContentColor.current
    Column(modifier, verticalArrangement = Arrangement.spacedBy(6.dp)) {
        for (b in blocks) when (b) {
            is Md.Heading -> Text(styled(b.text), style = if (b.level <= 2) MaterialTheme.typography.titleMedium else MaterialTheme.typography.titleSmall,
                color = Hall.goldBright, modifier = Modifier.padding(top = 6.dp))
            is Md.Paragraph -> {
                val italicOnly = b.text.startsWith("_") && b.text.endsWith("_")
                Text(styled(b.text), style = MaterialTheme.typography.bodyMedium, color = if (italicOnly) Hall.muted else text)
            }
            is Md.Item -> ItemRow(b)
            is Md.Quote -> Row {
                Box(Modifier.width(3.dp).height(20.dp).background(Hall.goldDim))
                Spacer(Modifier.width(8.dp))
                Text(styled(b.text), style = MaterialTheme.typography.bodyMedium, fontStyle = FontStyle.Italic, color = Hall.muted)
            }
            is Md.Code -> Box(Modifier.fillMaxWidth().background(Hall.code, RoundedCornerShape(5.dp))
                .border(1.dp, Hall.line, RoundedCornerShape(5.dp)).horizontalScroll(rememberScrollState()).padding(10.dp)) {
                Text(b.text, fontFamily = FontFamily.Monospace, fontSize = 12.sp, color = Hall.text)
            }
            is Md.Table -> Column(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState())) {
                b.rows.forEachIndexed { i, row ->
                    Row(Modifier.padding(vertical = 3.dp)) {
                        row.forEach { cell ->
                            Text(styled(cell), Modifier.width(140.dp).padding(end = 8.dp), style = MaterialTheme.typography.bodySmall,
                                fontWeight = if (i == 0) FontWeight.SemiBold else null, color = if (i == 0) Hall.gold else text)
                        }
                    }
                    if (i == 0) HorizontalDivider(color = Hall.line)
                }
            }
            Md.Rule -> HorizontalDivider(color = Hall.line, modifier = Modifier.padding(vertical = 6.dp))
        }
    }
}

@Composable
private fun ItemRow(b: Md.Item) {
    val high = b.text.startsWith("**(high)**")
    val body = remember(b.text) { styled(b.text.removePrefix("**(high)**").trim()) }
    Row(Modifier.fillMaxWidth().padding(start = (b.depth * 16).dp), verticalAlignment = Alignment.Top) {
        when {
            b.checked != null -> Box(
                Modifier.padding(top = 2.dp).size(16.dp).border(1.5.dp, if (b.checked) Hall.good else Hall.goldDim, RoundedCornerShape(3.dp)),
                contentAlignment = Alignment.Center,
            ) { if (b.checked) Icon(Icons.Filled.Check, null, tint = Hall.good, modifier = Modifier.size(12.dp)) }
            b.number != null -> Text("${b.number}.", color = Hall.gold, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.width(20.dp))
            else -> Box(Modifier.padding(top = 8.dp, start = 4.dp, end = 4.dp).size(5.dp).background(Hall.gold, CircleShape))
        }
        Spacer(Modifier.width(10.dp))
        Column(Modifier.weight(1f)) {
            if (high) Chip("high", Hall.bad)
            Text(body, style = MaterialTheme.typography.bodyMedium)
        }
        if (b.id != null) {
            Spacer(Modifier.width(6.dp))
            Chip(b.id, Hall.goldDim, mono = true)
        }
    }
}

/** A small rounded label. */
@Composable
fun Chip(text: String, color: Color, mono: Boolean = false, filled: Boolean = false, modifier: Modifier = Modifier) {
    Text(
        text,
        modifier
            .padding(vertical = 1.dp)
            .background(if (filled) color else color.copy(alpha = 0.12f), RoundedCornerShape(4.dp))
            .border(1.dp, color.copy(alpha = 0.6f), RoundedCornerShape(4.dp))
            .padding(horizontal = 6.dp, vertical = 1.dp),
        color = if (filled) Hall.ink else color,
        fontSize = 11.sp,
        fontFamily = if (mono) FontFamily.Monospace else Serif,
        maxLines = 1,
    )
}
