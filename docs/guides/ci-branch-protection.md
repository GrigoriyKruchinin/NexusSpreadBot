# CI и защита ветки main (GitHub)

Что это: после первого push GitHub сам запускает проверки (`.github/workflows/ci.yml`). Чтобы в `main`
нельзя было влить код с красными проверками, включи "branch protection" (правило защиты ветки).
Это действие делаешь ты сам в веб-интерфейсе (пункт U4); агенты настройки репозитория не меняют.

## Какие проверки есть
`lint`, `typecheck`, `unit` (покрытие не ниже 89 %), `integration` (временная база `nexus_test`
в контейнере GitHub), `secret-scan` (gitleaks по всей истории), `dependency-audit` (pip-audit),
`docker-build` (сборка образа, без публикации). Секреты репозитория не нужны.

## Как включить защиту
1. GitHub -> репозиторий -> Settings -> Branches -> Add branch protection rule (или Rulesets).
2. Branch name pattern: `main`.
3. Включи: **Require a pull request before merging**.
4. Включи: **Require status checks to pass before merging**, затем **Require branches to be up to date**.
5. В поиске проверок добавь все семь: `lint`, `typecheck`, `unit`, `integration`, `secret-scan`,
   `dependency-audit`, `docker-build`. (Они появятся в списке только после первого запуска CI.)
6. Включи: **Do not allow bypassing the above settings** и запрети force-push и удаление ветки
   (Allow force pushes / Allow deletions оставь выключенными).
7. Save changes.

## Дополнительно (рекомендуется)
- Settings -> Actions -> General -> Workflow permissions: **Read repository contents permissions**.
- Settings -> Actions -> General: Fork pull request workflows -> требовать одобрения для внешних.
- Settings -> Code security: включи Dependabot alerts и Secret scanning / Push protection.

## Если проверка красная
- `secret-scan`: в логе показан файл и правило, значение скрыто. Если это не настоящий ключ, а
  тестовая заглушка, скажи оркестратору: добавим узкое исключение в `.gitleaks.toml`.
  Если настоящий: немедленно отзови ключ на бирже/в Telegram, потом чистим историю (с твоего согласия).
- `dependency-audit`: найдена уязвимость в библиотеке; нужен патч-апдейт, скажи оркестратору.
- `integration`: падает, если имя базы не `nexus_test` (это защита от случайной записи в рабочую базу).
