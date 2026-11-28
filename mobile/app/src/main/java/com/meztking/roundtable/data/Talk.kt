package com.meztking.roundtable.data

/**
 * Talk on the phone: Android's own speech recogniser hears the owner, the words go to the planner as a question, and
 * the phone's own voice reads the answer. A command can be spoken too ("slash stop", "command retry T2"): one that
 * asks first (spends, deletes, builds) always waits for a tap on the screen; only one with no "Are you sure?" may be
 * started by a spoken "yes".
 */
object Talk {
    /** What the speech recogniser heard, as a command line ("/retry T2"), when it names one of [commands]. */
    fun commandFrom(heard: String, commands: List<SlashCommand>): String? {
        val words = heard.trim().lowercase().replace(Regex("[.,!?]"), "").split(Regex("\\s+")).filter { it.isNotEmpty() }
        if (words.size < 2 || words[0] !in LEAD) return null
        val rest = words.drop(1)
        // the longest command name that the words start with ("accessible forms" for /accessible-forms)
        val hit = commands.sortedByDescending { it.name.length }.firstOrNull { c ->
            val parts = c.name.lowercase().split('-')
            rest.size >= parts.size && rest.take(parts.size) == parts
        } ?: return null
        val tail = rest.drop(hit.name.split('-').size).joinToString(" ").uppercaseTaskIds()
        return "/${hit.name}" + if (tail.isNotBlank()) " $tail" else ""
    }

    /** The command a line names, from [commands]. */
    fun commandOf(line: String, commands: List<SlashCommand>): SlashCommand? =
        commands.firstOrNull { it.name == line.trim().removePrefix("/").substringBefore(' ') }

    /** May a spoken "yes" start [c]? Only when it has no "Are you sure?" of its own. */
    fun mayStartBySaying(c: SlashCommand?): Boolean = c != null && !c.confirm

    fun isYes(heard: String): Boolean = heard.trim().lowercase().replace(Regex("[.,!?]"), "") in YES
    fun isNo(heard: String): Boolean = heard.trim().lowercase().replace(Regex("[.,!?]"), "") in NO

    /** What the phone says before listening for "yes". */
    fun askAloud(c: SlashCommand): String = "${c.words}. Say yes to do it, or no."

    /** A reply made fit to read aloud: no Markdown marks, no code blocks, not too long. */
    fun forSpeaking(reply: String, max: Int = 600): String {
        val noCode = reply.replace(Regex("```[\\s\\S]*?```"), " (some code, on the screen) ")
        val flat = Markdown.plain(noCode).replace(Regex("\\s+"), " ").trim()
        return if (flat.length > max) flat.take(max).substringBeforeLast(". ", flat.take(max)) + "." else flat
    }

    private val LEAD = setOf("slash", "command", "/")
    private val YES = setOf("yes", "yes please", "yeah", "yep", "do it", "go ahead", "ok", "okay")
    private val NO = setOf("no", "no thanks", "stop", "cancel", "don't", "nope")

    private fun String.uppercaseTaskIds() = replace(Regex("\\bt(\\d+)\\b")) { "T" + it.groupValues[1] }
}
