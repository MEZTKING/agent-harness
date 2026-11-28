package com.meztking.roundtable.data

import com.meztking.roundtable.Brand
import com.meztking.roundtable.net.ApiJson
import com.meztking.roundtable.net.GitHubHub
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.Semaphore
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.sync.withPermit
import kotlinx.serialization.Serializable
import java.io.File
import java.security.MessageDigest
import java.time.Instant
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter
import java.time.temporal.ChronoUnit
import kotlin.random.Random

/**
 * The chat's history in the hub, through the GitHub API (Hub mode), with the phone's own copy (1.5.0).
 *
 * The layout is [ChatLayout]'s: each device writes only its own day files, `chats/<chat>/<day>.<seat>.jsonl`, so two
 * devices never write the same file; a reader merges every device's files by (at, seat, id). The phone keeps a copy
 * of every line it has seen in the same layout under its own files, so a chat opens at once and works offline; its
 * own day files are sent again when the hub couldn't be reached.
 *
 * Safety: every line is scrubbed of key-shaped text before it is written ([ChatSafety.scrub]); a picture loses its
 * EXIF and location before it goes ([ChatSafety.stripMeta]) and is capped; cards are honoured only by the trust
 * rule ([trusted]).
 */

/** The hub's files as the chat needs them; [GitHubChatFiles] in the app, an in-memory one in tests. */
interface ChatFiles {
    suspend fun names(dir: String): List<String>
    suspend fun text(path: String): String?
    suspend fun bytes(path: String): ByteArray?
    suspend fun write(path: String, data: ByteArray, message: String)
    /** Makes [path] only when it isn't there yet; true when this call made it. */
    suspend fun createOnly(path: String, data: ByteArray, message: String): Boolean
}

class GitHubChatFiles(private val hub: GitHubHub) : ChatFiles {
    override suspend fun names(dir: String) = hub.names(dir)
    override suspend fun text(path: String) = hub.text(path)
    override suspend fun bytes(path: String) = hub.bytes(path)
    override suspend fun write(path: String, data: ByteArray, message: String) = hub.writeBytes(path, data, message)
    override suspend fun createOnly(path: String, data: ByteArray, message: String) = hub.createOnly(path, data, message)
}

/** What a scrub did: the text kept and how many key-shaped strings it took out. */
data class Scrubbed(val text: String, val removed: Int)

object ChatSafety {
    const val REMOVED = "[key removed]"
    /** At most this much in pictures and files sent to the hub in one day from this phone, and in one chat. */
    const val DAY_BYTES = 15_000_000L
    const val CHAT_BYTES = 150_000_000L

    private val patterns = listOf(
        Regex("-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\\s\\S]*?(-----END [A-Z0-9 ]*PRIVATE KEY-----|$)"),
        Regex("\\bsk-(?:proj-|ant-)?[A-Za-z0-9_-]{16,}"),
        Regex("\\bgithub_pat_[A-Za-z0-9_]{20,}"),
        Regex("\\bgh[pousr]_[A-Za-z0-9]{20,}"),
        Regex("\\bAKIA[0-9A-Z]{16}\\b"),
        Regex("\\bxox[abprs]-[A-Za-z0-9-]{10,}"),
        Regex("\\bAIza[0-9A-Za-z_-]{30,}"),
    )
    /** `.env`-like lines: `SOMETHING_KEY=value`, `DB_PASSWORD: value`. */
    private val envLine = Regex("(?m)^(\\s*(?:export\\s+)?[A-Za-z][A-Za-z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD|PWD)[A-Za-z0-9_]*\\s*[=:]\\s*)(\\S.*)$",
        RegexOption.IGNORE_CASE)

    /** [text] with every key-shaped string replaced by [REMOVED]. */
    fun scrub(text: String): Scrubbed {
        var n = 0
        var out = text
        for (p in patterns) out = p.replace(out) { n++; REMOVED }
        out = envLine.replace(out) { m -> if (m.groupValues[2].trim() == REMOVED) m.value else { n++; m.groupValues[1] + REMOVED } }
        return Scrubbed(out, n)
    }

