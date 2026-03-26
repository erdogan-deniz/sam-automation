"""Главное окно SAM Automation GUI."""

from __future__ import annotations

import customtkinter as ctk

from gui.hotkey import GlobalHotkey, VK_ESCAPE
from gui.tabs.achievements import AchievementsTab
from gui.tabs.cards import CardsTab
from gui.tabs.playtime import PlaytimeTab
from gui.tabs.settings import SettingsTab


class SAMAutomationApp(ctk.CTk):
    """Главное окно SAM Automation с вкладками Achievements, Cards, Settings."""

    def __init__(self) -> None:
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        super().__init__()

        self.title("SAM Automation")
        self.geometry("720x620")
        self.minsize(600, 500)

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        tabs = ctk.CTkTabview(self)
        tabs.grid(row=0, column=0, padx=12, pady=12, sticky="nsew")

        tabs.add("Achievements")
        tabs.add("Cards")
        tabs.add("Playtime")
        tabs.add("Settings")

        settings_tab = tabs.tab("Settings")
        settings_tab.grid_columnconfigure(0, weight=1)
        settings_tab.grid_rowconfigure(0, weight=1)
        self._settings = SettingsTab(settings_tab)
        self._settings.grid(row=0, column=0, sticky="nsew")

        def check_config() -> bool:
            if self._settings.is_configured():
                return True
            self._settings.show_banner()
            tabs.set("Settings")
            return False

        ach_tab = tabs.tab("Achievements")
        ach_tab.grid_columnconfigure(0, weight=1)
        ach_tab.grid_rowconfigure(0, weight=1)
        self._ach = AchievementsTab(ach_tab, check_config=check_config)
        self._ach.grid(row=0, column=0, sticky="nsew")

        cards_tab = tabs.tab("Cards")
        cards_tab.grid_columnconfigure(0, weight=1)
        cards_tab.grid_rowconfigure(0, weight=1)
        self._cards = CardsTab(cards_tab, check_config=check_config)
        self._cards.grid(row=0, column=0, sticky="nsew")

        playtime_tab = tabs.tab("Playtime")
        playtime_tab.grid_columnconfigure(0, weight=1)
        playtime_tab.grid_rowconfigure(0, weight=1)
        self._playtime = PlaytimeTab(playtime_tab, check_config=check_config)
        self._playtime.grid(row=0, column=0, sticky="nsew")

        self._hotkey = GlobalHotkey(VK_ESCAPE, self._stop_all)
        self.title("SAM Automation  [Esc — остановить]")
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        if not self._settings.is_configured():
            self._settings.show_banner()
            tabs.set("Settings")

    def _stop_all(self) -> None:
        """Останавливает все активные скрипты (глобальный хоткей F10)."""
        self._ach.stop()
        self._cards.stop()
        self._playtime.stop()

    def _on_close(self) -> None:
        """Отменяет хоткей и закрывает окно."""
        self._hotkey.unregister()
        self.destroy()
