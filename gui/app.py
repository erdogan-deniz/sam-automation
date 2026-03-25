"""Главное окно SAM Automation GUI."""

from __future__ import annotations

import customtkinter as ctk

from gui.tabs.achievements import AchievementsTab
from gui.tabs.cards import CardsTab
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
        tabs.add("Settings")

        ach_tab = tabs.tab("Achievements")
        ach_tab.grid_columnconfigure(0, weight=1)
        ach_tab.grid_rowconfigure(0, weight=1)
        AchievementsTab(ach_tab).grid(row=0, column=0, sticky="nsew")

        cards_tab = tabs.tab("Cards")
        cards_tab.grid_columnconfigure(0, weight=1)
        cards_tab.grid_rowconfigure(0, weight=1)
        CardsTab(cards_tab).grid(row=0, column=0, sticky="nsew")

        settings_tab = tabs.tab("Settings")
        settings_tab.grid_columnconfigure(0, weight=1)
        settings_tab.grid_rowconfigure(0, weight=1)
        self._settings = SettingsTab(settings_tab)
        self._settings.grid(row=0, column=0, sticky="nsew")

        if not self._settings.is_configured():
            self._settings.show_banner()
            tabs.set("Settings")
