"""Launch a Zoo Tycoon copy for the lab or for two players on one PC.

zoo.exe refuses to start when another Zoo Tycoon window exists (FindWindowA check at 0x5337e6,
"is another instance running"). The launcher starts the copy suspended, overwrites that function's
first bytes with `xor eax, eax; ret` in the new process only, then resumes it. Nothing on disk changes.

The copy runs at below-normal priority; its windows are parked off-screen without taking focus.
"""

import ctypes
import ctypes.wintypes as wt
import os
import sys
import time

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
u32 = ctypes.WinDLL("user32", use_last_error=True)

CREATE_SUSPENDED = 0x4
BELOW_NORMAL_PRIORITY_CLASS = 0x4000
CREATE_UNICODE_ENVIRONMENT = 0x400
STARTF_USESHOWWINDOW = 0x1
SW_SHOWMINNOACTIVE = 7
PAGE_EXECUTE_READWRITE = 0x40

INSTANCE_CHECK = 0x5337E6
INSTANCE_CHECK_EXPECT = bytes.fromhex("81c164040000")  # add ecx, 0x464
INSTANCE_CHECK_PATCH = bytes.fromhex("31c0c3")  # xor eax, eax; ret


class STARTUPINFO(ctypes.Structure):
    _fields_ = [("cb", wt.DWORD), ("lpReserved", wt.LPWSTR), ("lpDesktop", wt.LPWSTR), ("lpTitle", wt.LPWSTR),
                ("dwX", wt.DWORD), ("dwY", wt.DWORD), ("dwXSize", wt.DWORD), ("dwYSize", wt.DWORD),
                ("dwXCountChars", wt.DWORD), ("dwYCountChars", wt.DWORD), ("dwFillAttribute", wt.DWORD),
                ("dwFlags", wt.DWORD), ("wShowWindow", wt.WORD), ("cbReserved2", wt.WORD),
                ("lpReserved2", ctypes.c_void_p), ("hStdInput", wt.HANDLE), ("hStdOutput", wt.HANDLE),
                ("hStdError", wt.HANDLE)]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [("hProcess", wt.HANDLE), ("hThread", wt.HANDLE), ("dwProcessId", wt.DWORD), ("dwThreadId", wt.DWORD)]


def _check(ok, what):
    if not ok:
        raise OSError(ctypes.get_last_error(), what)


def launch(game_dir, env_extra=None, minimized=True):  # minimized: start without focus
    exe = os.path.join(game_dir, "zoo.exe")
    env = dict(os.environ)
    env.update(env_extra or {})
    block = "".join(f"{k}={v}\0" for k, v in env.items()) + "\0"
    si = STARTUPINFO()
    si.cb = ctypes.sizeof(si)
    if minimized:
        si.dwFlags = STARTF_USESHOWWINDOW
        si.wShowWindow = SW_SHOWNOACTIVATE
    pi = PROCESS_INFORMATION()
    flags = CREATE_SUSPENDED | BELOW_NORMAL_PRIORITY_CLASS | CREATE_UNICODE_ENVIRONMENT
    _check(k32.CreateProcessW(exe, None, None, None, False, flags, ctypes.c_wchar_p(block), game_dir,
                              ctypes.byref(si), ctypes.byref(pi)), "CreateProcessW")
    try:
        buf = ctypes.create_string_buffer(len(INSTANCE_CHECK_EXPECT))
        n = ctypes.c_size_t()
        _check(k32.ReadProcessMemory(pi.hProcess, ctypes.c_void_p(INSTANCE_CHECK), buf, len(buf), ctypes.byref(n)), "read")
        if buf.raw != INSTANCE_CHECK_EXPECT:
            raise RuntimeError(f"unexpected zoo.exe build: bytes at {INSTANCE_CHECK:#x} are {buf.raw.hex()}")
        old = wt.DWORD()
        _check(k32.VirtualProtectEx(pi.hProcess, ctypes.c_void_p(INSTANCE_CHECK), 3, PAGE_EXECUTE_READWRITE, ctypes.byref(old)), "protect")
        _check(k32.WriteProcessMemory(pi.hProcess, ctypes.c_void_p(INSTANCE_CHECK), INSTANCE_CHECK_PATCH, 3, ctypes.byref(n)), "write")
        k32.VirtualProtectEx(pi.hProcess, ctypes.c_void_p(INSTANCE_CHECK), 3, old.value, ctypes.byref(old))
        k32.FlushInstructionCache(pi.hProcess, ctypes.c_void_p(INSTANCE_CHECK), 3)
    except Exception:
        k32.TerminateProcess(pi.hProcess, 1)
        raise
    k32.ResumeThread(pi.hThread)
    k32.CloseHandle(pi.hThread)
    k32.CloseHandle(pi.hProcess)
    return pi.dwProcessId


WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)


def windows_of(pid):
    found = []

    def cb(hwnd, _):
        p = wt.DWORD()
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
        if p.value == pid and u32.IsWindowVisible(hwnd):
            found.append(hwnd)
        return True

    u32.EnumWindows(WNDENUMPROC(cb), 0)
    return found


SW_SHOWNOACTIVATE = 4
SWP_NOSIZE, SWP_NOZORDER, SWP_NOACTIVATE = 0x1, 0x4, 0x10
PARK_X, PARK_Y = -4000, -4000


