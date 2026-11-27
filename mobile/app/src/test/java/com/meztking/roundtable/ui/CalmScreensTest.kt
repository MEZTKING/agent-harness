package com.meztking.roundtable.ui

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import com.github.takahirom.roborazzi.captureRoboImage
import com.meztking.roundtable.data.Ask
import com.meztking.roundtable.data.AskOption
import com.meztking.roundtable.data.LiveShots
import com.meztking.roundtable.data.LiveView
import com.meztking.roundtable.data.Mode
import com.meztking.roundtable.data.PlanDoc
import com.meztking.roundtable.data.PlanView
import com.meztking.roundtable.data.SeatView
import com.meztking.roundtable.data.SessionStep
import com.meztking.roundtable.data.SessionSummary
import com.meztking.roundtable.data.SessionTask
import com.meztking.roundtable.data.StatusDoc
import com.meztking.roundtable.net.Progress
import com.meztking.roundtable.ui.theme.RoundtableTheme
import com.meztking.roundtable.ui.theme.hallBackground
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode
import java.time.Instant
import java.time.temporal.ChronoUnit

/** The Plan and Live tabs short first (made-up projects): a plan waiting for the owner, and a finished one. */
@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(sdk = [34], qualifiers = "w400dp-h860dp-xhdpi", application = android.app.Application::class)
class CalmScreensTest {
    private fun ago(h: Long) = Instant.now().minus(h, ChronoUnit.HOURS).toString()

    @org.junit.Before fun steady() {
        android.provider.Settings.Global.putFloat(org.robolectric.RuntimeEnvironment.getApplication().contentResolver,
            android.provider.Settings.Global.ANIMATOR_DURATION_SCALE, 0f)
    }

    private fun shot(name: String, content: @Composable () -> Unit) {
        captureRoboImage("${System.getProperty("screenshots.dir") ?: "build/screenshots"}/calm-$name.png") {
            RoundtableTheme { Box(Modifier.fillMaxSize().hallBackground()) { content() } }
        }
    }

    private val taskNames = listOf("Copy the player into both apps", "One copy step for both", "The Android app around the player",
        "Keep the songs when the app closes", "Back button and screen turning", "The Windows app around the player", "Windows menus and keys",
        "An icon for both", "Build the phone file", "Build the Windows file", "Check both start", "Check saved songs survive",
        "Check the queue survives", "Pictures of both", "How to install", "Last checks")

    /** A finished plan as an older Roundtable published it: the heading was the builders' brief. */
    private val finishedMd = """
        _Plan status: done · plan ready · updated ${ago(5)} by Roundtable Hold_

        # Plan v2: Also ship the player as an Android app (APK) and a Windows app (EXE), so it runs off the web too. One code base: both wrap the same index.html, css and js. Android: a small native Kotlin app with WebViewAssetLoader. Desktop: Electron 45, electron-builder 26.

        The player gains two wrappers that load the same web files; a copy step keeps them in sync and a check mode stops drift.

        Estimate: about ${'$'}3.45, about 45 minutes

        Settings: budget about ${'$'}3.45; balanced (chosen) about ${'$'}3.45; quality about ${'$'}31.33

        ## In scope
        - scripts/sync-web.js — the single copy step (targets android and desktop, --check mode) plus a root package.json
        - android/ — Gradle project, WebViewAssetLoader, back button
        - desktop/ — Electron 45 main.js, preload.js, electron-builder 26

        ## Out of scope
        - App stores

        ## Decisions
        ### Which phones? [C1]
        - Android only (chosen): One phone app. {a}
        - Android and iPhone: Two phone apps. {b}

        ## Critique by a second model
        - [medium] supplies the concrete persistence evidence the owner asked for in T4

        ## Tasks
${taskNames.mapIndexed { i, t -> "        - [T${i + 1}] done $t (coder)" }.joinToString("\n")}
    """.trimIndent()

