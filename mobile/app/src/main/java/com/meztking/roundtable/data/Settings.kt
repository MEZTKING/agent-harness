package com.meztking.roundtable.data

import com.meztking.roundtable.net.ApiJson
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.longOrNull

/** One job ("coder") and the model that does it, with the models it may choose from. */
data class RoleChoice(val role: String, val model: String, val choices: List<String>) {
    val label: String get() = SharedSettings.roleLabel(role)
}

/**
 * The settings every machine shares: settings/shared.yaml in the hub, or GET /api/settings/shared on a machine.
 * Shape read: limits {name: number}, autopilot (yes/no or {on, cap, until}), default_profile, profiles (a list or
 * {name: {description}}), roles {job: model or [models]}, models (extra choices), updated_at, updated_by.
 */
data class SharedSettings(
    val limits: Map<String, Double> = emptyMap(),
    val autopilot: Boolean = false,
    val autopilotCap: Double? = null,
    val defaultProfile: String = "",
    val profiles: List<String> = emptyList(),
    val roles: List<RoleChoice> = emptyList(),
    val updatedAt: String = "",
    val updatedBy: String = "",
) {
    companion object {
        /** The limits the phone shows, in the order shown, with what each means. */
        val LIMITS = linkedMapOf(
            "max_real_usd_per_run" to "Most real money one run may spend (US \$)",
            "max_cost_usd" to "Most one project may cost in all (US \$)",
            "max_attempts_per_task" to "Tries per task before it stops and asks you",
            "max_steps_per_task" to "Steps in each try",
        )
        private val WHOLE = setOf("max_attempts_per_task", "max_steps_per_task")
        fun whole(key: String) = key in WHOLE

        private val ROLES = mapOf(
            "orchestrator" to "Plans the project", "planner" to "Plans the project", "manager" to "Splits the work into tasks",
            "coder" to "Writes the code", "critic" to "Checks the plan", "reviewer" to "Checks each task",
            "designer" to "Designs the screens", "scout" to "Looks things up first",
        )

        fun roleLabel(role: String) = ROLES[role] ?: role.replace('_', ' ').replaceFirstChar { it.uppercase() }

        fun parseJson(text: String?): SharedSettings? =
            text?.takeIf { it.isNotBlank() }?.let { runCatching { ApiJson.parseToJsonElement(it) as? JsonObject }.getOrNull() }
                ?.let { (it["settings"] as? JsonObject) ?: it }?.let { from(it) }

        fun parseYaml(text: String?): SharedSettings? = text?.takeIf { it.isNotBlank() }?.let { (MiniYaml.parse(it) as? JsonObject)?.let(::from) }

        /** [choices]: the models each job may use (from GET /api/roles), added to those the file names. */
        fun from(o: JsonObject, choices: Map<String, List<String>> = emptyMap()): SharedSettings {
            val limits = (o["limits"] as? JsonObject)?.mapNotNull { (k, v) -> (v as? JsonPrimitive)?.doubleOrNull?.let { k to it } }?.toMap().orEmpty()
            val ap = o["autopilot"]
            val on = (ap as? JsonPrimitive)?.booleanOrNull ?: ((ap as? JsonObject)?.get("on") as? JsonPrimitive)?.booleanOrNull ?: false
            val cap = ((ap as? JsonObject)?.get("cap") as? JsonPrimitive)?.doubleOrNull
            val profiles = when (val p = o["profiles"]) {
                is JsonArray -> p.mapNotNull { (it as? JsonPrimitive)?.contentOrNull ?: ((it as? JsonObject)?.get("name") as? JsonPrimitive)?.contentOrNull }
                is JsonObject -> p.keys.toList()
                else -> emptyList()
            }
            val extra = (o["models"] as? JsonArray)?.mapNotNull { (it as? JsonPrimitive)?.contentOrNull }.orEmpty()
            val roles = (o["roles"] as? JsonObject)?.map { (role, v) ->
                val models = when (v) {
                    is JsonPrimitive -> listOfNotNull(v.contentOrNull)
                    is JsonArray -> v.mapNotNull { (it as? JsonPrimitive)?.contentOrNull }
                    is JsonObject -> (v["models"] as? JsonArray)?.mapNotNull { (it as? JsonPrimitive)?.contentOrNull }
                        ?: listOfNotNull((v["model"] as? JsonPrimitive)?.contentOrNull)
                    else -> emptyList()
                }
                RoleChoice(role, models.firstOrNull().orEmpty(), (models + choices[role].orEmpty() + extra).distinct())
            }.orEmpty()
            return SharedSettings(limits, on, cap, str(o["default_profile"]), profiles, roles, str(o["updated_at"]), str(o["updated_by"]))
        }

        private fun str(e: JsonElement?) = (e as? JsonPrimitive)?.contentOrNull.orEmpty()

        /** GET /api/roles: each job's models, as choices. */
        fun roleChoices(text: String?): Map<String, List<String>> =
            runCatching { (ApiJson.parseToJsonElement(text.orEmpty()) as JsonObject)["roles"] as JsonArray }.getOrNull()?.mapNotNull { r ->
                val o = r as? JsonObject ?: return@mapNotNull null
                val name = str(o["name"]).ifBlank { return@mapNotNull null }
                name to (o["models"] as? JsonArray)?.mapNotNull { (it as? JsonPrimitive)?.contentOrNull }.orEmpty()
            }?.toMap().orEmpty()

        /** Only what changed, in the file's own shape: {limits: {...}, autopilot: {...}, default_profile, roles: {...}}. */
        fun changes(before: SharedSettings, after: SharedSettings): JsonObject {
            val out = linkedMapOf<String, JsonElement>()
            val lim = after.limits.filter { (k, v) -> before.limits[k] != v }
                .mapValues { (k, v) -> if (whole(k)) JsonPrimitive(v.toLong()) else JsonPrimitive(v) }
            if (lim.isNotEmpty()) out["limits"] = JsonObject(lim)
            if (before.autopilot != after.autopilot || before.autopilotCap != after.autopilotCap) {
                out["autopilot"] = JsonObject(buildMap {
                    put("on", JsonPrimitive(after.autopilot))
                    put("cap", after.autopilotCap?.let { JsonPrimitive(it) } ?: JsonNull)
                })
            }
            if (before.defaultProfile != after.defaultProfile) out["default_profile"] = JsonPrimitive(after.defaultProfile)
            val was = before.roles.associate { it.role to it.model }
            val roles = after.roles.filter { was[it.role] != it.model }.associate { it.role to JsonPrimitive(it.model) as JsonElement }
            if (roles.isNotEmpty()) out["roles"] = JsonObject(roles)
            return JsonObject(out)
        }
    }
}

