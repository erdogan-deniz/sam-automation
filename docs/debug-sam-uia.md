# Отладка UIA-дерева окна SAM.Game

Самый хрупкий слой проекта — чтение окна SAM.Game.exe через pywinauto UIA
(`app/sam/sam_status.py`, `manager_window.py`). Если SAM обновит UI, детект
достижений сломается, и нужно заново увидеть **реальную** структуру контролов
окна: где список достижений, что в статус-баре, какие `automation_id`.

Это memo заменяет прежний одноразовый скрипт `scripts/diag/dump_sam_window.py`
(удалён в v1.10.x как не-рабочий-в-цикле). Полная исходная версия — в истории
git (`git log --all -- scripts/diag/dump_sam_window.py`).

## Ключевая техника: обход дерева ТОЛЬКО через `.children()`

Ловушка (см. `CLAUDE.md`): окно из `app.windows()[0]` — это `UIAWrapper`, у него
**нет** `child_window()`/`wait()` (они только у `app.window(...)`). Вызов
`child_window()` на `UIAWrapper` → `AttributeError`, который project-код глотает
→ молчаливый вечный `None`. Поэтому дерево обходится рекурсивно через
`children()`:

```python
def walk(ctrl, depth, lines, counts):
    """Рекурсивно сериализует UIA-дерево: тип/класс/id/текст/состояние."""
    try:
        ctype = getattr(ctrl.element_info, "control_type", "") or ""
        counts[ctype] = counts.get(ctype, 0) + 1
        try:
            aid = ctrl.automation_id()
        except Exception:
            aid = ""
        try:
            cls = ctrl.friendly_class_name()
        except Exception:
            cls = ""
        try:
            txt = ctrl.window_text()
        except Exception:
            txt = ""
        state = ""
        for attr in ("is_checked", "is_selected"):
            try:
                fn = getattr(ctrl, attr, None)
                if callable(fn):
                    state += f" {attr}={fn()}"
            except Exception:
                pass
        lines.append(f"{'  ' * depth}[{ctype}] cls={cls!r} id={aid!r} text={txt!r}{state}")
    except Exception as e:
        lines.append(f"{'  ' * depth}<ошибка чтения контрола: {e}>")
        return
    try:
        for child in ctrl.children():
            walk(child, depth + 1, lines, counts)
    except Exception:
        pass
```

## Как снять дамп ad-hoc

Запускать **отдельно** от farm (конфликт за SAM). Steam должен быть запущен.

```python
import time
from app.config import load_config
from app.sam import ensure_sam, launch_picker, close_game, kill_process

cfg = load_config()
cfg.sam_game_exe_path = ensure_sam(cfg.sam_game_exe_path)
proc, session = launch_picker(cfg.sam_game_exe_path, launch_delay=cfg.launch_delay)
game_app = session.add_and_open_game(493180, timeout=cfg.load_timeout)  # свой appid
time.sleep(15)  # дать достижениям прогрузиться

lines, counts = [], {}
walk(game_app.windows()[0], 0, lines, counts)
print(f"Типы контролов: {counts}")
print("\n".join(lines))

close_game(game_app)
kill_process(proc)
```

Ожидаемая иерархия (её читает `_read_achievement_count` в `sam_status.py`):
`Manager → _MainTabControl → _AchievementsTabPage → _AchievementListView`, где
число `ListItem` в `_AchievementListView` = число достижений (0 = нет / пусто).
Статус-бар — только для быстрых негативов (`"error"` / `"Retrieved 0"`).
