"""Кастомные исключения для SAM automation."""


class SAMError(Exception):
    """Базовое исключение для всех ошибок SAM automation."""


class SAMLaunchError(SAMError):
    """Ошибка запуска SAM.Game.exe (файл не найден, не удалось запустить)."""


class SAMConnectionError(SAMError):
    """Не удалось подключиться к окну SAM через pywinauto."""


class SAMGameError(SAMError):
    """Ошибка от SAM при работе с конкретной игрой (игра не куплена, нет достижений)."""

    def __init__(self, game_id: int, message: str):
        self.game_id = game_id
        super().__init__(f"Game {game_id}: {message}")


class SAMTooManyErrors(SAMError):
    """Превышен лимит последовательных ошибок — аварийная остановка."""
