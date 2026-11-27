package com.meztking.roundtable.ui.theme

import android.app.Activity
import android.provider.Settings
import androidx.compose.runtime.SideEffect
import androidx.core.view.WindowCompat
import android.view.HapticFeedbackConstants
import com.meztking.roundtable.data.Accent
import com.meztking.roundtable.data.Comfort
import com.meztking.roundtable.data.Haptics
import com.meztking.roundtable.data.Look
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.tween
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.lerp
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.unit.Density
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.animateFloat
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
 * "Eclipse": the same tokens as the desktop app (style.css): black with a thin ring of light, violet for the
 * accent, ember orange only for what needs the owner. Three looks: Eclipse (the usual), Pitch (pure black for
 * OLED screens) and Ash (light, for sunlight; never the default). Every text colour reads at 4.5:1 or better
 * on the page and on a card; [lineStrong] (field and control borders) at 3:1.
 */
class Palette(
    val background: Color, val surface: Color, val sunken: Color, val raised: Color,
    val text: Color, val muted: Color, val accent: Color, val accentText: Color,
    /** What needs the owner (the old candle): ember orange. */
    val flare: Color,
    /** Decorative lines (card edges, dividers). */
    val line: Color,
    /** Borders of fields and controls. */
    val lineStrong: Color,
    val accentSoft: Color, val good: Color, val bad: Color, val warn: Color,
)

val Eclipse = Palette(
    background = Color(0xFF0A0A0F), surface = Color(0xFF14141C), sunken = Color(0xFF07070B), raised = Color(0xFF1C1C28),
    text = Color(0xFFECEBF4), muted = Color(0xFFA3A2B8), accent = Color(0xFFA78BFA), accentText = Color(0xFF0A0A0F),
    flare = Color(0xFFFF9D4D), line = Color(0xFF2A2A3A), lineStrong = Color(0xFF6B6A85),
    accentSoft = Color(0xFF2A2440), good = Color(0xFF7FD6A4), bad = Color(0xFFFF7A85), warn = Color(0xFFF2C14E),
)

/** Eclipse on pure black (saves battery on OLED screens); cards stay a shade above the floor. */
val Pitch = Palette(
    background = Color(0xFF000000), surface = Color(0xFF0F0F16), sunken = Color(0xFF000000), raised = Color(0xFF181822),
    text = Eclipse.text, muted = Eclipse.muted, accent = Eclipse.accent, accentText = Color(0xFF000000),
    flare = Eclipse.flare, line = Color(0xFF24243A), lineStrong = Eclipse.lineStrong,
    accentSoft = Color(0xFF221C36), good = Eclipse.good, bad = Eclipse.bad, warn = Eclipse.warn,
)

/** The light look, for sunlight and for anyone who reads better on light. */
val Ash = Palette(
    background = Color(0xFFF1F0F5), surface = Color(0xFFFFFFFF), sunken = Color(0xFFE6E5EE), raised = Color(0xFFFFFFFF),
    text = Color(0xFF14141C), muted = Color(0xFF55546A), accent = Color(0xFF5B3FD6), accentText = Color(0xFFFFFFFF),
    flare = Color(0xFFB3480A), line = Color(0xFFD9D8E3), lineStrong = Color(0xFF77768E),
    accentSoft = Color(0xFFE6E0FA), good = Color(0xFF1F6B45), bad = Color(0xFFB3202F), warn = Color(0xFF7A5200),
)

/**
 * The colours every screen uses. The names are older than Eclipse, so the screens didn't change; each reads the
 * palette that [RoundtableTheme] picked.
 */
object Hall {
    var palette by mutableStateOf(Eclipse)
    private val p get() = palette

    val bg get() = p.background
    val bgDeep get() = p.sunken
    val panel get() = p.surface
    val panelHi get() = p.raised
    val field get() = p.sunken
    val text get() = p.text
    val muted get() = p.muted
    val line get() = p.line
    val lineStrong get() = p.lineStrong
    val lineGold get() = p.line
    val gold get() = p.accent
    val goldBright get() = p.accent
    val goldDim get() = p.muted
    val amber get() = p.flare
    val accentSoft get() = p.accentSoft
    val good get() = p.good
    val bad get() = p.bad
    val ember get() = p.bad
    val warn get() = p.warn
    /** Cards for decisions and questions: the surface and the text on it. */
    val parchment get() = p.surface
    val parchmentLo get() = p.sunken
    val ink get() = p.text
    val inkSoft get() = p.muted
    val code get() = p.sunken
    /** Text on a filled accent button. */
    val onAccent get() = p.accentText
    /** The flare: only on what needs the owner. */
    val candle get() = p.flare
    val flare get() = p.flare
    /** Text drawn on the Ring's dark disc, which stays dark in every look. */
    val onWood = Color(0xFFECEBF4)
    /** The Ring's disc: the night inside the eclipse, in every look. */
    val disc = Color(0xFF07070B)

    /** Text that reads on [c] when it is used as a filled background. */
    fun on(c: Color): Color = if (c.luminance() > 0.4f) Ash.text else Eclipse.text

