package com.meztking.roundtable.data

import com.meztking.roundtable.net.ApiJson
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.put
import java.net.URLEncoder
import java.util.Base64

/** One choice on the plan's kind card. */
@Serializable
data class KindChoice(val id: String = "", val name: String = "", val recommended: Boolean = false)

@Serializable
data class KindExtra(val id: String = "", val name: String = "")

/** The first card on a plan (the plan document's `kind`, harness/kindstage.py `_kind_doc`). */
@Serializable
data class PlanKind(
    val id: String = "",
    val name: String = "",
    val question: String = "",
    val why: String = "",
    val confirmed: Boolean = false,
    val fixed: Boolean = false,
    val status: String = "trial",
    @kotlinx.serialization.SerialName("status_words") val statusWords: String = "",
    val extras: List<KindExtra> = emptyList(),
    val choices: List<KindChoice> = emptyList(),
    @kotlinx.serialization.SerialName("change_words") val changeWords: String = "",
)

@Serializable
data class KindNeed(val id: String = "", val name: String = "", val missing: Boolean = false)

@Serializable
data class KindProof(val id: String = "", val words: String = "", val optional: Boolean = false,
                     @kotlinx.serialization.SerialName("not_yet") val notYet: Boolean = false)

/** A kind in "What Roundtable can make" (kinds/model.py `card`). */
@Serializable
data class KindInfo(
    val id: String = "",
    val name: String = "",
    val blurb: String = "",
    val group: String = "",
    val status: String = "trial",
    @kotlinx.serialization.SerialName("status_words") val statusWords: String = "",
    val usable: Boolean = true,
    val typical: String = "",
    val missing: List<String> = emptyList(),
    val needs: List<KindNeed> = emptyList(),
    val examples: List<String> = emptyList(),
    val proof: List<KindProof> = emptyList(),
)

@Serializable
data class KindGroup(val group: String = "", val kinds: List<KindInfo> = emptyList())

@Serializable
data class KindsList(val groups: List<KindGroup> = emptyList(), val words: String = "")

/** A finished goal as one tile (kinds/gallery.py `summary`). */
@Serializable
data class GalleryTile(
    val project: String = "",
    val goal: String = "",
    val title: String = "",
    val kind: String = "",
    @kotlinx.serialization.SerialName("kind_name") val kindName: String = "",
    val line: String = "",
    val cover: String = "",
    val hidden: Boolean = false,
    val starred: Boolean = false,
    val path: String = "",
    val proven: Boolean = false,
)

@Serializable
data class GalleryList(val entries: List<GalleryTile> = emptyList(), val words: String = "")

@Serializable
data class GalleryPicture(val name: String = "", val src: String = "")

// ProofLine (id, passed, words, optional) is shared with the proof card: data/Proof.kt

@Serializable
data class GalleryModel(val task: String = "", val role: String = "", val model: String = "")

@Serializable
data class GalleryMore(val models: List<GalleryModel> = emptyList(), val commit: String = "")

@Serializable
data class GalleryOutput(val kind: String = "", val path: String = "")

/** One finished goal opened (kinds/gallery.py `one`). */
@Serializable
data class GalleryEntry(
    val project: String = "",
    val goal: String = "",
    val title: String = "",
    @kotlinx.serialization.SerialName("kind_name") val kindName: String = "",
    val line: String = "",
    val summary: String = "",
    val path: String = "",
    val hidden: Boolean = false,
    val starred: Boolean = false,
    val pictures: List<GalleryPicture> = emptyList(),
    val proof: List<ProofLine> = emptyList(),
    @kotlinx.serialization.SerialName("proof_words") val proofWords: String = "",
    val outputs: List<GalleryOutput> = emptyList(),
    val more: GalleryMore = GalleryMore(),
)

/** The phone's side of kinds and the Gallery: reading the PC's answers and building its requests. */
object Kinds {
    fun parseList(json: String): KindsList = runCatching { ApiJson.decodeFromString(KindsList.serializer(), json) }.getOrDefault(KindsList())
    fun parseGallery(json: String): GalleryList = runCatching { ApiJson.decodeFromString(GalleryList.serializer(), json) }.getOrDefault(GalleryList())
    fun parseEntry(json: String): GalleryEntry? = runCatching { ApiJson.decodeFromString(GalleryEntry.serializer(), json) }.getOrNull()

    /** The kind card from a plan document's JSON (its `kind`), or null when the plan has none. */
    fun planKind(planJson: String): PlanKind? = runCatching {
        val k = ApiJson.parseToJsonElement(planJson).jsonObject["kind"] as? JsonObject ?: return null
        ApiJson.decodeFromJsonElement(PlanKind.serializer(), k)
    }.getOrNull()

    private fun enc(s: String) = URLEncoder.encode(s, "UTF-8")
    fun galleryPath(hidden: Boolean = false) = if (hidden) "/api/gallery?hidden=1" else "/api/gallery"
    fun entryPath(project: String, goal: String) = "/api/gallery/one?project=${enc(project)}&goal=${enc(goal)}"
    fun flagBody(project: String, goal: String, key: String, value: Boolean): String =
        buildJsonObject { put("project", project); put("goal", goal); put(key, value) }.toString()
    fun setKindBody(path: String, id: String): String = buildJsonObject { put("path", path); put("id", id) }.toString()

    /** The proof lines as the owner reads them: "It opens with no errors ✓ · Played for a minute – not checked yet". */
    fun proofWords(lines: List<ProofLine>): String = lines.joinToString(" · ") {
        when (it.passed) {
            true -> "${it.words} ✓"
            false -> "${it.words} ✗"
            null -> "${it.words} – not checked yet"
        }
    }

    /** What the choice button says: "Yes, a website" for the guess not yet confirmed, else the kind's name. */
    fun choiceLabel(kind: PlanKind, c: KindChoice): String =
        if (c.recommended && !kind.confirmed) "Yes, a ${c.name.lowercase()}" else c.name

    /** A picture's bytes from its data URL ("data:image/png;base64,…"), or null. */
    fun pictureBytes(src: String): ByteArray? {
        val comma = src.indexOf(',')
        if (!src.startsWith("data:image/") || comma < 0 || !src.substring(0, comma).endsWith(";base64")) return null
        return runCatching { Base64.getDecoder().decode(src.substring(comma + 1)) }.getOrNull()
    }
}
