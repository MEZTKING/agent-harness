# PyInstaller recipe for the Darkness Harness desktop app (Roundtable Hold before 1.0.0).
#   pyinstaller packaging/roundtable.spec --noconfirm
# Output: dist/DarknessHarness/DarknessHarness(.exe) plus its support files, and RoundtableHold(.exe), a small
# starter under the old name that opens the new one (so a taskbar pin made before the rename still works).
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).parent
ICON = str(ROOT / "packaging" / "darkness.ico")
NAME = "DarknessHarness"        # brand.EXE without .exe
LEGACY_NAME = "RoundtableHold"  # brand.LEGACY_EXE without .exe

hidden = (
    collect_submodules("roundtable", filter=lambda name: "mcp_server" not in name)
    + collect_submodules("anthropic")
    + collect_submodules("openai")
    + collect_submodules("keyring")
    + collect_submodules("segno")  # phone access: pairing QR code
    + ["cryptography.x509", "cryptography.hazmat.primitives.asymmetric.ec"]  # phone access: TLS certificate
    + ["webview", "yaml"]
    # MCP tool servers for roles (Unreal's editor and others): the client and what it pulls in
    + collect_submodules("mcp", filter=lambda name: not name.startswith("mcp.cli"))
    + collect_submodules("mcp_types")
    + collect_submodules("tzdata")  # schedules keep summer time on Windows
)

a = Analysis(
    [str(ROOT / "packaging" / "roundtable_app.py")],
    pathex=[str(ROOT / "src")],
    datas=collect_data_files("roundtable") + collect_data_files("tzdata"),  # UI, prompts, templates
    hiddenimports=hidden,
    excludes=["mcp.cli", "tkinter", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=NAME,
    console=False,  # a windowed app: no console window
    icon=ICON,
)

# The old-name starter: its own tiny Analysis (standard library only), sharing the app's support files.
starter = Analysis(
    [str(ROOT / "packaging" / "old_name_starter.py")],
    excludes=["tkinter", "pytest", "roundtable"],
    noarchive=False,
)
starter_exe = EXE(
    PYZ(starter.pure),
    starter.scripts,
    [],
    exclude_binaries=True,
    name=LEGACY_NAME,
    console=False,
    icon=ICON,
)

coll = COLLECT(exe, starter_exe, a.binaries, a.datas, starter.binaries, starter.datas, name=NAME)
