"""Richer previews (preview.py): notebooks, archives (listed, never unpacked), Word, Excel and PowerPoint as text
and tables, Open as PDF with a made-up LibreOffice; Range requests on /raw/pfile; a PDF's text in Your documents.
Every file is made up in the test."""

from __future__ import annotations

import base64
import io
import json
import tarfile
import zipfile

import pytest

from roundtable import documents, preview
from roundtable.ui import filesapi

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16).decode()


def _zip(parts: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, text in parts.items():
            z.writestr(name, text)
    return buf.getvalue()


def make_docx() -> bytes:
    body = (f'<w:document {W}><w:body>'
            '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Lantern guide</w:t></w:r></w:p>'
            '<w:p><w:r><w:t xml:space="preserve">Light the </w:t></w:r><w:r><w:rPr><w:b/></w:rPr><w:t>wick</w:t></w:r>'
            '<w:r><w:rPr><w:i/></w:rPr><w:t> slowly</w:t></w:r></w:p>'
            '<w:p><w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr></w:pPr><w:r><w:t>Oil</w:t></w:r></w:p>'
            '<w:p><w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr></w:pPr><w:r><w:t>Glass</w:t></w:r></w:p>'
            '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Part</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Count</w:t></w:r></w:p></w:tc></w:tr>'
            '<w:tr><w:tc><w:p><w:r><w:t>Wick</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>3</w:t></w:r></w:p></w:tc></w:tr></w:tbl>'
            '</w:body></w:document>')
    return _zip({"word/document.xml": body, "word/vbaProject.bin": "macro bytes, never read"})


def make_xlsx() -> bytes:
    S = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    R = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    return _zip({
        "xl/workbook.xml": f'<workbook {S} {R}><sheets><sheet name="Stock" sheetId="1" r:id="rId1"/>'
                           f'<sheet name="Empty" sheetId="2" r:id="rId2"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                                      '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/>'
                                      '<Relationship Id="rId2" Target="worksheets/sheet2.xml"/>'
                                      '<Relationship Id="rId9" TargetMode="External" Target="http://example.invalid/x"/>'
                                      '</Relationships>',
        "xl/sharedStrings.xml": f'<sst {S}><si><t>Item</t></si><si><t>Count</t></si><si><t>Wick</t></si></sst>',
        "xl/worksheets/sheet1.xml": f'<worksheet {S}><sheetData>'
                                    '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>'
                                    '<row r="2"><c r="A2" t="s"><v>2</v></c><c r="C2"><v>7</v></c></row>'
                                    '<row r="3"><c r="A3" t="inlineStr"><is><t>Oil</t></is></c><c r="B3" t="b"><v>1</v></c></row>'
                                    '</sheetData></worksheet>',
        "xl/worksheets/sheet2.xml": f'<worksheet {S}><sheetData/></worksheet>',
    })


def make_pptx() -> bytes:
    P = 'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'
    A = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
    R = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'

    def slide(*lines):
        paras = "".join(f"<a:p><a:r><a:t>{t}</a:t></a:r></a:p>" for t in lines)
        return f"<p:sld {P} {A}><p:cSld><p:spTree><p:sp><p:txBody>{paras}</p:txBody></p:sp></p:spTree></p:cSld></p:sld>"

    return _zip({
        "ppt/presentation.xml": f'<p:presentation {P} {R}><p:sldIdLst><p:sldId id="256" r:id="rId2"/>'
                                f'<p:sldId id="257" r:id="rId1"/></p:sldIdLst></p:presentation>',
        "ppt/_rels/presentation.xml.rels": '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                                           '<Relationship Id="rId1" Target="slides/slide2.xml"/>'
                                           '<Relationship Id="rId2" Target="slides/slide1.xml"/></Relationships>',
        "ppt/slides/slide1.xml": slide("Lanterns", "Why they glow"),
        "ppt/slides/slide2.xml": slide("Next steps"),
    })


def make_notebook() -> bytes:
    return json.dumps({"nbformat": 4, "metadata": {"language_info": {"name": "python"}}, "cells": [
        {"cell_type": "markdown", "source": ["# Glow\n", "How bright"]},
        {"cell_type": "code", "execution_count": 1, "source": "print(2 + 2)", "outputs": [
            {"output_type": "stream", "name": "stdout", "text": ["4\n"]},
            {"output_type": "display_data", "data": {"image/png": PNG, "text/plain": "<Figure>"}},
            {"output_type": "display_data", "data": {"text/html": "<script>alert(1)</script>"}},
            {"output_type": "error", "ename": "ValueError", "evalue": "dim", "traceback": ["\x1b[31mValueError\x1b[0m: dim"]},
        ]},
    ]}).encode()


def test_kind_of_each_file():
    assert preview.kind("a.ipynb") == "notebook" and preview.kind("x.tar.gz") == "archive"
    assert preview.kind("app.APK") == "archive" and preview.kind("r.docx") == "office"
    assert preview.kind("clip.mp4") == "video" and preview.kind("song.ogg") == "audio" and preview.kind("a.py") == ""


def test_a_word_file_gives_headings_runs_lists_and_tables():
    d = preview.docx(make_docx())
    types = [b["type"] for b in d["blocks"]]
    assert types == ["heading", "para", "list", "table"]
    assert d["blocks"][0] == {"type": "heading", "level": 1, "text": "Lantern guide"}
    runs = d["blocks"][1]["runs"]
    assert [r["text"] for r in runs] == ["Light the ", "wick", " slowly"] and runs[1]["bold"] and runs[2]["italic"]
    assert len(d["blocks"][2]["items"]) == 2
    assert d["blocks"][3]["rows"] == [["Part", "Count"], ["Wick", "3"]]


def test_an_excel_file_gives_a_table_per_sheet():
    d = preview.xlsx(make_xlsx())
    assert [s["name"] for s in d["sheets"]] == ["Stock", "Empty"]
    assert d["sheets"][0]["rows"] == [["Item", "Count"], ["Wick", "", "7"], ["Oil", "TRUE"]]
    assert d["sheets"][1]["rows"] == []


def test_a_powerpoint_file_gives_each_slides_text_in_order():
    d = preview.pptx(make_pptx())
    assert d["slides"] == [{"n": 1, "title": "Lanterns", "lines": ["Why they glow"]},
                           {"n": 2, "title": "Next steps", "lines": []}]


def test_a_damaged_or_unusual_office_file_says_so():
    with pytest.raises(preview.PreviewError):
        preview.docx(b"not a zip")
    bomb = _zip({"word/document.xml": '<!DOCTYPE x [<!ENTITY a "aaaa">]><x>&a;</x>'})
    with pytest.raises(preview.PreviewError):
        preview.docx(bomb)


def test_a_notebook_shows_cells_and_kept_outputs_but_never_html():
    d = preview.notebook(make_notebook())
    assert d["language"] == "python" and [c["type"] for c in d["cells"]] == ["markdown", "code"]
    outs = d["cells"][1]["outputs"]
    assert outs[0] == {"kind": "text", "text": "4\n", "stream": "stdout"}
    assert outs[1]["kind"] == "image" and outs[1]["mime"] == "image/png"
    assert outs[2]["kind"] == "text" and "<script>" not in outs[2]["text"]
    assert outs[3]["kind"] == "error" and "\x1b" not in outs[3]["text"]
    with pytest.raises(preview.PreviewError):
        preview.notebook(b"{broken")


def test_a_zip_with_a_dot_dot_name_is_listed_and_never_written(tmp_path):
    z = tmp_path / "parts.zip"
    z.write_bytes(_zip({"ok/readme.txt": "hello", "../escape.txt": "nope", "/abs.txt": "nope"}))
    before = sorted(p.name for p in tmp_path.parent.rglob("*"))
    d = preview.archive(z)
    assert d["format"] == "zip" and d["count"] == 3 and d["unsafe"] == 2
    assert {e["name"]: e["unsafe"] for e in d["entries"]}["ok/readme.txt"] is False
    assert sorted(p.name for p in tmp_path.parent.rglob("*")) == before  # nothing new anywhere
    assert not (tmp_path.parent / "escape.txt").exists()


def test_a_tar_is_listed_with_its_links(tmp_path):
    t = tmp_path / "parts.tar.gz"
    with tarfile.open(t, "w:gz") as tf:
        data = b"glow"
        info = tarfile.TarInfo("lamp/a.txt")
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
        link = tarfile.TarInfo("lamp/out")
        link.type, link.linkname = tarfile.SYMTYPE, "../../etc/passwd"
        tf.addfile(link)
    d = preview.archive(t)
    assert d["format"] == "tar" and d["count"] == 2 and d["total"] == 4
    assert [e["unsafe"] for e in d["entries"]] == [False, True]
    with pytest.raises(preview.PreviewError):
        (tmp_path / "plain.zip").write_bytes(b"not an archive")
        preview.archive(tmp_path / "plain.zip")


def test_open_as_pdf_runs_libreoffice_in_a_temporary_folder_with_a_clean_environment(tmp_path, monkeypatch):
    src = tmp_path / "guide.docx"
    src.write_bytes(make_docx())
    seen = {}

    def fake(argv, timeout, env):
        seen.update(argv=argv, env=env)
        out = argv[argv.index("--outdir") + 1]
        import pathlib

        pathlib.Path(out).mkdir(parents=True, exist_ok=True)
        (pathlib.Path(out) / "in.pdf").write_bytes(b"%PDF-1.4 made up")
        return 0

    monkeypatch.setenv("OPENAI_API_KEY", "proxy-injected")
    out = preview.to_pdf(src, tmp_path / "cache" / "x.pdf", "soffice", run=fake)
    assert out.read_bytes().startswith(b"%PDF") and "--headless" in seen["argv"]
    assert str(src) not in seen["argv"] and any(a.startswith("-env:UserInstallation=") for a in seen["argv"])
    assert "OPENAI_API_KEY" not in seen["env"]
    with pytest.raises(preview.PreviewError):
        preview.to_pdf(src, tmp_path / "y.pdf", "soffice", run=lambda *a: 1)


def test_libreoffice_is_found_on_path_or_not_at_all(tmp_path):
    assert preview.libreoffice(which=lambda n: "/opt/lo/soffice" if n == "soffice" else None) == "/opt/lo/soffice"
    assert preview.libreoffice(which=lambda n: None, env={}) in ("", "/Applications/LibreOffice.app/Contents/MacOS/soffice")


# -- Range on the raw route --------------------------------------------------------------------------------
def test_range_requests_give_only_those_bytes(tmp_path):
    f = tmp_path / "clip.mp4"
    f.write_bytes(bytes(range(100)))
    body, ctype, h = filesapi.raw_answer(f, range_header="bytes=10-19")
    assert body == bytes(range(10, 20)) and ctype == "video/mp4"
    assert h["_status"] == "206" and h["Content-Range"] == "bytes 10-19/100" and h["Accept-Ranges"] == "bytes"
    body, _, h = filesapi.raw_answer(f, range_header="bytes=90-")
    assert body == bytes(range(90, 100)) and h["Content-Range"] == "bytes 90-99/100"
    body, _, h = filesapi.raw_answer(f, range_header="bytes=-5")
    assert body == bytes(range(95, 100))
    body, _, h = filesapi.raw_answer(f, range_header="bytes=500-600")  # can't be met: the whole file
    assert len(body) == 100 and "_status" not in h
    body, _, h = filesapi.raw_answer(f)
    assert len(body) == 100 and "_status" not in h and h["Accept-Ranges"] == "bytes"
    assert filesapi.byte_range("bytes=0-1,5-6", 100) is None and filesapi.byte_range("items=1-2", 100) is None
    song = tmp_path / "song.mp3"
    song.write_bytes(b"ID3")
    assert filesapi.raw_answer(song)[1] == "audio/mpeg"
    assert "sandbox" in filesapi.raw_answer(song)[2]["Content-Security-Policy"]


def test_the_listing_and_open_say_which_rich_view_a_file_has(tmp_path):
    (tmp_path / "parts.zip").write_bytes(_zip({"a": "b"}))
    (tmp_path / "nb.ipynb").write_bytes(make_notebook())
    items = {i["name"]: i for i in filesapi.list_dir(tmp_path)["items"]}
    assert items["parts.zip"]["preview"] == "archive" and items["nb.ipynb"]["preview"] == "notebook"
    f = filesapi.read_file(tmp_path, "nb.ipynb")
    assert f["preview"] == "notebook" and f["kind"] == "text" and "cells" in f["text"]  # the phone as before


# -- a PDF's text in Your documents --------------------------------------------------------------------------
def _pdf(text: str) -> bytes:
    """A tiny one-page PDF with ``text`` on it, written by hand."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def test_a_pdfs_text_is_read_when_pypdf_is_there(tmp_path):
    pytest.importorskip("pypdf")
    d = documents.add_file(tmp_path, "rules.pdf", _pdf("Lanterns glow at dusk"))
    f = documents.files_of(tmp_path, d)[0][1]
    assert "Lanterns glow at dusk" in documents.read_text(f)
    assert "name only" not in documents.view(tmp_path, d)["note"]


def test_without_pypdf_a_pdf_is_found_by_name(tmp_path, monkeypatch):
    monkeypatch.setattr(documents, "pdf_reader", lambda: None)
    d = documents.add_file(tmp_path, "rules.pdf", _pdf("Lanterns glow"))
    assert documents.read_text(documents.files_of(tmp_path, d)[0][1]) == ""
    assert "name only" in documents.view(tmp_path, d)["note"]
