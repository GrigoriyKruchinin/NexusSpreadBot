# Бесплатный хостинг для сканера

Цель: чтобы сканер работал 24/7 и не зависел от ноутбука (сон, WSL, перезагрузки Windows).
Бот **ничего не покупает и не выводит**, ключи у вас только на чтение.

> ⚠️ Условия бесплатных тарифов часто меняются. Перед регистрацией проверьте актуальные
> лимиты на сайте провайдера. Ниже — то, что известно на момент написания.

## Что нужно нашему стеку

6 контейнеров: PostgreSQL, Redis, scanner, 2 celery-воркера, celery beat. Работает постоянно,
ходит наружу на API бирж. Реалистичный минимум: **2 vCPU, 2 ГБ RAM, 20 ГБ диска**
(на 1 ГБ запускается только с swap и без запаса).

Две критичные вещи при выборе:
1. **Регион сервера.** Binance.com блокирует IP из США (ошибка `451 restricted location`).
   Выбирайте Европу (Франкфурт, Амстердам, Лондон и т.п.). Часть бесплатных тарифов
   доступна только в США — они нам не подходят.
2. **Постоянная работа.** Тарифы, где сервис «засыпает» без входящих запросов, не годятся:
   сканер сам ходит на биржи и входящего трафика не имеет.

## Сравнение вариантов

| Вариант | Бесплатно | Подходит? | Главная проблема |
|---|---|---|---|
| **Oracle Cloud Always Free** | да, без срока | ✅ лучший | Сложная регистрация (карта, иногда отказ), нет мест в популярных регионах |
| **Google Cloud e2-micro** | да, без срока | ⚠️ с оговорками | Только регионы США → Binance блокируется; 1 ГБ RAM |
| **Render (free)** | частично | ❌ | Сервисы засыпают, нет бесплатных фоновых воркеров, бесплатная БД истекает |
| **Fly.io / Railway** | только пробный кредит | ❌ | Постоянного бесплатного тарифа нет |
| **AWS Free Tier** | ограниченное время | ⚠️ временно | 1 ГБ RAM, по окончании срока платный |
| **Дешёвый VPS (Hetzner, Contabo и т.п.)** | нет, ~4–6 €/мес | ✅ самый надёжный | Платно, но стабильно и без регистрационных танцев |

**Рекомендация.** Пробуйте Oracle Always Free. Если регистрация не прошла (это бывает) —
берите VPS за ~4–6 € в месяц: для проекта, который должен собирать данные неделями,
это дешевле потерянного времени.

---

## Вариант 1. Oracle Cloud Always Free (рекомендуется)

### 1.1 Регистрация
1. Откройте cloud.oracle.com → **Sign up**.
2. Нужна банковская карта (для проверки, списывается и возвращается ~1 $). Карты некоторых
   стран и виртуальные карты могут не проходить.
3. **Home Region выберите в Европе** (например, Germany Central — Frankfurt). Регион дома
   изменить потом нельзя.

### 1.2 Создание сервера
1. **Compute → Instances → Create instance**.
2. Image: **Ubuntu 22.04** (или 24.04).
3. Shape: **Ampere (VM.Standard.A1.Flex)**, 2 OCPU и 12 ГБ RAM (в рамках бесплатных 4 OCPU / 24 ГБ).
   Если пишет `Out of capacity` — попробуйте позже или другой availability domain.
   Запасной вариант — AMD `VM.Standard.E2.1.Micro` (1 ГБ RAM, нужен swap, см. ниже).
4. SSH-ключ: загрузите **публичный** ключ (`~/.ssh/id_ed25519.pub`).
   Если ключа нет: `ssh-keygen -t ed25519 -C "nexus-host"`.
5. Нужен публичный IP. Входящие порты оставьте только **22 (SSH)**.

> Oracle может остановить «простаивающие» бесплатные инстансы. Сканер постоянно использует
> CPU и сеть, но если получите письмо — проверьте статус инстанса.

### 1.3 Подключение и подготовка
```bash
ssh ubuntu@<публичный-IP>
sudo apt update && sudo apt -y upgrade
sudo apt -y install ca-certificates curl git make
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER && newgrp docker
docker compose version          # должно работать
sudo systemctl enable docker    # автозапуск Docker после перезагрузки
```

