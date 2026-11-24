# Лабораторна робота 5. Контейнеризація

[Wishlist API](https://github.com/w1xes/wishlist-api) · [Wishlist UI](https://github.com/w1xes/wishlist-ui) · Реліз `v1.0.0`: [API](https://github.com/w1xes/wishlist-api/releases/tag/v1.0.0), [UI](https://github.com/w1xes/wishlist-ui/releases/tag/v1.0.0) · Пакети GHCR: [wishlist-api](https://github.com/w1xes/wishlist-api/pkgs/container/wishlist-api), [wishlist-ui](https://github.com/w1xes/wishlist-ui/pkgs/container/wishlist-ui)

Wishlist — застосунок зі списком бажань: API на FastAPI зберігає записи в Postgres і перевіряє Redis, UI на Vue 3 показує список і додає та видаляє бажання. У цій роботі обидва застосунки запаковано в образи, стек піднімається однією командою, а CI збирає образи й публікує їх у GitHub Container Registry. Подробиці, перевірки й виводи команд лежать у `docs/containers.md`: [API](https://github.com/w1xes/wishlist-api/blob/main/docs/containers.md) · [UI](https://github.com/w1xes/wishlist-ui/blob/main/docs/containers.md).

## Мій внесок

Роботу виконано індивідуально, тому весь код і налаштування мої.

- **Образ API.** Написав `Dockerfile` і `.dockerignore`: `python:3.12-slim`, залежності окремим шаром до коду, процес від користувача `app`, `CMD` у exec-формі, конфігурація лише змінними середовища. API тепер сам створює таблиці під час старту. Список дозволених origin для CORS у змінній `UI_ORIGIN` тепер може містити кілька адрес через кому. [PR Wishlist API №2](https://github.com/w1xes/wishlist-api/pull/2)
- **Образ UI.** Написав multi-stage `Dockerfile` (етап `build` на Node, фінальний nginx лише з `dist/`) і конфігурацію nginx, яка віддає `index.html` на будь-який маршрут. Змінну `VITE_API_URL` перейменував на `VITE_API_BASE` і передаю її через `ARG` під час збирання. [PR Wishlist UI №2](https://github.com/w1xes/wishlist-ui/pull/2)
- **Стек у Compose.** `compose.yaml` в `wishlist-api` піднімає Postgres, Redis, API і UI. Є healthcheck'и та порядок запуску, іменований том, обов'язковий пароль без значення за замовчуванням, порти лише для API й UI, політики перезапуску. Додав профіль `dev` з `develop.watch`. [PR Wishlist API №2](https://github.com/w1xes/wishlist-api/pull/2)
- **CI.** У `ci.yml` обох репозиторіїв з'явилися job'и `API image` і `UI image`: у pull request образ збирається без публікації, на push у `main` публікується з тегами `sha-<коміт>` і `main`, на тег `v*` з тегами `1.0.0`, `1.0`, `1` і `latest` для `linux/amd64` та `linux/arm64`. Окремі job'и `API image scan` і `UI image scan` запускають Trivy й не блокують pull request'и. Job'и `API image` і `UI image` додав в обов'язкові перевірки `main` в обох репозиторіях.
- **Реліз і докази.** Створив релізи `v1.0.0`, перевірив `docker pull` без входу в реєстр, зробив скриншоти пакетів, зібрав виводи `docker buildx imagetools inspect` і висновки зі звітів Trivy, провів діагностику трьох навмисних поломок за чеклистом. [PR Wishlist API №3](https://github.com/w1xes/wishlist-api/pull/3) · [PR Wishlist UI №3](https://github.com/w1xes/wishlist-ui/pull/3)

## Запуск стеку

Потрібні Git, Docker і Docker Compose v2 (команди використовують `--wait`). Для першого запуску потрібен інтернет, бо Docker завантажує базові образи, а Compose бере код UI з публічного репозиторію `wishlist-ui` (гілка `main`). Порти `8000` (API) і `8081` (UI) мають бути вільними, а інакше змініть `API_PORT` і `UI_PORT` у `.env`. Команди нижче для PowerShell.

```powershell
git clone https://github.com/w1xes/wishlist-api.git
Set-Location wishlist-api
Copy-Item .env.example .env
```

Відкрийте `.env` і впишіть власний пароль після `POSTGRES_PASSWORD=`, наприклад `POSTGRES_PASSWORD=мій-пароль-для-бази`. Решту змінних залишіть як є. Поки пароль порожній, Compose відмовляється стартувати з повідомленням `POSTGRES_PASSWORD is not set`.

```powershell
docker compose up -d --build --wait
```

Команда збирає образи API й UI та чекає, доки всі чотири сервіси мають статус `healthy`. Перший запуск може тривати кілька хвилин.

- Відкрийте [UI](http://localhost:8081), введіть `Настільна лампа` і натисніть **Додати**. Оновіть сторінку: запис знову завантажиться з API. Відкривайте `localhost:8081` або `127.0.0.1:8081`: лише ці дві адреси дозволені в CORS.
- Відкрийте [Swagger](http://localhost:8000/docs) і виконайте `GET /items`: запит повертає вміст таблиці Postgres. [Перевірка готовності](http://localhost:8000/ready) показує стан Postgres і Redis.
- `docker compose ps` показує стан сервісів. Назовні опубліковані лише UI та API, Postgres і Redis доступні тільки всередині мережі Compose.

Дані лежать в іменованому томі. Після `docker compose down` записи залишаються, після `docker compose down -v` том видаляється і база створюється наново порожньою.

```powershell
docker compose down      # зупинити, дані залишаються
docker compose down -v   # зупинити й видалити дані Postgres
```

### Готові образи з реєстру

Опубліковані образи завантажуються без входу в GHCR:

```powershell
docker pull ghcr.io/w1xes/wishlist-api:1.0.0
docker pull ghcr.io/w1xes/wishlist-ui:1.0.0
```

Образ UI зібрано з адресою API `http://localhost:8000`, тому він працює з API на цьому самому хості. Для іншої адреси образ UI треба зібрати з іншим `--build-arg VITE_API_BASE=...`.

### Якщо щось не запустилося

- `docker compose up` пише `required variable POSTGRES_PASSWORD is missing a value`: у `.env` не вписано пароль.
- Помилка `port is already allocated`: порт 8000 або 8081 зайнятий. Змініть `API_PORT` чи `UI_PORT` у `.env`. Якщо змінюєте їх, `VITE_API_BASE` і `UI_ORIGIN` підлаштовуються автоматично, але образ UI треба перезібрати (`docker compose up -d --build`).
- Змінили `POSTGRES_PASSWORD` після першого запуску: Postgres застосовує пароль лише при створенні тому, тому виконайте `docker compose down -v` і запустіть заново.
