"""A picture of a running program's window (wave 8).

``window_picture(pid, out)`` finds the top-level window that belongs to the process or one of the processes it
started (the smoke start runs the EXE through ``cmd /c start /wait``, so the window is a grandchild's), waits
up to ``wait`` seconds for one that is visible and not tiny, and saves its picture to ``out`` as a PNG:

    {"ok": bool, "file": str | None, "why": str, "state": "passed" | "empty" | "missing" | "unchecked" | "failed",
     "title": str, "size": [w, h]}

* The finder and the grabber are passed in (``find(pid) -> [window]``, ``grab(window) -> PIL image | PNG
  bytes | None``), so the tests need no window. A window is ``{"handle", "pid", "title", "rect": (left, top,
  right, bottom), "visible", "minimised"}``.
* The real ones are Windows only: ``EnumWindows`` and ``GetWindowThreadProcessId`` over the process and its
  children (a Toolhelp snapshot), then ``PrintWindow`` (which pictures the window even when another covers it),
  falling back to a grab of its rectangle with Pillow. Elsewhere, with nothing passed in, the answer is "not
  checked" with the reason, and never a failure.
* A black or single-colour picture is ``state: "empty"`` ("the window was empty"): the program started but
  drew nothing. Grabs are tried again until the wait is over, since a window can take a moment to paint.
"""


import io
import os
import time
from pathlib import Path
from typing import Any, Callable

MIN_WIDTH, MIN_HEIGHT = 100, 60  # smaller than this is a splash dot or a hidden helper window, not the program
POLL = 0.25  # seconds between looks
EMPTY_SPREAD = 6  # a picture whose every colour channel varies by no more than this is "empty"
_sleep = time.sleep
_clock = time.monotonic


def is_windows() -> bool:
    return os.name == "nt"


def _result(state: str, why: str, file: Path | None = None, win: dict[str, Any] | None = None,
            size: tuple[int, int] | None = None) -> dict[str, Any]:
    return {"ok": state == "passed", "file": str(file) if file else None, "why": why, "state": state,
            "title": str((win or {}).get("title") or "")[:200], "size": list(size) if size else []}


def usable(win: dict[str, Any]) -> bool:
    """A window worth picturing: visible, not minimised, and not tiny."""
    try:
        left, top, right, bottom = (int(x) for x in win.get("rect") or (0, 0, 0, 0))
    except (TypeError, ValueError):
        return False
    return bool(win.get("visible", True)) and not win.get("minimised") and \
        right - left >= MIN_WIDTH and bottom - top >= MIN_HEIGHT


def _area(win: dict[str, Any]) -> int:
    left, top, right, bottom = (int(x) for x in win["rect"])
    return (right - left) * (bottom - top)


def as_image(got: Any):
    """What a grabber gave (a Pillow image or PNG bytes) as an RGB Pillow image, or None."""
    from PIL import Image

    if got is None:
        return None
    if isinstance(got, (bytes, bytearray)):
        try:
            got = Image.open(io.BytesIO(bytes(got)))
            got.load()
        except Exception:  # noqa: BLE001 - not a picture
            return None
    if not hasattr(got, "convert"):
        return None
    return got.convert("RGB")


def is_empty(img) -> bool:
    """Black, white or any one colour all over (a little noise allowed)."""
    try:
        return all(hi - lo <= EMPTY_SPREAD for lo, hi in img.convert("RGB").getextrema())
    except Exception:  # noqa: BLE001
        return True


def window_picture(pid: int, out: Path, wait: float = 8.0, grab=None, find=None) -> dict:
    """Find the process's window (waiting up to ``wait`` seconds), picture it into ``out``; see the module."""
    if find is None or grab is None:
        if not is_windows():
            return _result("unchecked", "Not checked: a program's window is pictured on Windows only, and this "
                                        "computer isn't running Windows.")
        find = find or find_windows
        grab = grab or grab_window
    out = Path(out)
    deadline = _clock() + max(0.0, float(wait))
    seen: dict[str, Any] | None = None
    last_empty: tuple[Any, dict[str, Any]] | None = None
    error = ""
    while True:
        try:
            wins = [w for w in (find(int(pid)) or []) if usable(w)]
        except Exception as e:  # noqa: BLE001 - a finder that broke: said plainly, never a crash
            wins, error = [], f"its windows couldn't be listed ({str(e)[:200]})"
        if wins:
            win = max(wins, key=_area)  # the main window is the biggest of the program's own
            seen = win
            try:
                img = as_image(grab(win))
            except Exception as e:  # noqa: BLE001
                img, error = None, f"its picture couldn't be taken ({str(e)[:200]})"
            if img is not None and not is_empty(img):
                out.parent.mkdir(parents=True, exist_ok=True)
                img.save(out, "PNG")
                return _result("passed", f"Its window{_titled(win)} was pictured.", out, win, img.size)
            if img is not None:
                last_empty = (img, win)
        if _clock() >= deadline:
            break
        _sleep(POLL)
    secs = f"{float(wait):g}"
    if last_empty is not None:
        img, win = last_empty
        out.parent.mkdir(parents=True, exist_ok=True)
        img.save(out, "PNG")
        return _result("empty", f"The window was empty: the program{_titled(win)} opened a window but it stayed "
                                f"one plain colour for {secs} seconds.", out, win, img.size)
    if seen is not None:
        return _result("failed", f"Its window{_titled(seen)} appeared, but {error or 'no picture could be taken'}.",
                       None, seen)
    return _result("missing", f"No window appeared within {secs} seconds"
                              + (f": {error}." if error else ", so there was nothing to picture."))