/** One project setting as GET /api/project/settings gives it. */
data class ProjectSetting(
    val key: String,
    val value: JsonElement = JsonNull,
    val source: String = "",
    val default: JsonElement = JsonNull,
    val description: String = "",
    /** text, lines, map, int, number-map, choice */
    val type: String = "text",
    val choices: List<String> = emptyList(),
    /** number-map: the names it may hold */
    val keys: List<String> = emptyList(),
) {
    val label: String get() = ProjectSettings.LABELS[key] ?: key.replace('_', ' ').replaceFirstChar { it.uppercase() }
    val sourceWords: String get() = when (source) {
        "default", "" -> "the usual setting"
        "roundtable.yaml" -> "from the app's own roundtable.yaml"
        else -> "set for this project"
    }
}

data class ProjectSettingsView(val path: String = "", val items: List<ProjectSetting> = emptyList(), val warnings: List<String> = emptyList(), val errors: List<String> = emptyList())

/** Reading /api/project/settings, and turning what the owner typed back into values. */
object ProjectSettings {
    val LABELS = mapOf(
        "test" to "Test command", "env" to "Settings for the test", "setup" to "First-time set-up", "timeout" to "Time allowed (seconds)",
        "branch" to "Where the work goes", "rules_files" to "Rule files", "rules_budget" to "Most rules sent (characters)",
        "providers_allowed" to "Allowed AI makers", "profile" to "Set of models", "limits" to "Money and effort limits",
        "look" to "Choose a look first", "show_it" to "Pictures after each task", "notes" to "Notes for the planner",
        "checking" to "How carefully it's checked", "makers_allowed" to "Allowed model makers", "agent_memory" to "What agents remember",
        "stage_stop" to "Stop after each stage", "ask_first" to "Ask me first", "web_search" to "Search the web",
        "documents" to "Your documents", "perms" to "What each job may do",
    )

