# Лабораторна робота 4. Безперервна інтеграція

[Wishlist API](https://github.com/w1xes/wishlist-api) · [Wishlist UI](https://github.com/w1xes/wishlist-ui)

Wishlist — невеликий застосунок зі списком бажань. API на FastAPI зберігає записи в Postgres і перевіряє Redis, а UI на Vue 3 показує список, додає й видаляє бажання. Робота присвячена конвеєру GitHub Actions, який не дає злити в `main` код із червоними перевірками.

## Мій внесок

Роботу виконано індивідуально, тому весь код і налаштування мої.

- **Wishlist API.** Написав застосунок: збереження в Postgres, ендпоінти `/health` і `/ready` та тести, серед яких перевірка запису й читання в Postgres. Налаштував [CI](https://github.com/w1xes/wishlist-api/blob/main/.github/workflows/ci.yml): Ruff, pytest із Postgres і Redis як сервісами з перевіркою готовності, матриця Python 3.12 і 3.13, кеш залежностей, звіт покриття. Код і конвеєр потрапили в `main` комітами [6e38b1b](https://github.com/w1xes/wishlist-api/commit/6e38b1b) і [7aa43a2](https://github.com/w1xes/wishlist-api/commit/7aa43a2), до увімкнення ruleset.
- **Wishlist UI.** Написав інтерфейс: завантаження, додавання й видалення бажань. Налаштував [CI](https://github.com/w1xes/wishlist-ui/blob/main/.github/workflows/ci.yml): ESLint, `vue-tsc`, збірка з публікацією артефакту. Код і конвеєр потрапили в `main` комітом [e1097ff](https://github.com/w1xes/wishlist-ui/commit/e1097ff).
- **Нічні аудити.** У кожному репозиторії окремий workflow: `pip-audit` для API і `npm audit` для UI. Вони не входять до обов’язкових перевірок і не блокують pull request’и.
- **Захист `main`.** Увімкнув ruleset в обох репозиторіях: обов’язковий PR, обов’язкові перевірки статусу, актуальна гілка, скидання застарілих схвалень, заборона force-push і видалення, без винятків для адміністратора.
- **Доказ блокування.** Pull request №1 в кожному репозиторії навмисно ламає код: в API падає тест `/health`, в UI ESLint знаходить невикористану змінну. GitHub блокує злиття, а після виправлення в тому самому PR дозволяє його. Ці PR демонстраційні і не містять застосунку: [PR Wishlist API](https://github.com/w1xes/wishlist-api/pull/1) · [PR Wishlist UI](https://github.com/w1xes/wishlist-ui/pull/1). Скриншоти, журнали й вимірювання кешу лежать у `docs/checks.md` кожного репозиторію: [API](https://github.com/w1xes/wishlist-api/blob/main/docs/checks.md) · [UI](https://github.com/w1xes/wishlist-ui/blob/main/docs/checks.md).

## Локальний запуск

Потрібні Git і запущений Docker Desktop (або Docker Engine) з Docker Compose v2, бо команди використовують `--wait`. Порти `8000` (API) і `5174` (UI) мають бути вільними. Якщо вони зайняті, задайте `API_PORT` і `UI_PORT` у `.env`. Для першого запуску потрібен інтернет: Docker завантажує образи, а контейнери встановлюють залежності. Виконайте команди в PowerShell із каталогу, де мають з’явитися обидва репозиторії.

```powershell
git clone https://github.com/w1xes/wishlist-api.git
git clone https://github.com/w1xes/wishlist-ui.git

Set-Location wishlist-api
Copy-Item .env.example .env
docker compose up -d --wait --wait-timeout 150

Set-Location ../wishlist-ui
Copy-Item .env.example .env
docker compose up -d --wait --wait-timeout 150
```

У Linux або macOS замініть `Set-Location` на `cd`, а `Copy-Item` на `cp`.

Compose запускає Postgres, Redis і FastAPI у першому проєкті та Vite у другому. `.env.example` задає приклад локальної конфігурації. Рядок `POSTGRES_PASSWORD` можна замінити власним локальним паролем до першого запуску. Після першого запуску пароль у наявній базі змінить лише `docker compose down -v`, який видаляє дані.

- Відкрийте [UI](http://127.0.0.1:5174), введіть `Настільна лампа` і натисніть **Додати**. Оновіть сторінку й переконайтеся, що запис знову завантажився. Кнопка **Видалити** прибирає його зі списку та з бази. Відкривайте саме `127.0.0.1`, а не `localhost`: API дозволяє запити лише з цієї адреси.
- Відкрийте [Swagger](http://127.0.0.1:8000/docs) і виконайте `GET /items`. Запит повертає поточний вміст таблиці Postgres. [Перевірка готовності](http://127.0.0.1:8000/ready) повертає статус обох сервісів.

Зупиніть застосунки з каталогу `wishlist-ui`. Дані Postgres залишаться в Docker volume.

```powershell
docker compose down
Set-Location ../wishlist-api
docker compose down
```
