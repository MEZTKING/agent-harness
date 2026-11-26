package com.meztking.roundtable.data

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import com.meztking.roundtable.net.PcLink

/** The PC link, its token and the optional GitHub token, encrypted with a key kept in Android's keystore. */
class Store(context: Context) {
    private val prefs: SharedPreferences = try {
        open(context)
    } catch (e: Exception) {
        // the keystore key is gone (restored backup, OS bug): start afresh rather than crash
        context.deleteSharedPreferences("roundtable.secure")
        open(context)
    }

    private fun open(context: Context): SharedPreferences = EncryptedSharedPreferences.create(
        context, "roundtable.secure",
        MasterKey.Builder(context).setKeyScheme(MasterKey.KeyScheme.AES256_GCM).build(),
        EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
        EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
    )

    var link: PcLink?
        get() {
            val token = prefs.getString("token", null) ?: return null
            return PcLink(
                prefs.getString("pc_name", "PC")!!,
                prefs.getString("hosts", "")!!.split(",").filter { it.isNotBlank() },
                prefs.getInt("port", 8766),
                prefs.getString("fingerprint", "")!!,
                token,
            )
        }
        set(v) {
            prefs.edit().apply {
                if (v == null) listOf("token", "pc_name", "hosts", "port", "fingerprint").forEach { remove(it) }
                else putString("token", v.token).putString("pc_name", v.name).putString("hosts", v.hosts.joinToString(","))
                    .putInt("port", v.port).putString("fingerprint", v.fingerprint)
            }.apply()
        }

    /** Hub only (PC off): a GitHub token with read/write access to the hub repository. */
    var githubToken: String?
        get() = prefs.getString("gh_token", null)
        set(v) = prefs.edit().apply { if (v.isNullOrBlank()) remove("gh_token") else putString("gh_token", v.trim()) }.apply()

    var hubRepo: String
        get() = prefs.getString("hub_repo", "MEZTKING/agent-hub-data")!!
        set(v) = prefs.edit().putString("hub_repo", v.trim()).apply()

    /** Who the phone writes as in the hub (the owner's own project, usually "me"). */
    var identity: String
        get() = prefs.getString("identity", "me")!!
        set(v) = prefs.edit().putString("identity", v.trim()).apply()

    /**
     * "This phone": Roundtable set up to run on the phone itself. A connection of its own, next to the hub and
     * the PC (not instead of them); the launch token is never stored, the runtime keeps it in memory.
     */
    var thisPhone: Boolean
        get() = prefs.getBoolean("this_phone", false)
        set(v) = prefs.edit().putBoolean("this_phone", v).apply()

    /** When Roundtable on this phone wants to run a command: "run" (Run it) or "ask" (Ask me first). */
    var commandChoice: String
        get() = prefs.getString("command_choice", "")!!
        set(v) = prefs.edit().putString("command_choice", v).apply()

    /** Which way in is used when more than one is set up: "hub", "pc" or "phone". */
    var mode: String
        get() = prefs.getString("mode", null) ?: if (githubToken != null) "hub" else if (link != null) "pc" else ""
        set(v) = prefs.edit().putString("mode", v).apply()

    val configured: Boolean get() = githubToken != null || link != null || thisPhone

    /** The last table we showed, so the app opens with something while it refreshes. */
    var cachedHall: String
        get() = prefs.getString("cached_hall", "")!!
        set(v) = prefs.edit().putString("cached_hall", v).apply()

    var lastVersion: String
        get() = prefs.getString("last_version", "")!!
        set(v) = prefs.edit().putString("last_version", v).apply()

    /** Ids of Needs-you items already notified, so each is announced once. */
    var notified: Set<String>
        get() = prefs.getStringSet("notified", emptySet())!!
        set(v) = prefs.edit().putStringSet("notified", v.toList().takeLast(300).toSet()).apply()
}
