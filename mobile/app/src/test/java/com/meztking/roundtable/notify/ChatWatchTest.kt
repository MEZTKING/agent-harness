package com.meztking.roundtable.notify

import com.meztking.roundtable.data.ChatCard
import com.meztking.roundtable.data.ChatLine
import com.meztking.roundtable.data.ChatSummary
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ChatWatchTest {
    private val asked = ChatLine(id = "o", at = "1", who = "owner", seat = "me", text = "where does it stand?", state = "waiting")

    @Test fun onlyChatsThatWaitAreRead() {
        val list = listOf(ChatSummary("hall", "Hall"), ChatSummary("shop", "Shop", waiting = 1), ChatSummary("garden", "Garden", unread = 3))
        assertEquals(listOf("shop", "garden-was-waiting"), ChatWatch.toRead(list, setOf("garden-was-waiting")))
    }

    @Test fun aChatWaitsWhileThisPhonesMessageOrAQueuedCardDoes() {
        assertTrue(ChatWatch.pending(listOf(asked), "me"))
        assertFalse(ChatWatch.pending(listOf(asked), "another-phone"))
        val queued = ChatLine(id = "q", at = "2", who = "app", seat = "me", card = ChatCard(id = "c", title = "Build", state = "queued"))
        assertTrue(ChatWatch.pending(listOf(queued), "other"))
        assertFalse(ChatWatch.pending(listOf(asked.copy(state = "answered")), "me"))
    }

    @Test fun anAnswerBecomesOneNotificationOnce() {
        val answer = ChatLine(id = "a", at = "2", who = "chat", seat = "pc", text = "Two tasks left.", answers = "o")
        val got = ChatWatch.news("shop", "Shop", "shop", listOf(asked), listOf(asked, answer), "me")
        assertEquals(1, got.size)
        assertEquals("Your message was answered: Two tasks left.", got[0].title)
        assertEquals(NewsKind.NEEDS_YOU, got[0].kind)
        assertEquals(got[0].key, ChatWatch.news("shop", "Shop", "shop", listOf(asked), listOf(asked, answer), "me")[0].key)
        assertTrue(ChatWatch.news("shop", "Shop", "shop", listOf(asked, answer), listOf(asked, answer), "me").isEmpty())
    }
}