def _titled(win: dict[str, Any]) -> str:
    t = str(win.get("title") or "").strip()
    return f" ({t[:80]})" if t else ""


# -- Windows: the real finder and grabber ---------------------------------------------------------------------
def _process_tree(pid: int) -> set[int]:
    """``pid`` and every process it started, and theirs (a Toolhelp snapshot of all processes)."""
    import ctypes
    from ctypes import wintypes

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD),
                    ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                    ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
                    ("szExeFile", ctypes.c_wchar * 260)]

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    k32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    k32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    snap = k32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
    if not snap or snap == ctypes.c_void_p(-1).value:
        return {int(pid)}
    parents: dict[int, list[int]] = {}
    try:
        e = PROCESSENTRY32W()
        e.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        more = k32.Process32FirstW(snap, ctypes.byref(e))
        while more:
            parents.setdefault(int(e.th32ParentProcessID), []).append(int(e.th32ProcessID))
            more = k32.Process32NextW(snap, ctypes.byref(e))
    finally:
        k32.CloseHandle(snap)
    tree, todo = {int(pid)}, [int(pid)]
    while todo:
        for child in parents.get(todo.pop(), []):
            if child not in tree and child != 0:
                tree.add(child)
                todo.append(child)
    return tree


def find_windows(pid: int) -> list[dict[str, Any]]:
    """The top-level windows of ``pid`` and its children (Windows only)."""
    import ctypes
    from ctypes import wintypes

    pids = _process_tree(pid)
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [proc, wintypes.LPARAM]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    found: list[dict[str, Any]] = []

    def each(hwnd, _lparam):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if int(owner.value) in pids:
            r = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(r))
            n = user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            found.append({"handle": int(hwnd or 0), "pid": int(owner.value), "title": buf.value,
                          "rect": (r.left, r.top, r.right, r.bottom), "visible": bool(user32.IsWindowVisible(hwnd)),
                          "minimised": bool(user32.IsIconic(hwnd))})
        return True

    user32.EnumWindows(proc(each), 0)
    return found


def _print_window(win: dict[str, Any]):
    """``PrintWindow`` into a bitmap (pictures the window even under another): a Pillow image, or None."""
    import ctypes
    from ctypes import wintypes

    from PIL import Image

    left, top, right, bottom = (int(x) for x in win["rect"])
    w, h = right - left, bottom - top
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    vp = ctypes.c_void_p
    user32.GetWindowDC.restype, user32.GetWindowDC.argtypes = vp, [wintypes.HWND]
    user32.ReleaseDC.argtypes = [wintypes.HWND, vp]
    user32.PrintWindow.argtypes = [wintypes.HWND, vp, wintypes.UINT]
    gdi32.CreateCompatibleDC.restype, gdi32.CreateCompatibleDC.argtypes = vp, [vp]
    gdi32.CreateCompatibleBitmap.restype, gdi32.CreateCompatibleBitmap.argtypes = vp, [vp, ctypes.c_int, ctypes.c_int]
    gdi32.SelectObject.restype, gdi32.SelectObject.argtypes = vp, [vp, vp]
    gdi32.DeleteObject.argtypes = [vp]
    gdi32.DeleteDC.argtypes = [vp]

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long),
                    ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                    ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wintypes.DWORD),
                    ("biClrImportant", wintypes.DWORD)]

    gdi32.GetDIBits.argtypes = [vp, vp, wintypes.UINT, wintypes.UINT, vp, ctypes.POINTER(BITMAPINFOHEADER),
                                wintypes.UINT]
    hwnd = win["handle"]
    wdc = user32.GetWindowDC(hwnd)
    if not wdc:
        return None
    mdc = gdi32.CreateCompatibleDC(wdc)
    bmp = gdi32.CreateCompatibleBitmap(wdc, w, h)
    try:
        old = gdi32.SelectObject(mdc, bmp)
        ok = user32.PrintWindow(hwnd, mdc, 2)  # PW_RENDERFULLCONTENT: windows drawn by the graphics card too
        gdi32.SelectObject(mdc, old)  # GetDIBits wants the bitmap out of the device context
        if not ok:
            return None
        bmi = BITMAPINFOHEADER(biSize=ctypes.sizeof(BITMAPINFOHEADER), biWidth=w, biHeight=-h, biPlanes=1,
                               biBitCount=32, biCompression=0)
        buf = ctypes.create_string_buffer(w * h * 4)
        if not gdi32.GetDIBits(wdc, bmp, 0, h, buf, ctypes.byref(bmi), 0):
            return None
        return Image.frombuffer("RGB", (w, h), buf.raw, "raw", "BGRX", 0, 1)
    finally:
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mdc)
        user32.ReleaseDC(hwnd, wdc)


def grab_window(win: dict[str, Any]):
    """``PrintWindow`` first; when that fails or comes back one colour, a grab of the window's rectangle."""
    try:
        img = _print_window(win)
    except Exception:  # noqa: BLE001 - an old Windows or a window that refuses: the screen grab instead
        img = None
    if img is not None and not is_empty(img):
        return img
    from PIL import ImageGrab

    left, top, right, bottom = (int(x) for x in win["rect"])
    return ImageGrab.grab(bbox=(left, top, right, bottom), all_screens=True)


Finder = Callable[[int], list]
Grabber = Callable[[dict], Any]
