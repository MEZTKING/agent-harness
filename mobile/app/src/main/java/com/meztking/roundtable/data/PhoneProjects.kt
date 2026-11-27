package com.meztking.roundtable.data

import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import java.io.InputStream
import java.io.OutputStream
import java.util.Base64
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream

/**
 * Projects on the phone (DS-55, This phone only): the app's side of `phoneprojects.py`'s three routes. [call] is
 * the This phone API's feature call (`Api.feature`), so it is tested against a fake.
 */
class PhoneProjects(private val call: suspend (method: String, path: String, body: String?) -> String) {
    private val json = Json { ignoreUnknownKeys = true }

    @Serializable data class Done(val name: String = "", val files: Int = 0)
    @Serializable private data class Start(val upload: String = "", val part: Int = 1_000_000)
    @Serializable private data class Share(val id: String = "", val size: Long = 0, val parts: Int = 1)
    @Serializable private data class Part(val data: String = "")

    /** Clone [url] (https). [useKey]: a private repository, read with the phone's project key (never the hub's). */
    suspend fun clone(url: String, name: String = "", useKey: Boolean = false): Done =
        json.decodeFromString(Done.serializer(), call("POST", "/api/projects/clone", buildJsonObject {
            put("url", url.trim()); put("name", name.trim()); put("use_key", useKey)
        }.toString()))

    /** Send a zip in parts and unpack it as the new project [name]. [onSent] gets the bytes sent so far. */
    suspend fun import(name: String, zip: InputStream, onSent: (Long) -> Unit = {}): Done {
        val start = json.decodeFromString(Start.serializer(), call("POST", "/api/projects/import", "{}"))
        val buf = ByteArray(start.part.coerceIn(1024, 1_000_000))
        var index = 0
        var sent = 0L
        zip.use { input ->
            while (true) {
                val n = input.readNBytesCompat(buf)
                if (n <= 0 && index > 0) break
                call("POST", "/api/projects/import", buildJsonObject {
                    put("upload", start.upload); put("index", index); put("data", Base64.getEncoder().encodeToString(buf.copyOf(n.coerceAtLeast(0))))
                }.toString())
                sent += n.coerceAtLeast(0); index++; onSent(sent)
                if (n < buf.size) break
            }
        }
        return json.decodeFromString(Done.serializer(), call("POST", "/api/projects/import", buildJsonObject {
            put("upload", start.upload); put("name", name.trim()); put("done", true)
        }.toString()))
    }

    /** The project [name] as a zip (no `.harness`, `.git` or secret-named files: the harness leaves them out) into [out]. */
    suspend fun share(name: String, out: OutputStream): Long {
        val s = json.decodeFromString(Share.serializer(), call("GET", "/api/projects/share?name=" + java.net.URLEncoder.encode(name, "UTF-8"), null))
        var total = 0L
        out.use { o ->
            for (i in 0 until s.parts) {
                val p = json.decodeFromString(Part.serializer(), call("GET", "/api/projects/share?id=${s.id}&index=$i", null))
                val bytes = Base64.getDecoder().decode(p.data)
                o.write(bytes); total += bytes.size
            }
        }
        return total
    }

    companion object {
        /** A picked folder is zipped in the app, then sent like a zip. At most this many bytes and files. */
        const val MAX_BYTES = 300L * 1024 * 1024
        const val MAX_FILES = 20_000

        /** A plain project name from a picked file or folder ("my-game.zip" → "my-game"). */
        fun nameFrom(display: String): String =
            display.substringAfterLast('/').removeSuffix(".zip").removeSuffix(".git").replace(Regex("[^A-Za-z0-9 ._-]"), "-").trim('-', '.', ' ').take(80)

        /**
         * Zip a picked folder ([root]) into [out]: names checked (never `..`, `/` or empty), hidden `.harness`
         * folders left out, and refused past the caps. Returns the files written.
         */
        fun zipFolder(root: FolderSource, out: OutputStream, maxBytes: Long = MAX_BYTES, maxFiles: Int = MAX_FILES): Int {
            var files = 0
            var bytes = 0L
            ZipOutputStream(out).use { zip ->
                fun walk(node: FolderSource.Node, prefix: String) {
                    for (child in root.children(node)) {
                        val n = child.name
                        if (n.isEmpty() || n == "." || n == ".." || '/' in n || '\\' in n || n == ".harness") continue
                        val path = prefix + n
                        if (child.isFolder) { walk(child, "$path/"); continue }
                        if (++files > maxFiles) throw ProjectTooBig("That folder has too many files (more than $maxFiles).")
                        zip.putNextEntry(ZipEntry(path))
                        root.open(child).use { input ->
                            val buf = ByteArray(64 * 1024)
                            while (true) {
                                val r = input.read(buf)
                                if (r < 0) break
                                bytes += r
                                if (bytes > maxBytes) throw ProjectTooBig("That folder is too big to import (more than ${maxBytes / (1024 * 1024)} MB).")
                                zip.write(buf, 0, r)
                            }
                        }
                        zip.closeEntry()
                    }
                }
                walk(root.root, "")
            }
            return files
        }

        private fun InputStream.readNBytesCompat(buf: ByteArray): Int {
            var off = 0
            while (off < buf.size) {
                val r = read(buf, off, buf.size - off)
                if (r < 0) break
                off += r
            }
            return off
        }
    }
}

class ProjectTooBig(message: String) : java.io.IOException(message)

/** A folder the owner picked (on the device: the Storage Access Framework's tree), walked without the network. */
interface FolderSource {
    data class Node(val id: String, val name: String, val isFolder: Boolean)
    val root: Node
    fun children(node: Node): List<Node>
    fun open(node: Node): InputStream
}
