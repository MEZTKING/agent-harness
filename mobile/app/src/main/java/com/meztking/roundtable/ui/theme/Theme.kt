package com.meztking.roundtable.ui.theme

import android.provider.Settings
import android.view.HapticFeedbackConstants
import com.meztking.roundtable.data.Accent
import com.meztking.roundtable.data.Comfort
import com.meztking.roundtable.data.Haptics
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.lerp
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.unit.Density
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.keyframes
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.animateFloat
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.isSystemInDarkTheme
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
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.State
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.luminance
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.material3.LocalContentColor
import com.meztking.roundtable.R

/**
 * "Candlelit Oak": the same tokens as the desktop app (style.css, from the design file's tokens.css),
 * light and dark, plus a few derived from them (wells, the states, the wood of the table).
 */
class OakPalette(
    val background: Color, val surface: Color, val text: Color, val muted: Color,
    val accent: Color, val accentText: Color, val candle: Color, val oakLine: Color,
    val sunken: Color, val accentSoft: Color, val good: Color, val bad: Color, val warn: Color,
)

val LightOak = OakPalette(
    background = Color(0xFFF6EBD8), surface = Color(0xFFFFF8EA), text = Color(0xFF2B1D12), muted = Color(0xFF6E5A44),
    accent = Color(0xFF9A4A12), accentText = Color(0xFFFFF8EA), candle = Color(0xFFC9731F), oakLine = Color(0xFFDCC8A8),
    sunken = Color(0xFFEFE2CA), accentSoft = Color(0xFFF3DCC0), good = Color(0xFF4B6626), bad = Color(0xFFA3341C), warn = Color(0xFF855300),
)
val DarkOak = OakPalette(
    background = Color(0xFF1B1410), surface = Color(0xFF2A1F18), text = Color(0xFFF4E8D4), muted = Color(0xFFB9A58C),
    accent = Color(0xFFE8A33D), accentText = Color(0xFF1B1410), candle = Color(0xFFE8A33D), oakLine = Color(0xFF4A3828),
    sunken = Color(0xFF221913), accentSoft = Color(0xFF3A2A17), good = Color(0xFFA9C48F), bad = Color(0xFFF08A70), warn = Color(0xFFECB45A),
)

/**
 * The colours every screen uses. The names are the old theme's, so the screens didn't change; each now
 * reads the light or dark palette that [RoundtableTheme] picked.
 */
object Hall {
    var palette by mutableStateOf(DarkOak)
    private val p get() = palette

    val bg get() = p.background
    val bgDeep get() = p.sunken
    val panel get() = p.surface
    val panelHi get() = p.surface
    val field get() = p.sunken
    val text get() = p.text
    val muted get() = p.muted
    val line get() = p.oakLine
    val lineGold get() = p.oakLine
    val gold get() = p.accent
    val goldBright get() = p.accent
    val goldDim get() = p.muted
    val amber get() = p.candle
    val accentSoft get() = p.accentSoft
    val good get() = p.good
    val bad get() = p.bad
    val ember get() = p.bad
    val warn get() = p.warn
    /** Cards that used to be parchment are now oak cards: the surface and the text on it. */
    val parchment get() = p.surface
    val parchmentLo get() = p.sunken
    val ink get() = p.text
    val inkSoft get() = p.muted
    val code get() = p.sunken
    /** Text on a filled accent (amber) button. */
    val onAccent get() = p.accentText
    /** The candle glow: only on what needs the owner. */
    val candle get() = p.candle
    /** Text drawn on the dark wood of the table, in both looks. */
    val onWood = Color(0xFFF4E8D4)

    /** Text that reads on [c] when it is used as a filled background. */
    fun on(c: Color): Color = if (c.luminance() > 0.4f) LightOak.text else DarkOak.text

    fun status(s: String): Color = when (s) {
        "running" -> gold
        "waiting" -> candle
        "done" -> good
        else -> muted
    }
}

/** Fraunces for headings, Nunito Sans for everything else (both SIL Open Font Licence, in res/font). */
val Fraunces = FontFamily(Font(R.font.fraunces_600, FontWeight.SemiBold), Font(R.font.fraunces_700, FontWeight.Bold))
val NunitoSans = FontFamily(
    Font(R.font.nunito_sans_400, FontWeight.Normal), Font(R.font.nunito_sans_600, FontWeight.SemiBold),
    Font(R.font.nunito_sans_700, FontWeight.Bold),
)
/** The headings' face (the screens call it Serif). */
val Serif = Fraunces

