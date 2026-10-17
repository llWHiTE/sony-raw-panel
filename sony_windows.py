import ctypes as C
from ctypes import wintypes as W
import time

u = C.WinDLL('user32', use_last_error=True)
k = C.WinDLL('kernel32', use_last_error=True)
CALLBACK = C.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
u.EnumWindows.argtypes = [CALLBACK, W.LPARAM]
u.EnumChildWindows.argtypes = [W.HWND, CALLBACK, W.LPARAM]
u.GetWindowThreadProcessId.argtypes = [W.HWND, C.POINTER(W.DWORD)]
u.GetWindowTextW.argtypes = [W.HWND, W.LPWSTR, C.c_int]
u.GetClassNameW.argtypes = [W.HWND, W.LPWSTR, C.c_int]
u.GetDlgCtrlID.argtypes = [W.HWND]
u.IsWindowVisible.argtypes = [W.HWND]
u.IsWindowEnabled.argtypes = [W.HWND]
u.IsWindow.argtypes = [W.HWND]
u.GetParent.argtypes = [W.HWND]
u.GetParent.restype = W.HWND
u.GetWindow.argtypes = [W.HWND, W.UINT]
u.GetWindow.restype = W.HWND
u.GetMenu.argtypes = [W.HWND]
u.GetMenu.restype = W.HMENU
u.GetMenuState.argtypes = [W.HMENU, W.UINT, W.UINT]
u.SendMessageTimeoutW.argtypes = [W.HWND, W.UINT, C.c_size_t, C.c_ssize_t, W.UINT, W.UINT, C.POINTER(C.c_size_t)]
u.SendMessageTimeoutW.restype = C.c_ssize_t
u.PostMessageW.argtypes = [W.HWND, W.UINT, C.c_size_t, C.c_ssize_t]
k.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
k.OpenProcess.restype = W.HANDLE
k.QueryFullProcessImageNameW.argtypes = [W.HANDLE, W.DWORD, W.LPWSTR, C.POINTER(W.DWORD)]
k.CloseHandle.argtypes = [W.HANDLE]
k.CreateMutexW.argtypes = [C.c_void_p, W.BOOL, W.LPCWSTR]
k.CreateMutexW.restype = W.HANDLE


def pid(h):
    p = W.DWORD()
    u.GetWindowThreadProcessId(h, C.byref(p))
    return p.value


def executable(p):
    handle = k.OpenProcess(0x1000, False, p)
    if not handle:
        return ''
    try:
        b = C.create_unicode_buffer(32768)
        n = W.DWORD(len(b))
        return b.value if k.QueryFullProcessImageNameW(handle, 0, b, C.byref(n)) else ''
    finally:
        k.CloseHandle(handle)


def text(h):
    b = C.create_unicode_buffer(32768)
    u.GetWindowTextW(h, b, len(b))
    return b.value


def cls(h):
    b = C.create_unicode_buffer(256)
    u.GetClassNameW(h, b, len(b))
    return b.value


def windows(parent=None):
    result = []

    @CALLBACK
    def visit(h, _):
        result.append(h)
        return True

    if parent is None:
        u.EnumWindows(visit, 0)
    else:
        u.EnumChildWindows(parent, visit, 0)
    return result


def send(h, msg, wp=0, lp=0):
    result = C.c_size_t()
    if not u.SendMessageTimeoutW(h, msg, wp, lp, 2, 3000, C.byref(result)):
        raise RuntimeError('Sony window is not responding.')
    return result.value


def post(h, msg, wp=0, lp=0):
    if not u.PostMessageW(h, msg, wp, lp):
        raise C.WinError(C.get_last_error())


def control(parent, ident, kind):
    matches = [h for h in windows(parent) if u.GetDlgCtrlID(h) == ident and cls(h) == kind and u.IsWindowVisible(h)]
    if len(matches) != 1:
        raise RuntimeError('Unexpected Sony dialog: control %s/%s has %s matches.' % (ident, kind, len(matches)))
    return matches[0]


def set_text(h, value):
    b = C.create_unicode_buffer(value)
    send(h, 0x000C, 0, C.addressof(b))


def get_text(h):
    b = C.create_unicode_buffer(32768)
    send(h, 0x000D, len(b), C.addressof(b))
    return b.value


def select(h, index):
    send(h, 0x014E, index)
    parent = u.GetParent(h)
    ident = u.GetDlgCtrlID(h)
    for notification in (1, 9):
        send(parent, 0x0111, ident | (notification << 16), h)
    if send(h, 0x0147) != index:
        raise RuntimeError('Sony did not accept the requested format/color space.')


def click(h):
    if not u.IsWindowEnabled(h):
        raise RuntimeError('Required Sony button is disabled.')
    post(h, 0x00F5)


def wait(check, seconds, label):
    end = time.monotonic() + seconds
    interval = 0.02
    while time.monotonic() < end:
        result = check()
        if result:
            return result
        time.sleep(min(interval, max(0, end - time.monotonic())))
        interval = min(0.20, interval * 1.4)
    raise TimeoutError(label)
