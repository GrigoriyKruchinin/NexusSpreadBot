"""Message catalog (``en`` / ``ru``): every user-facing string of alerts, system events and digest.

Values are Telegram HTML fragments with ``str.format`` placeholders. Dynamic data is escaped by
the caller before it is substituted, never inside the catalog.
"""

from __future__ import annotations

from typing import Final, Literal

Language = Literal["en", "ru"]
DEFAULT_LANGUAGE: Final[Language] = "en"

EN: Final[dict[str, str]] = {
    "title_new": "🟢 <b>{coin}</b>/{quote}   <b>{net_pct}</b> net",
    "title_update": "🔄 <b>{coin}</b>/{quote}   <b>{net_pct}</b> net",
    "title_closed": "⚪ <b>Closed</b> · <b>{coin}</b>/{quote}",
    "conditional_one": "⚠️ conditional venue ({venues})",
    "conditional_many": "⚠️ conditional venues ({venues})",
    "buy": "Buy ",
    "sell": "Sell",
    "net": "Net after fees/slippage: <b>{net_pct}</b> (≈ {net_usd} on {notional})",
    "net_closed": "Last net: <b>{net_pct}</b>",
    "fees_estimated": "ℹ️ <i>Taker fee is an estimate</i>",
    "volume": "Volume: up to <b>{quote}</b> (≈ {base} {coin}) by orderbooks",
    "volume_scanned": "Volume: <b>{quote}</b> (≈ {base} {coin}) priced",
    "transfer_ok": "Transfer: <b>{network}</b> · fee {fee_base} {coin}{fee_usd}{time}",
    "fee_usd": " (≈ {usd})",
    "time": " · ≈ {minutes} (approx)",
    "time_unknown": " · time unknown",
    "transfer_unverified": "Transfer: ⚠️ <b>route not verified</b>{note}",
    "transfer_unavailable": "Transfer: ❌ <b>not available</b>{note}",
    "flags": "Withdraw {buy}: {w}   Deposit {sell}: {d}",
    "flag_open": "✅ open",
    "flag_closed": "❌ closed",
    "flag_unknown": "❓ unknown",
    "hint_closed": "❌ <i>Withdraw or deposit is closed: the transfer is not possible now</i>",
    "hint_unverified": "⚠️ <i>Not verified: check withdraw/deposit status manually</i>",
    "lifetime_new": "Lifetime: just opened",
    "lifetime": "Lifetime: {duration}",
    "lifetime_peak": "Lifetime: {duration}, peak {peak}",
    "closed_summary": "Lived {duration}, peak {peak}, last {last}",
    "closed_summary_nopeak": "Lived {duration}",
    "episode": "#{episode}",
    "suppressed": "⚠️ {n} more spreads suppressed (limit: {limit} new alerts per hour)",
    "d_sec": "{s} s",
    "d_min": "{m} m {s:02d} s",
    "d_hour": "{h} h {m:02d} m",
    "min": "{n} min",
    "just_opened": "just opened",
    # --- system events (scanner / exchanges / quarantine / watchdog) ---
    "sys_started": "🚀 <b>Nexus Spread Scanner started</b>",
    "sys_exchange": "{icon} <b>{name}</b> — markets: {markets}",
    "sys_exchange_transfers": " · transfers {pct}%",
    "sys_common": "🔗 Common pairs: <b>{n}</b>",
    "sys_threshold": "🎯 Threshold: net profit <b>≥ {pct}%</b> and <b>≥ ${usd}</b>",
    "sys_notional": "📦 Reference volume: <b>${usd}</b>",
    "sys_key_legend": "<blockquote>🔑 read-only key · 🌐 public data only</blockquote>",
    "sys_fallback": (
        "⚠️ Key NOT used (failed the read-only check), the venue runs in public mode: {venues}"
    ),
    "sys_unbound": "ℹ️ API key IP binding is not confirmed (recommended): {venues}",
    "sys_stopped": "🛑 <b>Nexus Spread Scanner stopped</b>\n<blockquote>{reason}</blockquote>",
    "stop_shutdown": "the scanner was stopped or is restarting (docker stop / make down)",
    "sys_down": (
        "⚠️ <b>{exchange} is unavailable</b>\n{sep}\n"
        "Consecutive errors: <b>{n}</b>\n<blockquote>{error}</blockquote>"
    ),
    "sys_recovered": "✅ <b>{exchange} is available again</b>\nDowntime: <b>{downtime}</b>",
    "sys_closed_title": "🏁 <b>Opportunity closed</b> · <code>{symbol}</code>",
    "sys_closed_duration": "⏱ Duration: <b>{duration}</b> · checks: {n}",
    "sys_closed_peak": "💰 Peak net profit: <b>{usd} ({pct})</b>",
    "sys_closed_latency": "⚡ Survived the execution delay: <b>{value}</b>",
    "sys_yes": "✅ yes",
    "sys_no": "❌ no",
    "sys_na": "n/a",
    "sys_closed_realerts": "🔁 Re-alerts: {n}",
    "sys_closed_reason": "<blockquote>Close reason: {reason}</blockquote>",
    "close_gap": "the spread disappeared",
    "close_quarantined": "the route was quarantined",
    "close_restart": "the scanner restarted",
    "sys_q_title": "🚫 <b>Routes quarantined: {n}</b> for <b>{hours} h</b>",
    "sys_q_note": (
        "<i>No alerts or orderbook checks for them; the quarantine ends earlier "
        "if the transfer route gets verified.</i>"
    ),
    "sys_more": "… and {n} more",
    "q_unverified_persistent": "the spread persists but the transfer route is not verified",
    "q_transfer_unavailable": "deposit or withdrawal of the coin is disabled",
    "sys_wd_alert": "🚨 <b>{title}: needs a check</b>\n<blockquote>{text}</blockquote>",
    "sys_wd_recovered": "✅ <b>{title}: problem resolved</b>\nLasted about <b>{duration}</b>",
    "wd_title_scanner": "Scanner",
    "wd_title_backup": "Backup",
    "wd_scanner_stale": (
        "the scanner has not written data for {minutes} min: check the scanner container"
    ),
    "wd_scanner_no_data": "the database has no scanner activity records",
    "wd_backup_missing": "the backup status file was not found",
    "wd_backup_unreadable": "the backup status file is unreadable",
    "wd_backup_failed": "the last backup failed ({minutes} min ago)",
    "wd_backup_not_copied": "the dump copy was not saved outside the container (disk not mounted?)",
    "wd_check_error": "the check cannot run (database or status file unavailable)",
    "wd_backup_stale": "the last backup was {minutes} min ago",
    "wd_unknown": "unknown reason: {minutes}",
    # --- daily digest ---
    "dg_title": "📊 <b>Daily digest</b>",
    "dg_no_conditional": "Conditional venues: none",
    "dg_episodes_all": "Episodes:   all {total}",
    "dg_conditional": "⚠️ Conditional venues (data is collected, no trading yet): {names}",
    "dg_episodes_split": "Episodes:   all {total} | excl. conditional (filter) {excl}",
    "dg_na": "n/a",
    "dg_ep_title": "🔀 <b>Opportunity episodes: {n}</b>",
    "dg_ep_split": "✅ verified {v} · ⚠️ unverified {u} · 🚫 quarantined {q}",
    "dg_ep_latency": "⚡ Survived the delay: <b>{n}</b> of {checked} checked",
    "dg_ep_duration": "⏱ Duration: median {median} · max {max}",
    "dg_top": "<b>Top routes by peak net profit</b>",
    "dg_q_title": "🚫 <b>Quarantine</b>: new {new} · active {active}",
    "dg_ex_none": "🌐 <b>Exchanges</b>: no data",
    "dg_ex_title": "🌐 <b>Exchanges</b>",
    "dg_ex_col_name": "Exchange",
    "dg_ex_col_uptime": "Uptime",
    "dg_ex_col_transfers": "Transfers",
    "dg_unverified": "<blockquote>Unverified opportunities (stored, no alerts): {n}</blockquote>",
    "pinned": (
        "ℹ️ Automated spread alerts from a self-hosted Nexus instance. Information only, "
        "<b>not financial advice</b>; numbers are estimates and may be outdated. Not affiliated "
        "with any exchange. Use at your own risk. This channel is private; please do not forward "
        "or republish the alerts (exchange data terms)."
    ),
}

