package com.meztking.roundtable.data

/**
 * A project's plan (plans/<project>.md, written by Roundtable Hold's plandoc.render_markdown),
 * with the parts the owner answers pulled out: decisions and their options, questions, ideas
 * and don'ts, each with the id that the hub commands need. Everything else stays markdown.
 */
data class PlanDoc(
    /** waiting for the owner | approved, building | done (or whatever the hub writes) */
    val state: String = "",
    val summaryLine: String = "",
    val updated: String = "",
    val title: String = "",
    val intro: List<Md> = emptyList(),
    val decisions: List<Decision> = emptyList(),
    val questions: List<Question> = emptyList(),
    val ideas: List<Idea> = emptyList(),
    val donts: List<Dont> = emptyList(),
    /** Every other section, in order, as markdown blocks. */
    val sections: List<StatusDoc.Section> = emptyList(),
) {
    data class Option(val id: String?, val label: String, val detail: String, val cost: String, val recommended: Boolean, val chosen: Boolean)
    data class Decision(val id: String?, val question: String, val options: List<Option>, val why: String)
    data class Question(val id: String?, val text: String, val answer: String)
    data class Idea(val id: String?, val state: String, val text: String, val why: String)
    data class Dont(val id: String?, val text: String)

    val waitingForOwner: Boolean get() = state.contains("waiting", ignoreCase = true)
    val approved: Boolean get() = state.contains("approved", ignoreCase = true) || state.equals("done", ignoreCase = true)
    val openChoices: Int get() = decisions.count { d -> d.options.none { it.chosen } } + questions.count { it.answer.isBlank() }

    companion object {
        private val statusRe = Regex("^_?Plan status:\\s*(.*?)_?$")
        private val bracketId = Regex("\\s*\\[([A-Za-z0-9_.-]+)\\]$")
        private val costRe = Regex("\\s*\\[([^\\]]+)\\]$")
        private val ideaRe = Regex("^\\[(\\w+)\\]\\s+(.*)$")

        fun parse(md: String): PlanDoc {
            if (md.isBlank()) return PlanDoc()
            val lines = md.replace("\r\n", "\n").lines().toMutableList()
            var state = ""; var summary = ""; var updated = ""
            val first = lines.indexOfFirst { it.isNotBlank() }
            if (first >= 0) statusRe.find(lines[first].trim())?.let { m ->
                val parts = m.groupValues[1].split(" · ").map { it.trim() }
                state = parts.firstOrNull().orEmpty()
                val upd = parts.lastOrNull { it.startsWith("updated ") }
                updated = upd?.removePrefix("updated ")?.substringBefore(" ").orEmpty()
                summary = parts.drop(1).filter { it != upd }.joinToString(" · ")
                lines[first] = ""
            }
            val blocks = Markdown.parse(lines.joinToString("\n"))

            var title = ""
            val intro = mutableListOf<Md>()
            val sections = mutableListOf<Pair<String, MutableList<Md>>>()
            for (b in blocks) {
                when {
                    b is Md.Heading && b.level == 1 && title.isEmpty() && sections.isEmpty() -> title = b.text
                    b is Md.Heading && b.level == 2 -> sections += b.text to mutableListOf()
                    sections.isEmpty() -> intro += b
                    else -> sections.last().second += b
                }
            }

            val decisions = mutableListOf<Decision>()
            val questions = mutableListOf<Question>()
            val ideas = mutableListOf<Idea>()
            val donts = mutableListOf<Dont>()
            val rest = mutableListOf<StatusDoc.Section>()
            for ((name, body) in sections) {
                when (name.lowercase()) {
                    "decisions" -> decisions += decisionsIn(body)
                    "questions for the owner" -> body.filterIsInstance<Md.Item>().forEach { item ->
                        val text = item.text.substringBefore("\n").let { Markdown.splitId(it) }
                        // later lines: "Answers: …" (the ready answers to tap) and "Answer: …" (the owner's)
                        val answer = item.text.lines().drop(1).map { it.trim() }
                            .firstOrNull { it.startsWith("Answer:") }?.removePrefix("Answer:")?.trim().orEmpty()
                        questions += Question(item.id ?: text.second, text.first.trim(), answer)
                    }
                    "ideas" -> body.filterIsInstance<Md.Item>().forEach { item ->
                        val m = ideaRe.find(item.text)
                        val (text, why) = splitWhy(m?.groupValues?.get(2) ?: item.text)
                        ideas += Idea(item.id, m?.groupValues?.get(1) ?: "open", text, why)
                    }
                    "don't", "dont", "don’t" -> {
                        body.filterIsInstance<Md.Item>().forEach { donts += Dont(it.id, it.text) }
                        rest += StatusDoc.Section(name, body)
                    }
                    else -> rest += StatusDoc.Section(name.let { bracketId.replace(it, "") }, body)
                }
            }
            return PlanDoc(state, summary, updated, title, intro, decisions, questions, ideas, donts, rest)
        }

        private fun decisionsIn(body: List<Md>): List<Decision> {
            val out = mutableListOf<Decision>()
            var q: String? = null; var qid: String? = null; var why = ""
            val opts = mutableListOf<Option>()
            fun flush() {
                if (q != null) out += Decision(qid, q!!, opts.toList(), why)
                q = null; qid = null; why = ""; opts.clear()
            }
            for (b in body) when (b) {
                is Md.Heading -> {
                    flush()
                    val m = bracketId.find(b.text)
                    q = if (m != null) b.text.substring(0, m.range.first).trim() else b.text
                    qid = m?.groupValues?.get(1)
                }
                is Md.Item -> if (q != null) opts += option(b)
                is Md.Paragraph -> if (q != null && b.text.startsWith("Why:")) why = b.text.removePrefix("Why:").trim()
                else -> {}
            }
            flush()
            return out
        }

        /** "Label (recommended): detail [cost]" with the id already split off. */
        private fun option(item: Md.Item): Option {
            var s = item.text
            var cost = ""
            costRe.find(s)?.let { cost = it.groupValues[1]; s = s.substring(0, it.range.first) }
            val head = s.substringBefore(": ")
            val detail = if (": " in s) s.substringAfter(": ").trim() else ""
            val recommended = head.endsWith("(recommended)")
            val chosen = head.endsWith("(chosen)")
            val label = head.removeSuffix("(recommended)").removeSuffix("(chosen)").trim()
            return Option(item.id, label, detail, cost, recommended, chosen)
        }

        /** "text (why)" -> (text, why). */
        private fun splitWhy(s: String): Pair<String, String> {
            val t = s.trim()
            if (!t.endsWith(")")) return t to ""
            var depth = 0
            for (i in t.indices.reversed()) {
                if (t[i] == ')') depth++ else if (t[i] == '(') { depth--; if (depth == 0) return t.substring(0, i).trim() to t.substring(i + 1, t.length - 1).trim() }
            }
            return t to ""
        }
    }
}
