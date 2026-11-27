package com.meztking.roundtable.data

import com.meztking.roundtable.Brand

/** What a failure's one button does. The screen that shows it decides how (a retry, a trip to Settings…). */
enum class FailureAction { TRY_AGAIN, PAIR_AGAIN, FIND_PC, CHECK_TIME, NEW_KEY, FIX_KEY_ACCESS, CHECK_REPO, OPEN_PC_APP, UPDATE_PC, RESTART_PHONE }

/**
 * Every failure the phone can show, named (DS-11): one plain sentence and one button each. Nothing else reaches
 * a screen: [of] turns any error into one of these, and [said] lets through only the harness's own short
 * sentences (written for the owner), never a class name, a status code, JSON or a stack trace.
 */
enum class Failure(val sentence: String, val button: String, val action: FailureAction) {
    // Pairing
    WRONG_CODE("That code isn't right. Check the code on your PC and type it again.", "Type it again", FailureAction.PAIR_AGAIN),
    CODE_EXPIRED("The PC isn't waiting for a phone any more (a code lasts 5 minutes). Press Pair a phone on the PC for a new one.", "Pair again", FailureAction.PAIR_AGAIN),
    TOO_MANY_CODES("Too many wrong codes. Press Pair a phone on the PC for a new one.", "Pair again", FailureAction.PAIR_AGAIN),
    PC_IDENTITY_CHANGED("This isn't the PC you paired with: its identity has changed. If you reinstalled ${Brand.NAME} there, pair again.", "Pair again", FailureAction.PAIR_AGAIN),
    PC_NOT_FOUND("Couldn't find your PC. Is it on and on the same Wi-Fi? Away from home, turn on Tailscale.", "Look again", FailureAction.FIND_PC),
    CLOCKS_APART("The phone's clock and the PC's are too far apart for a safe connection. Set both to the right time automatically.", "Open date and time", FailureAction.CHECK_TIME),
    NOT_PAIRED("This phone isn't paired with the PC any more. Pair it again from the PC's Settings.", "Pair again", FailureAction.PAIR_AGAIN),

    // Hub mode (GitHub)
    KEY_EXPIRED("GitHub refused the token. It may have expired: make a new one and paste it in Settings.", "Paste a new token", FailureAction.NEW_KEY),
    KEY_CANT_WRITE("The token can read but not write. It needs Contents: Read and write on the hub repository.", "Fix the token", FailureAction.FIX_KEY_ACCESS),
    TOO_MANY_REQUESTS("GitHub says we've asked too often. Wait a few minutes, then try again.", "Try again", FailureAction.TRY_AGAIN),
    REPO_MISSING("Couldn't find the hub repository. Check its name, and that the token can see it.", "Check the name", FailureAction.CHECK_REPO),
    HUB_CHANGED_MEANWHILE("GitHub didn't take the change because it changed at the same time. Try again.", "Try again", FailureAction.TRY_AGAIN),
    GITHUB_TROUBLE("GitHub is having trouble. Try again in a minute.", "Try again", FailureAction.TRY_AGAIN),

    // PC mode
    PC_APP_NOT_RUNNING("Your PC didn't answer. Is it on, with ${Brand.NAME} open and phone access on?", "Try again", FailureAction.OPEN_PC_APP),
    PC_TOO_OLD("Your PC's ${Brand.NAME} is too old for this. Update it on the PC (it offers the update itself), then try again.", "Try again", FailureAction.UPDATE_PC),
    PC_ONLY("That can only be done on the PC itself.", "OK", FailureAction.TRY_AGAIN),
    PC_TROUBLE("Something went wrong on the PC. Try again; if it keeps happening, look at Settings, Problems on the PC.", "Try again", FailureAction.TRY_AGAIN),

    // This phone
    PHONE_HARNESS_DOWN("${Brand.NAME} on this phone isn't answering. Open Settings, Harness on this phone, and press Restart.", "Restart it", FailureAction.RESTART_PHONE),

    // Anywhere
    OFFLINE("No connection. Is the phone online?", "Try again", FailureAction.TRY_AGAIN),
    TOO_SLOW("It took too long to answer. Try again.", "Try again", FailureAction.TRY_AGAIN),
    NOT_UNDERSTOOD("Got an answer the app doesn't understand. Update the app and the PC, then try again.", "Try again", FailureAction.TRY_AGAIN),
    UNKNOWN("Something went wrong. Try again, or send the details from Settings.", "Try again", FailureAction.TRY_AGAIN);

