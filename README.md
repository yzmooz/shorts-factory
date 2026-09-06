# Shorts Factory

Автоматизированный конвейер для оригинальных вертикальных YouTube Shorts:

`тема → DeepSeek/OpenAI API → Pexels → Edge TTS → 9:16 MP4 → очередь → YouTube Data API`

По умолчанию ролики только создаются и загружаются вручную после просмотра. Когда формат проверен, `youtube.auto_upload = true` включает ежедневную загрузку через планировщик Windows.

## Почему не копия MoneyPrinterV2

MoneyPrinterV2 послужил архитектурным референсом, но этот проект написан с нуля. MPV2 лицензирован по AGPL-3.0, загружает через Selenium/YouTube Studio и зависит от хрупких селекторов страницы. Здесь используется официальный OAuth и YouTube Data API, есть дедупликация тем, дневной лимит, пауза между загрузками и `private` по умолчанию.

## Рекомендуемый стартовый формат

В конфигурации выбрана ниша «удивительные факты о науке и мире» для общей аудитории 13+. Это семейно-безопасный, но не специально детский контент. Не переключайте `audience = "kids"` только ради охватов: аудитория должна отражать реальное назначение ролика. Если сценарии, персонажи, песни и подача явно ориентированы на детей, выберите `kids`; загрузчик автоматически выставит `selfDeclaredMadeForKids = true`.

Нельзя гарантировать большие охваты. Практичная цель первых 30 роликов — найти формат с хорошим удержанием, не выпускать десятки однотипных видео. Меняйте первые 1–2 секунды, визуальный прием и структуру, а не только тему.

## Быстрый запуск (Windows)

Требуются Python 3.11, FFmpeg, API-ключ DeepSeek или OpenAI и бесплатный API-ключ Pexels.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
Copy-Item .env.example .env
```

Откройте `.env` и вставьте один ключ:

```dotenv
DEEPSEEK_API_KEY=ваш_ключ
# или OPENAI_API_KEY=ваш_ключ
PEXELS_API_KEY=ваш_ключ_pexels
```

Pexels автоматически подбирает отдельное вертикальное фото для каждой сцены. При сборке
добавляются затемнение под текст и плавное приближение кадра. Сведения об авторах сохраняются
в `credits.json` и автоматически добавляются в описание YouTube. Для возврата к цветным фонам
без фото установите `visuals.provider = "gradient"`.

По умолчанию используется экономичный `deepseek-v4-flash`. Для OpenAI измените в `config.toml`:

```toml
[content]
provider = "openai"
openai_model = "gpt-5.6-luna"
```

Создайте тестовый ролик без обращения к платному API:

```powershell
.\.venv\Scripts\shorts-factory.exe generate --topic "Почему небо на Марсе красное" --demo
.\.venv\Scripts\shorts-factory.exe list
```

Откройте созданный `output/.../short.mp4`. Для настоящей API-генерации уберите `--demo`:

```powershell
.\.venv\Scripts\shorts-factory.exe generate --topic "Как пчелы объясняют дорогу"
```

## Подключение YouTube

1. Создайте проект в Google Cloud и включите **YouTube Data API v3**.
2. Настройте OAuth consent screen.
3. Создайте OAuth Client ID типа **Desktop app**.
4. Скачайте JSON и сохраните в корне как `client_secret.json`.
5. Оставьте `privacy = "private"` и загрузите одобренный черновик:

```powershell
.\.venv\Scripts\shorts-factory.exe upload 1
```

При первом запуске откроется окно Google. Токен сохранится локально в `youtube_token.json`; оба файла исключены из Git. Новые непроверенные API-проекты могут загружать видео только как private до прохождения аудита Google.

Планирование поддерживается через ISO 8601 и только для private-видео:

```powershell
.\.venv\Scripts\shorts-factory.exe upload 1 --publish-at "2026-08-03T18:30:00+03:00"
```

## Полная автоматизация

Сначала проверьте минимум 5–10 роликов вручную. Затем в `config.toml` установите:

```toml
[youtube]
privacy = "private" # либо public после аудита API-проекта
auto_upload = true
```

Создайте ежедневную задачу Windows:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install-schedule.ps1 -At "18:30"
```

Каждый запуск берет следующую неиспользованную строку из `topics.txt`. Когда темы
заканчиваются, DeepSeek автоматически предлагает новую пачку, исключая уже созданные
ролики, и сохраняет её в тот же файл. Размер пачки задаётся через
`content.topic_batch_size`. В текущей конфигурации разрешено до четырёх автоматических
роликов в день. Запас в 30 минут относительно шестичасового расписания учитывает время
рендера и загрузки, поэтому слоты не пропускаются из-за нескольких минут обработки.

### Автономная работа на VPS

На Ubuntu/Debian VPS проект запускается одним `systemd`-таймером в 03:00, 09:00,
15:00 и 21:00 по Москве. ChatGPT и домашний компьютер после установки не нужны.

С Windows-машины, где уже настроены `.env` и YouTube OAuth, выполните:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\deploy-vps.ps1 -SshHost "имя-из-ssh-config"
```

Команда переносит конфигурацию, API-ключи, OAuth-токен и базу опубликованных роликов,
ставит Python/FFmpeg/шрифты и включает таймер. Чтобы сразу после установки создать и
опубликовать один ролик, добавьте `-RunNow`. Логи на сервере:

```bash
journalctl -u shorts-factory.service -n 100 --no-pager
systemctl list-timers shorts-factory.timer
```

## Что потребуется от владельца канала

- выбор: общая аудитория 13+ (рекомендуемый старт) или действительно детский канал;
- Google-аккаунт с YouTube-каналом и файл OAuth `client_secret.json`;
- ручная проверка фактов и сценариев на первом этапе; темы DeepSeek пополняет автоматически;
- оплаченный API-ключ DeepSeek либо OpenAI; ключ хранится только в `.env`;
- бесплатный API-ключ Pexels для автоматического подбора изображений;
- только собственная или лицензированная музыка (необязательно);
- решение о языке, голосе, стиле и времени публикации;
- периодическая проверка YouTube Analytics: удержание первых секунд, досмотры и возврат зрителей.

## Полезные команды

```powershell
shorts-factory doctor
shorts-factory run-once
shorts-factory refill-topics --count 50
shorts-factory list
shorts-factory inspect 1
shorts-factory upload 1
```

Артефакты каждого ролика (`plan.json`, кадры, озвучка, SRT и MP4) сохраняются в `output/`. Это позволяет отредактировать сценарий или заменить визуалы до публикации.
