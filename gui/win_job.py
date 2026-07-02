"""Win32 Job Object — гарантированное убийство всего дерева процессов.

GUI запускает скрипт (farm.py и т.п.) как subprocess, а тот — внуков
SAM.Game.exe. Чтобы Stop/Esc/закрытие окна НЕ оставляли сирот (аккаунт
застревает in-game), дочерний процесс помещается в Job Object с флагом
KILL_ON_JOB_CLOSE: при terminate_job() или закрытии хендла ОС убивает
ВСЁ дерево разом — не полагаясь на сигналы, обработчики или
прерываемость time.sleep. На не-Windows — no-op заглушки.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

_IS_WIN = sys.platform == "win32"

_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
_JobObjectExtendedLimitInformation = 9
_PROCESS_TERMINATE = 0x0001
_PROCESS_SET_QUOTA = 0x0100


if _IS_WIN:
    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)

    _k32.CreateJobObjectW.restype = wintypes.HANDLE
    _k32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    _k32.SetInformationJobObject.restype = wintypes.BOOL
    _k32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    _k32.OpenProcess.restype = wintypes.HANDLE
    _k32.OpenProcess.argtypes = [
        wintypes.DWORD,
        wintypes.BOOL,
        wintypes.DWORD,
    ]
    _k32.AssignProcessToJobObject.restype = wintypes.BOOL
    _k32.AssignProcessToJobObject.argtypes = [
        wintypes.HANDLE,
        wintypes.HANDLE,
    ]
    _k32.TerminateJobObject.restype = wintypes.BOOL
    _k32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _k32.CloseHandle.restype = wintypes.BOOL
    _k32.CloseHandle.argtypes = [wintypes.HANDLE]

    class _BASIC_LIMIT(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_void_p),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_uint64),
            ("WriteOperationCount", ctypes.c_uint64),
            ("OtherOperationCount", ctypes.c_uint64),
            ("ReadTransferCount", ctypes.c_uint64),
            ("WriteTransferCount", ctypes.c_uint64),
            ("OtherTransferCount", ctypes.c_uint64),
        ]

    class _EXTENDED_LIMIT(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _BASIC_LIMIT),
            ("IoInfo", _IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]


def create_kill_on_close_job() -> int | None:
    """Создаёт Job Object с KILL_ON_JOB_CLOSE. HANDLE (int) или None."""
    if not _IS_WIN:
        return None
    job = _k32.CreateJobObjectW(None, None)
    if not job:
        return None
    info = _EXTENDED_LIMIT()
    info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    ok = _k32.SetInformationJobObject(
        job,
        _JobObjectExtendedLimitInformation,
        ctypes.byref(info),
        ctypes.sizeof(info),
    )
    if not ok:
        _k32.CloseHandle(job)
        return None
    return int(job)


def assign_process(job: int | None, pid: int) -> bool:
    """Помещает процесс (и его будущих потомков) в job."""
    if not _IS_WIN or not job:
        return False
    handle = _k32.OpenProcess(
        _PROCESS_TERMINATE | _PROCESS_SET_QUOTA, False, pid
    )
    if not handle:
        return False
    try:
        return bool(_k32.AssignProcessToJobObject(job, handle))
    finally:
        _k32.CloseHandle(handle)


def terminate_job(job: int | None) -> None:
    """Убивает все процессы в job (внуков в т.ч.) и закрывает хендл."""
    if not _IS_WIN or not job:
        return
    _k32.TerminateJobObject(job, 1)
    _k32.CloseHandle(job)