    fun status(s: String): Color = when (s) {
        "running" -> gold
        "waiting" -> candle
        "done" -> good
        else -> muted
    }
}

/**
 * Space Grotesk for headings, Inter for everything else, JetBrains Mono for code (all three SIL Open Font
 * Licence, static weights in res/font made from the fontsource 5.3.0 Latin files).
 */
val SpaceGrotesk = FontFamily(Font(R.font.space_grotesk_600, FontWeight.SemiBold), Font(R.font.space_grotesk_700, FontWeight.Bold))
val Inter = FontFamily(
    Font(R.font.inter_400, FontWeight.Normal), Font(R.font.inter_600, FontWeight.SemiBold), Font(R.font.inter_700, FontWeight.Bold),
)
val Mono = FontFamily(Font(R.font.jetbrains_mono_400, FontWeight.Normal))
/** The headings' face (the screens call it Serif, from the old look). */
val Serif = SpaceGrotesk

private fun scheme(p: Palette, dark: Boolean) = (if (dark) darkColorScheme() else lightColorScheme()).copy(
    primary = p.accent,
    onPrimary = p.accentText,
    primaryContainer = p.accentSoft,
    onPrimaryContainer = p.text,
    secondary = p.flare,
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
    surfaceContainerHigh = p.raised,
    surfaceContainerHighest = p.raised,
    outline = p.lineStrong,
    outlineVariant = p.line,
    error = p.bad,
    onError = p.accentText,
    inverseSurface = p.text,
    inverseOnSurface = p.background,
)

private val base = Typography()
private fun typography(p: Palette) = Typography(
    displayLarge = base.displayLarge.copy(fontFamily = SpaceGrotesk, fontWeight = FontWeight.Bold, letterSpacing = (-1).sp),
    displayMedium = base.displayMedium.copy(fontFamily = SpaceGrotesk, fontWeight = FontWeight.Bold, letterSpacing = (-0.8).sp),
    displaySmall = base.displaySmall.copy(fontFamily = SpaceGrotesk, fontWeight = FontWeight.Bold, color = p.text, letterSpacing = (-0.6).sp),
    headlineLarge = base.headlineLarge.copy(fontFamily = SpaceGrotesk, fontWeight = FontWeight.Bold, letterSpacing = (-0.5).sp),
    headlineMedium = base.headlineMedium.copy(fontFamily = SpaceGrotesk, fontWeight = FontWeight.Bold, letterSpacing = (-0.4).sp),
    headlineSmall = base.headlineSmall.copy(fontFamily = SpaceGrotesk, fontWeight = FontWeight.Bold, letterSpacing = (-0.3).sp),
    titleLarge = base.titleLarge.copy(fontFamily = SpaceGrotesk, fontWeight = FontWeight.Bold, letterSpacing = (-0.2).sp),
    titleMedium = base.titleMedium.copy(fontFamily = SpaceGrotesk, fontWeight = FontWeight.SemiBold, letterSpacing = (-0.1).sp),
    titleSmall = base.titleSmall.copy(fontFamily = SpaceGrotesk, fontWeight = FontWeight.SemiBold),
    bodyLarge = base.bodyLarge.copy(fontFamily = Inter),
    bodyMedium = base.bodyMedium.copy(fontFamily = Inter),
    bodySmall = base.bodySmall.copy(fontFamily = Inter),
    labelLarge = base.labelLarge.copy(fontFamily = Inter, fontWeight = FontWeight.SemiBold),
    labelMedium = base.labelMedium.copy(fontFamily = Inter, fontWeight = FontWeight.SemiBold),
    labelSmall = base.labelSmall.copy(fontFamily = Inter, fontWeight = FontWeight.SemiBold, letterSpacing = 0.6.sp),
)

/** Small capitals with wide spacing, as the desktop's section labels. */
val Label: TextStyle
    get() = TextStyle(fontFamily = Inter, fontSize = 12.sp, letterSpacing = 1.4.sp, fontWeight = FontWeight.SemiBold, color = Hall.muted)

/** The palette for a [look] (Eclipse when none) with the owner's [accent]. Violet on any look is the palette itself. */
fun paletteFor(look: Look = Look.ECLIPSE, accent: Accent = Accent.VIOLET): Palette {
    val base = when (look) { Look.ECLIPSE -> Eclipse; Look.PITCH -> Pitch; Look.ASH -> Ash }
    if (accent == Accent.VIOLET) return base
    val a = Color(if (look.dark) accent.dark else accent.light)
    return Palette(
        background = base.background, surface = base.surface, sunken = base.sunken, raised = base.raised,
        text = base.text, muted = base.muted, accent = a, accentText = base.accentText, flare = base.flare,
        line = base.line, lineStrong = base.lineStrong, accentSoft = lerp(base.surface, a, if (look.dark) 0.2f else 0.16f),
        good = base.good, bad = base.bad, warn = base.warn,
    )
}

