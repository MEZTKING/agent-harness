"""Projects on the phone (DS-55): clone, import a zip in parts, share without .harness or secrets."""

import base64
import io
import stat
import subprocess
import zipfile

import pytest

from roundtable import phoneprojects as pp


def _zip(entries: dict[str, bytes], links: tuple[str, ...] = ()) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
        for name in links:
            info = zipfile.ZipInfo(name)
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            zf.writestr(info, "/etc/passwd")
    return buf.getvalue()


def _upload(home, data: bytes) -> str:
    ok, start = pp.routes(home, home / "projects", lambda _k: None, "POST", "/api/projects/import", {}, {})
    up = start["upload"]
    for i in range(0, max(1, len(data)), pp.PART):
        pp.routes(home, home / "projects", lambda _k: None, "POST", "/api/projects/import", {},
                  {"upload": up, "index": i // pp.PART, "data": base64.b64encode(data[i:i + pp.PART]).decode()})
    return up


def _finish(home, up, name):
    return pp.routes(home, home / "projects", lambda _k: None, "POST", "/api/projects/import", {},
                     {"upload": up, "name": name, "done": True})[1]


def test_a_zip_in_parts_becomes_a_project(tmp_path, monkeypatch):
    monkeypatch.setattr(pp, "PART", 64)
    data = _zip({"tiny-game/main.py": b"print('hi')\n" * 20, "tiny-game/assets/a.txt": b"x"})
    up = _upload(tmp_path, data)
    got = _finish(tmp_path, up, "Tiny game")
    root = tmp_path / "projects" / "Tiny game"
    assert got["name"] == "Tiny game" and got["files"] == 2
    assert (root / "main.py").read_bytes().startswith(b"print")  # the one top folder is unwrapped
    assert (root / "assets" / "a.txt").exists()
    assert not list((tmp_path / "uploads").iterdir())  # the upload is gone


@pytest.mark.parametrize("bad", ["../x", "a/../../x", "/etc/x", "C:/x"])
def test_a_zip_pointing_outside_is_refused(tmp_path, bad):
    z = tmp_path / "in.zip"
    z.write_bytes(_zip({"ok.txt": b"1", bad: b"2"}))
    with pytest.raises(pp.ProjectError, match="outside"):
        pp.unpack(tmp_path / "projects", "p", z)
    assert not (tmp_path / "projects" / "p").exists()
    assert not (tmp_path.parent / "x").exists()


def test_a_link_is_refused(tmp_path):
    z = tmp_path / "in.zip"
    z.write_bytes(_zip({"ok.txt": b"1"}, links=("evil",)))
    with pytest.raises(pp.ProjectError, match="link"):
        pp.unpack(tmp_path / "projects", "p", z)


def test_over_the_cap_is_refused(tmp_path):
    z = tmp_path / "in.zip"
    z.write_bytes(_zip({"big.bin": b"0" * 5000}))
    with pytest.raises(pp.ProjectError, match="too big"):
        pp.unpack(tmp_path / "projects", "p", z, max_bytes=1000)
    z.write_bytes(_zip({f"f{i}": b"" for i in range(5)}))
    with pytest.raises(pp.ProjectError, match="too many"):
        pp.unpack(tmp_path / "projects", "p", z, max_files=3)


def test_never_over_an_existing_project(tmp_path):
    (tmp_path / "projects" / "mine").mkdir(parents=True)
    (tmp_path / "projects" / "mine" / "keep.txt").write_text("mine")
    z = tmp_path / "in.zip"
    z.write_bytes(_zip({"keep.txt": b"theirs"}))
    with pytest.raises(pp.ProjectError, match="already"):
        pp.unpack(tmp_path / "projects", "mine", z)
    assert (tmp_path / "projects" / "mine" / "keep.txt").read_text() == "mine"


def test_parts_out_of_order_are_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(pp, "PART", 4)
    up = pp.new_upload()
    pp.add_part(tmp_path, up, 0, base64.b64encode(b"abcd").decode())
    with pytest.raises(pp.ProjectError, match="missing"):
        pp.add_part(tmp_path, up, 2, base64.b64encode(b"efgh").decode())


@pytest.mark.parametrize("name", ["..", "../up", "a/b", "", ".hidden"])
def test_bad_names(tmp_path, name):
    with pytest.raises(pp.ProjectError):
        pp.project_name(name)


def test_a_shared_zip_holds_no_harness_git_or_secret(tmp_path, monkeypatch):
    monkeypatch.setattr(pp, "PART", 50)
    root = tmp_path / "projects" / "demo"
    for rel, text in {"main.py": "x", "src/app.js": "y", ".harness/plan.json": "{}", ".git/config": "token",
                      ".env": "KEY=1", "secrets/a.txt": "s", "id_rsa": "k", "signing/release.jks": "j",
                      "src/server.pem": "p", "README.md": "# demo"}.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text * 40)
    key = lambda _k: None  # noqa: E731
    start = pp.routes(tmp_path, tmp_path / "projects", key, "GET", "/api/projects/share", {"name": ["demo"]}, {})[1]
    data = b""
    for i in range(start["parts"]):
        part = pp.routes(tmp_path, tmp_path / "projects", key, "GET", "/api/projects/share",
                         {"id": [start["id"]], "index": [str(i)]}, {})[1]
        data += base64.b64decode(part["data"])
    assert len(data) == start["size"]
    names = sorted(zipfile.ZipFile(io.BytesIO(data)).namelist())
    assert names == ["demo/README.md", "demo/main.py", "demo/src/app.js"]
    assert not list((tmp_path / "uploads").iterdir())  # read to the end: nothing kept


def test_clone_uses_the_project_key_through_the_environment_only(tmp_path):
    seen = {}

    def run(argv, **kw):
        seen["argv"], seen["env"] = argv, kw["env"]
        (tmp_path / "projects" / "game").mkdir(parents=True)
        return subprocess.CompletedProcess(argv, 0, "", "")

    keys = {pp.PROJECT_GIT_KEY: "proj-secret", "ROUNDTABLE_HUB_TOKEN": "hub-secret"}
    ok, got = pp.routes(tmp_path, tmp_path / "projects", keys.get, "POST", "/api/projects/clone", {},
                        {"url": "https://github.com/someone/game.git", "use_key": True}, run=run)
    assert ok and got["name"] == "game"
    assert seen["argv"][:3] == ["git", "clone", "--"]
    assert not any("secret" in a for a in seen["argv"])
    header = base64.b64encode(b"x-access-token:proj-secret").decode()
    assert any(header in v for v in seen["env"].values())
    assert not any("hub-secret" in v for v in seen["env"].values())


def test_clone_refuses_other_addresses_and_existing(tmp_path):
    for url in ["git@github.com:a/b.git", "http://github.com/a/b", "file:///etc", "https://user:pw@github.com/a/b"]:
        with pytest.raises(pp.ProjectError, match="https"):
            pp.clone(tmp_path, url, run=lambda *a, **k: None)
    (tmp_path / "b").mkdir()
    with pytest.raises(pp.ProjectError, match="already"):
        pp.clone(tmp_path, "https://github.com/a/b", run=lambda *a, **k: None)


def test_a_private_repository_without_a_key_says_what_to_do(tmp_path):
    def run(argv, **kw):
        return subprocess.CompletedProcess(argv, 128, "", "fatal: could not read Username for 'https://github.com'")

    with pytest.raises(pp.ProjectError, match="project key"):
        pp.clone(tmp_path, "https://github.com/a/private", run=run)
    assert not (tmp_path / "private").exists()
