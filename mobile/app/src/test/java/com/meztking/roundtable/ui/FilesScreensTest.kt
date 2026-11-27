package com.meztking.roundtable.ui

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.foundation.layout.padding
import androidx.compose.ui.unit.dp
import com.github.takahirom.roborazzi.captureRoboImage
import com.meztking.roundtable.data.CommandLog
import com.meztking.roundtable.data.CommandRun
import com.meztking.roundtable.data.Crumb
import com.meztking.roundtable.data.FileItem
import com.meztking.roundtable.data.FolderView
import com.meztking.roundtable.data.OpenedFile
import com.meztking.roundtable.ui.theme.RoundtableTheme
import com.meztking.roundtable.ui.theme.hallBackground
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode
import java.time.Instant
import java.time.temporal.ChronoUnit

/** The Files screen: a folder, each kind of file, the command log and a project elsewhere (made-up project). */
@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(sdk = [34], qualifiers = "w400dp-h860dp-xhdpi", application = android.app.Application::class)
class FilesScreensTest {
    private fun ago(m: Long) = Instant.now().minus(m, ChronoUnit.MINUTES).toString()

    private fun shot(name: String, content: @Composable () -> Unit) {
        captureRoboImage("${System.getProperty("screenshots.dir") ?: "build/screenshots"}/$name.png") {
            RoundtableTheme { Box(Modifier.fillMaxSize().hallBackground()) { content() } }
        }
    }

    private val folder = FolderView(dir = "", crumbs = listOf(Crumb("Project", "")), test_command = "pytest -q", items = listOf(
        FileItem("src", "src", true, 0, "folder"), FileItem("tests", "tests", true, 0, "folder"),
        FileItem("README.md", "README.md", false, 812, "markdown"), FileItem("prices.csv", "prices.csv", false, 140, "csv"),
        FileItem("settings.json", "settings.json", false, 96, "json"), FileItem("logo.png", "logo.png", false, 20_480, "image"),
        FileItem("guide.pdf", "guide.pdf", false, 310_000, "pdf"), FileItem("app.py", "app.py", false, 2_300, "code")))

    @Test fun aFolder() = shot("40-files-folder") { FilesBody(FilesUi("lantern-app", folder = Load(folder)), FilesActions()) }

    @Test fun code() = shot("41-files-code") {
        FilesBody(FilesUi("lantern-app", opened = Load(OpenedFile(file = "app.py", name = "app.py", size = 2300, kind = "code", lang = "python",
            text = "# A made-up lantern\nimport time\n\n\ndef light(wick: int = 3) -> str:\n    \"\"\"Light it.\"\"\"\n    if wick > 0:\n        return \"lit\"\n    return None\n"))),
            FilesActions())
    }

    @Test fun markdown() = shot("42-files-markdown") {
        FilesBody(FilesUi("lantern-app", opened = Load(OpenedFile(file = "README.md", name = "README.md", size = 812, kind = "markdown",
            text = "# Lantern\n\nA made-up app that **lights** a lantern.\n\n- Tap to light\n- Hold to dim\n\n| Wick | Hours |\n|---|---|\n| short | 2 |\n| long | 6 |\n"))),
            FilesActions())
    }

    @Test fun tableAndJson() = shot("43-files-csv-json") {
        androidx.compose.foundation.layout.Column {
            Box(Modifier.weight(1f)) {
                FilesBody(FilesUi("lantern-app", opened = Load(OpenedFile(file = "prices.csv", name = "prices.csv", size = 140, kind = "csv",
                    rows = listOf(listOf("item", "price", "stock"), listOf("wick", "0.40", "120"), listOf("oil", "3.10", "14"))))), FilesActions())
            }
            Box(Modifier.weight(1f)) {
                FilesBody(FilesUi("lantern-app", opened = Load(OpenedFile(file = "settings.json", name = "settings.json", size = 96, kind = "json",
                    text = """{"name": "lantern", "colours": ["amber", "red"], "dim": {"after": 30, "to": 0.2}}"""))), FilesActions())
            }
        }
    }

    @Test fun commands() = shot("44-files-commands") {
        val log = CommandLog(test_command = "pytest -q", can_run = true, commands = listOf(
            CommandRun(ago(2), "T2", "Dim the lantern", "coder", "task", "pytest -q", 1, false, words = "failed (exit code 1)",
                output = "exit code: 1\n--- stdout ---\nFAILED tests/test_dim.py::test_dim - assert 0.5 == 0.2\n1 failed, 6 passed"),
            CommandRun(ago(5), "T2", "Dim the lantern", "checks", "checks", "pytest -q", null, true, words = "the checks passed"),
            CommandRun(ago(9), "T1", "Light the lantern", "reviewer", "task", "python -m lantern --check", 0, true, words = "worked"),
            CommandRun(ago(40), "", "", "you", "tests", "pytest -q", 0, true, words = "you ran the tests: worked")))
        FilesBody(FilesUi("lantern-app", tab = 1, log = Load(log), said = "The tests passed."), FilesActions())
    }

    @Test fun aCommandOpened() = shot("44b-files-command-open") {
        androidx.compose.foundation.layout.Column(androidx.compose.ui.Modifier.padding(16.dp)) {
            CommandRowForTest(CommandRun(ago(2), "T2", "Dim the lantern", "coder", "task", "pytest -q", 1, false, words = "failed (exit code 1)",
                output = "exit code: 1\n--- stdout ---\nFAILED tests/test_dim.py::test_dim - assert 0.5 == 0.2\n1 failed, 6 passed"))
        }
    }

    @Test fun projectElsewhere() = shot("45-files-elsewhere") {
        FilesBody(FilesUi("tide-clock", elsewhere = "These files are on your PC. Connect this phone to it (Settings, Your PC) to see them."), FilesActions())
    }
}
