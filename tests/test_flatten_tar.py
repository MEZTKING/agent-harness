"""The phone's runtime layers carry no hard links or pax headers (the phone refuses both)."""

import importlib.util
import io
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("flatten_tar", ROOT / "runtime" / "flatten_tar.py")
flatten_tar = importlib.util.module_from_spec(spec)
spec.loader.exec_module(flatten_tar)


def _add(t, name, data=b"", kind=tarfile.REGTYPE, link=""):
    m = tarfile.TarInfo(name)
    m.type, m.linkname, m.mode = kind, link, 0o755
    if kind == tarfile.REGTYPE:
        m.size = len(data)
        t.addfile(m, io.BytesIO(data))
    else:
        t.addfile(m)


def test_hard_links_become_copies_and_nothing_else_changes(tmp_path):
    src, dst = tmp_path / "in.tar", tmp_path / "out.tar"
    long_name = "usr/share/" + "x" * 120 + "/file.txt"
    with tarfile.open(src, "w:", format=tarfile.PAX_FORMAT) as t:
        _add(t, "usr", kind=tarfile.DIRTYPE)
        _add(t, "usr/bin", kind=tarfile.DIRTYPE)
        _add(t, "usr/bin/perl", b"#!perl body")
        _add(t, "usr/bin/perl5.36.0", kind=tarfile.LNKTYPE, link="usr/bin/perl")
        _add(t, "usr/bin/p", kind=tarfile.SYMTYPE, link="perl")
        _add(t, long_name, b"long")
    n = flatten_tar.flatten(str(src), str(dst))
    assert n["hardlinks"] == 1
    with tarfile.open(dst) as t:
        members = {m.name: m for m in t}
        assert not any(m.islnk() for m in members.values())
        assert not any(m.type in (tarfile.XHDTYPE, tarfile.XGLTYPE) for m in members.values())
        assert t.extractfile(members["usr/bin/perl5.36.0"]).read() == b"#!perl body"
        assert members["usr/bin/p"].issym() and members["usr/bin/p"].linkname == "perl"
        assert t.extractfile(members[long_name]).read() == b"long"
    raw = dst.read_bytes()
    # no pax ('x'/'g') header blocks: byte 156 of every header is the type flag
    assert b"ustar" in raw


def test_a_link_to_something_missing_is_refused(tmp_path):
    src = tmp_path / "in.tar"
    with tarfile.open(src, "w:") as t:
        _add(t, "a", kind=tarfile.LNKTYPE, link="nowhere")
    try:
        flatten_tar.flatten(str(src), str(tmp_path / "out.tar"))
    except ValueError as e:
        assert "nowhere" in str(e)
    else:
        raise AssertionError("expected a refusal")


def test_the_build_flattens_every_layer_before_compressing():
    build = (ROOT / "runtime" / "build.sh").read_text()
    assert build.index("flatten_tar.py") < build.index("xz -T0")