def park(pid):
    """Moves the copy's windows off-screen without focusing them.

    Not minimize: a minimized Zoo Tycoon window stops its whole game loop (no updateSim, so the
    console and the co-op tick freeze). Off-screen windows keep running.
    """
    for hwnd in windows_of(pid):
        if u32.IsIconic(hwnd):
            u32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
        r = wt.RECT()
        u32.GetWindowRect(hwnd, ctypes.byref(r))
        if r.left != PARK_X or r.top != PARK_Y:
            u32.SetWindowPos(hwnd, None, PARK_X, PARK_Y, 0, 0, SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)


def kill(pid):
    h = k32.OpenProcess(0x0001, False, pid)
    if h:
        k32.TerminateProcess(h, 0)
        k32.CloseHandle(h)


if __name__ == "__main__":
    pid = launch(sys.argv[1], dict(a.split("=", 1) for a in sys.argv[2:]))
    print(pid)
    for _ in range(30):
        time.sleep(1)
        park(pid)


def capture(pid, path):
    """Saves a PNG of the copy's main window (PrintWindow, works while parked off-screen).

    Needs Pillow; the lab puts it on sys.path from a private folder.
    """
    from PIL import Image

    g32 = ctypes.WinDLL("gdi32")
    hwnds = windows_of(pid)
    if not hwnds:
        return False
    hwnd = hwnds[0]
    r = wt.RECT()
    u32.GetClientRect(hwnd, ctypes.byref(r))
    w, h = r.right, r.bottom
    hdc = u32.GetDC(hwnd)
    mdc = g32.CreateCompatibleDC(hdc)
    bmp = g32.CreateCompatibleBitmap(hdc, w, h)
    g32.SelectObject(mdc, bmp)
    u32.PrintWindow(hwnd, mdc, 3)  # PW_CLIENTONLY | PW_RENDERFULLCONTENT

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG), ("biPlanes", wt.WORD),
                    ("biBitCount", wt.WORD), ("biCompression", wt.DWORD), ("biSizeImage", wt.DWORD),
                    ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG), ("biClrUsed", wt.DWORD),
                    ("biClrImportant", wt.DWORD)]

    bi = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
    buf = ctypes.create_string_buffer(w * h * 4)
    g32.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bi), 0)
    g32.DeleteObject(bmp)
    g32.DeleteDC(mdc)
    u32.ReleaseDC(hwnd, hdc)
    Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1).convert("RGB").save(path)
    return True


WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP = 0x200, 0x201, 0x202
WM_ACTIVATE, WM_ACTIVATEAPP = 0x6, 0x1C


def click(pid, x, y, settle=0.6):
    """Left-clicks client pixel (x, y) in the copy's window with posted messages.

    Zoo Tycoon handles its mouse through window messages, so this works on a parked, unfocused
    window and never moves the real mouse. It ignores the mouse while it thinks another app is
    active (with two copies, the one started last is), so tell it first that it is active.
    """
    hwnd = windows_of(pid)[0]
    lp = (y << 16) | (x & 0xFFFF)
    u32.PostMessageW(hwnd, WM_ACTIVATEAPP, 1, 0)
    u32.PostMessageW(hwnd, WM_ACTIVATE, 1, 0)
    u32.PostMessageW(hwnd, WM_MOUSEMOVE, 0, lp)
    time.sleep(0.2)
    u32.PostMessageW(hwnd, WM_LBUTTONDOWN, 1, lp)
    time.sleep(0.15)
    u32.PostMessageW(hwnd, WM_LBUTTONUP, 0, lp)
    time.sleep(settle)


def drag(pid, x0, y0, x1, y1, steps=8, settle=0.8, on_move=None):
    """Left-drags from client pixel (x0, y0) to (x1, y1) with posted messages (see click).

    on_move(x, y) runs before each mouse position is posted; the lab uses it to move the copy's fake
    mouse, since the game follows a drag through GetCursorPos rather than the messages.
    """
    on_move = on_move or (lambda x, y: None)
    hwnd = windows_of(pid)[0]
    u32.PostMessageW(hwnd, WM_ACTIVATEAPP, 1, 0)
    u32.PostMessageW(hwnd, WM_ACTIVATE, 1, 0)
    on_move(x0, y0)
    u32.PostMessageW(hwnd, WM_MOUSEMOVE, 0, (y0 << 16) | x0)
    time.sleep(0.2)
    u32.PostMessageW(hwnd, WM_LBUTTONDOWN, 1, (y0 << 16) | x0)
    for i in range(1, steps + 1):
        x, y = x0 + (x1 - x0) * i // steps, y0 + (y1 - y0) * i // steps
        time.sleep(0.08)
        on_move(x, y)
        u32.PostMessageW(hwnd, WM_MOUSEMOVE, 1, (y << 16) | x)  # MK_LBUTTON
    time.sleep(0.15)
    u32.PostMessageW(hwnd, WM_LBUTTONUP, 0, (y1 << 16) | x1)
    time.sleep(settle)


def wheel(pid, x, y, notches):
    """Scrolls the mouse wheel over client pixel (x, y); negative notches scroll down."""
    hwnd = windows_of(pid)[0]
    pt = wt.POINT(x, y)
    u32.ClientToScreen(hwnd, ctypes.byref(pt))  # WM_MOUSEWHEEL carries screen coordinates
    for _ in range(abs(notches)):
        delta = (120 if notches > 0 else -120) & 0xFFFF
        u32.PostMessageW(hwnd, 0x20A, delta << 16, ((pt.y & 0xFFFF) << 16) | (pt.x & 0xFFFF))
        time.sleep(0.3)
