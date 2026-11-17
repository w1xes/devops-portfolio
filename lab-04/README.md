# Лабораторна робота 4. Безперервна інтеграція

[Wishlist API](https://github.com/w1xes/wishlist-api) · [Wishlist UI](https://github.com/w1xes/wishlist-ui)

## Мій внесок

Підготував індивідуальний проєкт списку бажань. У Wishlist API реалізував збереження даних у Postgres, перевірку готовності Postgres і Redis, інтеграційні тести та CI з Ruff, pytest, матрицею Python і звітами покриття. У Wishlist UI реалізував завантаження, додавання та видалення бажань, а в CI налаштував ESLint, `vue-tsc` і публікацію збірки. Для обох репозиторіїв налаштував окремі нічні аудити залежностей.

Увімкнув обов’язкові перевірки для `main` і перевірив їх у двох демонстраційних PR. В API невдалий тест `/health` заблокував злиття, а в UI його заблокувала помилка ESLint. Після виправлень GitHub дозволив злиття в тих самих PR. [PR Wishlist API](https://github.com/w1xes/wishlist-api/pull/1) · [PR Wishlist UI](https://github.com/w1xes/wishlist-ui/pull/1)

## Локальний запуск

Потрібні Git і запущений Docker Desktop із підтримкою Linux-контейнерів. Виконайте команди в PowerShell із каталогу, де мають з’явитися обидва репозиторії.

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

Compose запускає Postgres, Redis і FastAPI у першому проєкті та Vite у другому. `.env.example` задає приклад локальної конфігурації. Рядок `POSTGRES_PASSWORD` можна замінити власним локальним паролем до першого запуску.

- Відкрийте [UI](http://127.0.0.1:5174), введіть `Настільна лампа` і натисніть **Додати**. Оновіть сторінку й переконайтеся, що запис знову завантажився. Кнопка **Видалити** прибирає його зі списку та з бази.
- Відкрийте [Swagger](http://127.0.0.1:8000/docs) і виконайте `GET /items`. Запит повертає поточний вміст таблиці Postgres. [Перевірка готовності](http://127.0.0.1:8000/ready) повертає статус обох сервісів.

Зупиніть застосунки з каталогу `wishlist-ui`. Дані Postgres залишаться в Docker volume.

```powershell
docker compose down
Set-Location ../wishlist-api
docker compose down
```