RU: Final[dict[str, str]] = {
    "title_new": "🟢 <b>{coin}</b>/{quote}   <b>{net_pct}</b> чистыми",
    "title_update": "🔄 <b>{coin}</b>/{quote}   <b>{net_pct}</b> чистыми",
    "title_closed": "⚪ <b>Закрыта</b> · <b>{coin}</b>/{quote}",
    "conditional_one": "⚠️ условная биржа ({venues})",
    "conditional_many": "⚠️ условные биржи ({venues})",
    "buy": "Покупка ",
    "sell": "Продажа",
    "net": "Чистый спред после комиссий и проскальзывания: <b>{net_pct}</b> "
    "(≈ {net_usd} на {notional})",
    "net_closed": "Последний чистый спред: <b>{net_pct}</b>",
    "fees_estimated": "ℹ️ <i>Комиссия тейкера оценочная</i>",
    "volume": "Объём: до <b>{quote}</b> (≈ {base} {coin}) по стаканам",
    "volume_scanned": "Объём: <b>{quote}</b> (≈ {base} {coin}) расчётный",
    "transfer_ok": "Перевод: <b>{network}</b> · комиссия {fee_base} {coin}{fee_usd}{time}",
    "fee_usd": " (≈ {usd})",
    "time": " · ≈ {minutes} (примерно)",
    "time_unknown": " · время неизвестно",
    "transfer_unverified": "Перевод: ⚠️ <b>маршрут не подтверждён</b>{note}",
    "transfer_unavailable": "Перевод: ❌ <b>недоступен</b>{note}",
    "flags": "Вывод {buy}: {w}   Ввод {sell}: {d}",
    "flag_open": "✅ открыт",
    "flag_closed": "❌ закрыт",
    "flag_unknown": "❓ неизвестно",
    "hint_closed": "❌ <i>Вывод или ввод закрыт: перевод сейчас невозможен</i>",
    "hint_unverified": "⚠️ <i>Не подтверждено: проверьте статус ввода/вывода вручную</i>",
    "lifetime_new": "Время жизни: только что открылась",
    "lifetime": "Время жизни: {duration}",
    "lifetime_peak": "Время жизни: {duration}, пик {peak}",
    "closed_summary": "Прожила {duration}, пик {peak}, последний {last}",
    "closed_summary_nopeak": "Прожила {duration}",
    "episode": "#{episode}",
    "suppressed": "⚠️ Подавлено ещё спредов: {n} (лимит: {limit} новых сообщений в час)",
    "d_sec": "{s} с",
    "d_min": "{m} мин {s:02d} с",
    "d_hour": "{h} ч {m:02d} мин",
    "min": "{n} мин",
    "just_opened": "только что",
    # --- системные события (сканер / биржи / карантин / watchdog) ---
    "sys_started": "🚀 <b>Nexus Spread Scanner запущен</b>",
    "sys_exchange": "{icon} <b>{name}</b> — рынков: {markets}",
    "sys_exchange_transfers": " · переводы {pct}%",
    "sys_common": "🔗 Общих пар: <b>{n}</b>",
    "sys_threshold": "🎯 Порог: чистая прибыль <b>≥ {pct}%</b> и <b>≥ ${usd}</b>",
    "sys_notional": "📦 Расчётный объём: <b>${usd}</b>",
    "sys_key_legend": (
        "<blockquote>🔑 ключ только для чтения · 🌐 только публичные данные</blockquote>"
    ),
    "sys_fallback": (
        "⚠️ Ключ НЕ использован (не прошёл проверку «только чтение»), "
        "биржа работает в публичном режиме: {venues}"
    ),
    "sys_unbound": "ℹ️ Привязка ключей к IP не подтверждена (рекомендуется): {venues}",
    "sys_stopped": "🛑 <b>Nexus Spread Scanner остановлен</b>\n<blockquote>{reason}</blockquote>",
    "stop_shutdown": "сканер остановлен или перезапускается (docker stop / make down)",
    "sys_down": (
        "⚠️ <b>{exchange} недоступна</b>\n{sep}\n"
        "Ошибок подряд: <b>{n}</b>\n<blockquote>{error}</blockquote>"
    ),
    "sys_recovered": "✅ <b>{exchange} снова доступна</b>\nПростой: <b>{downtime}</b>",
    "sys_closed_title": "🏁 <b>Возможность закрылась</b> · <code>{symbol}</code>",
    "sys_closed_duration": "⏱ Длительность: <b>{duration}</b> · проверок: {n}",
    "sys_closed_peak": "💰 Максимум чистой прибыли: <b>{usd} ({pct})</b>",
    "sys_closed_latency": "⚡ Пережила задержку исполнения: <b>{value}</b>",
    "sys_yes": "✅ да",
    "sys_no": "❌ нет",
    "sys_na": "н/д",
    "sys_closed_realerts": "🔁 Повторных алертов: {n}",
    "sys_closed_reason": "<blockquote>Причина закрытия: {reason}</blockquote>",
    "close_gap": "спред исчез",
    "close_quarantined": "связка отправлена в карантин",
    "close_restart": "сканер перезапускался",
    "sys_q_title": "🚫 <b>В карантин отправлено связок: {n}</b> на <b>{hours} ч</b>",
    "sys_q_note": (
        "<i>Алертов и проверки стаканов по ним не будет; карантин снимется раньше, "
        "если маршрут перевода подтвердится.</i>"
    ),
    "sys_more": "… и ещё {n}",
    "q_unverified_persistent": "спред держится, а маршрут перевода не подтверждён",
    "q_transfer_unavailable": "ввод или вывод монеты отключён",
    "sys_wd_alert": "🚨 <b>{title}: нужна проверка</b>\n<blockquote>{text}</blockquote>",
    "sys_wd_recovered": "✅ <b>{title}: проблема устранена</b>\nДлилась около <b>{duration}</b>",
    "wd_title_scanner": "Сканер",
    "wd_title_backup": "Резервная копия",
    "wd_scanner_stale": (
        "сканер не записывает данные уже {minutes} мин: проверьте контейнер scanner"
    ),
    "wd_scanner_no_data": "в базе нет записей работы сканера",
    "wd_backup_missing": "файл статуса резервного копирования не найден",
    "wd_backup_unreadable": "файл статуса резервного копирования нечитаем",
    "wd_backup_failed": "последняя резервная копия завершилась ошибкой ({minutes} мин назад)",
    "wd_backup_not_copied": "копия дампа не сохранена вне контейнера (диск не подключён?)",
    "wd_check_error": "проверка не выполняется (база данных или файл статуса недоступны)",
    "wd_backup_stale": "последняя резервная копия была {minutes} мин назад",
    "wd_unknown": "неизвестная причина: {minutes}",
    # --- ежедневный дайджест ---
    "dg_title": "📊 <b>Ежедневный дайджест</b>",
    "dg_no_conditional": "Условные биржи: нет",
    "dg_episodes_all": "Эпизоды:   все {total}",
    "dg_conditional": "⚠️ Условные биржи (данные собираются, торговать пока нельзя): {names}",
    "dg_episodes_split": "Эпизоды:   все {total} | без условных (фильтр) {excl}",
    "dg_na": "н/д",
    "dg_ep_title": "🔀 <b>Эпизодов возможностей: {n}</b>",
    "dg_ep_split": "✅ подтверждённых {v} · ⚠️ неподтверждённых {u} · 🚫 в карантине {q}",
    "dg_ep_latency": "⚡ Пережили задержку: <b>{n}</b> из {checked} проверенных",
    "dg_ep_duration": "⏱ Длительность: медиана {median} · максимум {max}",
    "dg_top": "<b>Топ связок по пиковой чистой прибыли</b>",
    "dg_q_title": "🚫 <b>Карантин</b>: новых {new} · активных {active}",
    "dg_ex_none": "🌐 <b>Биржи</b>: нет данных",
    "dg_ex_title": "🌐 <b>Биржи</b>",
    "dg_ex_col_name": "Биржа",
    "dg_ex_col_uptime": "Аптайм",
    "dg_ex_col_transfers": "Переводы",
    "dg_unverified": (
        "<blockquote>Неподтверждённые возможности (записаны, без алертов): {n}</blockquote>"
    ),
    "pinned": (
        "ℹ️ Автоматические уведомления о спредах от личной копии Nexus. Только информация, "
        "<b>не финансовый совет</b>; цифры — оценки и могут устареть. Не связано ни с одной "
        "биржей. Используйте на свой риск. Канал закрытый; пожалуйста, не пересылайте и не "
        "публикуйте эти сообщения (условия бирж на рыночные данные)."
    ),
}

CATALOGS: Final[dict[str, dict[str, str]]] = {"en": EN, "ru": RU}


def catalog(language: str) -> dict[str, str]:
    """Catalog of ``language``; unknown codes fall back to the default language."""
    return CATALOGS.get(language, CATALOGS[DEFAULT_LANGUAGE])


def pinned_text(language: str = DEFAULT_LANGUAGE) -> str:
    """Disclaimer for the channel's pinned message (legal text, once per channel, not per alert)."""
    return catalog(language)["pinned"]