    companion object {
        /** The failure [e] is, from its type, status and cause chain. Never returns the raw text. */
        fun of(e: Throwable?): Failure {
            if (e == null) return PC_APP_NOT_RUNNING
            val chain = generateSequence(e) { it.cause }.take(8).toList()
            // A sentence from this list, already chosen further down (GitHubHub, Api): keep it.
            chain.firstNotNullOfOrNull { c -> c.message?.let(::ofSentence) }?.let { return it }
            if (chain.any { it is java.security.cert.CertificateNotYetValidException || it is java.security.cert.CertificateExpiredException }) return CLOCKS_APART
            if (chain.any { it is javax.net.ssl.SSLPeerUnverifiedException || (it is java.security.cert.CertificateException) }) return PC_IDENTITY_CHANGED
            val status = (e as? com.meztking.roundtable.net.ApiException)?.status ?: 0
            val text = e.message.orEmpty()
            val low = text.lowercase()
            return when {
                "clock" in low || "not yet valid" in low -> CLOCKS_APART
                "github" in low -> fromGitHub(status, low)
                status == 0 && ("can't reach your pc" in low || "couldn't reach your pc" in low) -> PC_APP_NOT_RUNNING
                status == 0 && "isn't your pc" in low -> PC_IDENTITY_CHANGED
                status == 0 && "on this phone" in low -> PHONE_HARNESS_DOWN
                "code isn't right" in low || "doesn't belong to the pc" in low -> WRONG_CODE
                "isn't waiting for a phone" in low -> CODE_EXPIRED
                "too many wrong codes" in low -> TOO_MANY_CODES
                "isn't paired" in low || status == 401 -> NOT_PAIRED
                "only be done on the pc" in low -> PC_ONLY
                status == 404 && ("not found" in low || "unknown" in low || low.startsWith("http ")) -> PC_TOO_OLD
                status == 429 -> TOO_MANY_REQUESTS
                status >= 500 -> PC_TROUBLE
                else -> chain.firstNotNullOfOrNull(::byType) ?: UNKNOWN
            }
        }

        /** The words a screen shows for [e]: a sentence of this list, or the harness's own plain sentence ([said]). */
        fun words(e: Throwable?): String {
            val f = of(e)
            if (f != UNKNOWN) return f.sentence
            val status = (e as? com.meztking.roundtable.net.ApiException)?.status ?: 0
            return said(e?.message, status) ?: f.sentence
        }

        /** The failure a sentence on screen came from, for its button (null: the harness's own words; Try again). */
        fun ofSentence(text: String?): Failure? = text?.trim()?.let { t -> entries.firstOrNull { it.sentence == t } }

        /**
         * The harness's own answer, when it is a short plain sentence written for the owner (a 4xx from our
         * server: "No plan yet."). Anything that looks like machine text is refused.
         */
        fun said(text: String?, status: Int): String? {
            val t = text?.trim().orEmpty()
            if (status !in 400..499 || t.isEmpty() || t.length > 240) return null
            if (!t.first().isUpperCase() || t.last() !in ".!?)") return null
            if (RAW.any { it.containsMatchIn(t) }) return null
            return t
        }

        private val RAW = listOf(
            Regex("""\b\w*(Exception|Error)\b"""), Regex("""\bat [\w.$]+\("""), Regex("""[{}\[\]<>]"""), Regex("""\bHTTP\b"""),
            Regex("""https?://"""), Regex("""\b(null|undefined|NaN)\b"""), Regex("""Traceback|File "|line \d+"""), Regex("""[\w-]+\.(py|kt|java|js)\b"""),
            Regex("""\b[a-z]+_[a-z_]+\b"""), Regex("""\\n|\t"""), Regex("""^\d{3}\b"""),
        )

        private fun fromGitHub(status: Int, low: String): Failure = when {
            status == 401 -> KEY_EXPIRED
            status == 403 && ("rate limit" in low || "too often" in low) -> TOO_MANY_REQUESTS
            status == 403 -> KEY_CANT_WRITE
            status == 404 || "couldn't find" in low -> REPO_MISSING
            status == 409 || status == 422 -> HUB_CHANGED_MEANWHILE
            status >= 500 -> GITHUB_TROUBLE
            "too long" in low -> TOO_SLOW
            "can't reach" in low || "couldn't reach" in low -> OFFLINE
            "secure connection" in low -> CLOCKS_APART
            else -> GITHUB_TROUBLE
        }

        private fun byType(c: Throwable): Failure? = when (c) {
            is java.net.UnknownHostException -> OFFLINE
            is java.net.SocketTimeoutException -> TOO_SLOW
            is java.net.ConnectException, is java.net.NoRouteToHostException -> PC_APP_NOT_RUNNING
            is kotlinx.serialization.SerializationException, is IllegalArgumentException -> NOT_UNDERSTOOD
            else -> null
        }
    }
}
