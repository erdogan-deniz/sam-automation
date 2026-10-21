"""Кастомные исключения для SAM automation."""


class SAMError(Exception):
    """Базовое исключение для всех ошибок SAM automation."""


class SAMLaunchError(SAMError):
    """Ошибка запуска SAM.Game.exe (файл не найден, не удалось запустить)."""


class SAMConnectionError(SAMError):
    """Не удалось подключиться к окну SAM через pywinauto."""


class SAMGameError(SAMError):
    """Ошибка от SAM при работе с конкретной игрой (игра не куплена, нет достижений)."""

    def __init__(self, game_id: int, message: str) -> None:
        self.game_id = game_id
        self.message = message
        super().__init__(f"Game {game_id}: {message}")


class SAMGameNotOwned(SAMGameError):
    """SAM: «You don't own that game» — игры нет в библиотеке аккаунта.

    Не ошибка: истёкшая лицензия, бесплатные выходные, демо, семейный доступ.
    Игра идёт в not_owned.txt и больше не прогоняется.
    """


class SAMTooManyErrors(SAMError):
    """Превышен лимит последовательных ошибок — аварийная остановка."""


class SAMPickerBroken(SAMError):
    """SAM.Picker.exe не принимает ввод (висящий диалог, окно умерло).

    Поломка самого Picker, а не ошибка игры: farm перезапускает Picker и
    повторяет игру, не записывая её в error.txt.
    """
