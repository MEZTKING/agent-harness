# PyInstaller recipe for the Roundtable Hold desktop app.
#   pyinstaller packaging/roundtable.spec --noconfirm
# Output: dist/RoundtableHold/RoundtableHold(.exe) plus its support files.
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).parent
ICON = str(ROOT / "packaging" / "roundtable.ico")

hidden = (
    collect_submodules("roundtable", filter=lambda name: "mcp_server" not in name)
    + collect_submodules("anthropic")
    + collect_submodules("openai")
    + collect_submodules("keyring")
    + ["webview", "yaml"]
)

a = Analysis(
    [str(ROOT / "packaging" / "roundtable_app.py")],
    pathex=[str(ROOT / "src")],
    datas=collect_data_files("roundtable"),  # UI, prompts, templates
    hiddenimports=hidden,
    excludes=["mcp", "tkinter", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="RoundtableHold",
    console=False,  # a windowed app: no console window
    icon=ICON,
)
coll = COLLECT(exe, a.binaries, a.datas, name="RoundtableHold")
