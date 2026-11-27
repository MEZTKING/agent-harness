package com.meztking.roundtable.data

import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.util.Base64
import java.util.zip.ZipInputStream

class PhoneProjectsTest {
    /** A fake of phoneprojects.py's routes: parts must come in order, each a whole part but the last. */
    private class Fake(val part: Int) {
        val got = ByteArrayOutputStream()
        var indexes = mutableListOf<Int>()
        var finished: String? = null
        val shared = ByteArray(2500) { (it % 251).toByte() }

        suspend fun call(method: String, path: String, body: String?): String {
            val o = body?.let { Json.parseToJsonElement(it).jsonObject }
            return when {
                path == "/api/projects/import" && o?.get("upload") == null -> """{"upload": "abcdabcdabcdabcd", "part": $part}"""
                path == "/api/projects/import" && o?.get("done") != null -> { finished = o["name"]!!.jsonPrimitive.content; """{"name": "$finished", "files": 3}""" }
                path == "/api/projects/import" -> {
                    assertEquals(0, got.size() % part)
                    indexes += o!!["index"]!!.jsonPrimitive.content.toInt()
                    got.write(Base64.getDecoder().decode(o["data"]!!.jsonPrimitive.content)); "{}"
                }
                path.startsWith("/api/projects/share?name=") -> """{"id": "f00df00df00df00d", "size": ${shared.size}, "parts": 3}"""
                path.startsWith("/api/projects/share?id=") -> {
                    val i = path.substringAfter("index=").toInt()
                    """{"data": "${Base64.getEncoder().encodeToString(shared.copyOfRange(i * 1000, minOf(shared.size, (i + 1) * 1000)))}"}"""
                }
                else -> error(path)
            }
        }
    }

    @Test
    fun `a zip goes in whole parts, in order, and comes back whole`() = runBlocking {
        for (size in listOf(0, 1, 1024, 1025, 5000)) {
            val fake = Fake(1024)
            val data = ByteArray(size) { it.toByte() }
            val done = PhoneProjects(fake::call).import("Tiny game", ByteArrayInputStream(data))
            assertEquals("Tiny game", done.name)
            assertEquals(data.toList(), fake.got.toByteArray().toList())
            assertEquals((0 until fake.indexes.size).toList(), fake.indexes)
        }
        val fake = Fake(1024)
        val out = ByteArrayOutputStream()
        assertEquals(2500L, PhoneProjects(fake::call).share("demo", out))
        assertEquals(fake.shared.toList(), out.toByteArray().toList())
    }

    private class Tree(val files: Map<String, ByteArray>) : FolderSource {
        override val root = FolderSource.Node("", "My Game!", true)
        override fun children(node: FolderSource.Node): List<FolderSource.Node> {
            val prefix = if (node.id.isEmpty()) "" else node.id + "/"
            return files.keys.filter { it.startsWith(prefix) }.map { it.removePrefix(prefix).substringBefore('/') }.distinct().map { n ->
                FolderSource.Node(prefix + n, n, files.keys.none { it == prefix + n })
            }
        }
        override fun open(node: FolderSource.Node) = ByteArrayInputStream(files.getValue(node.id))
    }

    @Test
    fun `a picked folder is zipped without the harness's folder or odd names, within the caps`() {
        val tree = Tree(mapOf("main.py" to "x".toByteArray(), "src/a.kt" to "y".toByteArray(), ".harness/plan.json" to "{}".toByteArray(), "../evil" to "z".toByteArray()))
        val out = ByteArrayOutputStream()
        assertEquals(2, PhoneProjects.zipFolder(tree, out))
        val names = ZipInputStream(ByteArrayInputStream(out.toByteArray())).use { z -> generateSequence { z.nextEntry?.name }.toList() }
        assertEquals(listOf("main.py", "src/a.kt"), names.sorted())
        try { PhoneProjects.zipFolder(Tree(mapOf("big" to ByteArray(5000))), ByteArrayOutputStream(), maxBytes = 1000); fail() } catch (e: ProjectTooBig) {
            assertTrue(e.message!!.contains("too big"))
        }
        try { PhoneProjects.zipFolder(tree, ByteArrayOutputStream(), maxFiles = 1); fail() } catch (e: ProjectTooBig) { }
        assertEquals("My Game", PhoneProjects.nameFrom("My Game!"))
        assertEquals("tiny-game", PhoneProjects.nameFrom("/storage/Download/tiny-game.zip"))
    }
}
