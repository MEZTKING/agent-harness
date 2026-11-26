"""Roundtable on the phone itself (`roundtable phone serve --local`) and the phone runtime's build."""

import base64
import json
import lzma
import os
import secrets
import sys
import tarfile
import threading
import time
import urllib.error
import urllib.request
from io import BytesIO
from pathlib import Path

import pytest
import yaml

from roundtable import __version__, onphone
from roundtable.harness.config import load_config, parse_config
from roundtable.providers.scripted import ScriptedImages, ScriptedProvider

from .test_harness import RAW as HARNESS_RAW, Brain

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
TOKEN = "launch-" + secrets.token_urlsafe(24)
KEY_NAMES = list(onphone.PROVIDER_KEYS.values()) + [onphone.HUB_TOKEN]


@pytest.fixture
def clean_env():
    """The server sets HUB_CONFIG, keys and git settings in this process: put everything back."""
    before = dict(os.environ)
    for name in KEY_NAMES + ["ROUNDTABLE_SEAT", "ROUNDTABLE_WORKSPACES", "GIT_CONFIG_COUNT"]:
        os.environ.pop(name, None)
    yield
    os.environ.clear()
    os.environ.update(before)


@pytest.fixture
def server(tmp_path, clean_env):
    home = tmp_path / "home"
    os.environ["ROUNDTABLE_WORKSPACES"] = str(tmp_path / "workspaces")
    httpd, app = onphone.make_local_server(home, 0, TOKEN)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield {"httpd": httpd, "app": app, "home": home, "base": f"http://127.0.0.1:{httpd.server_address[1]}",
           "tmp": tmp_path}
    httpd.shutdown()
    httpd.server_close()


def call(srv, method, path, body=None, token=TOKEN, ctype="application/json"):
    data = json.dumps(body).encode() if body is not None else (b"" if method == "POST" else None)
    req = urllib.request.Request(srv["base"] + path, data=data, method=method)
    if token is not None:
        req.add_header("Authorization", f"Bearer {token}")
    if method == "POST":
        req.add_header("Content-Type", ctype)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


# -- the server ----------------------------------------------------------------------------------
def test_binds_loopback_only(server):
    assert server["httpd"].server_address[0] == "127.0.0.1"


def test_needs_a_launch_token(clean_env, tmp_path):
    for bad in ("", "short"):
        with pytest.raises(ValueError, match="ROUNDTABLE_LAUNCH_TOKEN"):
            onphone.make_local_server(tmp_path / "h", 0, bad)


def test_health_needs_no_token_and_says_little(server):
    assert call(server, "GET", "/api/health", token=None) == (200, {"ok": True, "version": __version__})


def test_every_other_request_needs_the_launch_token(server):
    for method, path in (("GET", "/api/projects"), ("GET", "/api/keys"), ("GET", "/api/ping"),
                         ("POST", "/api/keys"), ("POST", "/api/pair/claim"), ("GET", "/api/nowhere")):
        for token in (None, "wrong-" + TOKEN, TOKEN[:-1]):
            status, data = call(server, method, path, {} if method == "POST" else None, token=token)
            assert status == 401, (method, path, token)
            assert "launch token" in data["error"]
    # not JSON and no token: still 401, never a hint about the body
    assert call(server, "POST", "/api/keys", {}, token=None, ctype="text/plain")[0] == 401
    assert call(server, "GET", "/api/projects") == (200, [])
    assert call(server, "GET", "/api/ping")[1]["version"] == __version__
    # pairing is for a PC's server; on the phone it does not exist
    assert call(server, "POST", "/api/pair/claim", {"code": "X"})[0] == 403
    # a PC-only route stays closed, as on the paired server
    assert call(server, "GET", "/api/config")[0] == 403


def test_the_token_is_not_kept(server, tmp_path):
    home = server["home"]
    for f in home.rglob("*"):
        if f.is_file():
            assert TOKEN not in f.read_text(encoding="utf-8", errors="replace"), f
    assert TOKEN not in json.dumps(dict(os.environ))


