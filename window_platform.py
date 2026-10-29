# -*- coding: utf-8 -*-

import sys


def _x11_set_above(wid, on):
    import ctypes

    class XClientMessageEvent(ctypes.Structure):
        _fields_ = [
            ("type", ctypes.c_int),
            ("serial", ctypes.c_ulong),
            ("send_event", ctypes.c_int),
            ("display", ctypes.c_void_p),
            ("window", ctypes.c_ulong),
            ("message_type", ctypes.c_ulong),
            ("format", ctypes.c_int),
            ("data", ctypes.c_long * 5),
        ]

    class XEvent(ctypes.Union):
        _fields_ = [("xclient", XClientMessageEvent), ("pad", ctypes.c_long * 24)]

    try:
        x11 = ctypes.cdll.LoadLibrary("libX11.so.6")
    except OSError:
        return False

    x11.XOpenDisplay.restype = ctypes.c_void_p
    x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x11.XInternAtom.restype = ctypes.c_ulong
    x11.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
    x11.XDefaultRootWindow.restype = ctypes.c_ulong
    x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
    x11.XSendEvent.restype = ctypes.c_int
    x11.XSendEvent.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int,
                               ctypes.c_long, ctypes.POINTER(XEvent)]
    x11.XFlush.argtypes = [ctypes.c_void_p]
    x11.XCloseDisplay.argtypes = [ctypes.c_void_p]

    dpy = x11.XOpenDisplay(None)
    if not dpy:
        return False
    try:
        root = x11.XDefaultRootWindow(dpy)
        state = x11.XInternAtom(dpy, b"_NET_WM_STATE", False)
        above = x11.XInternAtom(dpy, b"_NET_WM_STATE_ABOVE", False)
        ev = XEvent()
        ev.xclient.type = 33
        ev.xclient.send_event = 1
        ev.xclient.window = wid
        ev.xclient.message_type = state
        ev.xclient.format = 32
        ev.xclient.data[0] = 1 if on else 0
        ev.xclient.data[1] = above
        ev.xclient.data[2] = 2
        mask = 0x00140000
        x11.XSendEvent(dpy, root, 0, mask, ctypes.byref(ev))
        x11.XFlush(dpy)
        return True
    except Exception:
        return False
    finally:
        x11.XCloseDisplay(dpy)


def set_native_topmost(wid, on):
    """Apply the native always-on-top hint where the platform supports it."""
    if sys.platform == "win32":
        import ctypes
        user32 = ctypes.windll.user32
        user32.SetWindowPos.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
        user32.SetWindowPos.restype = ctypes.c_int
        hwnd_topmost = ctypes.c_void_p(0xFFFFFFFFFFFFFFFF)
        hwnd_notopmost = ctypes.c_void_p(0xFFFFFFFFFFFFFFFE)
        swp_nosize, swp_nomove, swp_noactivate = 0x0001, 0x0002, 0x0010
        ok = user32.SetWindowPos(
            ctypes.c_void_p(wid),
            hwnd_topmost if on else hwnd_notopmost,
            0, 0, 0, 0, swp_nosize | swp_nomove | swp_noactivate)
        return bool(ok)
    if sys.platform.startswith("linux"):
        try:
            return _x11_set_above(wid, on)
        except Exception:
            return False
    return False
