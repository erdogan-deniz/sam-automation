"""Вкладка Settings: редактирование config.yaml."""

from __future__ import annotations

import sys
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from app.config import load_config

_CONFIG_PATH = Path("config.yaml")


class SettingsTab(ctk.CTkScrollableFrame):
    def __init__(self, master: ctk.CTkTabview, **kwargs) -> None:
        super().__init__(master, **kwargs)
        self.grid_columnconfigure(1, weight=1)
        self._build_ui()
        self._load()

    # ------------------------------------------------------------------
    # UI

    def _build_ui(self) -> None:
        row = 0

        # ── Required ──────────────────────────────────────────────────
        row = self._section("Required", row)

        self._steam_api_key = self._field("steam_api_key", row, show="*")
        row += 1
        self._steam_id = self._field("steam_id", row)
        row += 1

        # ── Paths ─────────────────────────────────────────────────────
        row = self._section("Paths", row)

        self._sam_exe, row = self._path_field("sam_game_exe_path", row, kind="file")
        self._steam_path, row = self._path_field("steam_path", row, kind="dir")

        # ── Timeouts ──────────────────────────────────────────────────
        row = self._section("Timeouts (seconds)", row)

        self._launch_delay = self._field("launch_delay", row)
        row += 1
        self._load_timeout = self._field("load_timeout", row)
        row += 1
        self._post_commit_delay = self._field("post_commit_delay", row)
        row += 1
        self._between_games_delay = self._field("between_games_delay", row)
        row += 1

        # ── Behaviour ─────────────────────────────────────────────────
        row = self._section("Behaviour", row)

        self._max_consecutive_errors = self._field("max_consecutive_errors", row)
        row += 1

        # ── Card farming ──────────────────────────────────────────────
        row = self._section("Card Farming", row)

        self._max_concurrent_games = self._field("max_concurrent_games", row)
        row += 1
        self._card_check_interval = self._field("card_check_interval", row)
        row += 1

        # ── Exclude IDs ───────────────────────────────────────────────
        row = self._section("Exclude App IDs (one per line)", row)

        self._exclude_ids = ctk.CTkTextbox(self, height=80, font=("Consolas", 12))
        self._exclude_ids.grid(row=row, column=0, columnspan=3, padx=8, pady=4, sticky="ew")
        row += 1

        # ── Save button ───────────────────────────────────────────────
        self._lbl_saved = ctk.CTkLabel(self, text="", text_color="green")
        self._lbl_saved.grid(row=row, column=0, columnspan=3, pady=(4, 0))
        row += 1

        btn = ctk.CTkButton(self, text="Save", command=self._save)
        btn.grid(row=row, column=0, columnspan=3, padx=8, pady=(4, 16), sticky="ew")

    def _section(self, title: str, row: int) -> int:
        """Рисует разделитель-заголовок, возвращает следующий row."""
        ctk.CTkLabel(
            self, text=title, font=("", 12, "bold"), anchor="w",
        ).grid(row=row, column=0, columnspan=3, padx=8, pady=(12, 2), sticky="w")
        return row + 1

    def _field(self, label: str, row: int, show: str = "") -> ctk.CTkEntry:
        """Строка label + entry, возвращает виджет entry."""
        ctk.CTkLabel(self, text=label, anchor="w").grid(
            row=row, column=0, padx=(8, 4), pady=2, sticky="w",
        )
        entry = ctk.CTkEntry(self, show=show)
        entry.grid(row=row, column=1, columnspan=2, padx=(0, 8), pady=2, sticky="ew")
        return entry

    def _path_field(
        self, label: str, row: int, kind: str
    ) -> tuple[ctk.CTkEntry, int]:
        """Строка label + entry + Browse, возвращает (entry, next_row)."""
        ctk.CTkLabel(self, text=label, anchor="w").grid(
            row=row, column=0, padx=(8, 4), pady=2, sticky="w",
        )
        entry = ctk.CTkEntry(self)
        entry.grid(row=row, column=1, padx=(0, 4), pady=2, sticky="ew")

        btn = ctk.CTkButton(
            self, text="Browse", width=70,
            command=lambda e=entry, k=kind: self._browse(e, k),
        )
        btn.grid(row=row, column=2, padx=(0, 8), pady=2)
        return entry, row + 1

    # ------------------------------------------------------------------
    # Browse

    def _browse(self, entry: ctk.CTkEntry, kind: str) -> None:
        if kind == "file":
            path = filedialog.askopenfilename(
                filetypes=[("Executable", "*.exe"), ("All", "*.*")]
            )
        else:
            path = filedialog.askdirectory()
        if path:
            entry.delete(0, "end")
            entry.insert(0, path)

    # ------------------------------------------------------------------
    # Load / Save

    def _load(self) -> None:
        cfg = load_config(str(_CONFIG_PATH))

        self._set(self._steam_api_key, cfg.steam_api_key)
        self._set(self._steam_id, cfg.steam_id)
        self._set(self._sam_exe, cfg.sam_game_exe_path)
        self._set(self._steam_path, cfg.steam_path)
        self._set(self._launch_delay, str(cfg.launch_delay))
        self._set(self._load_timeout, str(cfg.load_timeout))
        self._set(self._post_commit_delay, str(cfg.post_commit_delay))
        self._set(self._between_games_delay, str(cfg.between_games_delay))
        self._set(self._max_consecutive_errors, str(cfg.max_consecutive_errors))
        self._set(self._max_concurrent_games, str(cfg.max_concurrent_games))
        self._set(self._card_check_interval, str(cfg.card_check_interval))

        self._exclude_ids.delete("1.0", "end")
        if cfg.exclude_ids:
            self._exclude_ids.insert("1.0", "\n".join(str(i) for i in cfg.exclude_ids))

    def _save(self) -> None:
        exclude_raw = self._exclude_ids.get("1.0", "end").strip()
        exclude = []
        for line in exclude_raw.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                try:
                    exclude.append(int(line))
                except ValueError:
                    pass

        data: dict = {
            "steam_api_key": self._steam_api_key.get().strip(),
            "steam_id": self._steam_id.get().strip(),
            "sam_game_exe_path": self._sam_exe.get().strip(),
            "steam_path": self._steam_path.get().strip(),
            "launch_delay": self._float(self._launch_delay, 3.0),
            "load_timeout": self._float(self._load_timeout, 10.0),
            "post_commit_delay": self._float(self._post_commit_delay, 0.2),
            "between_games_delay": self._float(self._between_games_delay, 0.1),
            "max_consecutive_errors": self._int(self._max_consecutive_errors, 100),
            "max_concurrent_games": self._int(self._max_concurrent_games, 1),
            "card_check_interval": self._int(self._card_check_interval, 30),
        }

        if exclude:
            data["exclude_ids"] = exclude

        # Убираем пустые строки
        data = {k: v for k, v in data.items() if v != ""}

        _CONFIG_PATH.write_text(
            yaml.dump(data, allow_unicode=True, default_flow_style=False),
            encoding="utf-8",
        )
        self._lbl_saved.configure(text="Saved!")
        self.after(2000, lambda: self._lbl_saved.configure(text=""))

    # ------------------------------------------------------------------
    # Helpers

    @staticmethod
    def _set(widget: ctk.CTkEntry, value: str) -> None:
        widget.delete(0, "end")
        widget.insert(0, value)

    @staticmethod
    def _float(entry: ctk.CTkEntry, default: float) -> float:
        try:
            return float(entry.get())
        except ValueError:
            return default

    @staticmethod
    def _int(entry: ctk.CTkEntry, default: int) -> int:
        try:
            return int(entry.get())
        except ValueError:
            return default