    private val waitingMd = """
        _Plan status: waiting for the owner · plan ready: 1 choice · updated ${ago(1)} by Roundtable Hold_

        # Lantern timer for the kitchen

        A timer page with a glowing lantern that chimes when time is up.

        Estimate: about ${'$'}0.85 and 18 minutes

        ## The builders' brief (version 1)
        A lantern timer web app: index.html, app.js and style.css, no frameworks, one chime from a short WAV.

        ## Sets of models
        Settings: budget about ${'$'}0.31; balanced (chosen) about ${'$'}0.85; quality about ${'$'}6.10

        ## In scope
        - A start button
        - A chime

        ## Decisions
        ### What happens when time is up? [C1]
        - Ring once (recommended): A single chime. {a}
        - Ring until stopped: Keeps going until you press Stop. {b}

        ## Tasks
        - [T1] pending The timer page (coder)
        - [T2] pending The lantern glow (coder)
        - [T3] pending The chime (coder)
    """.trimIndent()

    private val words = com.meztking.roundtable.data.PlanWords("Lantern timer for the kitchen", "A timer page with a glowing lantern that chimes when time is up.",
        "Waiting for you: 1 choice", listOf("1 choice"), "about \$0.85 and 18 minutes")

    private val ask = Ask("choose:C1", "decision", "lantern-timer", header = "Choice", question = "What happens when time is up?",
        options = listOf(AskOption("a", "Ring once", "A single chime."), AskOption("b", "Ring until stopped", "Keeps going until you press Stop.")),
        recommended = "a", stamp = "s1")

    private val done = SeatView("music-box", "done", "done · 16 of 16", "A made-up music player", lastActivity = ago(5), progress = Progress(16, 16))
    private val waiting = SeatView("lantern-timer", "waiting", "Waiting for you", "A made-up timer", lastActivity = ago(1), hasPlan = true)
    private val noStatus = Load(StatusDoc())

    @Test fun planWaiting() = shot("plan-waiting") {
        ProjectScreen(ProjectUi("lantern-timer", waiting, Mode.HUB, "me", noStatus, Load(PlanView(PlanDoc.parse(waitingMd), canApprove = true, words = words)),
            Load(), asks = Load(listOf(ask))), ProjectActions(), initialTab = 1)
    }

    @Test fun planFinished() = shot("plan-finished") {
        ProjectScreen(ProjectUi("music-box", done, Mode.HUB, "me", noStatus, Load(PlanView(PlanDoc.parse(finishedMd))), Load()), ProjectActions(), initialTab = 1)
    }

    private fun picture(w: Int, h: Int): ByteArray {
        val bmp = android.graphics.Bitmap.createBitmap(w, h, android.graphics.Bitmap.Config.ARGB_8888)
        val c = android.graphics.Canvas(bmp)
        val p = android.graphics.Paint()
        c.drawColor(0xFF1E2230.toInt())
        p.color = 0xFFE0A050.toInt(); c.drawCircle(w * 0.3f, h * 0.45f, h * 0.22f, p)
        p.color = 0xFF3A4258.toInt(); for (i in 0 until 5) c.drawRect(w * 0.58f, h * (0.2f + i * 0.13f), w * 0.92f, h * (0.28f + i * 0.13f), p)
        val out = java.io.ByteArrayOutputStream(); bmp.compress(android.graphics.Bitmap.CompressFormat.PNG, 100, out); return out.toByteArray()
    }

    private val shots = LiveView(LiveShots("T16", ago(5), "Last checks", mapOf("desktop" to "latest-desktop.jpg", "phone" to "latest-phone.jpg")),
        mapOf("desktop" to picture(640, 400), "phone" to picture(195, 422)),
        SessionSummary("music-box", ago(5), SessionTask("T16", "Last checks", "coder", "done", 0.02, "done", listOf(
            SessionStep("say", "Both apps start and keep the queue."), SessionStep("tool", "● Run `npm run check`"),
            SessionStep("review", "✓ Approved: every check met.")))))

    @Test fun liveFinishedWithPictures() = shot("live-finished-pictures") {
        ProjectScreen(ProjectUi("music-box", done, Mode.HUB, "me", noStatus, Load(PlanView(PlanDoc.parse(finishedMd))), Load(), live = Load(shots)),
            ProjectActions(), initialTab = 3)
    }

    @Test fun liveFinishedWithout() = shot("live-finished-none") {
        ProjectScreen(ProjectUi("music-box", done, Mode.HUB, "me", noStatus, Load(PlanView(PlanDoc.parse(finishedMd))), Load(), live = Load(LiveView())),
            ProjectActions(), initialTab = 3)
    }
}
