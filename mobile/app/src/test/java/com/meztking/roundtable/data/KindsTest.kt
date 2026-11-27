package com.meztking.roundtable.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class KindsTest {
    private val plan = """{"summary": "x", "kind": {"id": "website", "name": "Website", "question": "This looks like a Website, because you said “site”. Right?",
        "confirmed": false, "fixed": false, "status": "trial", "status_words": "On trial", "extras": [],
        "choices": [{"id": "website", "name": "Website", "recommended": true}, {"id": "web-app", "name": "Web app"},
                    {"id": "other", "name": "Something else"}], "change_words": "Changing it re-plans the work.", "frozen": false}}"""

    @Test fun planKindIsReadFromThePlan() {
        val k = Kinds.planKind(plan)!!
        assertEquals("website", k.id)
        assertEquals("On trial", k.statusWords)
        assertEquals("Yes, a website", Kinds.choiceLabel(k, k.choices[0]))
        assertEquals("Web app", Kinds.choiceLabel(k, k.choices[1]))
        assertEquals("Website", Kinds.choiceLabel(k.copy(confirmed = true), k.choices[0]))
        assertNull(Kinds.planKind("""{"summary": "no kind yet"}"""))
        assertNull(Kinds.planKind("not json"))
    }

    @Test fun galleryListAndEntry() {
        val list = Kinds.parseGallery("""{"entries": [{"project": "cake-shop", "goal": "goal-1", "title": "Cake shop", "kind": "website",
            "kind_name": "Website", "line": "26 Nov · $3.45 · 41 min", "cover": "", "hidden": false, "starred": true, "proven": true, "extra": 1}],
            "words": "Everything finished, newest first."}""")
        assertEquals(1, list.entries.size)
        assertTrue(list.entries[0].starred)
        assertEquals("26 Nov · $3.45 · 41 min", list.entries[0].line)
        val e = Kinds.parseEntry("""{"project": "cake-shop", "goal": "goal-1", "title": "Cake shop", "pictures": [{"name": "desktop.png", "src": "data:image/png;base64,iVBORw0K"}],
            "proof": [{"id": "starts", "words": "It opens with no errors", "passed": true}, {"id": "plays", "words": "Played for a minute", "passed": null}],
            "more": {"models": [{"task": "T1", "role": "coder", "model": "a/coder"}], "commit": "abc"}}""")
        assertNotNull(e)
        assertEquals("It opens with no errors ✓ · Played for a minute – not checked yet", Kinds.proofWords(e!!.proof))
        assertEquals("a/coder", e.more.models[0].model)
        assertNull(Kinds.parseEntry("[]"))
    }

    @Test fun kindsListAndRequests() {
        val d = Kinds.parseList("""{"groups": [{"group": "Websites", "kinds": [{"id": "website", "name": "Website", "status": "trial",
            "status_words": "On trial", "usable": true, "missing": ["Playwright's browser"], "examples": ["a bakery site"],
            "proof": [{"id": "plays", "words": "Played for a minute", "not_yet": true}]}]}], "words": "w"}""")
        assertEquals("Websites", d.groups[0].group)
        assertTrue(d.groups[0].kinds[0].proof[0].notYet)
        assertEquals("/api/gallery/one?project=cake+shop&goal=goal-1", Kinds.entryPath("cake shop", "goal-1"))
        assertEquals("""{"project":"p","goal":"goal-1","hidden":true}""", Kinds.flagBody("p", "goal-1", "hidden", true))
        assertEquals("/api/gallery?hidden=1", Kinds.galleryPath(true))
    }

    @Test fun picturesFromDataUrlsOnly() {
        assertEquals(3, Kinds.pictureBytes("data:image/png;base64,AAAA")!!.size)
        assertNull(Kinds.pictureBytes("https://example.com/x.png"))
        assertNull(Kinds.pictureBytes("data:image/png,raw"))
        assertFalse(Kinds.pictureBytes("data:image/png;base64,!!!") != null)
    }
}
