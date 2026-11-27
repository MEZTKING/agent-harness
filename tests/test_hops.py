"""The hub's hop cap: two agents answering each other are stopped after HOP_CAP replies."""

from pathlib import Path

from roundtable.core.config import parse_config
from roundtable.core.store import FileStore
from roundtable.hub.service import HOP_CAP, Hub

RAW = {
    "storage": {"type": "file", "path": "data"},
    "default_policy": "deny",
    "agents": {"alpha": {"repo": "me/alpha"}, "beta": {"repo": "me/beta"}},
    "rules": [{"from": "*", "to": "*", "allow": ["message", "read_card"]}],
}


def make_hub(tmp_path: Path) -> Hub:
    return Hub(parse_config(RAW, tmp_path / "hub.yaml"), store=FileStore(tmp_path / "data"))


def test_new_message_starts_at_zero_and_replies_count_up(tmp_path):
    hub = make_hub(tmp_path)
    [m] = hub.send("alpha", "beta", "question", "what time?")
    assert m["hops"] == 0
    r = hub.reply("beta", m["id"], "noon")
    assert r["hops"] == 1 and not r.get("bounced")
    r2 = hub.reply("alpha", r["id"], "thanks")
    assert r2["hops"] == 2
    [shown] = [d for d in hub.inbox("beta", unread_only=False) if d["id"] == r2["id"]]
    assert shown["hops"] == 2


def test_ping_pong_is_stopped_and_bounced_to_the_sender(tmp_path):
    hub = make_hub(tmp_path)
    [m] = hub.send("alpha", "beta", "ping", "go")
    last, who = m, "beta"
    for _ in range(HOP_CAP):
        last = hub.reply(who, last["id"], "again")
        assert not last.get("bounced")
        who = "alpha" if who == "beta" else "beta"
    assert last["hops"] == HOP_CAP
    stopped = hub.reply(who, last["id"], "and again")
    assert stopped["bounced"] is True
    assert stopped["recipient"] == who and stopped["sender"] == who
    assert stopped["subject"].startswith("Stopped: ")
    assert "back and forth" in stopped["body"] and "and again" in stopped["body"]
    other = "alpha" if who == "beta" else "beta"
    assert stopped["bounced_to"] == [other]
    # it never reached the other agent
    assert all(d["id"] != stopped["id"] for d in hub.inbox(other, unread_only=False, limit=0))
    # it is in the sender's own inbox, in the same thread
    mine = hub.inbox(who, unread_only=False, limit=0)
    assert any(d["id"] == stopped["id"] and d["bounced"] for d in mine)
    assert stopped["thread_id"] == m["thread_id"]
    assert any(d["id"] == stopped["id"] for d in hub.thread(who, m["thread_id"]))


def test_send_with_in_reply_to_counts_from_the_parent(tmp_path):
    hub = make_hub(tmp_path)
    [m] = hub.send("alpha", "beta", "q", "x")
    [r] = hub.send("beta", "alpha", "Re: q", "y", kind="reply", in_reply_to=m["id"])
    assert r["hops"] == 1
    [far] = hub.send("beta", "alpha", "q", "z", in_reply_to=m["id"], _hops=HOP_CAP + 1)
    assert far["bounced"]


def test_old_messages_without_hops_still_work(tmp_path):
    hub = make_hub(tmp_path)
    [m] = hub.send("alpha", "beta", "old", "x")
    data = hub.store.read_json(f"inbox/beta/{m['id']}.json")
    data.pop("hops")
    hub.store.write_json({f"inbox/beta/{m['id']}.json": data}, "old format")
    assert hub.reply("beta", m["id"], "fine")["hops"] == 1
