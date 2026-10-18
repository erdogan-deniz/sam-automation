"""Настройка логирования: консоль + файл."""

import logging
import os
import sys
from datetime import datetime
from pathlib import Path

LOG_DIR = Path(__file__).parent.parent / "logs"

# Решение владельца 19.10.2026 (B-3): в папке каждого скрипта — 5 последних
# лог-файлов, более старые удаляются; файл, доросший до 20 МБ, продолжается в
# следующем (`<время>_part02.log`), и тот тоже входит в пятёрку.
LOG_KEEP_FILES = 5
LOG_MAX_BYTES = 20 * 1024 * 1024

SEPARATOR = "═" * 80


def _prune_logs(log_dir: Path, keep: int, current: Path) -> None:
    """Оставляет в log_dir `keep` самых новых *.log, текущий — всегда.

    Порядок — по имени: имена начинаются с `%Y-%m-%d_%H-%M-%S`, части одного
    запуска — `_partNN` с двузначным номером, поэтому имя = хронология.
    Не удалившийся файл (занят другим процессом) пропускается молча: чистка
    логов не повод ронять запуск.
    """
    files = sorted(p for p in log_dir.glob("*.log") if p != current)
    excess = len(files) + 1 - keep
    for old in files[: max(excess, 0)]:
        try:
            old.unlink()
        except OSError:
            pass


class _RollingFileHandler(logging.FileHandler):
    """Файловый лог с переходом на следующий файл по размеру.

    В отличие от logging.handlers.RotatingFileHandler, не переименовывает
    файлы (там app.log → app.log.1): каждая часть получает своё имя
    `<stem>_partNN.log`, а после каждого нового файла папка чистится до `keep`.
    """

    def __init__(
        self, log_dir: Path, stem: str, *, max_bytes: int, keep: int
    ) -> None:
        self._log_dir = log_dir
        self._stem = stem
        self._max_bytes = max_bytes
        self._keep = keep
        self._part = 1
        super().__init__(self._part_path(), encoding="utf-8")
        _prune_logs(log_dir, keep, Path(self.baseFilename))

    def _part_path(self) -> Path:
        suffix = "" if self._part == 1 else f"_part{self._part:02d}"
        return self._log_dir / f"{self._stem}{suffix}.log"

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if self.stream is None:  # как FileHandler.emit: переоткрыть
                self.stream = self._open()
            size = os.fstat(self.stream.fileno()).st_size
            incoming = len((self.format(record) + self.terminator).encode())
            if size and size + incoming > self._max_bytes:
                self._roll_over()
        except Exception:
            self.handleError(record)
            return
        super().emit(record)

    def _roll_over(self) -> None:
        if self.stream is not None:
            self.stream.close()
        self._part += 1
        path = self._part_path()
        self.baseFilename = os.fspath(path.resolve())
        self.stream = self._open()
        _prune_logs(self._log_dir, self._keep, path.resolve())


def centered(text: str, width: int = 70, char: str = "═") -> str:
    """Центрирует text между полосами из char до заданной ширины.

    Воспроизводит прежний inline-формат заголовков в скриптах:
    «═══ [1/10] ═══». При тексте шире width полосы исчезают (side ≤ 0).
    """
    side = (width - len(text) - 2) // 2
    bar = char * side  # при отрицательном side Python даёт "" — полос нет
    return f"{bar} {text} {bar}"


def ensure_utf8_stdout() -> None:
    """Переключает stdout на UTF-8 для не-Unicode терминалов (cp1251 и т.п.).

    Нужно для вывода ═, ✗ и кириллицы через print(); errors='replace' страхует.
    """
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def setup_logging(
    verbose: bool = False, name: str = "sam", category: str = ""
) -> logging.Logger:
    """Настраивает корневой логгер с выводом в консоль и файл.

    Файл создаётся в logs/<category>/TIMESTAMP.log (или logs/<name>/, если
    category пуст — name задаёт каталог, в имя файла он не входит).
    """
    log_dir = LOG_DIR / category if category else LOG_DIR / name
    log_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("sam_automation")
    if logger.handlers:
        return logger
    logger.setLevel(logging.DEBUG)

    # Формат
    fmt = logging.Formatter(
        "[%(asctime)s] %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )

    # Консоль — UTF-8 для не-Unicode терминалов (нужно для ═, ✗ и пр.).
    ensure_utf8_stdout()
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.DEBUG if verbose else logging.INFO)
    console.setFormatter(fmt)
    logger.addHandler(console)

    # Файл: 5 последних на скрипт, до 20 МБ каждый (см. LOG_KEEP_FILES).
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    file_handler = _RollingFileHandler(
        log_dir, timestamp, max_bytes=LOG_MAX_BYTES, keep=LOG_KEEP_FILES
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    return logger
