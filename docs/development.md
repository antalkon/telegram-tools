# Разработка

Стек:

- **Бэкенд:** Python 3.13, FastAPI, Telethon, SQLAlchemy 2 (async) + SQLite (aiosqlite, FTS5).
- **Фронтенд:** React 19, Vite, TypeScript, Tailwind CSS v4, TanStack Query/Virtual, react-force-graph.

## Запуск

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
cp .env.example .env   # задайте TGT_ADMIN_PASSWORD и TGT_SECRET_KEY
.venv/bin/uvicorn app.main:app --reload --port 8000
```

```bash
cd frontend
npm install
npm run dev            # http://localhost:5173, /api проксируется на :8000
```

### Демо-данные без Telegram

Скрипт заливает 5 каналов с пересекающейся аудиторией, переписками и спам-ботами:

```bash
cd backend && .venv/bin/python -m scripts.seed_demo
```

Убрать только демо, не трогая реальные сборы: `.venv/bin/python -m scripts.seed_demo --clear`.

### Проверки

```bash
cd backend && .venv/bin/python -m pytest      # тесты, Telegram подменяется фейковым клиентом
cd frontend && npm run lint && npm run build  # oxlint + tsc + vite
```

Те же проверки запускает CI на каждый push и pull request.

## Структура

```
backend/app/
  main.py                    FastAPI, роутеры, раздача собранного фронтенда
  config.py                  настройки (TGT_*)
  models.py, db.py           SQLAlchemy-модели; новые колонки добавляются при старте
  security.py                вход админа (JWT в httpOnly cookie), шифрование сессий
  tools/base.py              контракт Tool + реестр
  tools/comment_collector/   сборщик комментаторов: aggregate.py, collector.py, queries.py, export.py
  tools/chat_indexer/        индексатор сообщений и участников групп
  tools/channel_finder/      поиск каналов и чатов людей: профили, bio, @упоминания, инвайты
  insights/                  аналитика по всем источникам: users, sources, graph, search (FTS5)
  telegram/                  сессии и вход, ссылки, resolve, кэш peer'ов и аватарок, access hash'и, разбор bio
  jobs/                      фоновые задачи (прогресс в БД + SSE), планировщик мониторинга
  api/                       REST (/api/...)
backend/tests/               pytest; фейковые клиенты Telegram
backend/scripts/seed_demo.py демо-данные
frontend/src/
  pages/                     страницы панели
  components/, features/     UI-компоненты, сборщик, графики
  lib/api.ts                 типизированный клиент API
  lib/tools.ts               каталог инструментов в сайдбаре
```

## Как добавить инструмент

1. Создайте класс-наследник `Tool` (`backend/app/tools/base.py`) с `Input`-схемой (pydantic) и `async run(ctx, params)`.
   Прогресс отдаётся через `ctx.update(...)`, итог — через возвращаемый словарь.
2. Зарегистрируйте его вызовом `register(...)` и импортируйте модуль в `app/main.py`.
3. Добавьте свой роутер в `app/api/` и подключите его в `main.py`.
4. Во фронтенде: запись в `frontend/src/lib/tools.ts`, страница в `pages/`, маршрут в `App.tsx`.
5. Тест с фейковым клиентом в `backend/tests/`.

Раннер выполняет одну задачу на аккаунт за раз, остальные ставит в очередь. Длинные FloodWait нужно
показывать через `ctx.update(flood_wait_until=...)`, чтобы интерфейс вёл обратный отсчёт.
