package com.meztking.roundtable.data

import com.meztking.roundtable.net.ApiJson
import kotlinx.serialization.Serializable
import java.net.URLEncoder

/** One output a notebook cell kept: text, an error, or a picture (base64, from the file itself). */
@Serializable
data class NbOutput(val kind: String = "text", val text: String = "", val mime: String = "", val data: String = "")

@Serializable
data class NbCell(val type: String = "raw", val source: String = "", val count: Int? = null, val outputs: List<NbOutput> = emptyList())

@Serializable
data class ArchiveEntry(val name: String = "", val size: Long = 0, val folder: Boolean = false, val link: Boolean = false,
                        val unsafe: Boolean = false)

@Serializable
data class OfficeRun(val text: String = "", val bold: Boolean = false, val italic: Boolean = false)

/** A Word file's heading, paragraph, list or table, in order. */
@Serializable
data class OfficeBlock(val type: String = "", val text: String = "", val level: Int = 0, val runs: List<OfficeRun> = emptyList(),
                       val items: List<List<OfficeRun>> = emptyList(), val rows: List<List<String>> = emptyList()) {
    val plain: String get() = text.ifBlank { runs.joinToString("") { it.text } }
}

@Serializable
data class OfficeSheet(val name: String = "", val rows: List<List<String>> = emptyList())

@Serializable
data class OfficeSlide(val n: Int = 0, val title: String = "", val lines: List<String> = emptyList())

/**
 * A richer look at a file (GET /api/files/preview, preview.py): a notebook's cells, an archive's list of contents,
 * an office file's text, or the media type of a video or a song (handed to the phone's own player). [preview] is ""
 * when there's no richer view. Nothing in it is ever run or unpacked.
 */
@Serializable
data class FilePreview(
    val file: String = "", val name: String = "", val size: Long = 0, val preview: String = "", val words: String = "",
    val failed: Boolean = false, val mime: String = "",
    // a notebook
    val language: String = "", val cells: List<NbCell> = emptyList(), val more: Int = 0,
    // an archive
    val format: String = "", val entries: List<ArchiveEntry> = emptyList(), val count: Int = 0, val total: Long = 0, val unsafe: Int = 0,
    // an office file (a simple view)
    val office: String = "", val blocks: List<OfficeBlock> = emptyList(), val sheets: List<OfficeSheet> = emptyList(),
    val slides: List<OfficeSlide> = emptyList(),
) {
    val media: Boolean get() = preview == "video" || preview == "audio"

    /** The line to show when it can't be shown: the PC's own sentence when it worked, a plain one when it failed
     * (a failure's words may hold the PC's raw error). */
    val note: String get() = when {
        failed -> "This file can't be shown here. Save a copy to open it with another app."
        else -> words
    }
}

object Preview {
    fun url(path: String, file: String) = "/api/files/preview?path=${e(path)}&file=${e(file)}"
    fun parse(json: String): FilePreview = ApiJson.decodeFromString(FilePreview.serializer(), json)

    /** Which files to ask about: those the plain open can't show (the PC knows their kind by the name). */
    fun worthAsking(name: String): Boolean {
        val low = name.lowercase()
        return EXTS.any { low.endsWith(it) }
    }

    private val EXTS = listOf(".ipynb", ".zip", ".jar", ".apk", ".whl", ".aar", ".war", ".tar", ".tgz", ".tar.gz", ".tbz2",
        ".tar.bz2", ".txz", ".tar.xz", ".docx", ".xlsx", ".pptx", ".mp4", ".webm", ".ogv", ".m4v", ".mov", ".mp3", ".wav",
        ".ogg", ".oga", ".m4a", ".flac", ".aac", ".opus", ".nupkg", ".vsix", ".xpi")

    /** "12 files, 3.4 MB in all", and how many names point outside the folder. */
    fun archiveLine(p: FilePreview): String {
        val n = if (p.count > 0) p.count else p.entries.size
        val base = "$n item${if (n == 1) "" else "s"}, ${Files.size(p.total)} in all"
        return if (p.unsafe > 0) "$base. ${p.unsafe} would land outside the folder: never unpacked here." else "$base."
    }

    private fun e(s: String) = URLEncoder.encode(s, "UTF-8")
}

/** Find in a file: the lines holding the words (any case), with their numbers, at most [max] of them. */
object FindInFile {
    data class Hit(val number: Int, val line: String, val start: Int, val end: Int)

    fun hits(text: String, words: String, max: Int = 500): List<Hit> {
        val w = words.trim()
        if (w.isEmpty()) return emptyList()
        val out = mutableListOf<Hit>()
        text.lineSequence().forEachIndexed { i, line ->
            if (out.size >= max) return out
            val at = line.indexOf(w, ignoreCase = true)
            if (at >= 0) out += Hit(i + 1, line, at, at + w.length)
        }
        return out
    }

    fun countLine(hits: List<Hit>, words: String): String = when {
        words.isBlank() -> ""
        hits.isEmpty() -> "Not found in this file."
        hits.size == 1 -> "Found on 1 line."
        else -> "Found on ${hits.size} lines."
    }
}
