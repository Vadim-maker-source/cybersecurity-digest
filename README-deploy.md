# Развёртывание

Адрес: https://94.232.42.94:6752/. Каталог: /opt/cybersecurity-digest. Отдельный compose project cyber-digest. Чужие контейнеры не изменяются.

Нужны Docker/Compose, свободные TCP 80 и 6752 и закрытый .env с правами 600. TCP 80 обслуживает ACME и перенаправление на HTTPS. PostgreSQL и API наружу не опубликованы.

Запуск: `bash infra/scripts/deploy.sh --owner-authorized`. Скрипт получает IP-сертификат, собирает и запускает сервисы, проверяет HTTPS и PostgreSQL. Занятые чужими сервисами порты не освобождает.

Let's Encrypt выпускает шестидневные сертификаты IP ([документация](https://letsencrypt.org/2026/03/11/shorter-certs-certbot)). Сертификаты хранятся в игнорируемом shared/letsencrypt. Обновление: `bash infra/scripts/renew-certificate.sh`. На сервере требуется systemd timer дважды в сутки с reload только Nginx данного проекта.

При повторном развёртывании скрипт сохраняет backup базы в work/backups. Перед обновлением сохраните commit и образы. Не публикуйте dumps и не используйте down -v. Не выполняйте destructive rollback без проверки совместимости миграций.

Проверки: `docker compose -p cyber-digest -f compose.yml -f compose.server.yml ps` и `curl --fail https://94.232.42.94:6752/api/v1/health/ready`. Проверить также вход, GigaChat, реальный сбор, выпуск и экспорт. SMTP авторизация и доставка письма — разные проверки. Автоматическая отправка по умолчанию выключена.
