"""The owner's documents (documents.py): add, link, change, remove (moved aside), read Word, HTML and the rest.

Made-up files in tmp_path; the Word file is built here with zipfile.
"""

import base64
import io
import zipfile

import pytest

from roundtable import documents as docs
from roundtable import recall


def word_file(*paras):
    body = "".join(f'<w:p><w:r><w:t xml:space="preserve">{p}</w:t></w:r></w:p>' for p in paras)
    xml = ('<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
           f"<w:body>{body}</w:body></w:document>")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", xml)
    return buf.getvalue()


def test_add_a_file_and_read_it(tmp_path):
    d = docs.add_file(tmp_path, "style-guide.md", b"# Style\nUse round corners.")
    assert d["title"] == "Style guide" and d["projects"] == "all" and not d["private"]
    assert docs.all_documents(tmp_path) == [d]
    name, f = docs.files_of(tmp_path, d)[0]
    assert docs.read_text(f).startswith("# Style")


def test_a_word_file_is_read(tmp_path):
    d = docs.add_file(tmp_path, "brief.docx", word_file("The hero is a fox.", "Tom &amp; Jerry style chases."))
    text = docs.read_text(docs.files_of(tmp_path, d)[0][1])
    assert text == "The hero is a fox.\nTom & Jerry style chases."
    assert recall.find("fox hero", [], tmp_path)["pieces"][0]["doc"] == d["id"]


def test_html_loses_its_tags_and_scripts(tmp_path):
    assert docs.html_text("<html><head><title>x</title><script>bad()</script></head><body><p>Hello</p>"
                          "<p>there &amp; you</p></body></html>") == "Hello\n\nthere & you"


def test_a_pdf_is_kept_and_found_by_name_only(tmp_path):
    d = docs.add_file(tmp_path, "rules.pdf", b"%PDF-1.4 ...")
    assert docs.read_text(docs.files_of(tmp_path, d)[0][1]) == ""
    assert "PDF" in docs.view(tmp_path, d)["note"]


def test_upload_and_refusals(tmp_path):
    d = docs.add_upload(tmp_path, "a.txt", base64.b64encode(b"hello").decode())
    assert d["size"] == 5
    with pytest.raises(docs.DocumentError):
        docs.add_upload(tmp_path, "a.txt", "not base64!!")
    with pytest.raises(docs.DocumentError):
        docs.add_file(tmp_path, "tool.exe", b"MZ")


def test_link_a_folder_read_only(tmp_path):
    folder = tmp_path / "notes"
    (folder / "sub").mkdir(parents=True)
    (folder / "a.txt").write_text("Apples are red.", encoding="utf-8")
    (folder / "sub" / "b.md").write_text("Bananas are yellow.", encoding="utf-8")
    (folder / "c.bin").write_bytes(b"\0\1")
    before = sorted(p.name for p in folder.rglob("*"))
    d = docs.link_folder(tmp_path / "home", folder)
    assert d["kind"] == "folder" and [n for n, _ in docs.files_of(tmp_path / "home", d)] == ["a.txt", "sub/b.md"]
    assert recall.find("bananas", [], tmp_path / "home")["pieces"][0]["title"].endswith("sub/b.md")
    assert sorted(p.name for p in folder.rglob("*")) == before  # nothing written into it
    with pytest.raises(docs.DocumentError):
        docs.link_folder(tmp_path / "home", folder)
    with pytest.raises(docs.DocumentError):
        docs.link_folder(tmp_path / "home", tmp_path / "missing")


def test_change_who_may_use_it(tmp_path):
    d = docs.add_file(tmp_path, "a.txt", b"x")
    d = docs.change(tmp_path, d["id"], projects=["abc123def456"], private=True, title="Mine")
    assert d["projects"] == ["abc123def456"] and d["private"] and d["title"] == "Mine"
    assert docs.for_models(tmp_path) == []  # private: never for a model
    docs.change(tmp_path, d["id"], private=False)
    assert docs.for_models(tmp_path, "abc123def456") and not docs.for_models(tmp_path, "000000000000")
    assert docs.for_models(tmp_path, "abc123def456", setting="none") == []
    v = docs.view(tmp_path, docs.get(tmp_path, d["id"]), {"abc123def456": "Bakery"})
    assert v["who"] == "Bakery"


def test_remove_moves_it_aside(tmp_path):
    d = docs.add_file(tmp_path, "a.txt", b"Removed words")
    assert recall.find("removed words", [], tmp_path)["pieces"]
    docs.remove(tmp_path, d["id"])
    assert docs.all_documents(tmp_path) == []
    assert docs.removed(tmp_path)[0]["id"] == d["id"]
    assert (tmp_path / "documents" / ".removed" / f"{d['id']}-a.txt").read_bytes() == b"Removed words"
    assert not recall.find("removed words", [], tmp_path)["pieces"]
    with pytest.raises(docs.DocumentError):
        docs.remove(tmp_path, d["id"])
