"""The chat's history (chatstore.py, 1.5.0): day files one device owns, merged in order; changes as later copies;
the local copy; pictures made smaller without their location; keys never kept; claims. A made-up hub in a temp
folder, made-up devices."""

from __future__ import annotations

import io
import json
import threading
import time

import pytest

from roundtable import chatstore
from roundtable.core.config import load_config
from roundtable.hub.service import Hub

from .chatworld import HUB_RAW


@pytest.fixture
def hub(tmp_path):
    import yaml

    raw = json.loads(json.dumps(HUB_RAW))
    raw["storage"] = {"type": "file", "path": str(tmp_path / "hubdata")}
    raw["agents"] = {"me": {}, "harness": {}, "website": {"repo": "me/website", "title": "Website"},
                     "phone-abc123": {"title": "Phone (Test)", "role": "machine"}}
    raw["rules"] = [{"from": "*", "to": "*", "allow": ["read_card", "message"]}]
    (tmp_path / "hub.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")
    return Hub(load_config(str(tmp_path / "hub.yaml")))


def seat(monkeypatch, sid):
    monkeypatch.setenv("ROUNDTABLE_MACHINE", sid)


def test_two_devices_writing_the_same_day_never_clash_and_merge_in_order(tmp_path, hub, monkeypatch):
    pc, phone = tmp_path / "pc", tmp_path / "phone"
    seat(monkeypatch, "pc-desk")
    a = chatstore.append(pc, hub, "hall", {"who": "owner", "seat": "pc-desk", "text": "one"})
    time.sleep(0.003)  # (lines in the same millisecond are ordered by seat)
    seat(monkeypatch, "phone-abc123")
    b = chatstore.append(phone, hub, "hall", {"who": "owner", "seat": "phone-abc123", "text": "two"})
    time.sleep(0.003)
    seat(monkeypatch, "pc-desk")
    c = chatstore.append(pc, hub, "hall", {"who": "chat", "seat": "pc-desk", "text": "three", "answers": b["id"]})
    day = chatstore.today()
    files = sorted(p.name for p in (tmp_path / "hubdata" / "chats" / "hall").glob("*.jsonl"))
    assert files == [f"{day}.pc-desk.jsonl", f"{day}.phone-abc123.jsonl"]  # one file per device
    for home in (pc, phone, None):
        got = chatstore.read(home, hub, "hall")
        assert [x["text"] for x in got["lines"]] == ["one", "two", "three"]
        assert got["at"] == c["at"]
    assert chatstore.read(pc, hub, "hall")["lines"][1]["state"] == "answered"  # answered by the PC's line
    assert [x["text"] for x in chatstore.read(pc, hub, "hall", since=a["at"])["lines"]] == ["two", "three"]
    # the phone's copy now holds the PC's file too, so it opens offline
    assert (phone / "chats" / "hall" / f"{day}.pc-desk.jsonl").is_file()


def test_offline_lines_stay_here_and_reach_the_hub_later(tmp_path, hub, monkeypatch):
    seat(monkeypatch, "pc-desk")
    home = tmp_path / "pc"

    def broken(items, message):
        raise OSError("no network")

    real = hub.store.write_json
    hub.store.write_json = broken
    chatstore.append(home, hub, "hall", {"who": "owner", "seat": "pc-desk", "text": "kept"})
    assert chatstore.read(home, None, "hall")["lines"][0]["text"] == "kept"
    assert not (tmp_path / "hubdata" / "chats").exists()
    hub.store.write_json = real
    assert chatstore.push(home, hub) == 1
    assert chatstore.read(None, hub, "hall")["lines"][0]["text"] == "kept"


def test_a_change_is_a_later_copy_and_readers_see_it_again(tmp_path, hub, monkeypatch):
    seat(monkeypatch, "pc-desk")
    home = tmp_path / "pc"
    card = {"id": "c1", "title": "Build", "line": "About $1.", "command": "/run", "state": "open",
            "buttons": [{"id": "do", "words": "Build"}]}
    line = chatstore.append(home, hub, "hall", {"who": "chat", "seat": "pc-desk", "text": "ok", "card": card})
    after = chatstore.read(home, hub, "hall")["at"]
    chatstore.update(home, hub, "hall", line, card={**card, "state": "queued"})
    chatstore.update(home, hub, "hall", line, card={**card, "state": "done"})
    chatstore.update(home, hub, "hall", line, card={**card, "state": "open"})  # a stale copy never wins
    got = chatstore.read(home, hub, "hall")
    first = got["lines"][0]
    assert first["id"] == line["id"] and first["card"]["state"] == "done"
    assert first["at"] == line["at"]  # its place is kept
    assert all("card" not in x for x in got["lines"][1:])  # the state lines keep their words only
    assert sorted(x["text"] for x in got["lines"][1:]) == ["", "Done.", "Queued."]
    assert line["id"] in [x["id"] for x in chatstore.read(home, hub, "hall", since=after)["lines"]]
    # a waiting mark is the line again, same id: one line
    o = chatstore.append(home, hub, "hall", {"who": "owner", "seat": "pc-desk", "text": "hi"})
    chatstore.update(home, hub, "hall", o, state="waiting")
    owners = [x for x in chatstore.read(home, hub, "hall")["lines"] if x["who"] == "owner"]
    assert len(owners) == 1 and owners[0]["state"] == "waiting"