    /** Model words as plain text for the screen: no picture or link is ever drawn or opened from them. A markdown
     *  picture becomes its words, a link its words, and a web address stays plain text. */
    fun plainFromModel(text: String): String = text
        .replace(Regex("!\\[([^\\]]*)]\\([^)]*\\)")) { it.groupValues[1].ifBlank { "(picture)" } }
        .replace(Regex("\\[([^\\]]+)]\\([^)]*\\)")) { it.groupValues[1] }
        .replace(Regex("<img[^>]*>", RegexOption.IGNORE_CASE), "(picture)")
        .replace(Regex("<a\\s[^>]*>(.*?)</a>", setOf(RegexOption.IGNORE_CASE, RegexOption.DOT_MATCHES_ALL))) { it.groupValues[1] }

    /**
     * A picture without its EXIF, location and other notes: JPEG APP1–APP13 and APP15 and comments, PNG text, time
     * and EXIF chunks, WebP EXIF and XMP. Null for a picture whose notes can't be taken out here (it then stays on
     * the phone). Anything that isn't a picture is returned as it is.
     */
    fun stripMeta(bytes: ByteArray, mime: String): ByteArray? = when {
        isJpeg(bytes) -> stripJpeg(bytes)
        isPng(bytes) -> stripPng(bytes)
        isWebp(bytes) -> stripWebp(bytes)
        mime.startsWith("image/") -> null
        else -> bytes
    }

    fun isPicture(bytes: ByteArray, mime: String) = mime.startsWith("image/") || isJpeg(bytes) || isPng(bytes) || isWebp(bytes)

    private fun isJpeg(b: ByteArray) = b.size > 3 && b[0] == 0xFF.toByte() && b[1] == 0xD8.toByte()
    private fun isPng(b: ByteArray) = b.size > 8 && b.copyOfRange(0, 8).contentEquals(byteArrayOf(-119, 80, 78, 71, 13, 10, 26, 10))
    private fun isWebp(b: ByteArray) = b.size > 12 && String(b, 0, 4, Charsets.ISO_8859_1) == "RIFF" && String(b, 8, 4, Charsets.ISO_8859_1) == "WEBP"

    private fun stripJpeg(b: ByteArray): ByteArray? {
        val out = java.io.ByteArrayOutputStream(b.size)
        out.write(b, 0, 2)
        var i = 2
        while (i + 4 <= b.size) {
            if (b[i] != 0xFF.toByte()) return null
            val marker = b[i + 1].toInt() and 0xFF
            if (marker == 0xDA) { out.write(b, i, b.size - i); return out.toByteArray() } // the picture itself: as it is
            if (marker == 0xD9) { out.write(b, i, 2); return out.toByteArray() }
            if (marker == 0x01 || marker in 0xD0..0xD7) { out.write(b, i, 2); i += 2; continue }
            val len = ((b[i + 2].toInt() and 0xFF) shl 8) or (b[i + 3].toInt() and 0xFF)
            if (len < 2 || i + 2 + len > b.size) return null
            val drop = (marker in 0xE1..0xED) || marker == 0xEF || marker == 0xFE
            if (!drop) out.write(b, i, 2 + len)
            i += 2 + len
        }
        return null
    }

    private fun stripPng(b: ByteArray): ByteArray? {
        val out = java.io.ByteArrayOutputStream(b.size)
        out.write(b, 0, 8)
        var i = 8
        val drop = setOf("eXIf", "tEXt", "iTXt", "zTXt", "tIME")
        while (i + 12 <= b.size) {
            val len = ((b[i].toLong() and 0xFF) shl 24 or ((b[i + 1].toLong() and 0xFF) shl 16) or ((b[i + 2].toLong() and 0xFF) shl 8) or (b[i + 3].toLong() and 0xFF)).toInt()
            if (len < 0 || i + 12 + len > b.size) return null
            val type = String(b, i + 4, 4, Charsets.ISO_8859_1)
            if (type !in drop) out.write(b, i, 12 + len)
            i += 12 + len
            if (type == "IEND") return out.toByteArray()
        }
        return null
    }

