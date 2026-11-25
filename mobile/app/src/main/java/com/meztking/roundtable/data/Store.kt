package com.meztking.roundtable.data

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import com.meztking.roundtable.net.PcLink

/** The PC link, its token and the optional GitHub token, encrypted with a key kept in Android's keystore. */
class Store(context: Context) {
    private val prefs: SharedPreferences = EncryptedSharedPreferences.create(
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

    var lastVersion: String
        get() = prefs.getString("last_version", "")!!
        set(v) = prefs.edit().putString("last_version", v).apply()

    /** Ids of Needs-you items already notified, so each is announced once. */
    var notified: Set<String>
        get() = prefs.getStringSet("notified", emptySet())!!
        set(v) = prefs.edit().putStringSet("notified", v.toList().takeLast(300).toSet()).apply()
}