def test_the_apps_own_notices_stay_on_this_device(tmp_path, hub, monkeypatch):
    seat(monkeypatch, "pc-desk")
    home = tmp_path / "pc"
    chatstore.append(home, hub, "hall", {"who": "app", "seat": "pc-desk", "text": "Nothing can answer right now.",
                                         "card": {"id": "app-no_machine-1", "title": "", "line": "x", "command": "",
                                                  "state": "open", "buttons": [{"id": "add_key", "words": "Add"}]}})
    assert chatstore.read(home, hub, "hall")["lines"][0]["text"] == "Nothing can answer right now."
    assert chatstore.read(None, hub, "hall")["lines"] == []
    assert chatstore.push(home, hub) == 0


def test_keys_are_never_kept_or_sent(tmp_path, hub, monkeypatch):
    seat(monkeypatch, "pc-desk")
    home = tmp_path / "pc"
    secret = "sk-" + "a1b2c3d4" * 4
    text = (f"my key is {secret} and ghp_{'x' * 36}\nDEEPSEEK_API_KEY=abcdefgh12345678\n"
            "-----BEGIN RSA PRIVATE KEY-----\nMIIEow\n-----END RSA PRIVATE KEY-----\napi_key: zzzzzzzzzzzzzzzz")
    chatstore.append(home, hub, "hall", {"who": "owner", "seat": "pc-desk", "text": text})
    for p in list((tmp_path / "hubdata").rglob("*.jsonl")) + list(home.rglob("*.jsonl")):
        body = p.read_text(encoding="utf-8")
        assert secret not in body and "ghp_" not in body and "abcdefgh12345678" not in body
        assert "MIIEow" not in body and "zzzzzzzzzzzzzzzz" not in body
    assert chatstore.scrub(text)[1] == 5
    assert chatstore.scrub("api_key_env: DEEPSEEK_API_KEY and proxy-injected")[1] == 0
    f = chatstore.attach(home, hub, "hall", "notes.txt", f"token {secret}".encode())
    stored = (tmp_path / "hubdata" / "chats" / "hall" / "files" / f"{f['sha']}.{f['ext']}").read_bytes()
    assert secret.encode() not in stored and f["kind"] == "file"


def _jpeg_with_location(px=2400) -> bytes:
    from PIL import Image

    im = Image.new("RGB", (px, px // 2), (200, 30, 30))
    exif = Image.Exif()
    exif[0x8825] = {2: (51, 30, 0), 4: (0, 7, 0)}  # GPS: a place
    exif[0x010F] = "Made-up camera"
    out = io.BytesIO()
    im.save(out, "JPEG", exif=exif.tobytes())
    return out.getvalue()


def test_pictures_are_made_smaller_and_lose_their_location(tmp_path, hub, monkeypatch):
    from PIL import Image

    seat(monkeypatch, "pc-desk")
    home = tmp_path / "pc"
    data = _jpeg_with_location()
    assert Image.open(io.BytesIO(data)).getexif()
    f = chatstore.attach(home, hub, "hall", "photo.jpg", data)
    assert f["kind"] == "picture" and "on" not in f and f["size"] <= chatstore.FILE_MAX_BYTES
    kept = chatstore.file_bytes(None, hub, "hall", f"{f['sha']}.{f['ext']}")
    im = Image.open(io.BytesIO(kept))
    assert max(im.size) <= chatstore.PICTURE_PX and not im.getexif()
    assert b"Made-up camera" not in kept


def test_a_file_too_big_for_the_hub_stays_here(tmp_path, hub, monkeypatch):
    seat(monkeypatch, "pc-desk")
    home = tmp_path / "pc"
    f = chatstore.attach(home, hub, "hall", "big.bin", b"\0" * (chatstore.FILE_MAX_BYTES + 10))
    assert f["on"] == "pc-desk"
    assert not (tmp_path / "hubdata" / "chats" / "hall" / "files").exists()
    assert chatstore.file_bytes(home, None, "hall", f"{f['sha']}.{f['ext']}") is not None


def test_a_claim_is_taken_once_when_two_devices_try_at_the_same_moment(tmp_path, hub):
    won = []
    go = threading.Barrier(2)

    def take(s):
        go.wait()
        if chatstore.claim(hub, "hall", "t1", s):
            won.append(s)

    threads = [threading.Thread(target=take, args=(s,)) for s in ("pc-desk", "pc-laptop")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(won) == 1
    assert chatstore.claim(hub, "hall", "t1", won[0]) is True  # the winner may carry on
    other = "pc-laptop" if won[0] == "pc-desk" else "pc-desk"
    assert chatstore.claim(hub, "hall", "t1", other) is False


def test_waiting_lines_are_found_in_every_chat(tmp_path, hub, monkeypatch):
    seat(monkeypatch, "phone-abc123")
    w = chatstore.append(None, hub, "hall", {"who": "owner", "seat": "phone-abc123", "text": "hi", "state": "waiting"})
    chatstore.append(None, hub, "music", {"who": "owner", "seat": "phone-abc123", "text": "x", "state": "waiting"})
    assert sorted(x["chat"] for x in chatstore.waiting(hub)) == ["hall", "music"]
    seat(monkeypatch, "pc-desk")
    chatstore.append(None, hub, "hall", {"who": "chat", "seat": "pc-desk", "text": "hello", "answers": w["id"]})
    assert [x["chat"] for x in chatstore.waiting(hub)] == ["music"]


def test_a_broken_line_is_skipped(tmp_path, hub, monkeypatch):
    seat(monkeypatch, "pc-desk")
    chatstore.append(None, hub, "hall", {"who": "owner", "seat": "pc-desk", "text": "ok"})
    p = next((tmp_path / "hubdata" / "chats" / "hall").glob("*.jsonl"))
    p.write_text(p.read_text(encoding="utf-8") + '{"half": \n{"id": "x", "who": "me"}\n', encoding="utf-8")
    assert [x["text"] for x in chatstore.read(None, hub, "hall")["lines"]] == ["ok"]