    private fun stripWebp(b: ByteArray): ByteArray? {
        val body = java.io.ByteArrayOutputStream(b.size)
        var i = 12
        while (i + 8 <= b.size) {
            val type = String(b, i, 4, Charsets.ISO_8859_1)
            val len = (b[i + 4].toInt() and 0xFF) or ((b[i + 5].toInt() and 0xFF) shl 8) or ((b[i + 6].toInt() and 0xFF) shl 16) or ((b[i + 7].toInt() and 0xFF) shl 24)
            val padded = len + (len and 1)
            if (len < 0 || i + 8 + len > b.size) return null
            if (type != "EXIF" && type != "XMP ") {
                if (type == "VP8X") { // the flags say which notes follow: clear EXIF (0x08) and XMP (0x04)
                    val chunk = b.copyOfRange(i, minOf(b.size, i + 8 + padded))
                    chunk[8] = (chunk[8].toInt() and 0x08.inv() and 0x04.inv()).toByte()
                    body.write(chunk)
                } else body.write(b, i, minOf(8 + padded, b.size - i))
            }
            i += 8 + padded
        }
        val payload = body.toByteArray()
        val out = java.io.ByteArrayOutputStream(payload.size + 12)
        out.write("RIFF".toByteArray(Charsets.ISO_8859_1))
        val size = payload.size + 4
        out.write(byteArrayOf(size.toByte(), (size shr 8).toByte(), (size shr 16).toByte(), (size shr 24).toByte()))
        out.write("WEBP".toByteArray(Charsets.ISO_8859_1))
        out.write(payload)
        return out.toByteArray()
    }

    fun sha(b: ByteArray): String = MessageDigest.getInstance("SHA-256").digest(b).joinToString("") { "%02x".format(it) }
}

/**
 * One device's view of the chat history in the hub. [seat] is this phone's seat ([Store.chatSeat]); [local] the
 * folder of the phone's own copy (null: kept in memory only).
 */
