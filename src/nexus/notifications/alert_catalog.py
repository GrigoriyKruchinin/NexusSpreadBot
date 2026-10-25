"""Message catalog of the opportunity alerts (``en`` / ``ru``): every user-facing string lives here.

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
