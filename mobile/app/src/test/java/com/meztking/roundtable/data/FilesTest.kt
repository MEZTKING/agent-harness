package com.meztking.roundtable.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Files in the app: the PC's answers read, the command log's words, JSON folded and code coloured (made-up projects). */
class FilesTest {
    @Test fun readsAFolderAndWhereTheFilesAre() {
        val v = Files.folder("""{"here": true, "path": "C:/lab/lantern", "dir": "src", "crumbs": [{"name": "Project", "dir": ""}, {"name": "src", "dir": "src"}],
            "items": [{"name": "app.py", "path": "src/app.py", "folder": false, "size": 2048, "kind": "code"}], "more": 0, "test_command": "pytest -q"}""")
        assertEquals("src/app.py", v.items.single().path)
        assertEquals(listOf("", "src"), v.crumbs.map { it.dir })
        assertEquals("2.0 KB", Files.size(v.items.single().size))
        val away = Files.folder("""{"here": false, "words": "This project's files are on Laptop.", "machine_name": "Laptop"}""")
        assertFalse(away.here)
        assertEquals("This project's files are on Laptop.", away.words)
    }

    @Test fun readsAnOpenedFileAndItsBytes() {
        val f = Files.opened("""{"here": true, "file": "logo.png", "name": "logo.png", "size": 3, "kind": "image", "data": "AQID", "too_big": false}""")
        assertEquals(listOf<Byte>(1, 2, 3), f.bytes()!!.toList())
        assertEquals("image/png", Files.mimeOf(f))
        val csv = Files.opened("""{"kind": "csv", "rows": [["name", "count"], ["wick", "3"]]}""")
        assertEquals("wick", csv.rows[1][0])
        assertNull(Files.opened("""{"kind": "text", "too_big": true, "words": "too big"}""").bytes())
    }

    @Test fun theCommandLogInPlainWords() {
        val log = Files.log("""{"here": true, "test_command": "pytest -q", "can_run": true, "why_not": "", "commands": [
            {"at": "2026-11-27T10:03:00Z", "task": "T1", "task_title": "Light the wick", "who": "coder", "kind": "task", "command": "pytest -q",
             "exit_code": 1, "passed": false, "words": "failed (exit code 1)", "output": "1 failed"},
            {"at": "2026-11-27T10:02:00Z", "task": "T1", "who": "reviewer", "kind": "task", "command": "ls", "exit_code": 0, "passed": true, "words": "worked"},
            {"at": "2026-11-27T10:00:00Z", "kind": "tests", "who": "you", "command": "pytest -q", "exit_code": null, "passed": null, "words": "no exit code recorded"}]}""")
        assertEquals("3 commands, 1 didn't work.", Files.summary(log))
        assertEquals(listOf("✗", "✓", "·"), log.commands.map { Files.mark(it) })
        assertTrue(Files.detail(log.commands[0]).startsWith("failed (exit code 1) · T1 Light the wick"))
        assertTrue(Files.detail(log.commands[1]).contains("Reviewer"))
        assertTrue(Files.detail(log.commands[2]).contains("You"))
        assertEquals("No commands yet: they show here as the tasks run them.", Files.summary(CommandLog()))
    }

    @Test fun jobsReadAsRunningOrTheirWords() {
        assertEquals("ab12", Files.jobId("""{"id": "ab12", "status": "running"}"""))
        assertEquals(Triple(true, "Finished.", false), Files.job("""{"id": "ab12", "status": "running"}"""))
        assertEquals(Triple(false, "The tests passed.", true), Files.job("""{"status": "done", "result": {"ok": true, "words": "The tests passed."}}"""))
        assertEquals(false, Files.job("""{"status": "failed", "error": "RuntimeError: x"}""").third)
    }

    @Test fun jsonFoldsAndCodeIsColoured() {
        val t = JsonTree.parse("""{"a": [1, 2], "b": {"c": true}, "d": "x"}""")!!
        assertEquals("{ 3 fields }", t.summary)
        assertEquals("[ 2 items ]", t.kids[0].summary)
        assertEquals("true", t.kids[1].kids[0].leaf)
        assertEquals("string", t.kids[2].kind)
        assertNull(JsonTree.parse("{\"a\": "))
        val code = "# a note\nx = \"hi\"  // not a comment in Python\nreturn 42"
        val parts = CodeColours.spans(code, "python").map { code.substring(it.start, it.end) to it.part }
        assertTrue(parts.contains("# a note" to CodeColours.Part.COMMENT))
        assertTrue(parts.contains("\"hi\"" to CodeColours.Part.STRING))
        assertTrue(parts.contains("return" to CodeColours.Part.KEYWORD))
        assertTrue(parts.contains("42" to CodeColours.Part.NUMBER))
        assertTrue(parts.none { it.first.startsWith("//") })
        assertTrue(CodeColours.spans("// a\nlet y = 1", "javascript").first().part == CodeColours.Part.COMMENT)
        assertTrue(CodeColours.spans("anything", "").isEmpty())
    }

    @Test fun savedNamesStayInTheShareFolder() {
        assertEquals("passwd", Files.safeName("../../etc/passwd"))
        assertEquals("env", Files.safeName(".env"))
        assertEquals("my_report.pdf", Files.safeName("my:report.pdf"))
    }
}