def test_serve_local_takes_the_token_out_of_the_environment(clean_env, tmp_path, monkeypatch):
    seen = {}

    def fake(home, port, token):
        seen["token"], seen["env"] = token, os.environ.get("ROUNDTABLE_LAUNCH_TOKEN")
        raise ValueError("stop here")

    monkeypatch.setattr(onphone, "make_local_server", fake)
    monkeypatch.setenv("ROUNDTABLE_LAUNCH_TOKEN", TOKEN)
    assert onphone.serve_local(tmp_path / "h", 0) == 2
    assert seen == {"token": TOKEN, "env": None}


def test_cli_wants_local(capsys):
    assert onphone.main(["serve", "--port", "1"]) == 2
    assert "--local" in capsys.readouterr().err


def test_keys_are_saved_and_listed_without_values(server):
    secret = "sk-test-" + secrets.token_hex(8)
    status, data = call(server, "POST", "/api/keys", {"provider": "deepseek", "key": secret})
    assert status == 200 and secret not in json.dumps(data)
    keys = {k["provider"]: k for k in data["keys"]}
    assert keys["deepseek"] == {"provider": "deepseek", "name": "DEEPSEEK_API_KEY", "label": "DeepSeek", "set": True}
    assert keys["anthropic"]["set"] is False
    status, listed = call(server, "GET", "/api/keys")
    assert status == 200 and secret not in json.dumps(listed) and listed == data
    # in the key store's private file under the home, and in this process for the providers
    f = server["home"] / "config" / "keys.json"
    assert json.loads(f.read_text())["DEEPSEEK_API_KEY"] == secret
    if sys.platform != "win32":
        assert (f.stat().st_mode & 0o777) == 0o600
    assert os.environ["DEEPSEEK_API_KEY"] == secret
    # an empty key removes it; an unknown provider is refused plainly
    assert {k["provider"]: k["set"] for k in call(server, "POST", "/api/keys", {"provider": "deepseek", "key": ""})[1]["keys"]}["deepseek"] is False
    status, err = call(server, "POST", "/api/keys", {"provider": "nope", "key": "x"})
    assert status == 400 and "unknown provider" in err["error"]


def test_keys_are_loaded_at_the_next_start(clean_env, tmp_path):
    home = tmp_path / "h"
    httpd, _ = onphone.make_local_server(home, 0, TOKEN)
    httpd.server_close()
    from roundtable.desktop import KeyStore, Paths

    KeyStore(Paths(home), file_only=True).set("DEEPSEEK_API_KEY", "sk-saved")
    os.environ.pop("DEEPSEEK_API_KEY")
    httpd, _ = onphone.make_local_server(home, 0, TOKEN)
    httpd.server_close()
    assert os.environ["DEEPSEEK_API_KEY"] == "sk-saved"


def test_file_only_keystore_never_touches_a_keyring(tmp_path):
    from roundtable.desktop import KeyStore, Paths

    ks = KeyStore(Paths(tmp_path), file_only=True)
    assert ks.backend is None and ks.secure is False


