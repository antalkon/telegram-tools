# Развёртывание

Готовый образ публикуется в GitHub Container Registry при каждом пуше в `main`:

```
ghcr.io/antalkon/telegram-tools:latest
```

Платформы: `linux/amd64` и `linux/arm64` (подходят Raspberry Pi 4/5, Apple Silicon, ARM-серверы).

## Docker Compose (рекомендуется)

```bash
git clone https://github.com/antalkon/telegram-tools.git
cd telegram-tools
cp .env.example .env
# впишите TGT_ADMIN_PASSWORD и TGT_SECRET_KEY
docker compose pull
docker compose up -d
```

Панель откроется на http://127.0.0.1:8000.

Собрать образ из исходников, а не скачивать готовый:

```bash
docker compose up -d --build
```

## docker run

```bash
docker volume create tgt-data
docker run -d --name tg-toolkit --restart unless-stopped \
  -p 127.0.0.1:8000:8000 \
  -e TGT_ADMIN_PASSWORD='сложный-пароль' \
  -e TGT_SECRET_KEY="$(python3 -c 'import secrets;print(secrets.token_urlsafe(48))')" \
  -v tgt-data:/data \
  ghcr.io/antalkon/telegram-tools:latest
```

> Сохраните `TGT_SECRET_KEY`: без него сохранённые сессии Telegram не расшифровать.

## Теги образа

| Тег | Когда появляется |
|---|---|
| `latest` | Каждый пуш или мердж в `main` после зелёных тестов |
| `sha-<commit>` | Каждая сборка: зафиксировать конкретную версию |
| `1.2.3`, `1.2` | Пуш git-тега `v1.2.3` |

## HTTPS и reverse proxy

Контейнер слушает только `127.0.0.1`. Наружу выставляйте его через reverse proxy с HTTPS,
а в `.env` задайте `TGT_COOKIE_SECURE=true`.

Caddy:

```
tools.example.com {
    reverse_proxy 127.0.0.1:8000
}
```

nginx (прогресс задач идёт через SSE, поэтому буферизацию надо отключить):

```nginx
location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_buffering off;
    proxy_read_timeout 1h;
}
```

## Данные, бэкап и обновление

Все данные (SQLite и аватарки) лежат в томе `tgt-data`, в контейнере это `/data`.

Бэкап:

```bash
docker compose stop
docker run --rm -v telegram-tools_tgt-data:/data -v "$PWD":/backup alpine \
  tar czf /backup/tgt-backup-$(date +%F).tgz -C /data .
docker compose start
```

Обновление:

```bash
docker compose pull && docker compose up -d
```

Новые колонки в базе добавляются автоматически при старте. Перед обновлением всё равно сделайте бэкап.

Хотите хранить данные в папке, а не в томе? Замените в `docker-compose.yml` строку `tgt-data:/data`
на `./data:/data` и выдайте папку пользователю контейнера: `sudo chown -R 10001:10001 ./data`.

## Проверка состояния

`GET /api/health` возвращает `{"ok": true}`. Образ использует его в `HEALTHCHECK`, поэтому
`docker ps` показывает статус `healthy`.

## CI/CD

Workflow `.github/workflows/ci.yml` делает следующее:

1. Прогоняет тесты бэкенда (`pytest`), линт и сборку фронтенда.
2. Собирает мультиплатформенный образ.
3. Публикует образ в `ghcr.io/<owner>/<repo>`, если это пуш в `main`, тег `v*` или ручной запуск.
   В pull request образ только собирается, без публикации.

Отдельные секреты не нужны: используется встроенный `GITHUB_TOKEN` с правом `packages: write`.
Если образ должен скачиваться без `docker login`, после первой публикации откройте
**Packages → telegram-tools → Package settings → Change visibility → Public**.