Swap (обязательно для серверов с 1 ГБ RAM, полезно и для остальных):
```bash
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

Базовая защита:
```bash
sudo ufw allow OpenSSH && sudo ufw --force enable
sudo sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
sudo systemctl restart ssh
```
В консоли Oracle (Networking → Security List) оставьте открытым только порт 22.

> Ubuntu на Oracle по умолчанию содержит правила iptables; если сервер не отвечает по SSH
> после включения ufw — настройте через консоль Oracle (Instance → Console connection).

### 1.4 Код и секреты
```bash
git clone https://github.com/GrigoriyKruchinin/NexusSpreadBot.git
cd NexusSpreadBot
```
Если репозиторий приватный — используйте deploy key (GitHub → Settings → Deploy keys,
только чтение) или `gh auth login`.

Файл `.env` **не коммитится и не вставляется в чат**. Перенесите его со своего компьютера
(в нём только секреты: ключи, токен бота, пароли):
```bash
# выполняется на ВАШЕМ компьютере (WSL), не на сервере
scp ~/projects/NexusSpreadBot/.env ubuntu@<публичный-IP>:~/NexusSpreadBot/.env
ssh ubuntu@<публичный-IP> 'chmod 600 ~/NexusSpreadBot/.env'
```
Файл `config/nexus.toml` (все остальные настройки) приходит вместе с репозиторием через git, его копировать не нужно.

### 1.5 Запуск
**Сначала остановите локальный стек** (`make down` на ноутбуке) и убедитесь, что в Docker
Desktop на Windows нет старых контейнеров `nexus-*`. Два сканера с одним
`TELEGRAM_BOT_TOKEN` дублируют алерты и сообщения «остановлен».

```bash
cd ~/NexusSpreadBot
make up          # на сервере тот же compose-файл и та же команда
make ps          # через ~1 минуту все сервисы healthy
make logs s=scanner
```
В Telegram придёт **🚀 Nexus Spread Scanner запущен**.

Контейнеры стартуют с политикой `unless-stopped`, а Docker включён в автозапуск —
после перезагрузки сервера стек поднимется сам.

### 1.6 Перенос накопленных данных (по желанию)
Если нужна история эпизодов с ноутбука:
```bash
# на ноутбуке
docker compose -f docker-compose.yml exec -T postgres sh -c \
  'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' | gzip > nexus-backup.sql.gz
scp nexus-backup.sql.gz ubuntu@<публичный-IP>:~/

# на сервере (стек уже запущен, миграции применены)
cd ~/NexusSpreadBot
docker compose -f docker-compose.yml stop scanner
gunzip -c ~/nexus-backup.sql.gz | docker compose -f docker-compose.yml exec -T postgres sh -c \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
docker compose -f docker-compose.yml start scanner
```
Если сомневаетесь — проще начать с чистой БД: за неделю данных накопится достаточно.

---

## Вариант 2. Google Cloud (Always Free, e2-micro)

Бесплатно: 1 экземпляр `e2-micro` (0,25–1 vCPU, **1 ГБ RAM**), 30 ГБ диска, только в регионах
**us-west1, us-central1, us-east1**.

Минусы для нас:
- **IP из США → Binance вернёт `451`.** Придётся убрать `binance` из `[exchanges] enabled` в `config/nexus.toml`
  (теряем самую ликвидную биржу и большую часть маршрутов). Для проверки идеи это
  нежелательно.
- 1 ГБ RAM: нужен swap, запас по памяти минимален.
- Требуется привязка карты (при превышении бесплатных лимитов идут списания).

Если всё же хотите: Compute Engine → Create instance → e2-micro, регион US, Ubuntu 22.04,
диск 30 ГБ standard. Дальше шаги 1.3–1.5 из варианта 1 (SSH через `gcloud compute ssh`
или кнопку SSH в консоли).

---

## Вариант 3. Render (не рекомендуется)

- Бесплатный web service засыпает после ~15 минут без входящих запросов.
- Бесплатных фоновых воркеров (background worker, cron) нет — они платные.
- Бесплатная PostgreSQL удаляется через ограниченный срок.
- У нас 3 фоновых процесса (scanner, worker, beat) — на Render это платные сервисы.

Использовать можно только как эксперимент, для постоянной работы не подойдёт. Аналогично
Fly.io и Railway: постоянного бесплатного тарифа для такого стека у них нет, только пробный кредит.

---

## Вариант 4. Недорогой VPS (самый надёжный)

Hetzner (CX22, ~4 €/мес, 2 vCPU / 4 ГБ, Германия или Финляндия), Contabo, DigitalOcean и т.п.
Шаги те же, что в 1.3–1.5 (Ubuntu 22.04, Docker, swap, ufw, scp `.env`). На сервере/VPS включите IP-whitelist на ключах (IP сервера статичен).

---

## Контроль после переезда

- `make ps` — все сервисы `healthy`.
- `make logs s=scanner` — нет повторяющихся ошибок (`INVALID_KEY`, `451`, `429`).
- В Telegram один запуск, без серии «остановлен».
- Каждое утро (по `DIGEST_TZ`) приходит **📊 Ежедневный дайджест**.
- Раз в несколько дней: `docker system df` и `df -h` — диск не должен заполняться
  (в БД копятся оценки; старые данные чистит `worker-maintenance`).

## Безопасность

- Ключи бирж — только чтение, вывод отключён.
- `.env` на сервере: `chmod 600`, вход по SSH только по ключу, пароли отключены.
- Порт PostgreSQL и Redis наружу не открывать (в `docker-compose.yml` БД слушает
  только `127.0.0.1`).
- Если ключ или токен бота когда-либо оказался в чате/логах — перевыпустите его на бирже
  и через `/revoke` в @BotFather.
