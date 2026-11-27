package com.meztking.roundtable.data

import com.meztking.roundtable.net.ApiJson
import kotlinx.serialization.Serializable
import java.net.URLEncoder

/**
 * Proof for one finished task (the PC's GET /api/proof?path&task&inline=1, harness/proof.py): the app before and
 * after it, how much each picture changed, what a model that can see said (advice for the reviewer), and the tests.
 */
@Serializable
data class ProofSide(val commit: String = "", val dir: String = "", val pictures: Map<String, String> = emptyMap(),
                     val reused: Boolean = false, val note: String = "", val failed: String = "")

@Serializable
data class ProofPair(val kind: String = "", val before: String? = null, val after: String = "",
                     val change: Double? = null, val words: String = "")

@Serializable
data class ProofJudge(val looked: Boolean = false, val verdict: String? = null, val what_changed: String = "",
                      val problems: List<String> = emptyList(), val model: String = "", val cost_usd: Double = 0.0,
                      val words: String = "")

@Serializable
data class ProofTestSide(val ok: Boolean = false, val passed: Int? = null, val failed: Int? = null, val tail: String = "")

@Serializable
data class ProofTests(val command: String = "", val before: ProofTestSide? = null, val after: ProofTestSide? = null,
                      val verdict: String? = null, val broke: List<String> = emptyList(), val words: String = "")

@Serializable
data class ProofLine(val id: String = "", val passed: Boolean? = null, val words: String = "", val optional: Boolean = false)

@Serializable
data class ProofImages(val before: Map<String, String> = emptyMap(), val after: Map<String, String> = emptyMap())

@Serializable
data class TaskProof(
    val found: Boolean = false,
    val task: String = "",
    val title: String = "",
    val at: String = "",
    val ok: Boolean? = null,
    val words: String = "",
    val before: ProofSide? = null,
    val after: ProofSide? = null,
    val pairs: List<ProofPair> = emptyList(),
    val tests: ProofTests? = null,
    val judge: ProofJudge? = null,
    val lines: List<ProofLine> = emptyList(),
    val lines_text: String = "",
    val images: ProofImages = ProofImages(),
) {
    /** The judge's verdict when a model looked (shows_it, does_not, cant_tell), else null. */
    val verdict: String? get() = judge?.takeIf { it.looked }?.verdict

    /** The mark beside the line: ✓ ✗ ? or – (nobody looked). */
    val mark: String get() = when (verdict) { "shows_it" -> "✓"; "does_not" -> "✗"; "cant_tell" -> "?"; else -> "–" }

    /** Each picture with its before and after as bytes (before null when the picture is new). */
    fun pictures(): List<ProofPicture> = pairs.mapNotNull { p ->
        val after = images.after[p.kind]?.let { Live.dataUrl(it) } ?: return@mapNotNull null
        ProofPicture(p.kind, Proof.name(p.kind), images.before[p.kind]?.let { Live.dataUrl(it) }, after, p.words)
    }
}

class ProofPicture(val kind: String, val label: String, val before: ByteArray?, val after: ByteArray, val words: String)

object Proof {
    private val NAMES = mapOf("desktop" to "Computer", "phone" to "Phone", "dark" to "Dark mode", "start" to "Start",
                              "middle" to "Playing")

    fun name(kind: String): String = NAMES[kind] ?: kind

    /** The PC's address for one task's proof, pictures included (for Api.feature("GET", ...)). */
    fun url(path: String, task: String): String =
        "/api/proof?inline=1&path=${URLEncoder.encode(path, "UTF-8")}&task=${URLEncoder.encode(task, "UTF-8")}"

    /** The details folded under "More": who looked and what it cost, and the versions compared. */
    fun moreLines(p: TaskProof): List<String> {
        val out = mutableListOf<String>()
        val j = p.judge
        if (j != null && j.model.isNotBlank()) out += "Looked at by ${j.model}" + (if (j.cost_usd > 0) " · $%.4f".format(j.cost_usd) else "")
        val b = p.before
        if (b != null && b.commit.isNotBlank()) out += "Before: version ${b.commit.take(8)}" + (if (b.reused) " (pictures kept from earlier)" else "")
        val a = p.after
        if (a != null && a.commit.isNotBlank()) out += "After: version ${a.commit.take(8)}"
        return out
    }

    fun parse(json: String?): TaskProof? =
        json?.takeIf { it.isNotBlank() }?.let { runCatching { ApiJson.decodeFromString(TaskProof.serializer(), it) }.getOrNull() }

    /** The tooltip-like line under the mark, in plain words. */
    fun markWords(verdict: String?): String = when (verdict) {
        "shows_it" -> "A model that can see thinks the pictures show what the task asked for."
        "does_not" -> "A model that can see doesn't think so. It's advice: the reviewer decides."
        "cant_tell" -> "A model that can see couldn't tell from the pictures."
        else -> "Nobody looked at the pictures."
    }
}
