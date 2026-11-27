package com.meztking.roundtable.notify

import com.meztking.roundtable.net.ApiJson
import kotlinx.serialization.Serializable
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** The shared cases (src/test/resources/notify_cases.json), the same file tests/test_notify.py runs on notify.py. */
class NotifyCasesTest {
    @Serializable
    data class Expect(val key: String, val kind: String, val group: String, val quiet: Boolean, val title: String, val text: String,
                      val buttons: List<String>)

    @Serializable
    data class Case(val name: String, val old: Snapshot? = null, val new: Snapshot, val open: String? = null, val expect: List<Expect>)

    @Serializable
    data class Cases(val cases: List<Case>)

    private val cases: List<Case> = ApiJson.decodeFromString(Cases.serializer(),
        javaClass.classLoader!!.getResource("notify_cases.json")!!.readText()).cases

    @Test fun everySharedCase() {
        assertTrue(cases.size >= 10)
        for (c in cases) {
            val got = Classifier.classify(c.old, c.new, c.open).map {
                Expect(it.key, it.kind, it.group, it.quiet, it.title, it.text, it.buttons.map { b -> b.id })
            }
            assertEquals(c.name, c.expect, got)
            assertTrue(c.name, Classifier.classify(c.old, c.new, c.open).all { it.kind in NewsKind.ALL && it.at == c.new.at })
        }
    }
}
