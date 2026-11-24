"""Send a house's folder to the Windows Recycle Bin (standard library only, copied from Jarvis 2.0's pcfiles.py).

Only a fixed drive keeps a Recycle Bin: on a USB stick or a network drive "delete" would be for good, so it refuses
there and the caller moves the folder to Houses/.deleted instead.
"""
import errno
from pathlib import Path

FO_DELETE, FOF_SILENT, FOF_NOCONFIRMATION, FOF_ALLOWUNDO, FOF_NOERRORUI = 3, 0x4, 0x10, 0x40, 0x400
DRIVE_FIXED = 3


def to_bin(path):
    """SHFileOperationW with FOF_ALLOWUNDO: the Recycle Bin, as Explorer's Delete does, never for good."""
    import ctypes
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", wintypes.LPCWSTR),
                    ("pTo", wintypes.LPCWSTR), ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL),
                    ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]
    if ctypes.windll.kernel32.GetDriveTypeW(ctypes.c_wchar_p(Path(path).anchor)) != DRIVE_FIXED:
        raise OSError(errno.EPERM, "that drive has no Recycle Bin, so it would be gone for good")
    op = SHFILEOPSTRUCTW(None, FO_DELETE, str(path) + "\0", None,
                         FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI, False, None, None)
    code = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if code or op.fAnyOperationsAborted:
        raise OSError(f"Windows answered {code:#x}")
