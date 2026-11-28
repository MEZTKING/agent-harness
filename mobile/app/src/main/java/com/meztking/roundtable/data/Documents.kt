package com.meztking.roundtable.data

import com.meztking.roundtable.net.ApiJson
import kotlinx.serialization.Serializable
import java.net.URLEncoder

/** One of the owner's documents (GET /api/documents): what it is, who may use it, and a note when its words can't be read. */
@Serializable
data class DocumentItem(val id: String = "", val title: String = "", val name: String = "", val kind: String = "",
                        val kind_words: String = "", val who: String = "", val note: String = "", val private_words: String = "") {
    val heading: String get() = title.ifBlank { name.ifBlank { id } }

    /** "Folder · All projects · Never leaves this computer". */
    val line: String get() = listOf(kind_words, who, private_words).filter { it.isNotBlank() }.joinToString(" · ")
}

@Serializable
data class DocumentsList(val documents: List<DocumentItem> = emptyList(), val words: String = "", val removed: Int = 0)

/** Your documents on the phone, read only: adding or removing a folder stays on the PC. */
object Documents {
    const val URL = "/api/documents"
    const val ADD_ON_PC = "Add a folder on your PC: Settings, Your documents."

    fun parse(json: String): DocumentsList = ApiJson.decodeFromString(DocumentsList.serializer(), json)
}

/** One sound a project bought or made (GET /api/sounds). */
@Serializable
data class SoundItem(val name: String = "", val file: String = "", val kind: String = "", val service: String = "",
                     val cost_usd: Double? = null, val prompt: String = "", val seconds: Double? = null, val made_in_code: Boolean = false,
                     val licence: String = "") {
    val heading: String get() = name.ifBlank { file.substringAfterLast('/').substringBeforeLast('.') }

    /** "Bought from ElevenLabs · $0.08", "Made in code". */
    val line: String get() = when {
        made_in_code -> Words.t("Made in code")
        service.isNotBlank() -> Words.t("Made by {who}", "who" to service) + (cost_usd?.let { " · " + Money.usd(it) } ?: "")
        else -> cost_usd?.let { Money.usd(it) }.orEmpty()
    }
}

/** A project's sounds, what they cost and the cap ("$0.42 of $2"). Read only on the phone: Make it again stays on the PC. */
@Serializable
data class SoundsView(val sounds: List<SoundItem> = emptyList(), val spent_usd: Double = 0.0, val cap_usd: Double? = null,
                      val service: String = "", val words: String = "")

object Sounds {
    fun url(path: String) = "/api/sounds?path=${URLEncoder.encode(path, "UTF-8")}"

    fun parse(json: String): SoundsView = ApiJson.decodeFromString(SoundsView.serializer(), json)

    /** "$0.42 of $2 used"; just what was spent when there's no cap. */
    fun spendLine(v: SoundsView): String {
        val cap = v.cap_usd
        return if (cap != null) Words.t("{spent} of {cap} used", "spent" to Money.usd(v.spent_usd), "cap" to whole(cap))
        else Words.t("{spent} used", "spent" to Money.usd(v.spent_usd))
    }

    /** "$2" for a whole number of dollars, else as Money writes it. */
    private fun whole(v: Double): String = if (v > 0 && v % 1.0 == 0.0) "$" + v.toLong() else Money.usd(v)

    /** The files the phone's player can open (the project's own sound files only). */
    fun playable(s: SoundItem): Boolean {
        val f = s.file.lowercase()
        return f.isNotBlank() && !f.startsWith("/") && ".." !in f && "://" !in f &&
            listOf(".mp3", ".wav", ".ogg", ".oga", ".m4a", ".flac", ".aac", ".opus").any { f.endsWith(it) }
    }
}
