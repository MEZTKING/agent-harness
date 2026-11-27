"""The Eclipse art (docs/art.md): every picture is there, opens, has the right shape and stays under its size cap."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "roundtable" / "ui" / "static"
RES = ROOT / "mobile" / "app" / "src" / "main" / "res"

# path, size cap in KB, expected pixel size (None: any; "wide"/"tall": that shape)
ART = [
    (STATIC / "eclipse.webp", 250, "wide"),
    (STATIC / "ring.webp", 120, None),
    (STATIC / "emblem.png", 60, (128, 128)),
    (STATIC / "icon.png", 30, (64, 64)),
    (STATIC / "wordmark.webp", 60, "wide"),
    (ROOT / "packaging" / "darkness.ico", 200, None),
    (ROOT / "packaging" / "darkness.png", 120, (256, 256)),
    (RES / "drawable-nodpi" / "eclipse_phone.webp", 250, "tall"),
] + [(RES / f"mipmap-{d}" / "ic_launcher_foreground.png", 160, (px, px))
     for d, px in {"mdpi": 108, "hdpi": 162, "xhdpi": 216, "xxhdpi": 324, "xxxhdpi": 432}.items()]


@pytest.mark.parametrize("path,cap_kb,shape", ART, ids=[p.name if "mipmap" not in str(p) else p.parent.name for p, _, _ in ART])
def test_art_exists_and_fits(path, cap_kb, shape):
    assert path.is_file(), f"missing art: {path.relative_to(ROOT)}"
    assert path.stat().st_size <= cap_kb * 1024, f"{path.name} is over {cap_kb} KB"
    Image = pytest.importorskip("PIL.Image")  # the shape check needs Pillow (not a dependency)
    with Image.open(path) as im:
        w, h = im.size
    if shape == "wide":
        assert w > h
    elif shape == "tall":
        assert h > w
    elif shape:
        assert (w, h) == shape


def test_icon_carries_every_windows_size():
    Image = pytest.importorskip("PIL.Image")
    with Image.open(ROOT / "packaging" / "darkness.ico") as im:
        sizes = im.info.get("sizes") or set()
    for n in (16, 32, 48, 256):
        assert (n, n) in sizes


def test_art_is_logged():
    text = (ROOT / "docs" / "art.md").read_text(encoding="utf-8")
    for name in ("eclipse.webp", "ring.webp", "emblem.png", "icon.png", "wordmark.webp", "darkness.ico", "eclipse_phone.webp"):
        assert name in text
