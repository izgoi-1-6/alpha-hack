# Сторонние компоненты

Перечень библиотек, образов, данных и сервисов, на которые опирается «Кредитный маршрут». Версии зафиксированы: `backend/requirements.lock` и `frontend/package-lock.json`. Лицензии библиотек прочитаны из метаданных установленных пакетов: `importlib.metadata` в `backend/.venv` и `package.json` в `frontend/node_modules`. Тексты лицензий входят в сами пакеты.

## Бэкенд: прямые зависимости (`backend/requirements.txt`)

| Пакет | Версия | Лицензия | Для чего |
|---|---|---|---|
| fastapi | 0.115.12 | MIT | HTTP API |
| uvicorn | 0.34.2 | BSD-3-Clause | ASGI-сервер |
| SQLAlchemy | 2.0.41 | MIT | ORM и доступ к БД |
| alembic | 1.16.1 | MIT | Миграции схемы |
| psycopg[binary] (psycopg, psycopg-binary) | 3.2.9 | LGPL-3.0 (GNU Lesser General Public License v3) | Драйвер PostgreSQL; подключается как библиотека, без изменений |
| argon2-cffi | 23.1.0 | MIT | Хеширование паролей (Argon2id) |
| python-multipart | 0.0.32 | Apache-2.0 | Разбор multipart при загрузке файлов |
| Pillow | 13.0.0 | MIT-CMU | Проверка структуры JPEG и PNG |
| pypdf | 6.21.2 | BSD-3-Clause | Проверка структуры PDF |
| httpx | 0.28.1 | BSD-3-Clause | HTTP-клиент тестов (TestClient) |
| pytest | 8.4.2 | MIT | Тесты бэкенда |

## Бэкенд: транзитивные зависимости (`backend/requirements.lock`)

| Пакет | Версия | Лицензия |
|---|---|---|
| annotated-types | 0.8.0 | MIT |
| anyio | 4.15.1 | MIT |
| argon2-cffi-bindings | 26.1.0 | MIT |
| certifi | 2026.10.23 | MPL-2.0 |
| cffi | 2.1.1 | MIT-0 |
| click | 8.5.0 | BSD-3-Clause |
| h11 | 0.16.0 | MIT |
| httpcore | 1.0.9 | BSD-3-Clause |
| idna | 3.20 | BSD-3-Clause |
| iniconfig | 2.3.1 | MIT |
| Mako | 1.4.3 | MIT |
| MarkupSafe | 3.0.4 | BSD-3-Clause |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause |
| pluggy | 1.7.0 | MIT |
| pycparser | 3.12 | BSD-3-Clause |
| pydantic | 2.14.1 | MIT |
| pydantic_core | 2.50.1 | MIT |
| Pygments | 2.21.0 | BSD-2-Clause |
| starlette | 0.46.2 | BSD-3-Clause |
| typing-inspection | 0.4.4 | MIT |
| typing_extensions | 4.16.0 | PSF-2.0 |

## Фронтенд (`frontend/package.json`)

| Пакет | Версия | Лицензия | Для чего |
|---|---|---|---|
| react | 18.3.1 | MIT | Интерфейс |
| react-dom | 18.3.1 | MIT | Интерфейс |
| vite | 7.3.7 | MIT | Сборка и dev-сервер (dev) |
| typescript | 5.9.3 | Apache-2.0 | Проверка типов (dev) |
| @playwright/test | 1.56.1 | Apache-2.0 | Браузерные тесты (dev) |
| @types/react | 18.3.24 | MIT | Типы (dev) |
| @types/react-dom | 18.3.7 | MIT | Типы (dev) |

В сборку для браузера попадают только react, react-dom и их зависимости: scheduler 0.23.2, loose-envify 1.4.0 и js-tokens 4.0.0, все под MIT. Всего в `frontend/node_modules` на macOS (arm64) установлено 28 пакетов; на Linux состав платформенных пакетов другой, лицензии те же:

- 22 — MIT;
- 4 — Apache-2.0: typescript, @playwright/test, playwright, playwright-core;
- 1 — ISC: picocolors;
- 1 — BSD-3-Clause: source-map-js.