# -- the first start -------------------------------------------------------------------------------
def test_first_start_writes_a_ready_config(server):
    home, app = server["home"], server["app"]
    cfg = load_config(str(home / "config" / "harness.yaml"))
    assert cfg.roles, "no roles"
    for name, role in cfg.roles.items():
        assert [str(m) for m in role.models] == ["deepseek/deepseek-v4-flash"], name
    assert "deepseek-v4-pro" not in (home / "config" / "harness.yaml").read_text()
    assert cfg.planner_role == "orchestrator" and cfg.reviewer_role == "reviewer" and cfg.critic_role == "critic"
    assert cfg.token_saver.enabled is True
    assert cfg.limits.max_real_usd_per_run == onphone.MAX_REAL_USD_PER_RUN == 1.0
    assert cfg.limits.max_cost_usd == onphone.MAX_COST_USD
    assert cfg.providers["deepseek"]["api_key_env"] == "DEEPSEEK_API_KEY"
    # a local hub, with this phone's seat, which the harness reports to
    seat = app.agent
    assert seat.startswith("phone-") and len(seat) == len("phone-") + 6
    hub = yaml.safe_load((home / "config" / "hub.yaml").read_text())
    assert hub["storage"] == {"type": "file", "path": str(home / "hub-data")}
    assert seat in hub["agents"] and app.hub and not app.hub_error
    assert cfg.hub == {"config": str(home / "config" / "hub.yaml"), "agent": seat}
    # projects in the workspaces folder
    assert app.projects_dir == (server["tmp"] / "workspaces").resolve() and app.projects_dir.is_dir()
    assert call(server, "GET", "/api/hub") == (200, {"mode": "file", "url": "", "seat": seat, "error": "",
                                                     "token": False})


def test_first_start_keeps_what_is_there(clean_env, tmp_path):
    home = tmp_path / "h"
    os.environ["ROUNDTABLE_SEAT"] = "phone-pixel"
    onphone.ensure_phone_setup(onphone.Paths(home))
    harness = home / "config" / "harness.yaml"
    harness.write_text(harness.read_text() + "# mine\n")
    first = onphone.Paths(home).load_settings()
    onphone.ensure_phone_setup(onphone.Paths(home))
    assert harness.read_text().endswith("# mine\n")
    assert yaml.safe_load((home / "config" / "hub.yaml").read_text())["agents"]["phone-pixel"]
    assert onphone.Paths(home).load_settings() == first


def test_default_workspaces_under_the_home(clean_env, tmp_path):
    assert onphone.workspaces_dir(tmp_path) == tmp_path / "projects"


def test_hub_token_goes_to_git_through_the_environment_only():
    env = onphone.git_auth_env("https://github.com/someone/hub-data", "tok123")
    assert env["GIT_CONFIG_KEY_0"] == "http.https://github.com/.extraHeader"
    assert base64.b64decode(env["GIT_CONFIG_VALUE_0"].split()[-1]).decode() == "x-access-token:tok123"
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    with pytest.raises(ValueError):
        onphone.git_auth_env("file:///root/.roundtable", "tok")


# -- idea -> plan -> approve -> run, through the phone's routes ------------------------------------------
def wait_job(srv, view):
    for _ in range(200):
        status, job = call(srv, "GET", f"/api/jobs/{view['id']}")
        assert status == 200
        if job["status"] != "running":
            return job
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def test_idea_plan_approve_run(server):
    app = server["app"]
    cfg = parse_config(json.loads(json.dumps(HARNESS_RAW)))
    cfg.lab_dir = server["tmp"] / "lab"
    brain = Brain()
    cfg.register("a", ScriptedProvider("a", brain))
    cfg.register("b", ScriptedProvider("b", brain))
    cfg.register("img", ScriptedImages())
    app.cfg = lambda: cfg

    status, job = call(server, "POST", "/api/projects", {"dir": "bakery", "goal": "a bakery site", "approve": True})
    assert status == 200
    job = wait_job(server, job)
    assert job["status"] == "done", job
    assert job["result"]["status"] == "awaiting_approval"
    path = job["result"]["path"]
    assert Path(path).parent == app.projects_dir

    status, projects = call(server, "GET", "/api/projects")
    assert [p["name"] for p in projects] == ["bakery"]
    status, plan = call(server, "GET", f"/api/plan?path={path}")
    assert status == 200 and plan["approved"] is False and plan["tasks"]

    status, job = call(server, "POST", "/api/plan", {"path": path, "action": "approve"})
    assert status == 200
    job = wait_job(server, job)
    assert job["status"] == "done", job
    assert call(server, "GET", "/api/jobs")[0] == 200


