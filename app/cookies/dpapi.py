"""Win32-утилиты для DPAPI-расшифровки и обхода файловых блокировок."""

from __future__ import annotations

from pathlib import Path


def _dpapi_decrypt(data: bytes) -> bytes | None:
    """Расшифровывает DPAPI-защищённые данные через ctypes (без win32crypt)."""
    import ctypes
    import ctypes.wintypes

    class _DataBlob(ctypes.Structure):
        _fields_ = [
            ("cbData", ctypes.wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_char)),
        ]

    buf = ctypes.create_string_buffer(data, len(data))
    blob_in = _DataBlob(len(data), buf)
    blob_out = _DataBlob()
    ok = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
    )
    if not ok:
        return None
    result = ctypes.string_at(blob_out.pbData, blob_out.cbData)
    ctypes.windll.kernel32.LocalFree(blob_out.pbData)
    return result


def _copy_shared(src: Path, dst: Path) -> None:
    """Копирует файл с явными флагами FILE_SHARE_READ|WRITE|DELETE.

    Работает даже когда браузер держит файл открытым (SQLite byte-range locking).
    Падает с OSError если файл открыт с эксклюзивным доступом без sharing.
    """
    import ctypes
    import ctypes.wintypes as wt

    GENERIC_READ = 0x80000000
    FILE_SHARE_ALL = 0x7  # READ | WRITE | DELETE
    OPEN_EXISTING = 3
    INVALID_HANDLE = wt.HANDLE(-1).value

    k32 = ctypes.windll.kernel32
    # Без явного restype ctypes возвращает c_int (32-бит) — HANDLE на 64-бит Windows
    # может быть шире, тогда дескриптор будет обрезан и GetFileSizeEx упадёт.
    k32.CreateFileW.restype = wt.HANDLE
    k32.GetFileSizeEx.restype = wt.BOOL
    k32.ReadFile.restype = wt.BOOL

    h = k32.CreateFileW(
        str(src), GENERIC_READ, FILE_SHARE_ALL, None, OPEN_EXISTING, 0, None
    )
    if h == INVALID_HANDLE:
        err = k32.GetLastError()
        raise OSError(err, f"CreateFileW failed (err={err}): {src}")
    try:

        class _LargeInt(ctypes.Structure):
            _fields_ = [("QuadPart", ctypes.c_int64)]

        li = _LargeInt()
        if not k32.GetFileSizeEx(h, ctypes.byref(li)):
            raise OSError(k32.GetLastError(), f"GetFileSizeEx failed: {src}")
        size = li.QuadPart
        buf = ctypes.create_string_buffer(size)
        read = wt.DWORD()
        k32.ReadFile(h, buf, size, ctypes.byref(read), None)
        dst.write_bytes(bytes(buf)[: read.value])
    finally:
        k32.CloseHandle(h)