Остальные записи `package-lock.json` — пакеты под другие платформы, они не устанавливаются. Шрифты — системные. Иконки нарисованы в коде (`frontend/src/components.tsx`), сторонних наборов иконок и изображений нет.

## Базовые образы Docker

| Образ | Где | Лицензия основного ПО |
|---|---|---|
| `postgres:17.6-alpine` | `compose.yaml`, сервис `db` | PostgreSQL License (по данным проекта PostgreSQL; файла лицензии в образе нет) |
| `python:3.12.11-alpine` | `backend/Dockerfile` | PSF License 2.0 (`/usr/local/lib/python3.12/LICENSE.txt` в образе) |
| `node:24.8.0-alpine` | `frontend/Dockerfile`, только этап сборки | MIT (лицензия Node.js) |
| `nginx:1.27.5-alpine` | `frontend/Dockerfile`, раздача интерфейса | 2-clause BSD-like (метаданные пакета `nginx-1.27.5-r1` в образе) |

Образы основаны на Alpine Linux, системные пакеты которого распространяются под своими лицензиями.

## Модели

Обученных моделей нет. Скоринг — явные правила и баллы из аналитического ноутбука `scoring/alfa_scoring_simple.ipynb`, перенесённые в `backend/app/applications/scoring.py`. Описание — в [docs/products-and-scoring.md](docs/products-and-scoring.md).

## Данные и источники

- **Компании, учётные записи и ответы источников — синтетические** (`data/demo-companies.json`):
  - ИНН с правильной контрольной суммой, но сгенерированные; не утверждается, что эти номера никому не принадлежат;
  - названия, адреса и ФИО придуманы, реальных персональных данных нет.
- **Факты каталога** (`data/credit_catalog.json`) собраны с публичных страниц. Ссылка и дата сверки есть у каждого элемента в поле `source`:
  - Альфа-Банк: https://alfabank.ru/sme/profits/businesscredit/ (пять собственных кредитов и линий), https://alfabank.ru/sme/profits/goscredit/, https://alfabank.ru/sme/profits/ukl/, https://alfabank.ru/sme/profits/factoring/;
  - Корпорация МСП: https://corpmsp.ru/to-business/finansirovanie-lgotnye-programmy-kreditovaniya/psk_subsidizing/, https://corpmsp.ru/to-business/finansirovanie-lgotnye-programmy-kreditovaniya/psk_current/, https://corpmsp.ru/to-business/finansirovanie-lgotnye-programmy-kreditovaniya/borderline/, https://corpmsp.ru/to-business/obespechenie-kreditov-zaymov/zontichnye-poruchitelstva/.

  Это сведения исследования, а не проверенная политика банка.
- **Ключевая ставка Банка России** — 14 % с 2026-10-23, источник https://www.cbr.ru/press/keypr/ (`params.key_rate` каталога). От неё считаются ставки программ ПСК.
- **Продуктовое исследование** (`docs/research/`) ссылается на свои источники внутри документа.

## Заглушки вместо внешних сервисов

Ни один внешний сервис не вызывается. Вместо них работают локальные заглушки на синтетических данных:

| Сервис | Заглушка |
|---|---|
| Реестр (ЕГРЮЛ/ЕГРИП, реестр МСП, ФНС и открытые источники) и обороты | Данные компании из `data/demo-companies.json`; сбои и восстановление заданы в фикстуре |
| Бюро кредитных историй | `backend/app/applications/bki.py`: кредитная история и просрочка из фикстуры |
| Госуслуги / ЕСИА | `backend/app/authority.py`: всегда подтверждает директора из фикстуры |
| Уведомления | Записи в кабинете (канал `demo_in_app`); SMS и почта не отправляются |
| Проверка документов | Структурная проверка формата (pypdf, Pillow); содержание проверяет специалист |
| Альфа-Бизнес | Локальная страница `/alfa-business/{id}`: деньги не перечисляются, договор не подписывается |

## Товарные знаки

Названия «Альфа-Банк», «Альфа-Бизнес», «Корпорация МСП», «Госуслуги», «ЕСИА» и «Банк России» упоминаются только для описания. Логотипы и фирменная графика этих организаций в приложении не используются.
