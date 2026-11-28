package com.meztking.roundtable.data

import com.meztking.roundtable.net.ApiJson
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import java.net.URLEncoder

/** One `/` command (harness/slash.py): its name, what it does, what may follow it, and whether it asks first. */
@Serializable
data class SlashCommand(val name: String = "", val words: String = "", val args: String = "", val confirm: Boolean = false,
                        val slow: Boolean = false, val pc_only: Boolean = false, val kind: String = "command")

@Serializable
private data class SlashList(val commands: List<SlashCommand> = emptyList())

/** What a command line did: the reply, and [confirm] when nothing was done yet ("Are you sure?" first). */
@Serializable
data class SlashReply(val reply: String = "", val confirm: String = "", val command: String = "", val open: String = "",
                      val job: JsonObject? = null)

object Slash {
    fun url(path: String) = "/api/commands?path=${e(path)}"
    const val RUN = "/api/commands"

    /** The commands the phone may use (the PC-only ones run programs on the PC: left out here). */
    fun parse(json: String): List<SlashCommand> =
        ApiJson.decodeFromString(SlashList.serializer(), json).commands.filter { !it.pc_only }

    fun parseReply(json: String): SlashReply = ApiJson.decodeFromString(SlashReply.serializer(), json)

    /** The body of POST /api/commands. */
    fun body(path: String, line: String, confirmed: Boolean): String =
        buildJsonObject { put("path", path); put("line", line.trim()); put("confirmed", confirmed) }.toString()

    /** The menu while the box starts with "/": the commands whose name starts with what's typed (all of them for "/"),
     * plain commands before skills. Nothing once a space follows the name. */
    fun menu(text: String, all: List<SlashCommand>): List<SlashCommand> {
        if (!text.startsWith("/") || ' ' in text || '\n' in text) return emptyList()
        val typed = text.drop(1).lowercase()
        return all.filter { it.name.lowercase().startsWith(typed) }.sortedBy { if (it.kind == "command") 0 else 1 }
    }

    /** What picking [c] puts in the box: "/name " when something may follow it, else "/name". */
    fun pick(c: SlashCommand): String = if (c.args.isBlank()) "/${c.name}" else "/${c.name} "

    fun isCommand(text: String) = text.trimStart().startsWith("/")

    private fun e(s: String) = URLEncoder.encode(s, "UTF-8")
}

/** A message waiting for the next task (the queue, ui/chatapi.py). */
@Serializable
data class QueueItem(val id: String = "", val at: String = "", val text: String = "")

@Serializable
data class QueueView(val items: List<QueueItem> = emptyList(), val running: Boolean = false, val reply: String = "")

object Queue {
    fun url(path: String) = "/api/queue?path=${URLEncoder.encode(path, "UTF-8")}"
    const val CHANGE = "/api/queue"

    fun parse(json: String): QueueView = ApiJson.decodeFromString(QueueView.serializer(), json)

    /** POST /api/queue: change (with new [text]), remove or send_now. */
    fun body(path: String, action: String, id: String, text: String? = null): String = buildJsonObject {
        put("path", path); put("action", action); put("id", id); if (text != null) put("text", text)
    }.toString()

    /** The card's title line. */
    fun title(v: QueueView): String = when (v.items.size) {
        0 -> ""
        1 -> "1 message waits for the next task"
        else -> "${v.items.size} messages wait for the next task"
    }
}

/** One earlier follow-up to a task: a question and its answer, or a change (a new task). */
@Serializable
data class FollowItem(val at: String = "", val question: String = "", val answer: String = "", val change: String = "",
                      val model: String = "", val cost_usd: Double = 0.0)

@Serializable
private data class FollowList(val items: List<FollowItem> = emptyList())

@Serializable
data class FollowEstimate(val cost_usd: Double = 0.0, val model: String = "", val task: String = "")

/** What POST /api/follow said: the price first ([confirm]), a job started, or a change made ([reply], [task]). */
@Serializable
data class FollowReply(val confirm: String = "", val estimate: FollowEstimate? = null, val reply: String = "",
                       val task: String = "", val delivered: String = "", val job: JsonObject? = null)

object Follow {
    fun url(path: String, task: String) = "/api/follow?path=${e(path)}&task=${e(task)}"
    const val POST = "/api/follow"

    fun parse(json: String): List<FollowItem> = ApiJson.decodeFromString(FollowList.serializer(), json).items
    fun parseReply(json: String): FollowReply = ApiJson.decodeFromString(FollowReply.serializer(), json)

    fun body(path: String, task: String, text: String, mode: String, confirmed: Boolean): String = buildJsonObject {
        put("path", path); put("task", task); put("text", text.trim()); put("mode", mode); put("confirmed", confirmed)
    }.toString()

    private fun e(s: String) = URLEncoder.encode(s, "UTF-8")
}