    /** Shown first on the phone: the money and the checking. Everything else waits behind "More". */
    val FIRST = listOf("limits", "checking")

    /** The settings shown first (in [FIRST]'s order) and the rest (in the PC's order). */
    fun split(view: ProjectSettingsView): Pair<List<ProjectSetting>, List<ProjectSetting>> {
        val first = FIRST.mapNotNull { k -> view.items.firstOrNull { it.key == k } }
        return first to view.items.filter { it.key !in FIRST }
    }

    fun parse(text: String): ProjectSettingsView {
        val o = ApiJson.parseToJsonElement(text) as JsonObject
        fun strs(e: JsonElement?) = (e as? JsonArray)?.mapNotNull { (it as? JsonPrimitive)?.contentOrNull }.orEmpty()
        val items = (o["settings"] as? JsonArray)?.mapNotNull { e ->
            val s = e as? JsonObject ?: return@mapNotNull null
            val key = (s["key"] as? JsonPrimitive)?.contentOrNull ?: return@mapNotNull null
            ProjectSetting(key, s["value"] ?: JsonNull, (s["source"] as? JsonPrimitive)?.contentOrNull.orEmpty(), s["default"] ?: JsonNull,
                (s["description"] as? JsonPrimitive)?.contentOrNull.orEmpty(), (s["type"] as? JsonPrimitive)?.contentOrNull ?: "text",
                strs(s["choices"]), strs(s["keys"]))
        }.orEmpty()
        return ProjectSettingsView((o["path"] as? JsonPrimitive)?.contentOrNull.orEmpty(), items, strs(o["warnings"]), strs(o["errors"]))
    }

    private fun scalar(e: JsonElement?): String = when (e) {
        is JsonPrimitive -> if (e is JsonNull) "" else e.content
        null -> ""
        else -> e.toString()
    }

    /** A value as the owner edits it: lines for lists, "name: value" lines for maps. */
    fun draft(s: ProjectSetting): String = when (val v = s.value) {
        is JsonArray -> v.joinToString("\n") { scalar(it) }
        is JsonObject -> v.entries.joinToString("\n") { "${it.key}: ${scalar(it.value)}" }
        else -> scalar(v)
    }

    /** What the owner typed, as the setting's value; an error in plain words when it doesn't fit. */
    fun value(s: ProjectSetting, text: String): Result<JsonElement> = runCatching {
        val t = text.trim()
        when (s.type) {
            "int" -> JsonPrimitive(t.toLongOrNull() ?: error("${s.label}: write a whole number."))
            "choice" -> {
                if (s.choices.isNotEmpty() && t !in s.choices) error("${s.label}: pick one of the choices.")
                JsonPrimitive(t)
            }
            "lines" -> JsonArray(t.lines().map { it.trim().removePrefix("- ").trim() }.filter { it.isNotEmpty() }.map { JsonPrimitive(it) })
            "map", "number-map" -> JsonObject(t.lines().map { it.trim() }.filter { it.isNotEmpty() }.associate { line ->
                if (':' !in line) error("${s.label}: write each one as name: value.")
                val k = line.substringBefore(':').trim()
                val v = line.substringAfter(':').trim()
                if (s.type == "number-map") {
                    if (s.keys.isNotEmpty() && k !in s.keys) error("${s.label}: $k isn't one of ${s.keys.joinToString(", ")}.")
                    k to JsonPrimitive(v.toDoubleOrNull()?.let { if (it % 1.0 == 0.0 && SharedSettings.whole(k)) it.toLong() else it }
                        ?: error("${s.label}: $k needs a number."))
                } else k to JsonPrimitive(v)
            })
            else -> JsonPrimitive(t)
        }.let { if (it is JsonPrimitive && it.isString && it.content.isEmpty()) JsonNull else it }
    }

