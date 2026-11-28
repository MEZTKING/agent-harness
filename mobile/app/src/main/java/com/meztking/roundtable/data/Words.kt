package com.meztking.roundtable.data

/**
 * The words the owner reads, in their language (wave 9). A stub with its frozen shape: wave 9's phone helper
 * fills it from `assets/lang/<code>.json`, the same files as the desktop's `ui/static/lang/`.
 *
 * The key is the British English sentence itself, with `{name}` holes for values, so a missing translation
 * shows English and nothing ever shows a code. Until a table is in use every sentence stays English.
 */
object Words {
    private val HOLE = Regex("""\{(\w+)\}""")
    private val RTL = setOf("ar", "he", "fa", "ur")

    @Volatile private var lang: String = "en-GB"
    @Volatile private var table: Map<String, String> = emptyMap()

    /** Whether the language in use is written right to left (Arabic, Hebrew, Persian, Urdu). */
    val rtl: Boolean get() = lang.substringBefore('-') in RTL

    /** Use [table] (`{"English sentence": "translated"}`) for [lang]. */
    fun use(lang: String, table: Map<String, String>) {
        this.table = table
        this.lang = lang
    }

    /** [english] in the language in use, its `{holes}` filled: a `name to value` pair fills that hole, anything
     *  else fills the next hole in order. A hole with no value is left as it is. */
    fun t(english: String, vararg args: Any): String {
        val text = table[english]?.takeIf { it.isNotBlank() } ?: english
        if (args.isEmpty()) return text
        val named = args.filterIsInstance<Pair<*, *>>().associate { (k, v) -> k.toString() to v.toString() }
        val inOrder = args.filter { it !is Pair<*, *> }.map { it.toString() }.iterator()
        return HOLE.replace(text) { m ->
            named[m.groupValues[1]] ?: if (inOrder.hasNext()) inOrder.next() else m.value
        }
    }
}