private fun scheme(p: OakPalette, dark: Boolean) = (if (dark) darkColorScheme() else lightColorScheme()).copy(
    primary = p.accent,
    onPrimary = p.accentText,
    primaryContainer = p.accentSoft,
    onPrimaryContainer = p.text,
    secondary = p.candle,
    onSecondary = p.accentText,
    secondaryContainer = p.accentSoft,
    onSecondaryContainer = p.text,
    tertiary = p.good,
    background = p.background,
    onBackground = p.text,
    surface = p.background,
    onSurface = p.text,
    surfaceVariant = p.sunken,
    onSurfaceVariant = p.muted,
    surfaceContainerLowest = p.sunken,
    surfaceContainerLow = p.surface,
    surfaceContainer = p.surface,
    surfaceContainerHigh = p.surface,
    surfaceContainerHighest = p.surface,
    outline = p.oakLine,
    outlineVariant = p.oakLine,
    error = p.bad,
    onError = p.accentText,
    inverseSurface = p.text,
    inverseOnSurface = p.background,
)

private val base = Typography()
private fun typography(p: OakPalette) = Typography(
    displayLarge = base.displayLarge.copy(fontFamily = Fraunces, fontWeight = FontWeight.Bold),
    displayMedium = base.displayMedium.copy(fontFamily = Fraunces, fontWeight = FontWeight.Bold),
    displaySmall = base.displaySmall.copy(fontFamily = Fraunces, fontWeight = FontWeight.Bold, color = p.text),
    headlineLarge = base.headlineLarge.copy(fontFamily = Fraunces, fontWeight = FontWeight.Bold),
    headlineMedium = base.headlineMedium.copy(fontFamily = Fraunces, fontWeight = FontWeight.Bold),
    headlineSmall = base.headlineSmall.copy(fontFamily = Fraunces, fontWeight = FontWeight.Bold),
    titleLarge = base.titleLarge.copy(fontFamily = Fraunces, fontWeight = FontWeight.Bold),
    titleMedium = base.titleMedium.copy(fontFamily = Fraunces, fontWeight = FontWeight.SemiBold),
    titleSmall = base.titleSmall.copy(fontFamily = Fraunces, fontWeight = FontWeight.SemiBold),
    bodyLarge = base.bodyLarge.copy(fontFamily = NunitoSans),
    bodyMedium = base.bodyMedium.copy(fontFamily = NunitoSans),
    bodySmall = base.bodySmall.copy(fontFamily = NunitoSans),
    labelLarge = base.labelLarge.copy(fontFamily = NunitoSans, fontWeight = FontWeight.Bold),
    labelMedium = base.labelMedium.copy(fontFamily = NunitoSans, fontWeight = FontWeight.SemiBold),
    labelSmall = base.labelSmall.copy(fontFamily = NunitoSans, fontWeight = FontWeight.SemiBold, letterSpacing = 0.6.sp),
)

/** Small capitals with wide spacing, as the desktop's section labels. */
val Label: TextStyle
    get() = TextStyle(fontFamily = NunitoSans, fontSize = 12.sp, letterSpacing = 1.4.sp, fontWeight = FontWeight.Bold, color = Hall.muted)

/** The dark palette on a true-black floor (saves battery on OLED screens); the cards stay a warm, very dark oak. */
val BlackOak = OakPalette(
    background = Color(0xFF000000), surface = Color(0xFF17110D), text = DarkOak.text, muted = DarkOak.muted,
    accent = DarkOak.accent, accentText = Color(0xFF000000), candle = DarkOak.candle, oakLine = Color(0xFF3A2C20),
    sunken = Color(0xFF0B0806), accentSoft = DarkOak.accentSoft, good = DarkOak.good, bad = DarkOak.bad, warn = DarkOak.warn,
)

/** [base] with the owner's [accent] and, when dark, true black. Amber on the usual floor is the palette itself. */
fun paletteFor(dark: Boolean, accent: Accent = Accent.AMBER, trueBlack: Boolean = false): OakPalette {
    val base = if (!dark) LightOak else if (trueBlack) BlackOak else DarkOak
    if (accent == Accent.AMBER) return base
    val a = Color(if (dark) accent.dark else accent.light)
    return OakPalette(
        background = base.background, surface = base.surface, text = base.text, muted = base.muted,
        accent = a, accentText = base.accentText, candle = base.candle, oakLine = base.oakLine, sunken = base.sunken,
        accentSoft = lerp(base.surface, a, if (dark) 0.22f else 0.18f),
        good = base.good, bad = base.bad, warn = base.warn,
    )
}

/** The comfort settings for the screens that read them (Live's detail, haptics); null outside the app. */
val LocalComfort = staticCompositionLocalOf<Comfort?> { null }

