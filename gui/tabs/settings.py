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
    """Вкладка настроек: редактирование полей config.yaml через GUI."""

    def __init__(self, master: ctk.CTkTabview, **kwargs) -> None:
        super().__init__(master, **kwargs)
        self.grid_columnconfigure(1, weight=1)
        self._build_ui()
        self._load()

    # ------------------------------------------------------------------
    # UI

    def _build_ui(self) -> None:
        """Строит форму настроек: секции Required, Paths, Timeouts, Behaviour, Card Farming, Playtime."""
        row = 0

        # ── Banner (first-run) ─────────────────────────────────────────
        self._banner = ctk.CTkLabel(
            self,
            text="⚠ Заполните обязательные поля и нажмите Save перед запуском.",
            text_color="#f0a500",
            anchor="w",
        )
        self._banner.grid(row=row, column=0, columnspan=3, padx=8, pady=(8, 0), sticky="w")
        self._banner.grid_remove()
        row += 1

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
        self._game_ids_file, row = self._path_field("game_ids_file", row, kind="txt")

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

        # ── Playtime ──────────────────────────────────────────────────
        row = self._section("Playtime", row)

        self._playtime_idle_duration = self._field("playtime_idle_duration (seconds)", row)
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

    def is_configured(self) -> bool:
        """Возвращает True если обязательные поля (steam_api_key, steam_id) заполнены."""
        return bool(
            self._steam_api_key.get().strip()
            and self._steam_id.get().strip()
        )

    def show_banner(self) -> None:
        """Показывает предупреждающий баннер о незаполненных обязательных полях."""
        self._banner.grid()

    def hide_banner(self) -> None:
        """Скрывает баннер."""
        self._banner.grid_remove()

    # ------------------------------------------------------------------
    # Browse

    def _browse(self, entry: ctk.CTkEntry, kind: str) -> None:
        """Открывает диалог выбора файла или директории и вставляет путь в entry."""
        if kind == "file":
            path = filedialog.askopenfilename(
                filetypes=[("Executable", "*.exe"), ("All", "*.*")]
            )
        elif kind == "txt":
            path = filedialog.askopenfilename(
                filetypes=[("Text files", "*.txt"), ("All", "*.*")]
            )
        else:
            path = filedialog.askdirectory()
        if path:
            entry.delete(0, "end")
            entry.insert(0, path)

    # ------------------------------------------------------------------
    # Load / Save

    def _load(self) -> None:
        """Загружает значения из config.yaml и заполняет поля формы."""
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
        self._set(self._game_ids_file, cfg.game_ids_file or "")
        self._set(self._playtime_idle_duration, str(cfg.playtime_idle_duration))

        self._exclude_ids.delete("1.0", "end")
        if cfg.exclude_ids:
            self._exclude_ids.insert("1.0", "\n".join(str(i) for i in cfg.exclude_ids))

    # ------------------------------------------------------------------
    # Validation

    def _validate(self) -> list[str]:
        """Проверяет поля формы. Возвращает список сообщений об ошибках."""
        errors: list[str] = []

        if not self._steam_api_key.get().strip():
            errors.append("steam_api_key: обязателен")
        if not self._steam_id.get().strip():
            errors.append("steam_id: обязателен")

        # (entry, name, type, min_value)
        numeric_fields: list[tuple[ctk.CTkEntry, str, str, float]] = [
            (self._launch_delay,          "launch_delay",          "float", 0.0),
            (self._load_timeout,          "load_timeout",          "float", 0.1),
            (self._post_commit_delay,     "post_commit_delay",     "float", 0.0),
            (self._between_games_delay,   "between_games_delay",   "float", 0.0),
            (self._max_consecutive_errors,"max_consecutive_errors","int",   1.0),
            (self._max_concurrent_games,  "max_concurrent_games",  "int",   1.0),
            (self._card_check_interval,   "card_check_interval",   "int",   1.0),
            (self._playtime_idle_duration,"playtime_idle_duration","int",   1.0),
        ]
        for entry, name, kind, min_val in numeric_fields:
            raw = entry.get().strip()
            try:
                val = float(raw) if kind == "float" else int(raw)
                if val < min_val:
                    errors.append(f"{name}: должно быть ≥ {min_val:g}")
            except ValueError:
                errors.append(f"{name}: ожидается число, получено {raw!r}")

        return errors

    def _path_warnings(self) -> list[str]:
        """Возвращает предупреждения о несуществующих путях (не блокируют сохранение)."""
        warnings: list[str] = []
        checks = [
            (self._sam_exe,      "sam_game_exe_path", False),
            (self._steam_path,   "steam_path",        True),
            (self._game_ids_file,"game_ids_file",     False),
        ]
        for entry, name, is_dir in checks:
            raw = entry.get().strip()
            if not raw:
                continue
            p = Path(raw)
            if is_dir and not p.is_dir():
                warnings.append(f"{name}: папка не найдена")
            elif not is_dir and not p.exists():
                warnings.append(f"{name}: файл не найден")
        return warnings

    def _save(self) -> None:
        """Сохраняет текущие значения формы в config.yaml."""
        errors = self._validate()
        if errors:
            self._lbl_saved.configure(
                text="Ошибки:\n" + "\n".join(errors), text_color="#e05555",
            )
            return

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
            "launch_delay": float(self._launch_delay.get()),
            "load_timeout": float(self._load_timeout.get()),
            "post_commit_delay": float(self._post_commit_delay.get()),
            "between_games_delay": float(self._between_games_delay.get()),
            "max_consecutive_errors": int(self._max_consecutive_errors.get()),
            "max_concurrent_games": int(self._max_concurrent_games.get()),
            "card_check_interval": int(self._card_check_interval.get()),
            "game_ids_file": self._game_ids_file.get().strip(),
            "playtime_idle_duration": int(self._playtime_idle_duration.get()),
        }

        if exclude:
            data["exclude_ids"] = exclude

        # Убираем пустые строки
        data = {k: v for k, v in data.items() if v != ""}

        _CONFIG_PATH.write_text(
            yaml.dump(data, allow_unicode=True, default_flow_style=False),
            encoding="utf-8",
        )
        if self.is_configured():
            self.hide_banner()

        warnings = self._path_warnings()
        if warnings:
            msg = "Сохранено (предупреждения):\n" + "\n".join(warnings)
            self._lbl_saved.configure(text=msg, text_color="#f0a500")
        else:
            self._lbl_saved.configure(text="Saved!", text_color="green")
        self.after(4000, lambda: self._lbl_saved.configure(text=""))

    # ------------------------------------------------------------------
    # Helpers

    @staticmethod
    def _set(widget: ctk.CTkEntry, value: str) -> None:
        widget.delete(0, "end")
        widget.insert(0, value)