# -- the runtime build: manifest and signature -------------------------------------------------------------
def _tar_xz(path: Path, files: dict[str, bytes]) -> Path:
    raw = BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, BytesIO(data))
    path.write_bytes(lzma.compress(raw.getvalue()))
    return path


@pytest.fixture
def runtime_tools():
    sys.path.insert(0, str(RUNTIME))
    import make_manifest
    import sign_manifest

    yield make_manifest, sign_manifest
    sys.path.remove(str(RUNTIME))


def test_manifest_is_signed_and_checks_with_the_test_key(tmp_path, runtime_tools, clean_env):
    make_manifest, sign_manifest = runtime_tools
    layers = []
    for abi, arch in (("arm64-v8a", "aarch64"), ("x86_64", "x86_64")):
        base = _tar_xz(tmp_path / f"roundtable-base-{arch}.tar.xz", {"etc/os-release": b"debian", "usr/bin/x": b"12"})
        app = _tar_xz(tmp_path / f"roundtable-app-{arch}.tar.xz", {"opt/roundtable/venv/bin/roundtable": b"#!"})
        layers += [(abi, "base", base), (abi, "roundtable", app)]
    out = tmp_path / "manifest.json"
    assert make_manifest.main(["--release-tag", "runtime-2026.11.26-1", "--repo", "someone/agent-harness",
                               "--roundtable-version", "0.7.3"]
                              + [a for abi, name, p in layers for a in ("--layer", f"{abi}:{name}:{p}")]
                              + ["--out", str(out)]) == 0
    assert sign_manifest.main([str(out), "--key-env", "NO_SUCH_KEY_FOR_TESTS", "--test-fallback"]) == 0

    m = json.loads(out.read_bytes())
    pub = base64.b64decode((RUNTIME / "test-key" / "public.b64").read_text().strip())
    assert len(pub) == 32
    assert m["product"] == "roundtable" and m["channel"] == "test" and m["schemaVersion"] == 1
    assert m["sequence"] == 2026112601 and m["releaseId"] == "2026.11.26-1"
    assert m["signing"] == {"algorithm": "Ed25519", "keyId": sign_manifest.key_id(pub),
                            "signatureFile": "manifest.json.sig"}
    assert m["signing"]["keyId"] == (RUNTIME / "test-key" / "key-id.txt").read_text().strip()
    assert m["assetBaseUrl"] == "https://github.com/someone/agent-harness/releases/download/runtime-2026.11.26-1/"
    assert m["runtime"]["entrypoint"] == "/opt/roundtable/venv/bin/roundtable"
    assert m["runtime"]["readinessPrefix"] == onphone.READY
    assert set(m["archs"]) == {"arm64-v8a", "x86_64"}
    arm = m["archs"]["arm64-v8a"]
    assert arm["debianArch"] == "arm64" and [x["name"] for x in arm["layers"]] == ["base", "roundtable"]
    base = arm["layers"][0]
    assert base["file"] == "roundtable-base-aarch64.tar.xz" and base["compression"] == "xz"
    assert base["entries"] == 2 and base["unpackedSize"] == len(b"debian") + 2
    assert base["size"] == (tmp_path / base["file"]).stat().st_size and len(base["sha256"]) == 64
    assert arm["layers"][1]["owns"] == ["/opt/roundtable"]

    data = out.read_bytes()
    sig = (tmp_path / "manifest.json.sig").read_text()
    assert sign_manifest.verify(data, sig, pub)
    assert sign_manifest.main([str(out), "--verify", str(RUNTIME / "test-key" / "public.b64")]) == 0
    for i in (0, len(data) // 2, len(data) - 2):
        changed = bytearray(data)
        changed[i] ^= 0x01
        assert not sign_manifest.verify(bytes(changed), sig, pub)
    other = sign_manifest.raw_public(sign_manifest.Ed25519PrivateKey.generate())
    assert not sign_manifest.verify(data, sig, other)
    assert not sign_manifest.verify(data, "not base64!", pub)


def test_a_real_key_signs_stable(tmp_path, runtime_tools, clean_env):
    make_manifest, sign_manifest = runtime_tools
    m = make_manifest.build_manifest(release_tag="runtime-2026.11.27-3", repo="x/y", roundtable_version="1.0.0",
                                     layers=[("x86_64", "base", _tar_xz(tmp_path / "b.tar.xz", {"a": b"1"})),
                                             ("x86_64", "roundtable", _tar_xz(tmp_path / "r.tar.xz", {"b": b"2"}))])
    out = tmp_path / "manifest.json"
    out.write_bytes(make_manifest.dump(m))
    seed = os.urandom(32)
    os.environ["RT_TEST_SIGNING_KEY"] = base64.b64encode(seed).decode()
    assert sign_manifest.main([str(out), "--key-env", "RT_TEST_SIGNING_KEY"]) == 0
    signed = json.loads(out.read_bytes())
    key = sign_manifest.Ed25519PrivateKey.from_private_bytes(seed)
    assert signed["channel"] == "stable" and signed["sequence"] == 2026112703
    assert sign_manifest.verify(out.read_bytes(), (tmp_path / "manifest.json.sig").read_text(),
                                sign_manifest.raw_public(key))
    # no key and no fallback: refuses
    os.environ.pop("RT_TEST_SIGNING_KEY")
    assert sign_manifest.main([str(out), "--key-env", "RT_TEST_SIGNING_KEY"]) == 2


def test_manifest_refuses_bad_input(tmp_path, runtime_tools):
    make_manifest, _ = runtime_tools
    with pytest.raises(ValueError):
        make_manifest.sequence_from_tag("v1.0")
    one = _tar_xz(tmp_path / "b.tar.xz", {"a": b"1"})
    with pytest.raises(ValueError):  # a roundtable layer is missing
        make_manifest.build_manifest(release_tag="runtime-2026.11.26-1", repo="x/y", roundtable_version="1",
                                     layers=[("x86_64", "base", one)])
    with pytest.raises(ValueError):
        make_manifest.build_manifest(release_tag="runtime-2026.11.26-1", repo="x/y", roundtable_version="1",
                                     layers=[("mips", "base", one)])


def test_test_key_is_labelled_and_matches():
    from cryptography.hazmat.primitives import serialization

    readme = (RUNTIME / "test-key" / "README.md").read_text()
    assert "TEST" in readme and "public" in readme.lower()
    priv = serialization.load_pem_private_key((RUNTIME / "test-key" / "private.pem").read_bytes(), password=None)
    raw = priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    assert base64.b64encode(raw).decode() == (RUNTIME / "test-key" / "public.b64").read_text().strip()


def test_runtime_workflow_is_valid():
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "runtime.yml").read_text(encoding="utf-8"))
    on = wf.get("on", wf.get(True))  # YAML 1.1 reads a bare `on` as true
    assert on["workflow_dispatch"]["inputs"]["release_tag"]["required"] is False
    assert "runtime/**" in on["push"]["paths"] and on["push"]["branches"] == ["main"]
    assert set(wf["jobs"]) == {"layers", "manifest"}
    assert wf["jobs"]["layers"]["strategy"]["matrix"]["abi"] == ["aarch64", "x86_64"]
    assert wf["jobs"]["manifest"]["needs"] == "layers"
    steps = json.dumps(wf["jobs"]["manifest"]["steps"])
    assert "RUNTIME_SIGNING_KEY" in steps and "--test-fallback" in steps and "gh release create" in steps
    assert "qemu" in json.dumps(wf["jobs"]["layers"]["steps"])
    for f in ("Dockerfile", "build.sh", "make_manifest.py", "sign_manifest.py", "smoke.sh"):
        assert (RUNTIME / f).is_file(), f
