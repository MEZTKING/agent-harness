package com.meztking.roundtable.data

import com.meztking.roundtable.net.ApiJson
import kotlinx.serialization.Serializable
import java.math.BigDecimal
import java.math.RoundingMode
import java.text.NumberFormat
import java.util.Locale

/** The PC's rate (GET /api/rates, ui/moneyapi.py): pounds for one dollar. The phone asks no outside service. */
@Serializable
data class Rate(
    val currency: String = "GBP",
    val per_usd: Double? = null,
    val at: String = "",
    val source: String = "none",
    val stale: Boolean = false,
    val show: String = "usd+gbp",
    val words: String = "",
)

/** Costs also in pounds: "≈ £0.95" beside the dollars, the same words as the desktop (money.pounds_text). */
object Pounds {
    fun parse(json: String): Rate = runCatching { ApiJson.decodeFromString(Rate.serializer(), json) }.getOrDefault(Rate())

    /** "≈ £0.95", or "" with no rate or no amount. Half up; pennies under £100, whole pounds above. */
    fun text(usd: Double?, perUsd: Double?): String {
        if (usd == null || perUsd == null || usd.isNaN() || perUsd.isNaN() || usd.isInfinite() || perUsd.isInfinite()) return ""
        if (perUsd <= 0 || usd < 0) return ""
        val gbp = BigDecimal(usd.toString()).multiply(BigDecimal(perUsd.toString()))
        if (gbp.signum() == 0) return "≈ £0.00"
        if (gbp < BigDecimal("0.005")) return "≈ under £0.01"
        if (gbp >= BigDecimal(100)) {
            val whole = gbp.setScale(0, RoundingMode.HALF_UP).toLong()
            return "≈ £" + NumberFormat.getIntegerInstance(Locale.UK).format(whole)
        }
        return "≈ £" + gbp.setScale(2, RoundingMode.HALF_UP).toPlainString()
    }

    /** For the project's money line: "" when pounds are off or there is no rate yet. Dollars stay first. */
    fun beside(usd: Double?, rate: Rate?): String =
        if (rate == null || rate.show != "usd+gbp") "" else text(usd, rate.per_usd)
}
