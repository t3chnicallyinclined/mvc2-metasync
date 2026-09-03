#!/usr/bin/env python3
"""gamekeys.py -- focus the game window, tap keys into the Collection's front-end, take a screenshot.

    python gamekeys.py focus
    python gamekeys.py tap enter down down enter        # one tap per word; 30 ms hold, 350 ms settle (arcade-host calibration)
    python gamekeys.py shot <out.png>                    # screenshot of the game window's client area (GDI)
    python gamekeys.py state                             # read-only: clock / mode / paused / scene

Key facts (memory mvc-arcade-autohost-re, Windows port): scancodes up=0x48ext down=0x50ext left=0x4Bext right=0x4Dext
enter=0x1C backspace=0x0E lctrl=0x1D; each tap moves exactly one item with a SHORT hold and >=0.28 s settle.
The Collection front-end (game list, options) is OUTSIDE the DC sim; the receipt player only needs the process to be
inside the MvC2 title/menus so that FUN_140607d60 ticks. The shim's tick hook does the rest.
"""
import ctypes
import ctypes.wintypes as w
import os
import subprocess
import sys
import time

user32 = ctypes.windll.user32
SCAN = {"up": (0x48, True), "down": (0x50, True), "left": (0x4B, True), "right": (0x4D, True),
        "enter": (0x1C, False), "back": (0x0E, False), "lctrl": (0x1D, False), "esc": (0x01, False),
        "space": (0x39, False), "lshift": (0x2A, False), "z": (0x2C, False), "x": (0x2D, False)}
KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP, KEYEVENTF_SCANCODE = 0x1, 0x2, 0x8


def game_pid():
    out = subprocess.check_output(["tasklist", "/FI", "IMAGENAME eq MarvelVsCapcomFightingCollection.exe", "/FO", "CSV", "/NH"]).decode(errors="replace")
    for line in out.splitlines():
        if line.startswith('"'):
            return int(line.split('","')[1])
    return None


def game_hwnd():
    pid = game_pid()
    if not pid:
        return None
    found = []
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)

    def cb(h, _):
        p = w.DWORD()
        user32.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value == pid and user32.IsWindowVisible(h):
            n = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(h, n, 256)
            if n.value:
                found.append((h, n.value))
        return True
    user32.EnumWindows(WNDENUMPROC(cb), 0)
    for h, t in found:
        if "CAPCOM" in t.upper():
            return h
    return found[0][0] if found else None


def focus():
    h = game_hwnd()
    if not h:
        print("no game window"); return False
    # ALT tap unlocks SetForegroundWindow for a background caller (the arcade_host.ps1 trick)
    user32.keybd_event(0x12, 0, 0, 0); user32.keybd_event(0x12, 0, KEYEVENTF_KEYUP, 0)
    user32.SetForegroundWindow(h)
    time.sleep(0.3)
    ok = user32.GetForegroundWindow() == h
    print("focus %s (hwnd %s)" % ("OK" if ok else "FAILED", hex(h)))
    return ok


def tap(name, hold=0.03, settle=0.35):
    sc, ext = SCAN[name]
    fl = KEYEVENTF_SCANCODE | (KEYEVENTF_EXTENDEDKEY if ext else 0)
    user32.keybd_event(0, sc, fl, 0)
    time.sleep(hold)
    user32.keybd_event(0, sc, fl | KEYEVENTF_KEYUP, 0)
    time.sleep(settle)


def shot(path):
    """full primary-screen GDI capture (the game runs fullscreen in the foreground; PrintWindow of a D3D window is black)."""
    ps = r"""
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms
$b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($b.X, $b.Y, 0, 0, $bmp.Size)
$small = New-Object System.Drawing.Bitmap $bmp, ([int]($b.Width/2)), ([int]($b.Height/2))
$small.Save('%s', [System.Drawing.Imaging.ImageFormat]::Png)
Write-Host "shot $($b.Width) x $($b.Height) (saved at half size) -> %s"
""" % (path, path)
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=30)
    print((r.stdout + r.stderr).strip())
    return os.path.exists(path)


def state():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from replay_receipt import Proc
    p = Proc()
    live = p.live()
    gs = live["game_state"]
    print({k: (hex(v) if isinstance(v, int) and k in ("blk", "arena", "ggpo_session", "exe_base", "game_state") else v)
           for k, v in live.items()}, "scene", p.d(gs + 8) if gs else None)


if __name__ == "__main__":
    c = sys.argv[1] if len(sys.argv) > 1 else "state"
    if c == "focus":
        focus()
    elif c == "tap":
        focus()
        for k in sys.argv[2:]:
            tap(k)
            print("tap", k)
    elif c == "shot":
        shot(os.path.abspath(sys.argv[2]))
    else:
        state()
