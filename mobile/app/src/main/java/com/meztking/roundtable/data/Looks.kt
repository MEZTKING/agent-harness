package com.meztking.roundtable.data

import com.meztking.roundtable.net.ApiJson
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.net.URLEncoder

/** One look's pictures: how the app looks on a computer and on a phone, each a data address. */
data class LookPictures(val desktop: String = "", val phone: String = "") {
    /** The pictures to show, the computer's first. */
    val shown: List<String> get() = listOf(desktop, phone).filter { it.isNotBlank() }
}

/**
 * The look's pictures on its card (GET /api/plan/looks): only data addresses (`data:image/…;base64,…`) the PC sent with
 * the plan. A picture is never fetched from anywhere else: an address that isn't a data address is dropped.
 */
object Looks {
    fun url(path: String) = "/api/plan/looks?path=${URLEncoder.encode(path, "UTF-8")}"

    /** Only a picture carried in the answer itself; never an address to go and fetch. */
    fun safe(address: String?): Boolean {
        val a = address?.trim().orEmpty()
        return a.startsWith("data:image/") && ";base64," in a
    }

    /** `{"pictures": {look id: {desktop, phone}}}`; anything not a data address is left out. */
    fun parse(json: String): Map<String, LookPictures> {
        val o = runCatching { ApiJson.parseToJsonElement(json) as? JsonObject }.getOrNull() ?: return emptyMap()
        val pics = o["pictures"] as? JsonObject ?: return emptyMap()
        return pics.mapNotNull { (id, v) ->
            val p = v as? JsonObject ?: return@mapNotNull null
            fun one(k: String) = (p[k] as? JsonPrimitive)?.takeIf { it.isString }?.content?.takeIf { safe(it) }.orEmpty()
            LookPictures(one("desktop"), one("phone")).takeIf { it.shown.isNotEmpty() }?.let { id to it }
        }.toMap()
    }

    /** The pictures a card's own options carry (the new-project cards): an option whose `picture` is a data address. */
    fun fromOptions(ask: Ask): Map<String, LookPictures> =
        ask.options.mapNotNull { o -> o.picture?.takeIf { safe(it) }?.let { o.id to LookPictures(desktop = it) } }.toMap()

    /** The pictures for a card: those the plan sent for its options, then any its options carry themselves. */
    fun forCard(ask: Ask, plan: Map<String, LookPictures>): List<Pair<String, String>> {
        val all = plan + fromOptions(ask).filterKeys { it !in plan }
        return ask.options.flatMap { o -> (all[o.id] ?: o.picture?.let { all[it] })?.shown.orEmpty().map { o.label to it } }
    }

    /** The bytes of a data address, or null. */
    fun bytes(address: String): ByteArray? = if (!safe(address)) null else Live.dataUrl(address)
}