    /** The settings whose text changed, as {key: value}; the first problem stops it. */
    fun changes(view: ProjectSettingsView, drafts: Map<String, String>): Result<JsonObject> = runCatching {
        JsonObject(view.items.filter { s -> drafts[s.key]?.let { it.trim() != draft(s).trim() } == true }
            .associate { s -> s.key to value(s, drafts.getValue(s.key)).getOrThrow() })
    }
}

/**
 * Just enough YAML for settings/shared.yaml: nested maps by indentation, "- item" lists, [a, b] lists, quoted or
 * plain scalars (numbers, true/false, null), and # notes. Not a general YAML reader.
 */
object MiniYaml {
    private data class Line(val indent: Int, val text: String)

    fun parse(text: String): JsonElement {
        val lines = text.lines().map { stripComment(it).trimEnd() }.filter { it.isNotBlank() && it.trim() != "---" }
            .map { Line(it.length - it.trimStart().length, it.trim()) }
        var pos = 0
        fun block(indent: Int): JsonElement {
            if (pos >= lines.size) return JsonNull
            if (lines[pos].text.startsWith("- ") || lines[pos].text == "-") {
                val items = mutableListOf<JsonElement>()
                while (pos < lines.size && lines[pos].indent == indent && (lines[pos].text.startsWith("- ") || lines[pos].text == "-")) {
                    val rest = lines[pos].text.removePrefix("-").trim()
                    pos++
                    items += if (rest.isEmpty()) block(lines.getOrNull(pos)?.indent ?: indent) else scalar(rest)
                }
                return JsonArray(items)
            }
            val map = linkedMapOf<String, JsonElement>()
            while (pos < lines.size && lines[pos].indent == indent) {
                val t = lines[pos].text
                if (':' !in t) { pos++; continue }
                val k = unquote(t.substringBefore(':').trim())
                val rest = t.substringAfter(':').trim()
                pos++
                map[k] = when {
                    rest.isNotEmpty() -> scalar(rest)
                    pos < lines.size && lines[pos].indent > indent -> block(lines[pos].indent)
                    pos < lines.size && lines[pos].indent == indent && lines[pos].text.startsWith("- ") -> block(indent)
                    else -> JsonNull
                }
            }
            return JsonObject(map)
        }
        return if (lines.isEmpty()) JsonObject(emptyMap()) else block(lines[0].indent)
    }

    private fun scalar(v: String): JsonElement {
        if (v.startsWith("[") && v.endsWith("]")) return JsonArray(v.removeSurrounding("[", "]").split(",").map { it.trim() }.filter { it.isNotEmpty() }.map { scalar(it) })
        if (v.startsWith("{") && v.endsWith("}")) return JsonObject(v.removeSurrounding("{", "}").split(",").filter { ':' in it }
            .associate { unquote(it.substringBefore(':').trim()) to scalar(it.substringAfter(':').trim()) })
        if ((v.startsWith('"') && v.endsWith('"') && v.length >= 2) || (v.startsWith('\'') && v.endsWith('\'') && v.length >= 2)) return JsonPrimitive(unquote(v))
        return when (v.lowercase()) {
            "true", "yes", "on" -> JsonPrimitive(true)
            "false", "no", "off" -> JsonPrimitive(false)
            "null", "~" -> JsonNull
            else -> v.toLongOrNull()?.let { JsonPrimitive(it) } ?: v.toDoubleOrNull()?.let { JsonPrimitive(it) } ?: JsonPrimitive(v)
        }
    }

    private fun unquote(v: String): String = when {
        v.length >= 2 && v.startsWith('"') && v.endsWith('"') -> v.substring(1, v.length - 1).replace("\\\"", "\"")
        v.length >= 2 && v.startsWith('\'') && v.endsWith('\'') -> v.substring(1, v.length - 1).replace("''", "'")
        else -> v
    }

    private fun stripComment(s: String): String {
        var q: Char? = null
        for ((i, c) in s.withIndex()) {
            if (q != null) { if (c == q) q = null; continue }
            if (c == '"' || c == '\'') q = c
            else if (c == '#' && (i == 0 || s[i - 1].isWhitespace())) return s.substring(0, i)
        }
        return s
    }

    @Suppress("unused") private fun JsonPrimitive.num(): Number? = longOrNull ?: doubleOrNull
}
