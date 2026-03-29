"""Вкладка Cards: обнаружение и фарм trading card drops."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import customtkinter as ctk

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from collections.abc import Callable

from app.cards.card_cache import load_card_done_ids
from gui.runner import ScriptRunner

_DETECT_SCRIPT = Path(__file__).resolve().parent.parent.parent / "scripts" / "cards" / "scan.py"
_FARM_SCRIPT = Path(__file__).resolve().parent.parent.parent / "scripts" / "cards" / "farm.py"

_PROGRESS_RE = re.compile(r"\[(\d+)/(\d+)\]")


class CardsTab(ctk.CTkFrame):
    """Вкладка управления trading cards: обнаружение дропов и запуск фарма."""

    def __init__(
        self,
        master: ctk.CTkTabview,
        check_config: Callable[[], bool] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(master, **kwargs)
        self._check_config = check_config or (lambda: True)
        self._runner = ScriptRunner()
        self._runner.on_output = self._on_output
        self._runner.on_finish = self._on_finish

        self._build_ui()
        self.refresh_stats()

    # ------------------------------------------------------------------
    # UI

    def _build_ui(self) -> None:
        """Строит все виджеты вкладки: статистику, кнопки, прогресс-бар, лог."""
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        # Stats
        stats_frame = ctk.CTkFrame(self, fg_color="transparent")
        stats_frame.grid(row=0, column=0, padx=16, pady=(16, 8), sticky="ew")
        stats_frame.grid_columnconfigure((0, 1), weight=1)

        self._lbl_done = self._stat_label(stats_frame, "Card Done", 0)
        self._lbl_status = self._stat_label(stats_frame, "Status", 1)

        # Buttons
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.grid(row=1, column=0, padx=16, pady=4, sticky="ew")
        btn_frame.grid_columnconfigure((0, 1, 2, 3, 4), weight=1)

        self._btn_fast = ctk.CTkButton(
            btn_frame, text="Detect (fast)", command=self._detect_fast,
        )
        self._btn_fast.grid(row=0, column=0, padx=4, sticky="ew")

        self._btn_exact = ctk.CTkButton(
            btn_frame, text="Detect (exact)", command=self._detect_exact,
        )
        self._btn_exact.grid(row=0, column=1, padx=4, sticky="ew")

        self._btn_farm = ctk.CTkButton(
            btn_frame, text="Farm Cards", command=self._farm,
        )
        self._btn_farm.grid(row=0, column=2, padx=4, sticky="ew")

        self._btn_reset = ctk.CTkButton(
            btn_frame, text="Reset", fg_color="#555", hover_color="#666",
            command=self._reset,
        )
        self._btn_reset.grid(row=0, column=3, padx=4, sticky="ew")

        self._btn_stop = ctk.CTkButton(
            btn_frame, text="Stop", fg_color="#a33", hover_color="#c44",
            command=self._stop,
        )
        self._btn_stop.grid(row=0, column=4, padx=4, sticky="ew")
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
        done = len(load_card_done_ids())
        self._lbl_done.configure(text=str(done))
        self._lbl_status.configure(text="Idle")

    # ------------------------------------------------------------------
    # Button handlers

    def _detect_fast(self) -> None:
        """Запускает быстрое обнаружение дропов (метод A, без авторизации)."""
        self._start_script(_DETECT_SCRIPT, ["--fast"])

    def _detect_exact(self) -> None:
        """Запускает точное обнаружение дропов (метод B, нужна JWT авторизация)."""
        self._start_script(_DETECT_SCRIPT, ["--exact"])

    def _farm(self) -> None:
        """Запускает основной цикл фарма trading cards."""
        self._start_script(_FARM_SCRIPT, [])

    def _reset(self) -> None:
        """Сбрасывает прогресс фарма и начинает заново."""
        self._start_script(_FARM_SCRIPT, ["--reset"])

    def stop(self) -> None:
        """Останавливает текущий запущенный скрипт (публичный метод для хоткея)."""
        self._runner.stop()

    def _stop(self) -> None:
        """Останавливает текущий запущенный скрипт."""
        self._runner.stop()

    # ------------------------------------------------------------------
    # Script lifecycle

    def _start_script(self, script: Path, args: list[str]) -> None:
        """Запускает скрипт, переводит кнопки в disabled и начинает polling вывода."""
        if self._runner.is_running:
            return
        if not self._check_config():
            return
        self._clear_log()
        self._progress.set(0)
        self._lbl_progress.configure(text="")
        self._lbl_status.configure(text="Running…")
        self._set_buttons_state("disabled")
        self._btn_stop.grid()
        self._runner.run(script, args)
        self._schedule_poll()

    def _schedule_poll(self) -> None:
        """Планирует следующий вызов _poll через 100 мс."""
        self.after(100, self._poll)

    def _poll(self) -> None:
        """Забирает накопленный вывод и перезапускает polling если скрипт ещё работает."""
        self._runner.poll_output()
        if self._runner.is_running:
            self._schedule_poll()

    def _on_output(self, line: str) -> None:
        """Добавляет строку в лог и обновляет прогресс-бар если найден паттерн [N/M]."""
        self._append_log(line)
        m = _PROGRESS_RE.search(line)
        if m:
            current, total = int(m.group(1)), int(m.group(2))
            if total > 0:
                self._progress.set(current / total)
                self._lbl_progress.configure(text=f"{current} / {total}")

    def _on_finish(self, returncode: int) -> None:
        """Вызывается по завершении скрипта: логирует код возврата, восстанавливает кнопки."""
        self._append_log(f"\n--- exit code: {returncode} ---")
        self._lbl_status.configure(text="Done" if returncode == 0 else f"Error ({returncode})")
        self._set_buttons_state("normal")
        self._btn_stop.grid_remove()
        self.refresh_stats()

    # ------------------------------------------------------------------
    # Log helpers

    def _append_log(self, text: str) -> None:
        """Добавляет строку текста в лог-виджет и прокручивает вниз."""
        self._log.configure(state="normal")
        self._log.insert("end", text + "\n")
        self._log.see("end")
        self._log.configure(state="disabled")

    def _clear_log(self) -> None:
        """Очищает содержимое лог-виджета."""
        self._log.configure(state="normal")
        self._log.delete("1.0", "end")
        self._log.configure(state="disabled")

    def _set_buttons_state(self, state: str) -> None:
        """Устанавливает состояние ("normal"/"disabled") для основных кнопок действий."""
        for btn in (self._btn_fast, self._btn_exact, self._btn_farm, self._btn_reset):
            btn.configure(state=state)
