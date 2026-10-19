# Stage 1 — локальный запуск сканера (read-only)

Этот гайд готовит всё необходимое для запуска **Nexus Spread Scanner V1** на ноутбуке:
сканер следит за стаканами 5 бирж, считает чистый спред с учётом комиссий, проскальзывания
и стоимости перевода, и шлёт алерты в Telegram. **Бот ничего не покупает, не продаёт и не
выводит** — в V1 нужны только ключи «только чтение».

Порядок: Telegram-бот → `TELEGRAM_CHAT_ID` → API-ключи бирж (опционально, но желательно) →
`.env` → запуск.

> **Нет аккаунтов на биржах?** Сканер полностью работает без ключей — см. раздел
> [«Быстрый старт без ключей»](#быстрый-старт-без-ключей) ниже. Ключи можно добавить позже.

---

## Быстрый старт без ключей

Нужно только: Docker, Telegram-бот (разделы 1–2) и пароль для локальной БД.

```bash
cp .env.example .env && chmod 600 .env
openssl rand -base64 32            # скопируйте результат в POSTGRES_PASSWORD
```

В `.env` заполните **только три** значения, всё остальное оставьте как есть
(строки `*_API_KEY` / `*_API_SECRET` / `*_API_PASSPHRASE` — пустыми):

```dotenv
TELEGRAM_BOT_TOKEN=<токен от @BotFather>
TELEGRAM_CHAT_ID=<ваш chat id>
POSTGRES_PASSWORD=<сгенерированный пароль, не короче 12 символов>
```

Запуск и проверка:

```bash
make up-local           # сборка и запуск (первый раз — несколько минут)
make ps-local           # через ~1 минуту все сервисы healthy, migrator — exited (0)
make logs s=scanner     # каждые ~10 с строка sweep_done
```

В Telegram придёт **🚀 Nexus Spread Scanner started**: у каждой биржи пометка 🌐 (публичные
данные) и число пар. Это подтверждает всю цепочку: сканер → очередь → worker → Telegram.

**Что работает без ключей:** тикеры, стаканы (REST и WebSocket), расчёт чистого спреда с
комиссиями и проскальзыванием, алерты, запись всех оценок в БД. Статусы вводов/выводов
публикуют KuCoin и Gate.io; для Binance, Bybit и OKX их нет, поэтому алерты по этим биржам
приходят с пометкой **⚠️ Transfer path unverified**, а комиссии — с **ℹ️ Taker fee is an
estimate**. Перед реальной сделкой проверяйте ввод/вывод монеты вручную.

**Увидеть алерт быстрее** (при порогах 0.3 % / $5 их может не быть часами): временно
поставьте в `.env` `SPREAD_MIN_NET_PROFIT_PCT=0.05` и `SPREAD_MIN_NET_PROFIT_USD=0.5`,
выполните `make up-local`, дождитесь сообщения **💹 Arbitrage Opportunity** и верните значения
`0.3` и `5` (снова `make up-local`).

**Посмотреть статистику в БД** (порт открыт только на 127.0.0.1):

```bash
docker compose -f docker-compose.local.yml exec postgres \
  psql -U nexus -d nexus -c "select status, count(*) from spread_evaluations \
  where evaluated_at > now() - interval '1 hour' group by 1 order by 2 desc;"
```

Остановка: `make down-local` (данные сохраняются). Когда появятся аккаунты — создайте
read-only ключи по разделу 3, впишите их в `.env` и снова выполните `make up-local`.

---

## 0. Предварительные требования

| Что | Проверка | Примечание |
|---|---|---|
| Docker Engine + Compose v2 | `docker compose version` | На Windows — Docker Desktop с WSL2 backend |
| GNU Make | `make --version` | В WSL: `sudo apt install make` |
| uv (для разработки/тестов) | `uv --version` | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Git | `git --version` | |

Ноутбук должен иметь стабильный интернет; спящий режим останавливает сканирование.

---

## 1. Создание Telegram-бота и `TELEGRAM_BOT_TOKEN`

1. В Telegram откройте **@BotFather** (проверьте синюю галочку верификации).
2. Отправьте `/newbot`.
3. Введите отображаемое имя, например `Nexus Spread Scanner`.
4. Введите username бота — должен оканчиваться на `bot`, например `nexus_spread_grisha_bot`.
5. BotFather пришлёт токен вида `1234567890:AAH...`. Это и есть **`TELEGRAM_BOT_TOKEN`**.

> ⚠️ Токен = полный контроль над ботом. Не отправляйте его никому, не коммитьте в git,
> не вставляйте в чат с ассистентом. Если токен утёк — в @BotFather: `/revoke` → выберите бота.

Рекомендуемые настройки в @BotFather (необязательно):
- `/setdescription` — описание бота.
- `/setjoingroups` → `Disable`, если бот будет писать только вам лично (защита от добавления в чужие группы).

---

## 2. Получение `TELEGRAM_CHAT_ID`

### Вариант A — личные сообщения (рекомендуется для начала)

1. Найдите своего бота по username и нажмите **Start** (или отправьте любое сообщение).
   Без этого бот не сможет вам писать.
2. Откройте в браузере (подставьте свой токен):
   ```
   https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/getUpdates
   ```
3. В ответе найдите `"chat":{"id":123456789,...}` — число **`123456789`** и есть `TELEGRAM_CHAT_ID`.
   Если ответ `{"ok":true,"result":[]}` — отправьте боту ещё одно сообщение и обновите страницу.

### Вариант B — группа или канал

1. Создайте группу/канал и добавьте туда бота (для канала — как администратора с правом публикации).
2. Напишите сообщение в группу (в канале — опубликуйте пост).
3. Откройте тот же URL `getUpdates`. ID группы — **отрицательное** число, например `-1001234567890`.
   Минус — часть ID, копируйте его целиком.

> Если в группе бот не видит сообщений: @BotFather → `/setprivacy` → выберите бота → `Disable`,
> затем удалите и снова добавьте бота в группу.

---

## 3. API-ключи бирж (только чтение)

### Зачем ключи, если стаканы публичные?

Стаканы и тикеры сканер читает **без ключей**. Ключи «только чтение» нужны, чтобы:

- получать **статусы депозитов/выводов и комиссии сетей** (у Binance, Bybit и OKX эти данные
  доступны только с ключом). Без них сканер не может исключить «фальшивые» спреды, когда на
  одной из бирж закрыты вводы/выводы монеты — это главная причина ложных сигналов;
- в будущем — учитывать **ваш личный уровень комиссий** (VIP-tier).

Без ключей сканер работает, но в алертах будет пометка
**«⚠️ Transfer path unverified»** для бирж без данных.

> **Пример из первого запуска.** За 1,5 часа без ключей пришёл 21 алерт по ZIL и ONE:
> спред ~1 % держался десятки минут. Причина — на Binance нативные сети ZIL и ONE
> приостановлены, монету нельзя перевести, поэтому спред и не закрывается. С ключами
> сканер видит статус сетей и такие связки не алертит, а в Stage 1.5 ещё и автоматически
> отправляет их в карантин.

Ключи нужны для **всех 7 бирж**: Bybit, Binance, OKX, Gate.io, KuCoin, MEXC, Bitget
(MEXC и Bitget подключаются в Stage 1.5). HTX не поддерживается — биржа под санкциями.

### Общие правила безопасности (для всех бирж)

- ✅ Включайте **только чтение** (Read / Read-Only / General).
- ❌ **Никогда** не включайте: Trade, Withdraw, Transfer, Margin, Futures, Sub-account.
  Бот спроектирован так, что вывод средств невозможен в принципе, но ключ должен быть
  безопасен даже при утечке.
- Включите 2FA на каждой бирже — без него большинство бирж не даёт создать ключ.
- Сохраняйте `Secret` и `Passphrase` сразу — биржа покажет секрет **только один раз**.
- Привязка к IP: на ноутбуке IP обычно динамический, поэтому для read-only ключей в V1
  её можно не включать. В V2 (торговые ключи на VPS) привязка к IP будет **обязательной**.
- Создавайте **отдельный ключ под бота**, не переиспользуйте ключи других сервисов.

### 3.1 Bybit

1. Войдите на bybit.com → иконка профиля → **API**.
2. **Create New Key** → **System-generated API Keys**.
3. Тип: **API Transaction**, название: `nexus-scanner-readonly`.
4. Permissions: **Read-Only**. Не отмечайте ни одного пункта в разделах Orders/Trade/Assets
   с правом записи; **Withdrawal — выключено**.
5. IP restriction: можно оставить без привязки. Учтите: ключи **без IP-привязки Bybit
   может деактивировать через 3 месяца** — тогда создайте новый.
6. Подтвердите 2FA, сохраните:
   - API Key → `BYBIT_API_KEY`
   - API Secret → `BYBIT_API_SECRET`

### 3.2 Binance

1. binance.com → профиль → **Account → API Management**.
2. **Create API** → тип **System generated** (HMAC) → название `nexus-scanner-readonly`.
3. После создания нажмите **Edit restrictions** и убедитесь, что отмечено **только**
   **Enable Reading**. Все остальные (Spot & Margin Trading, Withdrawals, Universal Transfer,
   Futures и т.д.) — **выключены**.
4. IP access: **Unrestricted** допустимо только для read-only ключа.
5. Сохраните:
   - API Key → `BINANCE_API_KEY`
   - Secret Key → `BINANCE_API_SECRET`

> Binance.com недоступен в ряде юрисдикций. Если ваш аккаунт на региональной версии
> (Binance US / TR и т.п.) — сообщите, это другой API и потребует отдельного адаптера.

### 3.3 OKX

1. okx.com → профиль → **API** (API keys).
2. **Create V5 API key** → назначение: **API trading** (это просто тип ключа),
   название `nexus-scanner-readonly`.
3. Придумайте **Passphrase** (не путать с паролем от аккаунта) — запишите его, восстановить нельзя.
4. Permissions: только **Read**. **Trade** и **Withdraw** — не отмечать.
5. IP: можно оставить пустым. OKX может автоматически удалять ключи без IP-привязки после
   длительной неактивности — если сканер начнёт получать `Invalid API key`, создайте ключ заново.
6. Сохраните:
   - API Key → `OKX_API_KEY`
   - Secret Key → `OKX_API_SECRET`
   - Passphrase → `OKX_API_PASSPHRASE`

### 3.4 Gate.io

1. gate.io → профиль → **API Management** → **Create API Key**.
2. Тип: **API v4 Key**, название `nexus-scanner-readonly`.
3. Account mode: **Classic** (или текущий режим вашего аккаунта).
4. Permissions: для **Spot/Margin** и **Wallet** выберите **Read Only**.
   **Withdraw** — не включать. Остальные разделы — отключены.
5. IP whitelist: можно не указывать.
6. Сохраните:
   - Key → `GATEIO_API_KEY`
   - Secret → `GATEIO_API_SECRET`

### 3.5 KuCoin

1. kucoin.com → профиль → **API Management** → **Create API**.
2. Тип: **API Trading**, название `nexus-scanner-readonly`.
3. Придумайте **API Passphrase** — запишите его.
4. Permissions: только **General** (это чтение). **Spot Trading, Margin, Futures, Transfer,
   Withdrawal** — **не отмечать**.
5. IP restriction: можно не включать.
6. Сохраните:
   - API Key → `KUCOIN_API_KEY`
   - API Secret → `KUCOIN_API_SECRET`
   - Passphrase → `KUCOIN_API_PASSPHRASE`

### 3.6 MEXC (Stage 1.5)

1. mexc.com → профиль → **API Management** → **Create API Key**.
2. Название (Notes): `nexus-scanner-readonly`.
3. Permissions: отметьте **только просмотр** — в разделах Account и Spot пункты вида
   **View account details / View order details** (Read). Пункты с правом записи
   (**Trade**, **Withdraw**, **Transfer**, Futures) — **не отмечать**.
4. IP binding: можно не указывать. У MEXC ключи без IP-привязки действуют ограниченный срок
   (обычно 90 дней) — после истечения создайте новый.
5. Подтвердите 2FA, сохраните:
   - Access Key → `MEXC_API_KEY`
   - Secret Key → `MEXC_API_SECRET`

### 3.7 Bitget (Stage 1.5)

1. bitget.com → профиль → **API Management** → **Create API** →
   **System-generated API key**.
2. Название: `nexus-scanner-readonly`.
3. Придумайте **Passphrase** (8–32 символа, буквы и цифры) — запишите его, восстановить нельзя.
4. Permissions: **Read-only** (только чтение). **Trade**, **Withdraw**, **Transfer** — **не
   отмечать**.
5. IP binding: можно не указывать (ключ без привязки может быть ограничен по сроку — при
   ошибке `Invalid API key` создайте новый).
6. Подтвердите 2FA, сохраните:
   - API Key → `BITGET_API_KEY`
   - Secret Key → `BITGET_API_SECRET`
   - Passphrase → `BITGET_API_PASSPHRASE`

> **Bitget, единый торговый аккаунт (UTA).** Сканер запрашивает вашу комиссию через
> классический эндпоинт `common/trade-rate`. Если аккаунт переведён в UTA и запрос не
> проходит, бот использует публичную ставку Bitget (0,2 %) и помечает её в алертах как
> оценочную — это безопасно (комиссия завышена, а не занижена), но часть сигналов может
> отсеяться.

> Если какую-то биржу вы не используете — оставьте её переменные пустыми, сканер будет
> работать с ней через публичные данные. Чтобы полностью отключить биржу — уберите её из
> `EXCHANGES_ENABLED`.

---

## 4. Настройка `.env`

1. В корне проекта:
   ```bash
   cp .env.example .env
   chmod 600 .env
   ```
   Файл `.env` уже в `.gitignore` — в git он не попадёт. Агент Claude настроен так, что
   **не читает** `.env`.

2. Откройте `.env` в редакторе и заполните:

   ```dotenv
   # --- Telegram ---
   TELEGRAM_BOT_TOKEN=1234567890:AAH...
   TELEGRAM_CHAT_ID=123456789

   # --- PostgreSQL (локально придумайте любой надёжный пароль) ---
   POSTGRES_PASSWORD=<длинный случайный пароль>

   # --- Биржи ---
   EXCHANGES_ENABLED=["bybit","binance","okx","gateio","kucoin"]

   BYBIT_API_KEY=...
   BYBIT_API_SECRET=...
   BINANCE_API_KEY=...
   BINANCE_API_SECRET=...
   OKX_API_KEY=...
   OKX_API_SECRET=...
   OKX_API_PASSPHRASE=...
   GATEIO_API_KEY=...
   GATEIO_API_SECRET=...
   KUCOIN_API_KEY=...
   KUCOIN_API_SECRET=...
   KUCOIN_API_PASSPHRASE=...

   # Stage 1.5 (после реализации 1.5.1 добавьте "mexc","bitget" в EXCHANGES_ENABLED)
   MEXC_API_KEY=...
   MEXC_API_SECRET=...
   BITGET_API_KEY=...
   BITGET_API_SECRET=...
   BITGET_API_PASSPHRASE=...
   ```

   Случайный пароль можно сгенерировать так: `openssl rand -base64 32`.

3. Параметры стратегии (уже выставлены по вашим ответам, менять не обязательно):

   | Переменная | Значение | Смысл |
   |---|---|---|
   | `SPREAD_MIN_NET_PROFIT_PCT` | `0.3` | Минимальный чистый профит, % |
   | `SPREAD_MIN_NET_PROFIT_USD` | `5` | Минимальный чистый профит, $ (оба условия обязательны) |
   | `SPREAD_REFERENCE_NOTIONAL_USD` | `1000` | Объём сделки для расчёта проскальзывания по стакану |
   | `SPREAD_ALERT_COOLDOWN_S` | `600` | Не повторять алерт по той же связке чаще, чем раз в N секунд |
   | `SPREAD_MAX_GROSS_SPREAD_PCT` | `20` | Спреды выше — подозрительные (разные токены с одним тикером / делистинг), не алертятся |
   | `SPREAD_MAX_UNVERIFIED_GROSS_SPREAD_PCT` | `5` | Более строгий предел, если не подтверждены маршрут перевода **и** адрес контракта токена |
   | `TELEGRAM_ALERT_MAX_AGE_S` | `30` | Алерт, застрявший в очереди дольше, не отправляется (возможность уже ушла) |
   | `TELEGRAM_EVENT_MAX_AGE_S` | `300` | Системное сообщение (биржа недоступна/восстановилась, старт/стоп) старше этого не отправляется, чтобы не вводить в заблуждение |
   | `SCANNER_MIN_QUOTE_VOLUME_USD` | `50000` | Игнорировать пары с суточным объёмом ниже |
   | `SCANNER_WS_ENABLED` | `true` | Стаканы «горячих» связок (недавно был положительный чистый спред) получать по WebSocket — свежее и без лишних REST-запросов |
   | `SCANNER_WS_MAX_STREAMS` | `20` | Максимум одновременных WebSocket-подписок |
   | `SCANNER_WS_HOT_TTL_S` | `300` | Сколько секунд держать подписку после последнего положительного спреда |

   Полный список переменных с комментариями — в `.env.example`.

---

## 5. Запуск и проверка

```bash
make up-local          # собрать и запустить весь стек
make ps-local          # статус контейнеров — все должны быть healthy
make logs s=scanner    # логи сканера
```

Что должно произойти:
1. Поднимаются `postgres` и `redis`, затем `migrator` применяет миграции и завершается.
2. Стартуют `scanner`, `worker-alerts`, `worker-maintenance`, `beat`.
3. В Telegram приходит сообщение **🚀 Nexus Spread Scanner started** со списком бирж.
4. При появлении спреда, проходящего фильтры, придёт алерт **💹 Arbitrage Opportunity**.

### Как читать алерт

- **⚠️ Transfer path unverified** — сканер не смог подтвердить, что монету можно вывести с
  биржи покупки и завести на биржу продажи (нет ключей или биржа не публикует статусы).
  Проверьте статус депозитов/выводов вручную. С read-only ключами таких пометок меньше.
- **ℹ️ Taker fee is an estimate** — комиссия взята из справочника ccxt, а не персональная.
  С ключами подтягивается ваша реальная комиссия: для Binance, Bybit и Gate.io — сразу, для
  OKX — по конкретной паре, когда она становится кандидатом на алерт (кэш 6 часов).
- Все суммы рассчитаны для объёма `SPREAD_REFERENCE_NOTIONAL_USD` с учётом глубины стакана.

При порогах 0.3 % / $5 алертов может не быть часами — это нормально для ликвидных пар.
Для проверки цепочки можно временно поставить `SPREAD_MIN_NET_PROFIT_PCT=0.05` и
`SPREAD_MIN_NET_PROFIT_USD=0.5`, перезапустить (`make up-local`) и потом вернуть значения.

Остановка: `make down-local` (данные в БД сохраняются в Docker volume).

---

## 6. Частые проблемы

| Симптом | Причина / решение |
|---|---|
| Нет сообщения о старте в Telegram | Не нажали **Start** у бота; неверный `TELEGRAM_CHAT_ID`; для группы — забыли минус |
| `401` / `Invalid API key` в логах биржи | Опечатка в ключе/секрете, не тот passphrase (OKX, KuCoin), ключ истёк/удалён (ключи без IP-привязки) |
| `451` / `restricted location` от Binance | Гео-блокировка Binance.com в вашем регионе — уберите `binance` из `EXCHANGES_ENABLED` |
| Контейнер `scanner` unhealthy | `make logs s=scanner` — чаще всего нет сети или биржа ограничила частоту запросов |
| Ноутбук уснул — алертов нет | Отключите сон на время работы или дождитесь V2 (VPS) |

---

## 7. Чек-лист перед запуском

- [ ] Бот создан, токен в `.env`, боту нажат **Start**
- [ ] `TELEGRAM_CHAT_ID` в `.env`
- [ ] Ключи бирж созданы **только с правом чтения**, вывод выключен
      (Bybit, Binance, OKX, Gate.io, KuCoin, MEXC, Bitget)
- [ ] `.env` заполнен, права `600`, в git не попал (`git status` его не показывает)
- [ ] `make up-local` → все сервисы healthy → пришло сообщение о старте