/** The older way to ask: [dark] with or without [trueBlack]. */
fun paletteFor(dark: Boolean, accent: Accent = Accent.VIOLET, trueBlack: Boolean = false): Palette =
    paletteFor(if (!dark) Look.ASH else if (trueBlack) Look.PITCH else Look.ECLIPSE, accent)

/** The comfort settings for the screens that read them (Live's detail, haptics); null outside the app. */
val LocalComfort = staticCompositionLocalOf<Comfort?> { null }

/**
 * The app's theme. The look comes from Comfort (Eclipse when nothing is chosen); [dark] is for previews and tests:
 * false shows Ash, true shows the chosen dark look (Eclipse or Pitch).
 */
@Composable
fun RoundtableTheme(dark: Boolean? = null, content: @Composable () -> Unit) {
    val ctx = LocalContext.current
    val comfort = remember(ctx) { runCatching { Comfort.get(ctx) }.getOrNull() }
    val chosen = comfort?.look ?: Look.ECLIPSE
    val look = when (dark) {
        null -> chosen
        false -> Look.ASH
        true -> if (chosen == Look.ASH) Look.ECLIPSE else chosen
    }
    val p = paletteFor(look, comfort?.accent ?: Accent.VIOLET)
    if (Hall.palette !== p) Hall.palette = p
    // the status and navigation bar icons follow the look, not the phone's own light or dark setting
    val view = LocalView.current
    SideEffect {
        val window = (view.context as? Activity)?.window ?: return@SideEffect
        WindowCompat.getInsetsController(window, view).run {
            isAppearanceLightStatusBars = !look.dark
            isAppearanceLightNavigationBars = !look.dark
        }
    }
    val density = LocalDensity.current
    val scale = comfort?.textScale ?: 1f
    MaterialTheme(
        colorScheme = scheme(p, look.dark),
        typography = typography(p),
        shapes = Shapes(extraSmall = RoundedCornerShape(6.dp), small = RoundedCornerShape(8.dp), medium = RoundedCornerShape(10.dp),
            large = RoundedCornerShape(10.dp), extraLarge = RoundedCornerShape(16.dp)),
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

/** True when the app shows a dark look (Eclipse or Pitch). */
val isDarkLook: Boolean get() = Hall.palette.background.luminance() < 0.4f

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

/** The floor behind every screen: plain, so the glow stays for what needs the owner. */
fun Modifier.hallBackground(): Modifier = this.background(Hall.bg)

/** True when the phone asks for less motion (animations turned off in its settings). */
@Composable
fun reducedMotion(): Boolean {
    val ctx = LocalContext.current
    return remember(ctx) {
        runCatching { Settings.Global.getFloat(ctx.contentResolver, Settings.Global.ANIMATOR_DURATION_SCALE, 1f) == 0f }.getOrDefault(false)
    }
}

/** The Ring breathing: 0..1 and back on a slow 6-second cycle; steady when motion is reduced. */
@Composable
fun ringBreath(): State<Float> {
    if (reducedMotion()) return remember { mutableStateOf(0.5f) }
    val t = rememberInfiniteTransition(label = "ring")
    return t.animateFloat(0f, 1f, infiniteRepeatable(tween(3000, easing = FastOutSlowInEasing), RepeatMode.Reverse), label = "breath")
}

/**
 * The flare on what needs the owner: it lights up over 400 ms, then breathes with the Ring (0..1). Steady when
 * motion is reduced.
 */
@Composable
fun flare(): State<Float> {
    if (reducedMotion()) return remember { mutableStateOf(0.8f) }
    val lit = remember { Animatable(0f) }
    LaunchedEffect(Unit) { lit.animateTo(1f, tween(400, easing = FastOutSlowInEasing)) }
    val breath = ringBreath()
    return remember { derivedStateOf { lit.value * (0.65f + 0.35f * breath.value) } }
}

/** A card (the desktop's cards). [highlight] edges it with the flare: only for what needs the owner. */
@Composable
fun Panel(modifier: Modifier = Modifier, highlight: Boolean = false, content: @Composable ColumnScope.() -> Unit) {
    val shape = RoundedCornerShape(10.dp)
    Column(
        modifier
            .background(Hall.panel, shape)
            .border(if (highlight) 2.dp else 1.dp, if (highlight) Hall.candle else Hall.line, shape)
            .padding(16.dp),
        content = content,
    )
}

/** A card for a decision or a question: the surface, a hairline edge, and a small seal in the corner. */
@Composable
fun Parchment(modifier: Modifier = Modifier, seal: Color = Hall.ember, content: @Composable ColumnScope.() -> Unit) {
    val shape = RoundedCornerShape(10.dp)
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

/** Buttons on a card: the filled accent one for the main answer, an outline for the rest. */
object ParchmentButtons {
    @Composable fun main() = ButtonDefaults.buttonColors(containerColor = Hall.gold, contentColor = Hall.onAccent)
    @Composable fun other() = ButtonDefaults.outlinedButtonColors(contentColor = Hall.ink)
    val otherBorder: BorderStroke get() = BorderStroke(1.dp, Hall.lineStrong)
}
