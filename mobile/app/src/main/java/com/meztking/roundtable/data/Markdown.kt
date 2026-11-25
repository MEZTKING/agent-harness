package com.meztking.roundtable.data

/**
 * A small markdown reader for the hub's generated pages (status and plans). It knows what those
 * pages use: headings, paragraphs, bullet and checkbox lists (with nesting), numbered lists,
 * quotes, fenced code, rules and simple tables; inline bold, italic, code and links.
 */
sealed interface Md {
    data class Heading(val level: Int, val text: String) : Md
    data class Paragraph(val text: String) : Md
    /** A list item; [checked] is null for a plain bullet. [id] is a trailing `abc123` or {id} tag. */
    data class Item(val text: String, val checked: Boolean? = null, val depth: Int = 0, val number: Int? = null, val id: String? = null) : Md
    data class Quote(val text: String) : Md
    data class Code(val text: String) : Md
    data class Table(val rows: List<List<String>>) : Md
    data object Rule : Md
}

sealed interface Inline {
    val text: String
    data class Plain(override val text: String) : Inline
    data class Bold(override val text: String) : Inline
    data class Italic(override val text: String) : Inline
    data class Code(override val text: String) : Inline
    data class Link(override val text: String, val url: String) : Inline
}

object Markdown {
    private val itemRe = Regex("^(\\s*)(?:([-*+])|(\\d+)[.)])\\s+(.*)$")
    private val checkRe = Regex("^\\[([ xX])]\\s+(.*)$")
    private val trailingCodeId = Regex("\\s+`([0-9a-f]{4,12})`$")
    private val trailingBraceId = Regex("\\s+\\{([A-Za-z0-9_:.-]+)}$")

    fun parse(md: String): List<Md> {
        val out = mutableListOf<Md>()
        val para = StringBuilder()
        fun flush() {
            if (para.isNotBlank()) out += Md.Paragraph(para.toString().trim())
            para.clear()
        }
        val lines = md.replace("\r\n", "\n").lines()
        var i = 0
        while (i < lines.size) {
            val raw = lines[i]
            val line = raw.trimEnd()
            val t = line.trim()
            when {
                t.startsWith("```") -> {
                    flush()
                    val code = StringBuilder()
                    i++
                    while (i < lines.size && !lines[i].trim().startsWith("```")) { code.appendLine(lines[i]); i++ }
                    out += Md.Code(code.toString().trimEnd())
                }
                t.isEmpty() -> flush()
                t.startsWith("#") && t.trimStart('#').startsWith(" ") -> {
                    flush()
                    out += Md.Heading(t.takeWhile { it == '#' }.length.coerceAtMost(6), t.trimStart('#').trim())
                }
                t == "---" || t == "***" || t == "___" -> { flush(); out += Md.Rule }
                t.startsWith(">") -> { flush(); out += Md.Quote(t.removePrefix(">").trim()) }
                t.startsWith("|") && t.endsWith("|") -> {
                    flush()
                    val rows = mutableListOf<List<String>>()
                    while (i < lines.size && lines[i].trim().let { it.startsWith("|") && it.endsWith("|") }) {
                        val cells = lines[i].trim().removePrefix("|").removeSuffix("|").split("|").map { it.trim() }
                        if (!cells.all { it.matches(Regex(":?-{2,}:?")) }) rows += cells
                        i++
                    }
                    out += Md.Table(rows)
                    continue
                }
                itemRe.matches(line) -> {
                    flush()
                    val m = itemRe.find(line)!!
                    val depth = m.groupValues[1].replace("\t", "  ").length / 2
                    var text = m.groupValues[4]
                    var checked: Boolean? = null
                    checkRe.find(text)?.let { c -> checked = c.groupValues[1] != " "; text = c.groupValues[2] }
                    val (clean, id) = splitId(text)
                    out += Md.Item(clean, checked, depth, m.groupValues[3].toIntOrNull(), id)
                }
                raw.startsWith("  ") && out.lastOrNull() is Md.Item && para.isEmpty() -> {
                    // a continuation line of the previous list item ("  Answer: ...")
                    val last = out.removeAt(out.lastIndex) as Md.Item
                    out += last.copy(text = last.text + "\n" + t)
                }
                else -> { if (para.isNotEmpty()) para.append(' '); para.append(t) }
            }
            i++
        }
        flush()
        return out
    }

    /** "text `abc123`" or "text {Q1}" -> ("text", id). */
    fun splitId(text: String): Pair<String, String?> {
        trailingBraceId.find(text)?.let { return text.substring(0, it.range.first) to it.groupValues[1] }
        trailingCodeId.find(text)?.let { return text.substring(0, it.range.first) to it.groupValues[1] }
        return text to null
    }

