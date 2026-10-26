# API

FastAPI, SQLAlchemy 2, Alembic, PostgreSQL 17. Устройство модулей описано в [архитектуре](../docs/architecture.md), схема данных — в [модели данных](../docs/data-model.md), правила — в [продуктах и скоринге](../docs/products-and-scoring.md) и [состояниях заявки](../docs/application-states.md).

Команды выполняются из корня репозитория:

```sh
backend/.venv/bin/alembic -c backend/alembic.ini upgrade head   # миграции
./scripts/run-api.sh                                            # API на http://127.0.0.1:8000
```

Описание API — `docs/api/openapi.yaml`; интерактивная версия — http://127.0.0.1:8000/docs. После изменения маршрутов выгрузите описание заново: `backend/.venv/bin/python scripts/export-api-docs.py`. Команды POST, PATCH и DELETE требуют заголовок `Origin: http://localhost:5173`, в том числе из скриптов и тестов.

Тесты запускаются из этого каталога командой `.venv/bin/pytest`. Без `TEST_DATABASE_URL` каждый тест работает на изолированной SQLite в памяти. С `TEST_DATABASE_URL`, указывающей на одноразовую базу PostgreSQL с именем на `_test`, выполняются и тесты гонок. Внешние сервисы не вызываются. Подробнее — в [тестовых сценариях](../docs/tests/test-scenarios.md).
