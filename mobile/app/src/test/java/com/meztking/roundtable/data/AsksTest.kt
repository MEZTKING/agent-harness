package com.meztking.roundtable.data

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class AsksTest {
    // the shape asks.py writes (made-up project)
    private val json = """
        {"project": "lantern-app", "at": "2026-11-26T10:00:00Z", "asks": [
          {"id": "money", "kind": "money", "header": "Money", "question": "This project reached its limit of ${'$'}5.00. Carry on?",
           "detail": "", "options": [
             {"id": "more", "label": "Carry on with ${'$'}2.00 more", "description": "Raises the limit.", "confirm": "This lets it spend up to ${'$'}2.00 more. Carry on?"},
             {"id": "stop", "label": "Stop here", "description": "Nothing more is spent."}],
           "recommended": "more", "multi": false, "allow_other": true, "other_hint": "Anything to tell it?", "stamp": "abc1234567",
           "answer": null, "source": {"pause": "budget"}, "project": "lantern-app", "path": "/home/x/lantern-app", "unknown": 1},
          {"id": "answer:Q2", "kind": "question", "header": "Pages", "question": "Which pages matter most?", "options": [
             {"id": "a", "label": "Menu"}, {"id": "b", "label": "Map"}], "recommended": "a", "multi": true,
           "answer": {"chosen": ["a"], "other": "and a form"}, "stamp": "s2"}
        ]}
    """.trimIndent()

    @Test fun parsesTheCards() {
        val asks = Asks.parse(json)
        assertEquals(listOf("money", "answer:Q2"), asks.map { it.id })
        val m = asks[0]
        assertEquals("Money", m.header)
        assertEquals("more", m.options.first().id)
        assertTrue(m.options.first().confirm!!.startsWith("This lets it"))
        assertNull(m.options[1].confirm)
        assertEquals("/home/x/lantern-app", m.path)
        assertTrue(asks[1].multi)
        assertEquals(AskAnswer(listOf("a"), "and a form"), asks[1].answer)
        assertEquals(emptyList<Ask>(), Asks.parse("not json"))
        assertEquals(emptyList<Ask>(), Asks.parse(null))
    }

    @Test fun moneyNeedsAreYouSure() {
        val m = Asks.parse(json)[0]
        assertEquals("more", AskReply(listOf("more")).needsConfirm(m)?.id)
        assertNull(AskReply(listOf("more"), confirmed = true).needsConfirm(m))
        assertNull(AskReply(listOf("stop")).needsConfirm(m))
        assertTrue(AskReply(emptyList(), " ").empty)
    }

    @Test fun answerCommandForTheHub() {
        val q = Asks.parse(json)[1]
        val f = Asks.commandFields(q, AskReply(listOf("a", "b"), " and a form "))
        assertEquals("answer:Q2", f["id"])
        assertEquals(listOf("a", "b"), f["chosen"])
        assertEquals("and a form", f["other"])
        assertNull(f["confirmed"])
        assertEquals("s2", f["stamp"])
        assertEquals(true, Asks.commandFields(q, AskReply(listOf("a"), confirmed = true))["confirmed"])
    }

    @Test fun answerBodyForThePc() {
        val m = Asks.parse(json)[0]
        val body = Json.parseToJsonElement(Asks.requestBody(m, AskReply(listOf("more"), "", confirmed = true))).jsonObject
        assertEquals("/home/x/lantern-app", body["path"]!!.jsonPrimitive.content)
        assertEquals("money", body["id"]!!.jsonPrimitive.content)
        assertEquals(listOf("more"), body["chosen"]!!.jsonArray.map { it.jsonPrimitive.content })
        assertEquals("true", body["confirmed"]!!.jsonPrimitive.content)
        assertEquals("abc1234567", body["stamp"]!!.jsonPrimitive.content)
    }

    @Test fun cardsFromAnOlderHubsPlan() {
        val md = """
            _Plan status: waiting for the owner · plan ready · updated 2026-11-25T22:41:05Z by Roundtable Hold_

            # Plan v1: Light it

            ## Decisions
            ### When time is up? [C4]
            - Ring until stopped: Keeps going. [Medium] {B}
            - Ring once (recommended): A single chime. [Low] {A}
            Why: Once is enough.

            ## Questions for the owner
            - Which colour? {Q1}
              Answers: Amber (recommended) {a}; Blue {b}
            - Offline? {Q2}
              Answer: yes

            ## Ideas
            - [open] A sound picker (people like choice) {I1}
            - [rejected] Ads {I2}
        """.trimIndent()
        val doc = PlanDoc.parse(md)
        assertEquals(listOf("", "yes"), doc.questions.map { it.answer }) // "Answers:" are the ready ones, not the owner's
        val asks = Asks.fromPlan(doc, "lantern-app")
        assertEquals(listOf("choose:C4", "answer:Q1", "idea:I1"), asks.map { it.id })
        assertEquals(listOf("A", "B"), asks[0].options.map { it.id }) // recommended first
        assertEquals("A", asks[0].recommended)
        assertEquals("A single chime. · Low", asks[0].options[0].description)
        assertEquals(emptyList<AskOption>(), asks[1].options) // only the text box
        assertEquals("yes", asks[2].options[0].id)
        assertEquals(emptyList<Ask>(), Asks.fromPlan(PlanDoc.parse(md.replace("waiting for the owner", "approved, building")), "x"))
    }
}
