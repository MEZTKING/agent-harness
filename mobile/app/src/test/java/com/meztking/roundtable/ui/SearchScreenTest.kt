package com.meztking.roundtable.ui

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import com.github.takahirom.roborazzi.captureRoboImage
import com.meztking.roundtable.data.FilePeek
import com.meztking.roundtable.data.Search
import com.meztking.roundtable.data.SearchHit
import com.meztking.roundtable.data.SearchOpen
import com.meztking.roundtable.data.SearchResult
import com.meztking.roundtable.ui.theme.RoundtableTheme
import com.meztking.roundtable.ui.theme.hallBackground
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode

/** The Search screen with made-up results (no network). With -Pscreenshots each is saved as a PNG. */
@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(sdk = [34], qualifiers = "w400dp-h860dp-xhdpi", application = android.app.Application::class)
class SearchScreenTest {
    private fun shot(name: String, content: @Composable () -> Unit) {
        captureRoboImage("${System.getProperty("screenshots.dir") ?: "build/screenshots"}/$name.png") {
            RoundtableTheme { Box(Modifier.fillMaxSize().hallBackground()) { content() } }
        }
    }

    private val hits = listOf(
        SearchHit("memory", "The owner wants the menu page first.", "Bakery site · Memory", open = SearchOpen("memory", path = "/made/up/bakery")),
        SearchHit("task", "Task T1: Menu page", "Bakery site · Tasks", "List every pastry. The reviewer said the sourdough row is missing from the menu.",
            open = SearchOpen("project", path = "/made/up/bakery", tab = "plan", task = "T1")),
        SearchHit("journal", "Use a warm colour for the menu header", "Bakery site · Journal (decision)", "Use a warm colour for the menu header, like the shop sign.",
            at = "2026-11-26T10:00:00Z", open = SearchOpen("journal", agent = "bakery-site")),
        SearchHit("file", "src/menu.js", "Bakery site · Files", "const menu = ['croissant', 'baguette'];", open = SearchOpen("file", path = "/made/up/bakery", file = "src/menu.js", line = 1)),
    )

    @Test fun results() = shot("search_results") {
        SearchView("menu", {}, 0, {}, Load(SearchResult("menu", hits, 4, "4 found.")), available = true, onBack = {}, onRetry = {}, onHit = {})
    }

    @Test fun emptyAndNotConnected() {
        shot("search_empty") { SearchView("", {}, 0, {}, Load(), available = true, onBack = {}, onRetry = {}, onHit = {}) }
        shot("search_no_pc") { SearchView("", {}, 0, {}, Load(), available = false, onBack = {}, onRetry = {}, onHit = {}) }
    }

    @Test fun aFileOpened() = shot("search_file") {
        SearchOpened(hits[3], Load(Opened.File(FilePeek("src/menu.js", 1, 1, listOf("const menu = ['croissant', 'baguette'];", "// opening hours: 8 till 4")))), onBack = {})
    }

    @Test fun aMemoryOpened() = shot("search_memory") {
        SearchOpened(hits[0], Load(Opened.Text("Bakery site: memory", "# Memory\n\n## Rules (never moved)\n- Prices are in pounds.\n\n## Pinned facts\n- The owner wants the menu page first.\n", "1 rule, 1 fact")), onBack = {})
    }

    @Test fun placesCoverEveryKind() {
        val all = Search.places.flatMap { it.second.split(",") }.filter { it.isNotBlank() }.toSet()
        assert(all.containsAll(listOf("plan", "task", "memory", "journal", "letter", "note", "file")))
    }
}
