# Безопасность

Нашли уязвимость? Не публикуйте её в открытом issue. Сообщите через
[GitHub Security Advisories](https://github.com/antalkon/telegram-tools/security/advisories/new).

Рекомендации по эксплуатации:

- Задайте сложный `TGT_ADMIN_PASSWORD` и случайный `TGT_SECRET_KEY` (см. [docs/configuration.md](docs/configuration.md)).
- Не выставляйте порт 8000 в интернет напрямую. Используйте reverse proxy с HTTPS и `TGT_COOKIE_SECURE=true`.
- Том `/data` содержит зашифрованные сессии Telegram и собранные данные. Храните бэкапы так же бережно.
- Для сбора используйте отдельный аккаунт Telegram.
