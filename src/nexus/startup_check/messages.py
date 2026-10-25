"""Bilingual (en/ru) texts of the startup check.

Every text is a template filled with SAFE parameters only (venue names, rule names, status
words, exception class names). Secrets, URLs and exchange responses never reach this module.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from nexus.startup_check.checks import Item

DOCS: Final = "docs/guides/quickstart.md"

#: code -> (en, ru). ``{docs}`` is always available.
MESSAGES: Final[dict[str, tuple[str, str]]] = {
    "tg_token_missing": (
        "TELEGRAM_BOT_TOKEN is empty. Create a bot with @BotFather (/newbot), paste the token into "
        ".env, see {docs}.",
        "TELEGRAM_BOT_TOKEN пуст. Создайте бота у @BotFather (/newbot), вставьте токен в .env, "
        "см. {docs}.",
    ),
    "tg_token_placeholder": (
        "TELEGRAM_BOT_TOKEN still holds the example value. Replace it with your own bot token from "
        "@BotFather, see {docs}.",
        "В TELEGRAM_BOT_TOKEN остался пример из шаблона. Подставьте токен вашего бота от "
        "@BotFather, см. {docs}.",
    ),
    "tg_token_format": (
        "TELEGRAM_BOT_TOKEN has a wrong format (expected '<digits>:<token>'). Copy it from "
        "@BotFather again without spaces or quotes, see {docs}.",
        "Неверный формат TELEGRAM_BOT_TOKEN (нужно '<цифры>:<токен>'). Скопируйте его у "
        "@BotFather заново, без пробелов и кавычек, см. {docs}.",
    ),
    "tg_token_rejected": (
        "Telegram rejected the bot token (401). It is wrong or revoked: get a fresh one from "
        "@BotFather (/token), see {docs}.",
        "Telegram отклонил токен бота (401): он неверный или отозван. Получите новый у @BotFather "
        "(/token), см. {docs}.",
    ),
    "tg_unreachable": (
        "Could not reach Telegram ({detail}), so the token and chat were NOT verified. Check the "
        "internet connection; if Telegram is blocked in your country use a VPN.",
        "Не удалось связаться с Telegram ({detail}), токен и чат НЕ проверены. Проверьте "
        "интернет; если Telegram заблокирован в вашей стране, включите VPN.",
    ),
    "tg_api_error": (
        "Telegram answered with an unexpected error (HTTP {detail}). Try again in a minute.",
        "Telegram вернул неожиданную ошибку (HTTP {detail}). Повторите через минуту.",
    ),
    "tg_bot_ok": (
        "Telegram bot token is valid (bot @{detail}).",
        "Токен Telegram-бота верный (бот @{detail}).",
    ),
    "tg_chat_missing": (
        "TELEGRAM_CHAT_ID is empty. Use your numeric id (ask @userinfobot) or -100... for a "
        "channel/group, see {docs}.",
        "TELEGRAM_CHAT_ID пуст. Укажите свой числовой id (спросите @userinfobot) или -100... для "
        "канала/группы, см. {docs}.",
    ),
    "tg_chat_format": (
        "TELEGRAM_CHAT_ID must be a number (e.g. 123456789 or -1001234567890) or @channel_name.",
        "TELEGRAM_CHAT_ID должен быть числом (например 123456789 или -1001234567890) или "
        "@имя_канала.",
    ),
    "tg_chat_not_found": (
        "Chat not found. Write /start to your bot first (private chat) or add the bot to the "
        "group/channel, then check TELEGRAM_CHAT_ID, see {docs}.",
        "Чат не найден. Напишите боту /start (личный чат) или добавьте бота в группу/канал, затем "
        "проверьте TELEGRAM_CHAT_ID, см. {docs}.",
    ),
    "tg_chat_username": (
        "Chat '@name' was not found. A channel by @name works only if it is PUBLIC; for a private "
        "channel use its numeric id (-100...), see {docs}.",
        "Чат '@имя' не найден. Канал по @имени работает только если он ПУБЛИЧНЫЙ; для приватного "
        "канала укажите числовой id (-100...), см. {docs}.",
    ),
    "tg_bot_kicked": (
        "The bot was removed from this chat or is blocked. Add it back (channels: as "
        "administrator), see {docs}.",
        "Бот удалён из этого чата или заблокирован. Добавьте его снова (в канал как "
        "администратора), см. {docs}.",
    ),
    "tg_not_admin": (
        "The bot is not an administrator of the channel. Channel settings -> Administrators -> "
        "add the bot with 'Post messages' and 'Edit messages of others', see {docs}.",
        "Бот не администратор канала. Настройки канала -> Администраторы -> добавьте бота с "
        "правами 'Публикация сообщений' и 'Редактирование чужих сообщений', см. {docs}.",
    ),
    "tg_cannot_post": (
        "The bot is an administrator but lacks rights: {detail}. Enable them in the channel's "
        "administrator settings, see {docs}.",
        "Бот администратор, но без прав: {detail}. Включите их в настройках администратора "
        "канала, см. {docs}.",
    ),
    "tg_cannot_send": (
        "The bot is restricted in this chat and cannot send messages. Lift the restriction or "
        "make the bot an administrator, see {docs}.",
        "Бот ограничен в этом чате и не может писать. Снимите ограничение или сделайте бота "
        "администратором, см. {docs}.",
    ),
    "tg_chat_ok": (
        "Telegram chat reachable ({detail}).",
        "Чат Telegram доступен ({detail}).",
    ),
    "tg_test_sent": (
        "Test message sent to the chat.",
        "Тестовое сообщение отправлено в чат.",
    ),
    "tg_test_failed": (
        "Test message was not delivered (HTTP {detail}). Check the bot's rights in the chat.",
        "Тестовое сообщение не доставлено (HTTP {detail}). Проверьте права бота в чате.",
    ),
    "tg_test_text": ("Nexus: setup check OK", "Nexus: проверка настройки пройдена"),
    "venue_public": (
        "{venue}: no key, PUBLIC mode (prices and order books work; transfer fees and "
        "deposit/withdrawal status are not read).",
        "{venue}: ключа нет, ПУБЛИЧНЫЙ режим (цены и стаканы работают; комиссии переводов и "
        "статусы ввода/вывода не читаются).",
    ),
    "venue_keyed": (
        "{venue}: key accepted, read-only, KEYED mode.",
        "{venue}: ключ принят, только чтение, режим С КЛЮЧОМ.",
    ),
    "venue_incomplete": (
        "{venue}: key settings incomplete ({detail}); running in PUBLIC mode. Fill the key and "
        "secret (and passphrase where required) together or clear them, see {docs}.",
        "{venue}: настройки ключа неполные ({detail}); работаем в ПУБЛИЧНОМ режиме. Заполните "
        "ключ и секрет (и passphrase, если нужен) вместе или очистите их, см. {docs}.",
    ),
    "venue_rejected": (
        "{venue}: key rejected or venue unreachable, running in PUBLIC mode. Check the key, secret "
        "(passphrase) and that it is not expired, see {docs}.",
        "{venue}: ключ отклонён или биржа недоступна, работаем в ПУБЛИЧНОМ режиме. Проверьте ключ, "
        "секрет (passphrase) и срок действия, см. {docs}.",
    ),
    "venue_withdraw": (
        "{venue}: the key can WITHDRAW or transfer funds ({detail}); refused, running in PUBLIC "
        "mode. Create a new READ-ONLY key (withdrawals and trading disabled) and delete the old "
        "one, see {docs}.",
        "{venue}: ключ может ВЫВОДИТЬ или переводить средства ({detail}); отклонён, работаем в "
        "ПУБЛИЧНОМ режиме. Создайте новый ключ ТОЛЬКО НА ЧТЕНИЕ (вывод и торговля выключены), "
        "старый удалите, см. {docs}.",
    ),
    "venue_policy": (
        "{venue}: the key does not meet the read-only policy ({detail}); refused, running in "
        "PUBLIC mode. Recreate it with read-only rights, see {docs}.",
        "{venue}: ключ не соответствует политике только-чтение ({detail}); отклонён, работаем в "
        "ПУБЛИЧНОМ режиме. Создайте его заново с правами только на чтение, см. {docs}.",
    ),
    "db_password": (
        "POSTGRES_PASSWORD is missing or shorter than 12 characters. Set it in .env "
        "(openssl rand -base64 32), see {docs}.",
        "POSTGRES_PASSWORD не задан или короче 12 символов. Задайте его в .env "
        "(openssl rand -base64 32), см. {docs}.",
    ),
    "db_unreachable": (
        "Database is not reachable ({detail}). Is the stack running (make up)? Does "
        "POSTGRES_PASSWORD match the one the database was created with?",
        "База данных недоступна ({detail}). Запущен ли стек (make up)? Совпадает ли "
        "POSTGRES_PASSWORD с тем, с которым создавалась база?",
    ),
    "db_not_migrated": (
        "Database has no schema yet. Run: make migrate (make up does it automatically).",
        "В базе ещё нет схемы. Выполните: make migrate (make up делает это автоматически).",
    ),
    "db_outdated": (
        "Database schema is behind the code (at {detail}). Run: make migrate.",
        "Схема БД отстаёт от кода (версия {detail}). Выполните: make migrate.",
    ),
    "db_ok": (
        "Database reachable, migrations at head ({detail}).",
        "База доступна, миграции применены полностью ({detail}).",
    ),
    "db_skipped": (
        "Database check skipped (--no-db).",
        "Проверка базы пропущена (--no-db).",
    ),
    "config_error": (
        "Settings are invalid ({detail}). Check config/nexus.toml and .env, see {docs}.",
        "Некорректные настройки ({detail}). Проверьте config/nexus.toml и .env, см. {docs}.",
    ),
    "summary_ok": (
        "RESULT: OK, you can start.",
        "ИТОГ: всё в порядке, можно запускать.",
    ),
    "summary_warn": (
        "RESULT: OK with warnings (see above).",
        "ИТОГ: можно запускать, но есть предупреждения (см. выше).",
    ),
    "summary_fail": (
        "RESULT: FIX THE ERRORS above, then run again.",
        "ИТОГ: исправьте ошибки выше и запустите снова.",
    ),
}

_MARK = {"ok": "[ OK ]", "warn": "[WARN]", "fail": "[FAIL]"}
_IDX = {"en": 0, "ru": 1}


def text(code: str, language: str, **params: str) -> str:
    """Localized text for ``code`` (unknown language falls back to English)."""
    template = MESSAGES[code][_IDX.get(language, 0)]
    return template.format(docs=DOCS, **{"detail": "", "venue": "", **params})


def render(items: list[Item], language: str) -> str:
    """Human-readable report: one line per item plus a summary line."""
    lines = [f"{_MARK[i.status]} {text(i.code, language, **i.params)}" for i in items]
    if any(i.status == "fail" for i in items):
        summary = "summary_fail"
    elif any(i.status == "warn" for i in items):
        summary = "summary_warn"
    else:
        summary = "summary_ok"
    lines.append(text(summary, language))
    return "\n".join(lines)
