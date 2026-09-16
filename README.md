# ИНК • Расписание — MAX-бот

MAX-бот расписания группы **ЭС7-24** (Институт нефти и газа, ishnk.ru).
Порт Telegram-бота [FullDozzer/FullDozzer](https://github.com/FullDozzer/FullDozzer)
на российский мессенджер **MAX** ([dev.max.ru/docs-api](https://dev.max.ru/docs-api)).

Перенесена вся функциональность 1:1, заменён только транспорт:
парсинг сайта, PNG-картинки, подписки, мониторинг изменений, история учёбы,
прогноз в академических часах, статусы и скрытые поздравления работают как раньше.

## Возможности

- 📅 Расписание группы на сегодня / завтра / любую дату — красивой PNG-картинкой
- ✍️ Понимание текста: «расписание», «расписание на 4 сентября», «расписание на завтра»
- 👨‍🏫 Расписание преподавателей: «расписание преподавателя Аглиуллиной»
  (единый справочник `staff_directory.py`, навигация по дням кнопками)
- 🔔 Подписки: бот каждые 5 минут проверяет сайт и присылает PNG
  «Расписание опубликовано / изменилось» с построчным списком изменений
- 📖 История учёбы и прогноз «Изучено: X / Y акад. ч» на каждой картинке
- ℹ️ `/status` — PNG-карточка состояния (подписки, прогресс, аптайм, ресурсы)
- 🎂 Скрытая ежедневная проверка дней рождения группы (блок `happyCard`)
- 🛡 Rate limit, проверка админа в группах, часовой пояс `Asia/Yekaterinburg`

## Команды

| Команда | Описание |
|---|---|
| `/today` | Расписание только на сегодня |
| `/schedule` | Расписание только на завтра |
| `/date ДАТА` | По дате: `04.09.2026`, `4 сентября`, `понедельник`, `завтра` |
| `расписание …` | То же текстом, без слэша |
| `/subscribe` | Включить уведомления в этот чат |
| `/unsubscribe` | Отключить уведомления |
| `/status` | Статус бота картинкой |
| `/help` | Помощь |

## Как получить токен

1. Найди **@MasterBot** в мессенджере MAX и создай бота
   (ник 11–60 символов, заканчивается на `_bot`).
2. Забери токен (MasterBot или `business.max.ru` → Чат-боты → Настройки).
3. Для публикации бота нужна верификация юрлица на
   [dev.max.ru](https://dev.max.ru) и модерация карточки (до 48 часов).

## Быстрый старт (Long Polling)

```bash
cp .env.example .env
# впиши MAX_BOT_TOKEN в .env

pip install -r requirements.txt
python bot.py
```

Напиши боту `/start`. Без `MAX_WEBHOOK_URL` бот работает через
Long Polling — это режим разработки (MAX рекомендует его только для тестов).

## Docker

```bash
docker build -t inkmaxbot .
docker run -d --restart unless-stopped \
  --env-file .env \
  -v inkmaxbot-data:/app/data \
  --name inkmaxbot inkmaxbot
```

## Production: Webhook

MAX требует для production Webhook: `https://`, валидный сертификат
(подойдёт сертификат УЦ Минцифры), порт **443** без указания в URL.

```bash
# .env
MAX_WEBHOOK_URL=https://bot.example.com
MAX_WEBHOOK_PATH=/max/webhook
MAX_WEBHOOK_SECRET=случайная-строка-минимум-5-символов
PORT=8080
```

На сервере подними реверс-прокси (nginx/Caddy) `https://bot.example.com`
→ `http://127.0.0.1:8080`, затем запусти бота — подписка
`POST /subscriptions` оформится автоматически при старте.
Проверка секрета идёт по заголовку `X-Max-Bot-Api-Secret`.
Доступен health-check `GET /health`.

> Важно: при активной webhook-подписке Long Polling не работает.
> Для возврата в polling-режим удали подписку (очисти `MAX_WEBHOOK_URL`
> и вызови `DELETE /subscriptions?url=...`).

## Переменные окружения

| Переменная | По умолчанию | Описание |
|---|---|---|
| `MAX_BOT_TOKEN` | — | Токен MAX-бота (`BOT_TOKEN` — alias) |
| `MAX_API_BASE_URL` | `https://platform-api2.max.ru` | Домен MAX Bot API |
| `MAX_WEBHOOK_URL` | пусто | Базовый https-URL → webhook-режим |
| `MAX_WEBHOOK_PATH` | `/max/webhook` | Путь подписки и сервера |
| `MAX_WEBHOOK_SECRET` | пусто | Секрет webhook-подписки |
| `PORT` | `8080` | Порт webhook/health сервера |
| `MAX_SSL_VERIFY` | `true` | Проверка TLS MAX API |
| `MAX_SSL_CA_BUNDLE` | `certs/max_ca_bundle.crt` | Дополнительные корневые сертификаты (путь/каталог/PEM, `none` — не добавлять) |
| `GROUP_NAME` / `GROUP_ID` | `ЭС7-24` / `508` | Группа и её ID на сайте |
| `BASE_URL` / `STAFF_BASE_URL` | см. `.env.example` | Источники расписания |
| `BIRTHDAY_URL` / `BIRTHDAY_CHAT_ID` | — | Дни рождения группы |
| `CHECK_INTERVAL` | `300` | Проверка изменений, секунды |
| `HTTP_TIMEOUT` | `20` | Таймаут запросов к сайту |
| `RATE_LIMIT_*` | `10` / `8` / `30` | Окно, лимит, кулдаун предупреждений |
| `DATA_DIR` | `data` | SQLite-база и временные PNG |

`chat_id` для `BIRTHDAY_CHAT_ID` приходит в событиях `bot_added`/`bot_started` —
добавь бота в чат группы и посмотри логи, либо подпиши чат `/subscribe`
с названием группы (бот найдёт его сам).

## TLS: сертификат MAX API

Бот проверяет TLS-сертификат MAX. Если цепочка не собирается, он падает
на старте с такой ошибкой:

```
MAX API недоступен ([0] connection_error: Cannot connect to host
platform-api2.max.ru:443 ssl:True [SSLCertVerificationError: (1,
'[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed:
unable to get local issuer certificate (_ssl.c:1016)')]).
```

Что это бывает и что делать:

1. **Сертификат от УЦ Минцифры (Russian Trusted CA).** Его нет ни в наборе
   Mozilla, ни в `ca-certificates` образа `python:3.11-slim`. Репозиторий
   содержит бандл — `certs/max_ca_bundle.crt` (корневой и выпускающий
   сертификаты с официального CDN Госуслуг `gu-st.ru`; отпечатки и команды
   проверки — в `certs/README.md`). Бот добавляет его к системному
   хранилищу в своём SSL-контексте: проверка сертификата остаётся полной,
   качать и ставить ничего не нужно. В стартовом логе видно, что
   подхватилось:

   ```
   TLS: системное хранилище + /app/certs/max_ca_bundle.crt
   ```

   Не доверяешь этому УЦ — `MAX_SSL_CA_BUNDLE=none`, и останется только
   системное хранилище.
2. **Устаревший или отсутствующий `ca-certificates`** (срезанный образ,
   сборка без сети). У `max.ru` есть и обычные публичные сертификаты
   (Google Trust Services, TrustAsia, HARICA, SSL.com) — они в стандартном
   наборе есть, поэтому чинится так:
   `apt-get update && apt-get install -y ca-certificates && update-ca-certificates`.
3. **Прокси/файрвол подменяет TLS** — добавь CA своего прокси тем же
   параметром: `MAX_SSL_CA_BUNDLE=/etc/ssl/corp-proxy-ca.pem`.
4. `MAX_SSL_VERIFY=false` — полностью выключает проверку сертификата.
   Крайний вариант для закрытого контура, а не рабочее решение.

Диагностика:

```bash
# чем реально подписан сертификат MAX
openssl s_client -connect platform-api2.max.ru:443 -servername platform-api2.max.ru \
  -showcerts </dev/null 2>/dev/null | grep -E 's:|i:|Verify return code'

# та же проверка, но с бандлом из репозитория
openssl s_client -connect platform-api2.max.ru:443 -servername platform-api2.max.ru \
  -CAfile certs/max_ca_bundle.crt </dev/null 2>/dev/null | grep 'Verify return code'

# что видит Python в этом образе
python -c "import ssl;print(ssl.get_default_verify_paths())"
```

## Архитектура

```
bot.py              — весь бот: парсинг, рендер, БД, MAX-транспорт, main()
staff_directory.py  — единый справочник преподавателей (STAFF_ID — истина)
fonts/              — DejaVuSans (regular + bold) для PNG
certs/              — корневые сертификаты УЦ Минцифры для TLS (см. certs/README.md)
data/               — bot.db (SQLite) и временные картинки (не в git)
tests/
  test_schedule_bot.py — 125 тестов логики (парсинг, рендер, БД, мониторинг)
  test_max_transport.py — 81 тест MAX-слоя (API-клиент, кнопки, роутинг,
    webhook-сервер, TLS-доверие, сквозная отправка)
```

Транспорт MAX — собственный лёгкий клиент на `aiohttp`, без сторонних SDK:
`POST /messages`, `PUT /messages`, `POST /answers`, `POST /uploads`,
`GET /updates`, `POST /subscriptions`, `PATCH /me/commands`.
Расписание уходит как PNG: `upload (type=image)` → сообщение с
`image`-вложением + `inline_keyboard`. Тексты и клавиатуры — HTML-разметка
MAX (`format=html`), payload кнопок — те же строки, что были `callback_data`.

## Тесты

```bash
pip install -r requirements.txt
python -m unittest discover -s tests -v
```

Ожидается `Ran 187 tests … OK`.

## Отличия от Telegram-версии

- Транспорт переписан с aiogram на MAX Bot API; весь остальной код
  (парсинг `ishnk.ru`, Pillow-рендер, SQLite, мониторинг, прогноз) — без изменений,
  тексты сообщений и формат подписей сохранены.
- Callback-подтверждения: в MAX API нет всплывающих toast — нажатие просто
  подтверждается (`POST /answers`).
- Проверка админа идёт через `GET /chats/{id}/members/admins`; если бот сам
  не может получить список (403), подписка не блокируется.
- Учти лимиты MAX: ≤30 rps глобально, ≤2 сообщения/сек в один чат
  (в клиенте есть per-chat троттлинг), текст ≤4000 символов.
- В групповых чатах бот получает события, только если он администратор
  (требование платформы MAX).