    /** Inline spans: **bold**, __bold__, *italic*, _italic_, `code`, [text](url). */
    fun inline(s: String): List<Inline> {
        val out = mutableListOf<Inline>()
        val plain = StringBuilder()
        fun flush() { if (plain.isNotEmpty()) { out += Inline.Plain(plain.toString()); plain.clear() } }
        var i = 0
        while (i < s.length) {
            val c = s[i]
            fun closeAt(marker: String, from: Int): Int = s.indexOf(marker, from).takeIf { it > from } ?: -1
            when {
                c == '`' -> {
                    val end = closeAt("`", i + 1)
                    if (end > 0) { flush(); out += Inline.Code(s.substring(i + 1, end)); i = end + 1; continue }
                }
                (s.startsWith("**", i) || s.startsWith("__", i)) -> {
                    val m = s.substring(i, i + 2)
                    val end = closeAt(m, i + 2)
                    if (end > 0) { flush(); out += Inline.Bold(s.substring(i + 2, end)); i = end + 2; continue }
                }
                (c == '*' || c == '_') && (i == 0 || !s[i - 1].isLetterOrDigit()) && i + 1 < s.length && !s[i + 1].isWhitespace() -> {
                    val end = closeAt(c.toString(), i + 1)
                    if (end > 0 && (end + 1 >= s.length || !s[end + 1].isLetterOrDigit())) {
                        flush(); out += Inline.Italic(s.substring(i + 1, end)); i = end + 1; continue
                    }
                }
                c == '[' -> {
                    val close = s.indexOf("](", i)
                    val end = if (close > 0) s.indexOf(')', close) else -1
                    if (close > 0 && end > 0 && '\n' !in s.substring(i, end)) {
                        flush(); out += Inline.Link(s.substring(i + 1, close), s.substring(close + 2, end)); i = end + 1; continue
                    }
                }
            }
            plain.append(c)
            i++
        }
        flush()
        return out
    }

    /** Plain text with the inline marks removed, for previews and notifications. */
    fun plain(s: String): String = inline(s).joinToString("") { it.text }
}

/** One project's status page (status/<project>.md), split into the parts the app shows natively. */
data class StatusDoc(
    val title: String = "",
    val description: String = "",
    val updated: String = "",
    /** The sections after the header, each a heading and its blocks. */
    val sections: List<Section> = emptyList(),
) {
    data class Section(val title: String, val blocks: List<Md>)
    data class Todo(val text: String, val high: Boolean, val id: String?)

    fun section(name: String): Section? = sections.firstOrNull { it.title.equals(name, ignoreCase = true) }

    val todos: List<Todo>
        get() = section("To do")?.blocks.orEmpty().filterIsInstance<Md.Item>().map {
            val high = it.text.startsWith("**(high)**")
            Todo(it.text.removePrefix("**(high)**").trim(), high, it.id)
        }

    /** "Where we left off": when, what, and the next steps. */
    val leftOffAt: String
        get() = section("Where we left off")?.blocks?.filterIsInstance<Md.Paragraph>()?.firstOrNull()?.text
            ?.let { Regex("^\\*\\*([^*]+)\\*\\*").find(it)?.groupValues?.get(1) }.orEmpty()

    val leftOff: String
        get() = section("Where we left off")?.blocks?.filterIsInstance<Md.Paragraph>()?.firstOrNull()?.text
            ?.replace(Regex("^\\*\\*[^*]+\\*\\*:?\\s*"), "").orEmpty()

    val nextSteps: List<String>
        get() = section("Where we left off")?.blocks.orEmpty().filterIsInstance<Md.Item>().map { it.text }

    val isEmpty: Boolean get() = title.isEmpty() && sections.isEmpty()

    companion object {
        private val updatedRe = Regex("^_?Updated (\\S+)")

        fun parse(md: String): StatusDoc {
            if (md.isBlank()) return StatusDoc()
            val blocks = Markdown.parse(md)
            var title = ""
            val intro = mutableListOf<String>()
            var updated = ""
            val sections = mutableListOf<Section>()
            var cur: MutableList<Md>? = null
            var curTitle = ""
            for (b in blocks) {
                when {
                    b is Md.Heading && b.level == 1 && title.isEmpty() && cur == null -> title = b.text
                    b is Md.Heading && b.level == 2 -> {
                        if (cur != null) sections += Section(curTitle, cur)
                        curTitle = b.text; cur = mutableListOf()
                    }
                    cur == null && b is Md.Paragraph && updatedRe.containsMatchIn(b.text) ->
                        updated = updatedRe.find(b.text)!!.groupValues[1].trimEnd('_', '.', ',')
                    cur == null && b is Md.Paragraph -> intro += b.text
                    cur != null -> cur.add(b)
                }
            }
            if (cur != null) sections += Section(curTitle, cur)
            return StatusDoc(title, intro.joinToString("\n\n"), updated, sections)
        }
    }
}
