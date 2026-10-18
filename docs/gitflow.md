# Git-flow процесс

## Ветки

- **main** — лицевая / production. Всегда равна **последнему выпущенному
  релизу** (помечен тегом `vX.Y.Z`). README и docs здесь — актуальные для
  выпущенной версии. Напрямую сюда **не коммитят** — только через PR (см.
  «Примечание» ниже: кого GitHub останавливает, а кого нет).
- **develop** — интеграционная. Сюда вливаются завершённые фичи; бежит
  впереди `main` до следующего релиза.
- **feature/&lt;slug&gt;** — отдельная фича или фикс. Ответвляется от `develop`,
  вливается обратно в `develop` через `--no-ff`.
- **release/X.Y.Z** — подготовка релиза. От `develop` → в `main` (+тег) и
  обратно в `develop`.
- **hotfix/X.Y.Z** — срочный фикс прода. От `main` → в `main` (+тег) и в
  `develop`.

## Потоки

### Фича

```bash
git checkout -b feature/foo develop
#  ... работа, коммиты ...
git checkout develop && git merge --no-ff feature/foo
git branch -d feature/foo
```

### Релиз (когда в `develop` накопились фичи)

```bash
git checkout -b release/1.0.0 develop
#  ... финальные правки: версия, changelog, доки ...
#  PR release/1.0.0 -> main, смёрджить на GitHub
git tag v1.0.0                                    # на main
git checkout develop && git merge --no-ff origin/main   # вернуть релиз в develop
git branch -d release/1.0.0                       # backmerge сделан — ветка больше не нужна
```

### Hotfix (срочный баг в проде)

```bash
git checkout -b hotfix/1.0.1 main
#  ... фикс ...
#  PR hotfix/1.0.1 -> main, смёрджить + тег v1.0.1
git checkout develop && git merge --no-ff origin/main   # вернуть фикс в develop
git branch -d hotfix/1.0.1
```

## Версии (semver)

`MAJOR.MINOR.PATCH` — major: несовместимые изменения; minor: новые фичи;
patch: исправления.

## Примечание

Релиз и hotfix вливаются в `main` через Pull Request на GitHub, затем
помечаются тегом.

Защита ветки `main` на GitHub: обязательный PR (одобрения не требуются) и
обязательная проверка CI `check` со strict — ветка должна быть свежей
относительно `main`. Force-push запрещён. **На администраторов репозитория
защита не распространяется** (`enforce_admins: false`, решение владельца
19.10.2026): с аккаунта владельца прямой push в `main` технически пройдёт.
Его сдерживают правило этого документа и harness агента, который прямой
push в `main` блокирует. Не полагаться на то, что GitHub остановит ошибку
владельца.
