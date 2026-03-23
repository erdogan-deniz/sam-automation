"""Вкладка Achievements: сканирование библиотеки и разблокировка достижений."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import customtkinter as ctk

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from app.cache import ALL_IDS_FILE, load_done_ids, load_error_ids, load_no_achievements_ids
from app.id_file import read_ids_ordered
from gui.runner import ScriptRunner

_SCAN_SCRIPT = Path(__file__).resolve().parent.parent.parent / "scripts" / "achievements" / "scan.py"
_UNLOCK_SCRIPT = Path(__file__).resolve().parent.parent.parent / "scripts" / "achievements" / "unlock.py"

_PROGRESS_RE = re.compile(r"\[(\d+)/(\d+)\]")


class AchievementsTab(ctk.CTkFrame):
    def __init__(self, master: ctk.CTkTabview, **kwargs) -> None:
        super().__init__(master, **kwargs)
        self._runner = ScriptRunner()
        self._runner.on_output = self._on_output
        self._runner.on_finish = self._on_finish
        self._poll_id: str | None = None

        self._build_ui()
        self.refresh_stats()

    # ------------------------------------------------------------------
    # UI

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)  # log expands

        # Stats
        stats_frame = ctk.CTkFrame(self, fg_color="transparent")
        stats_frame.grid(row=0, column=0, padx=16, pady=(16, 8), sticky="ew")
        stats_frame.grid_columnconfigure((0, 1, 2, 3), weight=1)

        self._lbl_library = self._stat_label(stats_frame, "Library", 0)
        self._lbl_done = self._stat_label(stats_frame, "Done", 1)
        self._lbl_errors = self._stat_label(stats_frame, "Errors", 2)
        self._lbl_no_ach = self._stat_label(stats_frame, "No ach.", 3)

        # Buttons
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.grid(row=1, column=0, padx=16, pady=4, sticky="ew")
        btn_frame.grid_columnconfigure((0, 1, 2, 3), weight=1)

        self._btn_scan = ctk.CTkButton(btn_frame, text="Scan Library", command=self._scan)
        self._btn_scan.grid(row=0, column=0, padx=4, sticky="ew")

        self._btn_unlock = ctk.CTkButton(btn_frame, text="Unlock All", command=self._unlock)
        self._btn_unlock.grid(row=0, column=1, padx=4, sticky="ew")

        self._btn_reset = ctk.CTkButton(
            btn_frame, text="Reset Progress", fg_color="#555", hover_color="#666",
            command=self._reset,
        )
        self._btn_reset.grid(row=0, column=2, padx=4, sticky="ew")

        self._btn_stop = ctk.CTkButton(
            btn_frame, text="Stop", fg_color="#a33", hover_color="#c44",
            command=self._stop,
        )
        self._btn_stop.grid(row=0, column=3, padx=4, sticky="ew")
        self._btn_stop.grid_remove()

        # Progress
        progress_frame = ctk.CTkFrame(self, fg_color="transparent")
        progress_frame.grid(row=2, column=0, padx=16, pady=4, sticky="ew")
        progress_frame.grid_columnconfigure(0, weight=1)

        self._progress = ctk.CTkProgressBar(progress_frame)
        self._progress.grid(row=0, column=0, padx=(0, 8), sticky="ew")
        self._progress.set(0)

        self._lbl_progress = ctk.CTkLabel(progress_frame, text="", width=80, anchor="w")
        self._lbl_progress.grid(row=0, column=1)

        # Log
        self._log = ctk.CTkTextbox(self, state="disabled", wrap="word", font=("Consolas", 12))
        self._log.grid(row=3, column=0, padx=16, pady=(4, 16), sticky="nsew")

    @staticmethod
    def _stat_label(parent: ctk.CTkFrame, title: str, col: int) -> ctk.CTkLabel:
        frame = ctk.CTkFrame(parent)
        frame.grid(row=0, column=col, padx=4, sticky="ew")
        ctk.CTkLabel(frame, text=title, font=("", 11), text_color="gray").pack(pady=(6, 0))
        lbl = ctk.CTkLabel(frame, text="—", font=("", 18, "bold"))
        lbl.pack(pady=(0, 6))
        return lbl

    # ------------------------------------------------------------------
    # Stats

    def refresh_stats(self) -> None:
        library = len(read_ids_ordered(ALL_IDS_FILE)) if ALL_IDS_FILE.exists() else 0
        done = len(load_done_ids())
        errors = len(load_error_ids())
        no_ach = len(load_no_achievements_ids())

        self._lbl_library.configure(text=str(library))
        self._lbl_done.configure(text=str(done))
        self._lbl_errors.configure(text=str(errors))
        self._lbl_no_ach.configure(text=str(no_ach))

    # ------------------------------------------------------------------
    # Button handlers

    def _scan(self) -> None:
        self._start_script(_SCAN_SCRIPT, [])

    def _unlock(self) -> None:
        self._start_script(_UNLOCK_SCRIPT, [])

    def _reset(self) -> None:
        self._start_script(_UNLOCK_SCRIPT, ["--reset"])

    def _stop(self) -> None:
        self._runner.stop()

    # ------------------------------------------------------------------
    # Script lifecycle

    def _start_script(self, script: Path, args: list[str]) -> None:
        if self._runner.is_running:
            return
        self._clear_log()
        self._progress.set(0)
        self._lbl_progress.configure(text="")
        self._set_buttons_state("disabled")
        self._btn_stop.grid()
        self._runner.run(script, args)
        self._schedule_poll()

    def _schedule_poll(self) -> None:
        self._poll_id = self.after(100, self._poll)

    def _poll(self) -> None:
        self._runner.poll_output()
        if self._runner.is_running:
            self._schedule_poll()

    def _on_output(self, line: str) -> None:
        self._append_log(line)
        m = _PROGRESS_RE.search(line)
        if m:
            current, total = int(m.group(1)), int(m.group(2))
            if total > 0:
                self._progress.set(current / total)
                self._lbl_progress.configure(text=f"{current} / {total}")

    def _on_finish(self, returncode: int) -> None:
        self._append_log(f"\n--- exit code: {returncode} ---")
        self._set_buttons_state("normal")
        self._btn_stop.grid_remove()
        self.refresh_stats()

    # ------------------------------------------------------------------
    # Log helpers

    def _append_log(self, text: str) -> None:
        self._log.configure(state="normal")
        self._log.insert("end", text + "\n")
        self._log.see("end")
        self._log.configure(state="disabled")

    def _clear_log(self) -> None:
        self._log.configure(state="normal")
        self._log.delete("1.0", "end")
        self._log.configure(state="disabled")

    def _set_buttons_state(self, state: str) -> None:
        for btn in (self._btn_scan, self._btn_unlock, self._btn_reset):
            btn.configure(state=state)
