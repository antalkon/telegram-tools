<div align="center">

# TG Toolkit — Telegram comment scraper, chat indexer and audience analytics

**A self-hosted web panel for Telegram OSINT and analytics.** It collects every commenter of a channel,
indexes group and forum history, and offers full-text search over messages, audience overlaps, a relationship
graph, and discovery of the channels and chats owned by the people in your database.

[![CI](https://github.com/antalkon/telegram-tools/actions/workflows/ci.yml/badge.svg)](https://github.com/antalkon/telegram-tools/actions/workflows/ci.yml)
[![Docker image](https://img.shields.io/badge/ghcr.io-antalkon%2Ftelegram--tools-2AABEE?logo=docker&logoColor=white)](https://github.com/antalkon/telegram-tools/pkgs/container/telegram-tools)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

[Русский](README.ru.md)

</div>

---

TG Toolkit talks to Telegram over **MTProto** ([Telethon](https://github.com/LonamiWebs/Telethon)) as a regular
user account, because the Bot API cannot read the history of other people's channels. Everything stays on your
machine: one container and one SQLite file, with no cloud services. The UI is in Russian.

## Features

- **Channel commenter collector.** Give it a channel link and it lists everyone who ever commented on its posts:
  avatar, name, @username, ID, Premium/bot/deleted flags, comment and post counts, first and last comment.
- **Chat indexer.** Works with groups, supergroups, forums and discussion chats. It stores the full history,
  or messages since a date, or the last N messages, with authors, replies and topics, plus the member list
  when it is visible.
- **People's channels.** Finds the channels and chats of the people in your database, then indexes any of them
  in one click. It looks at:
  - the personal channel pinned to the profile;
  - links in the bio (`t.me/…`, invites, `name.t.me`, `tg://`);
  - `@mentions` in the bio, where only channels and chats are kept;
  - the channels people post as.
- **Sources** gathers channels and chats in one list. You can:
  - fetch only what is new since the last run;
  - re-index with different options;
  - monitor on a schedule, with notifications in the panel and in Telegram.
- **Full-text search** (SQLite FTS5) with phrases, exclusions, filters, context and top authors.
  It also finds people by their profile metadata and by the text of PDFs attached to them.
- **Profile metadata and documents.** Add a full name, email, phone, country, city, address and passport
  number to anyone in the database by hand, and attach PDF files. All of it is searchable.
- **Analytics:**
  - user dossiers with an activity heatmap, a relationship graph and a suspicion score;
  - per-channel dynamics;
  - an audience-overlap matrix;
  - an interactive people ↔ channels graph.
- **Export** to XLSX, CSV and JSON.
- **HTTP API and MCP server.** Every panel feature is in the HTTP API, documented with
  [Scalar](https://scalar.com) at `/api/docs` (OpenAPI 3.1). AI agents such as Claude Code, Claude Desktop and
  Cursor connect to the built-in MCP server at `/mcp`. Both use API tokens from the settings page, read-only
  or full access.
- **Rate-limit aware:**
  - FloodWait countdowns, after which the job resumes where it stopped;
  - a ban on one request method is parked while the other methods keep running;
  - caching.
- **Secure by default:**
  - Telegram sessions are stored encrypted;
  - the panel is password-protected, with a JWT in an httpOnly cookie;
  - the container runs as a non-root user and has a healthcheck;
  - the image is built for amd64 and arm64.

## Quick start

```bash
git clone https://github.com/antalkon/telegram-tools.git && cd telegram-tools
cp .env.example .env    # set TGT_ADMIN_PASSWORD and TGT_SECRET_KEY
docker compose up -d    # http://127.0.0.1:8000
```

You can also run the image directly:

```bash
docker run -d --name tg-toolkit -p 127.0.0.1:8000:8000 -v tgt-data:/data \
  -e TGT_ADMIN_PASSWORD='password' -e TGT_SECRET_KEY='long-random-string' \
  ghcr.io/antalkon/telegram-tools:latest
```

Then connect a Telegram account in **Аккаунты → Добавить** (Accounts → Add). You will need the `api_id` and
`api_hash` from [my.telegram.org/apps](https://my.telegram.org/apps), then your phone number, the login code
and your 2FA password if you have one.

The image `ghcr.io/antalkon/telegram-tools:latest` is rebuilt by GitHub Actions on every push to `main`,
after the tests pass. Version tags `vX.Y.Z` also publish the `X.Y.Z` and `X.Y` tags.

## Documentation (Russian)

- [Deployment](docs/deployment.md): Docker, HTTPS reverse proxy, backups, updates, CI/CD
- [Configuration](docs/configuration.md): `TGT_*` environment variables
- [How it works](docs/how-it-works.md): Telegram internals, rate limits
- [API and MCP](docs/api-and-mcp.md): tokens, HTTP API, connecting AI agents, the MCP tool list
- [Development](docs/development.md): local setup, tests, demo data, adding a tool

## Responsible use

The panel only sees what the connected account can see. Follow the
[Telegram API Terms of Service](https://core.telegram.org/api/terms) and your local data-protection laws.
Do not use it for spam, harassment or stalking.

## License

[MIT](LICENSE)
