package com.meztking.roundtable.ui.theme

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.material3.LocalContentColor

/** The desktop app's "council hall" palette (style.css). */
object Hall {
    val bg = Color(0xFF12100D)
    val bgDeep = Color(0xFF0C0A08)
    val panel = Color(0xFF1D1915)
    val panelHi = Color(0xFF25201A)
    val field = Color(0xFF15120F)
    val text = Color(0xFFEBE1CB)
    val muted = Color(0xFFAB9D84)
    val line = Color(0xFF372F25)
    val lineGold = Color(0xFF5D4C2E)
    val gold = Color(0xFFD0AB62)
    val goldBright = Color(0xFFECD08F)
    val goldDim = Color(0xFF8F7642)
    val amber = Color(0xFFE2A24A)
    val accentSoft = Color(0xFF2B2314)
    val good = Color(0xFFA9C48F)
    val bad = Color(0xFFF08A70)
    val ember = Color(0xFFD9583C)
    val warn = Color(0xFFECB45A)
    val parchment = Color(0xFFD3C29C)
    val parchmentLo = Color(0xFFC2AE84)
    val ink = Color(0xFF2A2015)
    val inkSoft = Color(0xFF5A4A33)
    val code = Color(0xFF100E0B)

    fun status(s: String): Color = when (s) {
        "running" -> amber
        "waiting" -> bad
        "done" -> good
        else -> muted
    }
}

val Serif = FontFamily.Serif

private val scheme = darkColorScheme(
    primary = Hall.gold,
    onPrimary = Hall.ink,
    primaryContainer = Hall.accentSoft,
    onPrimaryContainer = Hall.goldBright,
    secondary = Hall.amber,
    onSecondary = Hall.ink,
    secondaryContainer = Hall.panelHi,
    onSecondaryContainer = Hall.goldBright,
    tertiary = Hall.good,
    background = Hall.bg,
    onBackground = Hall.text,
    surface = Hall.bg,
    onSurface = Hall.text,
    surfaceVariant = Hall.panelHi,
    onSurfaceVariant = Hall.muted,
    surfaceContainerLowest = Hall.bgDeep,
    surfaceContainerLow = Hall.panel,
    surfaceContainer = Hall.panel,
    surfaceContainerHigh = Hall.panelHi,
    surfaceContainerHighest = Color(0xFF2E281F),
    outline = Hall.lineGold,
    outlineVariant = Hall.line,
    error = Hall.bad,
    onError = Hall.ink,
    inverseSurface = Hall.parchment,
    inverseOnSurface = Hall.ink,
)

private val base = Typography()
private val typography = Typography(
    displaySmall = base.displaySmall.copy(fontFamily = Serif, fontWeight = FontWeight.SemiBold, color = Color(0xFFF3E6C6)),
    headlineMedium = base.headlineMedium.copy(fontFamily = Serif, fontWeight = FontWeight.SemiBold),
    headlineSmall = base.headlineSmall.copy(fontFamily = Serif, fontWeight = FontWeight.SemiBold),
    titleLarge = base.titleLarge.copy(fontFamily = Serif, fontWeight = FontWeight.SemiBold),
    titleMedium = base.titleMedium.copy(fontFamily = Serif, fontWeight = FontWeight.SemiBold),
    titleSmall = base.titleSmall.copy(fontFamily = Serif, fontWeight = FontWeight.SemiBold),
    labelSmall = base.labelSmall.copy(letterSpacing = 0.6.sp),
)

/** Small capitals with wide spacing, as the desktop's section labels. */
val Label = TextStyle(fontFamily = Serif, fontSize = 12.sp, letterSpacing = 2.4.sp, fontWeight = FontWeight.SemiBold, color = Hall.gold)

@Composable
fun RoundtableTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = scheme,
        typography = typography,
        shapes = Shapes(small = RoundedCornerShape(5.dp), medium = RoundedCornerShape(8.dp), large = RoundedCornerShape(14.dp)),
    ) {
        // text drawn straight on the hall (not inside a Surface) is parchment-light, not black
        CompositionLocalProvider(LocalContentColor provides Hall.text, content = content)
    }
}

/** The hall behind every screen: candle glow from above over dark stone. */
fun Modifier.hallBackground(): Modifier = this.background(Hall.bg).drawBehind {
    drawRect(Brush.radialGradient(listOf(Hall.amber.copy(alpha = 0.13f), Color.Transparent),
        center = Offset(size.width * 0.55f, -size.height * 0.05f), radius = size.maxDimension * 0.65f))
    drawRect(Brush.radialGradient(listOf(Color.Transparent, Color.Black.copy(alpha = 0.45f)),
        center = Offset(size.width / 2, size.height * 0.4f), radius = size.maxDimension * 0.9f))
}

/** A gold-edged panel (the desktop's cards). */
@Composable
fun Panel(modifier: Modifier = Modifier, highlight: Boolean = false, content: @Composable ColumnScope.() -> Unit) {
    val shape = RoundedCornerShape(8.dp)
    Column(
        modifier
            .background(Brush.verticalGradient(listOf(Hall.panelHi, Hall.panel)), shape)
            .border(1.dp, if (highlight) Hall.gold else Hall.lineGold, shape)
            .padding(14.dp),
        content = content,
    )
}

/** B's parchment decision card: aged paper, ink text, a small wax seal in the corner. */
@Composable
fun Parchment(modifier: Modifier = Modifier, seal: Color = Hall.ember, content: @Composable ColumnScope.() -> Unit) {
    val shape = RoundedCornerShape(6.dp)
    Box(modifier) {
        Column(
            Modifier
                .fillMaxWidth()
                .background(Brush.verticalGradient(listOf(Hall.parchment, Hall.parchmentLo)), shape)
                .border(BorderStroke(1.dp, Hall.goldDim), shape)
                .drawBehind {
                    // a faint darker edge, like old paper
                    drawRect(Brush.radialGradient(listOf(Color.Transparent, Hall.inkSoft.copy(alpha = 0.18f)),
                        center = center, radius = size.maxDimension * 0.75f))
                    // the wax seal
                    val r = 9.dp.toPx()
                    val c = Offset(size.width - 18.dp.toPx(), 18.dp.toPx())
                    drawCircle(Brush.radialGradient(listOf(seal, androidx.compose.ui.graphics.lerp(seal, Color.Black, 0.45f)), center = c, radius = r), r, c)
                    drawCircle(Color.Black.copy(alpha = 0.18f), r * 0.55f, c, style = androidx.compose.ui.graphics.drawscope.Stroke(1.5f))
                }
                .padding(start = 16.dp, end = 34.dp, top = 14.dp, bottom = 14.dp),
        ) {
            CompositionLocalProvider(LocalContentColor provides Hall.ink) { content() }
        }
    }
}

/** Buttons on parchment: a gold one for the main answer, an ink outline for the rest. */
object ParchmentButtons {
    @Composable fun main() = ButtonDefaults.buttonColors(containerColor = Hall.gold, contentColor = Hall.ink)
    @Composable fun other() = ButtonDefaults.outlinedButtonColors(contentColor = Hall.ink)
    val otherBorder = BorderStroke(1.dp, Hall.inkSoft)
}