@Composable
fun RoundtableTheme(dark: Boolean = isSystemInDarkTheme(), content: @Composable () -> Unit) {
    val ctx = LocalContext.current
    val comfort = remember(ctx) { runCatching { Comfort.get(ctx) }.getOrNull() }
    val p = paletteFor(dark, comfort?.accent ?: Accent.AMBER, comfort?.trueBlack == true)
    if (Hall.palette !== p) Hall.palette = p
    val density = LocalDensity.current
    val scale = comfort?.textScale ?: 1f
    MaterialTheme(
        colorScheme = scheme(p, dark),
        typography = typography(p),
        shapes = Shapes(extraSmall = RoundedCornerShape(8.dp), small = RoundedCornerShape(12.dp), medium = RoundedCornerShape(14.dp),
            large = RoundedCornerShape(18.dp), extraLarge = RoundedCornerShape(24.dp)),
    ) {
        // text drawn straight on the page (not inside a Surface) uses the theme's text colour; the owner's text size
        // multiplies the phone's own
        CompositionLocalProvider(
            LocalContentColor provides p.text,
            LocalComfort provides comfort,
            LocalDensity provides if (scale == 1f) density else Density(density.density, density.fontScale * scale),
            content = content,
        )
    }
}

/** A short buzz at the owner's chosen strength (nothing when Haptics is off). */
@Composable
fun rememberHaptics(): () -> Unit {
    val view = LocalView.current
    val comfort = LocalComfort.current
    return remember(view, comfort) {
        {
            when (comfort?.haptics ?: Haptics.LIGHT) {
                Haptics.OFF -> {}
                Haptics.LIGHT -> view.performHapticFeedback(HapticFeedbackConstants.CLOCK_TICK)
                Haptics.STRONG -> view.performHapticFeedback(HapticFeedbackConstants.LONG_PRESS)
            }
        }
    }
}

/** The warm floor behind every screen, with a soft candle light from above. */
fun Modifier.hallBackground(): Modifier = this.background(Hall.bg).drawBehind {
    drawRect(Brush.radialGradient(listOf(Hall.candle.copy(alpha = 0.08f), Color.Transparent),
        center = Offset(size.width * 0.5f, -size.height * 0.05f), radius = size.maxDimension * 0.6f))
}

/** True when the phone asks for less motion (animations turned off in its settings). */
@Composable
fun reducedMotion(): Boolean {
    val ctx = LocalContext.current
    return remember(ctx) {
        runCatching { Settings.Global.getFloat(ctx.contentResolver, Settings.Global.ANIMATOR_DURATION_SCALE, 1f) == 0f }.getOrDefault(false)
    }
}

/** A slow, three-second candle flicker (0..1) for what needs the owner; steady when motion is reduced. */
@Composable
fun candleFlicker(): State<Float> {
    if (reducedMotion()) return remember { mutableStateOf(0.6f) }
    val t = rememberInfiniteTransition(label = "candle")
    return t.animateFloat(0.55f, 0.55f, infiniteRepeatable(keyframes {
        durationMillis = 3000
        0.55f at 0; 1f at 1050; 0.4f at 1800; 0.85f at 2400; 0.55f at 3000
    }, RepeatMode.Restart), label = "flicker")
}

/** An oak card (the desktop's cards). [highlight] lights it with the candle: only for what needs the owner. */
@Composable
fun Panel(modifier: Modifier = Modifier, highlight: Boolean = false, content: @Composable ColumnScope.() -> Unit) {
    val shape = RoundedCornerShape(18.dp)
    Column(
        modifier
            .background(Hall.panel, shape)
            .border(if (highlight) 2.dp else 1.dp, if (highlight) Hall.candle else Hall.line, shape)
            .padding(16.dp),
        content = content,
    )
}

/** A card for a decision or a question: the surface, a hairline oak edge, and a small seal in the corner. */
@Composable
fun Parchment(modifier: Modifier = Modifier, seal: Color = Hall.ember, content: @Composable ColumnScope.() -> Unit) {
    val shape = RoundedCornerShape(18.dp)
    Box(modifier) {
        Column(
            Modifier
                .fillMaxWidth()
                .background(Hall.parchment, shape)
                .border(BorderStroke(1.dp, Hall.line), shape)
                .drawBehind {
                    val r = 5.dp.toPx()
                    drawCircle(seal, r, Offset(size.width - 18.dp.toPx(), 18.dp.toPx()))
                }
                .padding(start = 18.dp, end = 30.dp, top = 16.dp, bottom = 16.dp),
        ) {
            CompositionLocalProvider(LocalContentColor provides Hall.ink) { content() }
        }
    }
}

/** Buttons on a card: the amber one for the main answer, an outline for the rest. */
object ParchmentButtons {
    @Composable fun main() = ButtonDefaults.buttonColors(containerColor = Hall.gold, contentColor = Hall.onAccent)
    @Composable fun other() = ButtonDefaults.outlinedButtonColors(contentColor = Hall.ink)
    val otherBorder: BorderStroke get() = BorderStroke(1.dp, Hall.line)
}
