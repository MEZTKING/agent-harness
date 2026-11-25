package com.meztking.roundtable.net

import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

val ApiJson = Json { ignoreUnknownKeys = true; coerceInputValues = true; explicitNulls = false }

@Serializable
data class Progress(val done: Int = 0, val total: Int = 0)

@Serializable
data class JournalEntry(
    val id: String = "",
    val agent: String = "",
    val kind: String = "",
    val text: String = "",
    val created_at: String = "",
    val status: String = "",
    val priority: String = "normal",
    val next: List<String> = emptyList(),
    val details: String = "",
)

@Serializable
data class Brief(
    val agent: String = "",
    val repo: String = "",
    val description: String = "",
    val last_activity: String = "",
    val last_session: JournalEntry? = null,
    val open_todos: List<JournalEntry> = emptyList(),
    val open_plans: List<JournalEntry> = emptyList(),
    val recent_done: List<JournalEntry> = emptyList(),
    val recent_decisions: List<JournalEntry> = emptyList(),
)

/** One project at the table: a hub project, a harness run, or both merged by name. */
@Serializable
data class Seat(
    val id: String,
    val kind: String = "hub",
    val status: String = "idle", // running | waiting | idle | done
    val detail: String = "",
    val actions: List<String> = emptyList(),
    val repo: String = "",
    val description: String = "",
    val last_activity: String = "",
    val open_todos: Int = 0,
    val high: Int = 0,
    val unread: Int = 0,
    val path: String? = null,
    val failed_task: String? = null,
    val progress: Progress? = null,
    val goal: String = "",
    val spent_usd: Double = 0.0,
    val brief: Brief? = null,
)

@Serializable
data class NeedItem(
    val kind: String, // run | todo | messages
    val project: String,
    val text: String = "",
    val actions: List<String> = emptyList(),
    val path: String? = null,
    val task: String? = null,
    val id: String? = null,
    val at: String = "",
)

@Serializable
data class Health(val model: String, val passed: Int = 0, val total: Int = 0, val state: String = "ok", val at: String = "")

@Serializable
data class RoundtableData(
    val seats: List<Seat> = emptyList(),
    val needs_you: List<NeedItem> = emptyList(),
    val health: List<Health> = emptyList(),
    val spend_today: Double = 0.0,
    val synced_at: String = "",
    val agent: String? = null,
    val running_jobs: Int = 0,
)

@Serializable
data class FeedItem(
    val at: String = "",
    val project: String = "",
    val kind: String = "",
    val who: String = "",
    val task: String = "",
    val role: String = "",
    val model: String = "",
    val text: String = "",
)

@Serializable
data class Attempt(val model: String = "", val outcome: String = "", val cost_usd: Double? = null)

@Serializable
data class Task(
    val id: String,
    val title: String = "",
    val role: String = "",
    val description: String = "",
    val acceptance: String = "",
    val depends_on: List<String> = emptyList(),
    val status: String = "pending",
    val summary: String = "",
    val attempts: List<Attempt> = emptyList(),
)

@Serializable
data class ProjectMeta(
    val goals: List<String> = emptyList(),
    val status: String = "",
    val spent_usd: Double = 0.0,
    val plan_approved: Boolean = false,
)

@Serializable
data class LogLine(val at: String = "", val text: String = "")

@Serializable
data class ProjectDetail(
    val path: String,
    val name: String = "",
    val meta: ProjectMeta = ProjectMeta(),
    val tasks: List<Task> = emptyList(),
    val events: List<LogLine> = emptyList(),
    val summary: String = "",
    val files: List<String> = emptyList(),
)

@Serializable
data class ChatMessage(val who: String = "", val text: String = "", val at: String = "", val steer: Boolean = false)

@Serializable
data class ChatReply(val reply: String = "")

@Serializable
data class Message(
    val id: String,
    val sender: String = "",
    val recipient: String = "",
    val kind: String = "",
    val subject: String = "",
    val body: String = "",
    val created_at: String = "",
    val thread_id: String = "",
    val read: Boolean = false,
)

@Serializable
data class JobView(val id: String = "", val kind: String = "", val title: String = "", val status: String = "")

@Serializable
data class Changes(val version: String = "", val changed: Boolean = false)

@Serializable
data class Ping(val name: String = "", val version: String = "", val device: String = "", val agent: String? = null)

@Serializable
data class PairResult(val token: String, val device_id: String, val name: String = "")