class HubChat(
    private val files: ChatFiles,
    val seat: String,
    val device: String = "This phone",
    private val local: File? = null,
    private val clock: () -> Instant = Instant::now,
    /** How many day files of each chat are read (the newest). */
    private val days: Int = 14,
) {
    private val lock = Mutex()
    /** The phone's copy when there's no folder for it: path -> the lines in that day file. */
    private val memory = HashMap<String, List<ChatLine>>()
    private val dirty = LinkedHashSet<String>()
    /** How many key-shaped strings the last [append] took out (the box warns the owner). */
    @Volatile var lastRemoved: Int = 0
        private set

    fun now(): String = DateTimeFormatter.ISO_INSTANT.format(clock().truncatedTo(ChronoUnit.MILLIS)).let {
        if ('.' in it) it else it.removeSuffix("Z") + ".000Z"
    }

    fun newId(): String = DateTimeFormatter.ofPattern("yyyyMMdd'T'HHmmssSSS").withZone(ZoneOffset.UTC).format(clock()) +
        "-" + "%08x".format(Random.nextInt())

    fun today(): String = DateTimeFormatter.ISO_LOCAL_DATE.withZone(ZoneOffset.UTC).format(clock())

    // -- the phone's own copy ---------------------------------------------------------------------------------------

    private fun localFile(path: String): File? = local?.let { File(it, path.removePrefix(ChatLayout.ROOT + "/")) }

    private fun loadLocal(path: String): List<ChatLine> {
        memory[path]?.let { return it }
        val f = localFile(path) ?: return emptyList()
        if (!f.isFile) return emptyList()
        return parseFile(f.readText()).also { memory[path] = it }
    }

    private fun saveLocal(path: String, lines: List<ChatLine>) {
        memory[path] = lines
        val f = localFile(path) ?: return
        f.parentFile?.mkdirs()
        val tmp = File(f.parentFile, ".${f.name}.tmp")
        tmp.writeText(render(lines))
        if (!tmp.renameTo(f)) { f.delete(); tmp.renameTo(f) }
    }

    private fun localDays(chat: String): List<String> {
        val dir = local?.let { File(it, chat) }
        val onDisk = dir?.listFiles()?.map { it.name }.orEmpty()
        val inMemory = memory.keys.filter { it.startsWith("${ChatLayout.ROOT}/$chat/") }.map { it.substringAfterLast('/') }
        return (onDisk + inMemory).filter { DAY.matches(it) }.distinct()
    }

    // -- reading ----------------------------------------------------------------------------------------------------

    /**
     * Every line of [chat] this phone can see, merged in order, with the trust rule applied: a card stays only on a
     * `chat` line answering an owner line typed here, or on this phone's own app lines. An owner line that a `chat`
     * line answers reads as answered. [online] false: only the phone's own copy is read.
     */
    suspend fun lines(chat: String, online: Boolean = true): List<ChatLine> = lock.withLock {
        require(ChatLayout.isChat(chat)) { "not a chat" }
        if (online) runCatching { pull(chat) }
        merged(chat)
    }

    /** Reads the hub's newest day files of [chat] into the phone's copy (its own files: the phone's copy wins). */
    private suspend fun pull(chat: String) = coroutineScope {
        val names = files.names("${ChatLayout.ROOT}/$chat").filter { DAY.matches(it) }
        val newest = names.map { it.substringBefore('.') }.distinct().sortedDescending().take(days).toSet()
        val gate = Semaphore(6)
        names.filter { it.substringBefore('.') in newest && !it.endsWith(".${safe(seat)}.jsonl") }.map { n ->
            async { gate.withPermit { n to files.text("${ChatLayout.ROOT}/$chat/$n") } }
        }.awaitAll().forEach { (n, text) -> if (text != null) saveLocal("${ChatLayout.ROOT}/$chat/$n", parseFile(text)) }
    }

    private fun merged(chat: String): List<ChatLine> {
        val all = localDays(chat).flatMap { loadLocal("${ChatLayout.ROOT}/$chat/$it") }
            .distinctBy { it.seat to it.id }.sortedWith(ChatLayout.order)
        return trusted(all, seat)
    }

    /** The lines since [since] as GET /api/chats/read gives them; `can` says whether the phone can answer now. */
    suspend fun read(chat: String, since: String = "", can: CanAnswer = CanAnswer(), online: Boolean = true): ChatRead {
        val lines = lines(chat, online)
        val shown = if (since.isBlank()) lines.takeLast(200) else lines.filter { it.at > since }
        return ChatRead(shown, lines.lastOrNull()?.at ?: since, null, can)
    }

    /** This phone's owner lines that nothing has answered yet. */
    suspend fun waiting(chat: String, online: Boolean = true): List<ChatLine> =
        lines(chat, online).filter { it.who == "owner" && it.seat == seat && it.state == "waiting" }

    // -- writing ----------------------------------------------------------------------------------------------------

    /**
     * Writes [line] into this phone's day file (scrubbed; id, time, seat and device filled in), first in the phone's
     * copy and then in the hub. A hub that can't be reached keeps it for [flush]; the line is returned either way.
     */
    suspend fun append(chat: String, line: ChatLine): ChatLine {
        val text = ChatSafety.scrub(line.text)
        val thinking = line.thinking?.let { ChatSafety.scrub(it) }
        lastRemoved = text.removed + (thinking?.removed ?: 0)
        val l = line.copy(
            id = line.id.ifBlank { newId() }, at = line.at.ifBlank { now() }, seat = seat,
            device = line.device ?: device, text = text.text, thinking = thinking?.text,
            card = line.card?.let { c -> c.copy(title = ChatSafety.scrub(c.title).text, line = ChatSafety.scrub(c.line).text) },
        )
        val path = ChatLayout.dayPath(chat, l.at.take(10), seat)
        lock.withLock {
            saveLocal(path, (loadLocal(path).filter { it.id != l.id } + l).sortedWith(ChatLayout.order))
            dirty += path
        }
        runCatching { flush() }
        return l
    }

    /** Sends this phone's changed day files to the hub. False when the hub couldn't be reached (they're kept). */
    suspend fun flush(): Boolean {
        val todo = lock.withLock { dirty.toList() }
        for (path in todo) {
            val text = lock.withLock { render(loadLocal(path)) }
            val safe = ChatSafety.scrub(text).text // once more, the whole file: nothing key-shaped reaches the hub
            try {
                files.write(path, safe.toByteArray(), "chat: ${path.substringAfter("${ChatLayout.ROOT}/").substringBefore('/')} (${Brand.SHORT} phone app)")
                lock.withLock { dirty -= path }
            } catch (e: Exception) {
                return false
            }
        }
        return true
    }

    val unsent: Boolean get() = dirty.isNotEmpty()

    /**
     * A picture or small file for [chat]: its notes taken out, then kept as `files/<sha>.<ext>` in the hub. One too big
     * (more than 1.5 MB), one whose notes can't be taken out, or one past the day's or chat's total stays on this phone
     * (`on`: this seat) and the others see its name and size.
     */
    suspend fun attach(chat: String, name: String, mime: String, bytes: ByteArray): ChatFile {
        val picture = ChatSafety.isPicture(bytes, mime)
        val clean = ChatSafety.stripMeta(bytes, mime)
        val ext = name.substringAfterLast('.', "").lowercase().replace(Regex("[^a-z0-9]"), "").take(8).ifEmpty { if (picture) "jpg" else "bin" }
        val kind = if (picture) "picture" else "file"
        val data = clean ?: bytes
        val sha = ChatSafety.sha(data).take(40)
        val stays = ChatFile(name, sha, ext, data.size.toLong(), kind, on = seat)
        if (clean == null || data.size > ChatLayout.FILE_MAX_BYTES) return stays
        val ledger = lock.withLock { ledger() }
        if (ledger.day == today() && ledger.dayBytes + data.size > ChatSafety.DAY_BYTES) return stays
        if ((ledger.chats[chat] ?: 0L) + data.size > ChatSafety.CHAT_BYTES) return stays
        return try {
            files.write(ChatLayout.filePath(chat, sha, ext), data, "chat: a ${kind} for $chat (${Brand.SHORT} phone app)")
            lock.withLock {
                val l = ledger()
                val dayBytes = (if (l.day == today()) l.dayBytes else 0L) + data.size
                saveLedger(Ledger(today(), dayBytes, l.chats + (chat to ((l.chats[chat] ?: 0L) + data.size))))
            }
            ChatFile(name, sha, ext, data.size.toLong(), kind)
        } catch (e: Exception) {
            stays
        }
    }

    /** A file of [chat] from the hub (pictures shown in the chat are only ever the chat's own files). */
    suspend fun file(chat: String, f: ChatFile): ByteArray? =
        if (f.on != null) null else runCatching { files.bytes(ChatLayout.filePath(chat, f.sha, f.ext)) }.getOrNull()

    /** Takes the answering of [turn] (first to reach the hub wins). */
    suspend fun claim(chat: String, turn: String): Boolean {
        val body = """{"at": "${now()}", "seat": "$seat"}""" + "\n"
        return files.createOnly(ChatLayout.claimPath(chat, turn), body.toByteArray(), "chat: $seat answers $turn (${Brand.SHORT} phone app)")
    }

    /** What every other device says the chat cost today, from the day files it has read ([chats]: those to look in). */
    suspend fun othersSpentToday(chats: List<String>): Double {
        val day = today()
        return chats.filter { ChatLayout.isChat(it) }.sumOf { c ->
            lock.withLock { localDays(c).filter { it.startsWith(day) && !it.endsWith(".${safe(seat)}.jsonl") }
                .flatMap { loadLocal("${ChatLayout.ROOT}/$c/$it") } }.sumOf { it.costUsd ?: 0.0 }
        }
    }

    /** The chats this phone has a copy of, newest spoken-in first. */
    fun known(): List<String> = (local?.listFiles()?.filter { it.isDirectory }?.map { it.name }.orEmpty() +
        memory.keys.map { it.substringAfter("${ChatLayout.ROOT}/").substringBefore('/') }).filter { ChatLayout.isChat(it) }.distinct()

    @Serializable
    private data class Ledger(val day: String = "", val dayBytes: Long = 0, val chats: Map<String, Long> = emptyMap())

    @Volatile private var memLedger = Ledger()

    private fun ledger(): Ledger {
        val f = local?.let { File(it, ".uploads.json") } ?: return memLedger
        return runCatching { ApiJson.decodeFromString(Ledger.serializer(), f.readText()) }.getOrDefault(Ledger())
    }

    private fun saveLedger(l: Ledger) {
        memLedger = l
        val f = local?.let { File(it, ".uploads.json") } ?: return
        f.parentFile?.mkdirs(); f.writeText(ApiJson.encodeToString(Ledger.serializer(), l))
    }

    companion object {
        private val DAY = Regex("^\\d{4}-\\d{2}-\\d{2}\\.[A-Za-z0-9_.-]+\\.jsonl$")

        fun parseFile(text: String): List<ChatLine> = text.lineSequence().filter { it.isNotBlank() }
            .mapNotNull { runCatching { ChatLayout.parseLine(it) }.getOrNull() }
            .filter { it.id.isNotBlank() && it.at.isNotBlank() && it.who in ChatLayout.WHO }.toList()

        fun render(lines: List<ChatLine>): String = lines.joinToString("") { ChatLayout.lineJson(it) + "\n" }

        private fun safe(s: String) = s.replace(Regex("[^A-Za-z0-9_.-]+"), "-").trim('.', '-').ifEmpty { "x" }

        /** The chat of a seat: "hall" for none, else its name in the hub made into a chat id (chatstore.chat_id). */
        fun chatOf(seat: SeatView?): String = seat?.chat?.takeIf { it.isNotBlank() } ?: chatOf(seat?.let { it.hubName.ifBlank { it.id } })

        fun chatOf(project: String?): String {
            if (project.isNullOrBlank()) return ChatLayout.HALL
            val s = project.lowercase().replace(Regex("[^a-z0-9]+"), "-").trim('-').take(80).trim('-').ifEmpty { "x" }
            return if (s == ChatLayout.HALL) "project-hall" else s
        }

        /**
         * The trust rule. A card is kept only on (a) a `chat` line that answers an owner line typed on [mine], or
         * (b) an `app` line [mine] wrote itself. Later lines carrying the same card id may change its state (a machine
         * saying it's done), never its command, title or price; a foreign one gets no buttons. The newest carrier
         * shows the card; the earlier ones show their words only. An owner line a `chat` line answers is answered.
         */
        fun trusted(all: List<ChatLine>, mine: String): List<ChatLine> {
            val owners = all.filter { it.who == "owner" && it.seat == mine }.map { it.id }.toSet()
            val answered = all.filter { it.who == "chat" && it.answers != null }.map { it.answers }.toSet()
            fun honoured(l: ChatLine) = (l.who == "chat" && l.answers in owners) || (l.who == "app" && l.seat == mine)
            val origin = HashMap<String, ChatCard>()
            val newest = HashMap<String, Int>()
            all.forEachIndexed { i, l ->
                val c = l.card ?: return@forEachIndexed
                if (c.id !in origin && honoured(l)) origin[c.id] = c
                if (c.id in origin) newest[c.id] = i
            }
            return all.mapIndexed { i, l ->
                val c = l.card
                val fixed = when {
                    c == null -> null
                    origin[c.id] == null || newest[c.id] != i -> null
                    else -> origin.getValue(c.id).let { o ->
                        if (c === o) o else o.copy(state = c.state, queuedFor = c.queuedFor,
                            buttons = if (l.seat == mine) c.buttons else emptyList())
                    }
                }
                val state = if (l.who == "owner" && l.id in answered) "answered" else l.state
                if (fixed == c && state == l.state) l else l.copy(card = fixed, state = state)
            }
        }
    }
}

/** What the phone notifies about the chat (notify/Notifier.kt through a hook-up): a waiting message answered, a
 *  queued card done. Each once: compare the lines read before with the lines read now. */
object ChatNotices {
    fun news(before: List<ChatLine>, after: List<ChatLine>, seat: String): List<String> {
        val seen = before.map { it.seat + "|" + it.id }.toSet()
        val waited = before.filter { it.who == "owner" && it.seat == seat && it.state == "waiting" }.map { it.id }.toSet()
        val queued = before.mapNotNull { it.card }.filter { it.state == "queued" || it.state == "running" }.map { it.id }.toSet()
        return after.filter { it.seat + "|" + it.id !in seen }.mapNotNull { l ->
            when {
                l.who == "chat" && l.answers in waited -> Words.t("Your message was answered: {words}", "words" to l.text.take(80))
                l.card != null && l.card.id in queued && l.card.state == "done" -> Words.t("Done: {title}", "title" to l.card.title)
                else -> null
            }
        }
    }
}
