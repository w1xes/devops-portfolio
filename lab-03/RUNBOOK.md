# Робоча інструкція запуску та демонстрації лабораторної 3

Команди нижче призначені для **Bash у Linux** та виконуються з кореня
репозиторію. Це набір CLI-утиліт, а не вебзастосунок: загального сервера,
`npm start` або Docker Compose тут немає. Постійно працюють лише Telegram-бот
і, якщо потрібний розклад, Supercronic.

## 1. Що було пропущено в попередній інструкції

- `/workspace/devops-portfolio` — шлях іншого середовища. У цьому середовищі
  репозиторій розташований у `/home/w1xes/chnu/devops/devops-portfolio`.
- `source lab-03/activate.sh` **не встановлює залежності**, а лише налаштовує
  `PATH`, `GOPATH`, `GOCACHE` та суворий режим Bash (`set -euo pipefail`).
  На свіжому clone спочатку потрібний `dev-setup.sh`.
- До встановлення залежностей `check.sh` зупинявся з
  `shellcheck: command not found`. Три тести хуків також падали через відсутні
  Ruff/ShellCheck. Go, Supercronic і готового organizer у свіжому clone не було.
- `--test-message` надсилає одне повідомлення й завершується.
  Для відповідей на `/status` та інші команди треба **окремо запустити бота**.
- Одного `TELEGRAM_CHAT_ID` недостатньо: потрібний власний секрет
  `TELEGRAM_BOT_TOKEN`. ID з чужого прикладу не є вашим ID.
- `MONITOR_LOG` використовує системний `monitor.sh`; Python-монітор API та бот
  пишуть у `TOOLKIT_LOG`. Це різні журнали.
- `core.hooksPath` не переноситься через Git clone: його треба налаштувати.
- Файла `/workspace/lab-03-demonstration.md` у репозиторії немає.
  Нижче наведено самодостатній сценарій інциденту та розкладу.

## 2. Одноразова підготовка

Відкрийте термінал Bash у VS Code:

```bash
cd /home/w1xes/chnu/devops/devops-portfolio
pwd
python3 --version
./lab-03/dev-setup.sh
source lab-03/activate.sh

command -v python3 go ruff shellcheck supercronic
go version
./lab-03/check.sh
file lab-03/bin/organizer
```

Для іншого комп'ютера замініть тільки шлях у `cd` на шлях до свого clone.
Потрібні Python 3.12+, Bash 4+, `python3-venv`, `curl`, CA-сертифікати,
OpenSSL, GNU tar/coreutils, util-linux (`flock`), procps та `make`.
Встановлення завантажує інструменти з інтернету.

Якщо в Debian/Ubuntu відсутні системні пакети, встановіть їх і повторіть
підготовку (лише на машині, де маєте право встановлювати пакети):

```bash
sudo apt-get update
sudo apt-get install -y python3 python3-venv curl ca-certificates \
  openssl tar gzip coreutils util-linux procps make file
```

Якщо системний Python старіший за 3.12, спочатку встановіть підтримуваний
Python засобами свого дистрибутива.

`dev-setup.sh` створює локальну `.venv`, встановлює пакети з
`requirements-dev.txt`, Go 1.27.3 із перевіркою SHA-256 та Supercronic v0.2.34.
Підтримувані платформи bootstrap: Linux x86-64 та ARM64.
Він не запускає бота, не встановлює хуки й не створює розклад.

**Очікуваний результат `check.sh`:** успішні ShellCheck, Ruff, gofmt,
`go vet`, **54 Python-тести та 3 Go-тести**, після чого створюється
`lab-03/bin/organizer`. `file` має показати `statically linked`.
Загальна перевірка не потребує справжнього токена Telegram.

У **кожному новому терміналі** повторюйте:

```bash
cd /home/w1xes/chnu/devops/devops-portfolio
source lab-03/activate.sh
```

Після `source` діє `-e`: очікувані ненульові коди демонстрацій треба
обробляти через `if` або `||`, як у прикладах нижче, інакше shell може завершитися.

## 3. Окрема тека для демонстрації

У головному терміналі:

```bash
DEMO_DIR=$(mktemp -d /tmp/lab03-demo.XXXXXX)
export DEMO_DIR
mkdir -p "$DEMO_DIR/my project" "$DEMO_DIR/backups"
printf 'Hello from backup demo\n' > "$DEMO_DIR/my project/hello.txt"

export BACKUP_LOG="$DEMO_DIR/backup.log"
export MONITOR_LOG="$DEMO_DIR/monitor.log"
export ORGANIZER_LOG="$DEMO_DIR/organizer.log"
export TOOLKIT_LOG="$DEMO_DIR/toolkit.jsonl"
printf 'Демонстраційна тека: %s\n' "$DEMO_DIR"
```

Цей блок потрібний лише раз на демонстрацію. Усі команди з `$DEMO_DIR`
виконуйте в цьому самому терміналі: нова вкладка не успадкує його змінні.
За потреби в іншій вкладці задайте `export DEMO_DIR=...`, скопіювавши
надрукований шлях, і повторіть визначення журналів.

## 4. Резервне копіювання

```bash
./lab-03/backup.sh --help
printf 'Do not delete\n' > "$DEMO_DIR/backups/foreign.txt"

for i in {1..6}; do
  ./lab-03/backup.sh \
    --source "$DEMO_DIR/my project" \
    --dest "$DEMO_DIR/backups" \
    --keep 3
done

find "$DEMO_DIR/backups" -name '*.tar.gz' -type f | sort
find "$DEMO_DIR/backups" -name '*.tar.gz' -type f | wc -l
```

Очікується **3 архіви**. Шлях із пробілом працює завдяки лапкам.
Перевірка dry-run, незмінності вмісту та стороннього файла:

```bash
find "$DEMO_DIR/backups" -type f -exec sha256sum {} + | sort > "$DEMO_DIR/before.sha256"

./lab-03/backup.sh \
  --source "$DEMO_DIR/my project" \
  --dest "$DEMO_DIR/backups" --keep 1 --dry-run

find "$DEMO_DIR/backups" -type f -exec sha256sum {} + | sort > "$DEMO_DIR/after.sha256"
diff -u "$DEMO_DIR/before.sha256" "$DEMO_DIR/after.sha256"
find "$DEMO_DIR/backups" -name '*.tar.gz' -type f | wc -l
cat "$DEMO_DIR/backups/foreign.txt"

./lab-03/backup.sh \
  --source "$DEMO_DIR/missing" --dest "$DEMO_DIR/backups" \
  || printf 'Код помилки: %s (очікується 3)\n' "$?"
tail -n 6 "$BACKUP_LOG"
```

Очікується: `diff` нічого не друкує, залишаються 3 архіви та `foreign.txt`;
неіснуюче джерело повертає **3**, без traceback.
Dry-run не створює навіть запису у файл журналу.

Hash канонічного шляху розділяє джерела з однаковою назвою; UTC-мітки
дозволяють сортувати архіви. Новий архів спочатку створюється як тимчасовий,
і лише після успіху `tar` публікується перейменуванням. Ротація видаляє тільки
архіви цього джерела. `-e`, `-u`, `pipefail` виявляють відповідно необроблені
помилки команд, невстановлені змінні та помилки всередині конвеєрів.

## 5. Монітор API без Telegram

```bash
cat lab-03/config/api.json
python3 lab-03/api_monitor.py \
  --config lab-03/config/api.json \
  --output "$DEMO_DIR/api.json" --no-notify \
  || printf 'Код перевірки: %s\n' "$?"
python3 -m json.tool "$DEMO_DIR/api.json"

python3 lab-03/demo_api.py --output-dir "$DEMO_DIR/four-failures"
python3 -m json.tool "$DEMO_DIR/four-failures/results.json"
```

Поля цілі: `url` — адреса, `expected_status` — очікуваний HTTP-код,
`timeout` — секунди, `threshold_ms` — поріг тривалості відповіді в мілісекундах.

Публічний GitHub залежить від мережі: ненульовий код перевірки не обов'язково
означає помилку запуску. Дивіться `failure_type` у JSON.
Батьківська тека `--output` повинна існувати.

`demo_api.py` сам запускає й зупиняє локальні HTTP/TLS-сервери та перевіряє
чотири типи збоїв:

| `failure_type` | Причина | `attempts` |
|---|---|---|
| `dns` | Ім'я `.invalid` не розв'язується | 2 |
| `connection_refused` | TCP-порт не приймає з'єднання | 2 |
| `certificate` | Прострочений тестовий TLS-сертифікат | 2 |
| `unexpected_status` | Сервер повернув 418 замість 200 | 1 |

Успішний демонстратор завершується **0**, хоча всі його цілі нездорові.
Він обходить HTTP-проксі для цілей і потребує OpenSSL та працездатного
локального DNS-резолвера; доступ до публічних тестових API не потрібний.

## 6. Telegram: спочатку секрети, потім постійний процес

Використовуйте **свого** бота, створеного через [@BotFather](https://t.me/BotFather).
Не записуйте токен у Git, у текст команд або в чат з асистентом.
Введення нижче приховане й не зберігає сам токен в історії команд:

```bash
read -rsp 'Telegram bot token: ' TELEGRAM_BOT_TOKEN
printf '\n'
export TELEGRAM_BOT_TOKEN
python3 lab-03/telegram_bot.py --discover-chat
```

Після запуску discovery надішліть **новий `/start`** своєму боту у приватному
чаті. Команда покаже кандидата `TELEGRAM_CHAT_ID` і завершиться.
Перевірте, що це ваш чат, потім введіть його ID:

```bash
read -rp 'Ваш Telegram chat ID: ' TELEGRAM_CHAT_ID
export TELEGRAM_CHAT_ID
python3 lab-03/telegram_bot.py --test-message

python3 lab-03/telegram_bot.py \
  --config lab-03/config/api.json --interval 60
```

**Остання команда залишається працювати в терміналі.** Лише тепер бот
відповідатиме на команди. Зупинка — Ctrl+C; це не вебсервер, браузер відкривати
не потрібно. Для справжнього Telegram потрібний вихідний HTTPS до
`api.telegram.org`. Деталі постійної служби: [TELEGRAM.md](TELEGRAM.md).

У Telegram виконайте:

```text
/status
/targets
/check
/interval 15
/pause
/status
/check
/resume
```

`/status` читає останній звіт, `/check` робить нову перевірку навіть під час
паузи. `/pause` зупиняє лише автоматичний розклад.
Інтервал та пауза зберігаються у state-файлі: на повторному запуску
збережені налаштування мають пріоритет над `--interval`.

Не запускайте два polling-процеси або discovery одночасно з одним токеном.
Зупиніть попередній процес через Ctrl+C або відповідну службу, зокрема
на іншій машині. Різні state-файли не усувають конфлікт токена в Telegram.

## 7. Живий інцидент та відновлення API

Спочатку зупиніть попереднього бота. Використаємо два термінали:
**A — локальний HTTP-сервер**, **B — бот**. В обох виконайте `cd` та
`source` з розділу 2. У B мають бути введені Telegram token і chat ID
з розділу 6. `$DEMO_DIR` у цьому розділі не потрібний.

У терміналі A створіть окрему конфігурацію і запустіть сервер:

```bash
mkdir -p lab-03/var
cat > lab-03/var/live-api.json <<'JSON'
{
  "targets": [
    {
      "name": "local-demo",
      "url": "http://127.0.0.1:18765/",
      "expected_status": 200,
      "timeout": 2,
      "threshold_ms": 2000
    }
  ]
}
JSON

python3 -m http.server 18765 --bind 127.0.0.1 \
  --directory lab-03/tests/fixtures
```

Сервер має залишитися працювати. Якщо отримали `Address already in use`,
не зупиняйте невідомий процес: виберіть вільний порт і змініть його
**і в конфігурації, і в команді сервера**.

У терміналі B перевірте готовність і запустіть бота з новим станом,
щоб попередня пауза/історія інцидентів не вплинули на демонстрацію:

```bash
curl --fail --noproxy '*' http://127.0.0.1:18765/
python3 lab-03/api_monitor.py \
  --config lab-03/var/live-api.json \
  --output lab-03/var/live-check.json --direct --no-notify

LIVE_STATE=$(mktemp -d "$PWD/lab-03/var/live-state.XXXXXX")
python3 lab-03/telegram_bot.py \
  --config lab-03/var/live-api.json \
  --output "$LIVE_STATE/results.json" \
  --state "$LIVE_STATE/state.json" --interval 10 --direct
```

1. У Telegram надішліть `/check`: очікується здоровий `local-demo`.
2. У терміналі A натисніть Ctrl+C: сервер припинить слухати порт.
3. Надішліть `/check` або зачекайте наступної перевірки. Очікується
   `connection_refused`, 2 спроби та сповіщення про проблему.
4. У A повторіть **ту саму команду `python3 -m http.server ...`**.
5. Знову надішліть `/check` або зачекайте. Очікується
   **«API відновився»** та здоровий результат.
6. Наприкінці зупиніть обидва процеси через Ctrl+C.

`--direct` обходить проксі лише для перевірюваного локального API,
а не для Telegram. Повторні однакові інциденти приглушуються: відсутність
другого однакового повідомлення не є помилкою.

## 8. Git-хуки

Спочатку перевірте чинне налаштування:

```bash
git config --show-origin --get core.hooksPath || true
```

Якщо вже є сторонній шлях хуків, не перезаписуйте його без узгодження.
Якщо значення відсутнє або ви свідомо обрали хуки лабораторної:

```bash
git config --local core.hooksPath lab-03/hooks
git config --get core.hooksPath

PYTHONPATH=lab-03 python3 -m unittest discover \
  -s lab-03/tests -p test_hooks.py -v
./lab-03/hooks/pre-push
```

Очікуються `lab-03/hooks`, **4 успішні тести хуків**, потім 54 Python-тести
і 3 Go-тести через `pre-push`. Для запуску Git з термінала він має успадкувати
активований `PATH`; інший термінал або GUI Git може не бачити лінтери.

Тести хуків самі створюють тимчасові репозиторії та перевіряють блокування
поганого staged-вмісту, виправлення тільки у working tree, успішний чистий
індекс і невдалий runner. Робити демонстраційні коміти в основному репозиторії
не потрібно. `pre-commit` перевіряє саме **індекс Git**; після виправлення
потрібний повторний `git add`.

Хуки можна обійти через `--no-verify`. Незалежну перевірку виконує CI;
для обов'язкового блокування merge потрібний GitHub ruleset/branch protection.

## 9. Бонус: системний монітор і розклад

У головному терміналі з `$DEMO_DIR`:

```bash
cat lab-03/config/monitor.env
./lab-03/monitor.sh || printf 'Код монітора: %s\n' "$?"
MEM_MAX=0 ./lab-03/monitor.sh \
  || printf 'Код монітора: %s (очікується 11 лише за RAM-alert)\n' "$?"
tail -n 12 "$MONITOR_LOG"
```

Очікуються CPU, RAM і вільний диск. `MEM_MAX=0` спричиняє RAM `ALERT`.
Код **11** означає лише RAM-alert; якщо одночасно перевищено інші пороги,
код буде **1** (змішані тривоги). Щоб ізолювати саме RAM на навантаженій машині:

```bash
CPU_MAX=100 DISK_MIN_FREE=0 MEM_MAX=0 ./lab-03/monitor.sh \
  || printf 'Код ізольованої перевірки RAM: %s (очікується 11)\n' "$?"
```

Конфігурація є довіреним shell-файлом; змінні середовища перевизначають
типові пороги. Системний монітор сам по собі не запускає розклад.

Згенеруйте crontab зі **справжнім абсолютним шляхом**, а не запускайте
без змін шаблон із `config/monitor.crontab`:

```bash
printf 'SHELL=/bin/bash\n* * * * * cd "%s" && MONITOR_LOG="%s/monitor-cron.log" ./lab-03/monitor.sh >> "%s/cron-output.log" 2>&1\n' \
  "$PWD" "$DEMO_DIR" "$DEMO_DIR" > "$DEMO_DIR/monitor.crontab"
cat "$DEMO_DIR/monitor.crontab"
supercronic -test "$DEMO_DIR/monitor.crontab"
supercronic "$DEMO_DIR/monitor.crontab"
```

Для наведених шляхів команду можна копіювати без змін. Якщо ваш шлях містить
`"`, `$`, зворотну лапку, `\` або `%`, перед використанням адаптуйте екранування.

Остання команда працює в передньому плані. Дочекайтеся кількох хвилин:
перший запуск відбувається на наступній хвилинній межі, не одразу.
Потім Ctrl+C і перегляд:

```bash
tail -n 30 "$DEMO_DIR/monitor-cron.log"
tail -n 20 "$DEMO_DIR/cron-output.log"
```

За п'ять хвилинних запусків має бути п'ять записів `result=finished`
із різними часовими мітками. Старий `evidence/monitor-cron.txt` не є
підтвердженням нового запуску. Supercronic тут не встановлює системний crontab:
після Ctrl+C цей розклад більше не працює.

## 10. Бонус: аналізатор журналів

```bash
cat lab-03/tests/fixtures/access.combined
python3 lab-03/log_analyzer.py \
  --input lab-03/tests/fixtures/access.combined \
  --output "$DEMO_DIR/access.json" --format json --top 3
PYTHONPATH=lab-03 python3 -m unittest discover \
  -s lab-03/tests -p test_log_analyzer.py -v
```

Очікується: 4 коректні й 2 пошкоджені рядки; `192.0.2.10` — 2 запити;
`2xx`, `3xx`, `4xx`, `5xx` — по одному, `1xx` — 0.
Пік `2026-10-20T07:00:00Z` — 3 запити: дата взята з fixture, не з поточного часу.
Файл читається потоково; час нормалізується до UTC.

## 11. Бонус: Go organizer

Бінарник створюється **успішним завершенням** `check.sh`, а не активацією:

```bash
file lab-03/bin/organizer
./lab-03/bin/organizer categories
mkdir -p "$DEMO_DIR/files"
printf 'document\n' > "$DEMO_DIR/files/report.pdf"
printf 'image\n' > "$DEMO_DIR/files/photo.PNG"
printf 'video\n' > "$DEMO_DIR/files/video.mp4"
printf 'archive\n' > "$DEMO_DIR/files/backup.zip"

./lab-03/bin/organizer organize --source "$DEMO_DIR/files" --dry-run
find "$DEMO_DIR/files" -maxdepth 2 -type f | sort
./lab-03/bin/organizer organize --source "$DEMO_DIR/files"
find "$DEMO_DIR/files" -maxdepth 2 -type f | sort

python3 lab-03/benchmark_startup.py \
  --output "$DEMO_DIR/benchmark.json" --runs 30
python3 -m json.tool "$DEMO_DIR/benchmark.json"
```

Після dry-run файли залишаються на місці; після звичайного запуску лежать у
`documents`, `images`, `videos`, `archives`. Для повторної демонстрації
використайте нову теку: відтворення вхідних файлів поверх уже відсортованих
створить колізії, які утиліта навмисно відхиляє.

Якщо потрібно зібрати тільки organizer, без лінтерів і тестів:

```bash
mkdir -p lab-03/bin
(cd lab-03/organizer && CGO_ENABLED=0 go build -trimpath \
  -ldflags='-s -w' -o ../bin/organizer .)
```

## 12. Швидка діагностика

| Симптом | Що перевірити |
|---|---|
| `cd: /workspace/...: No such file` | Використайте реальний шлях із розділу 2 |
| `shellcheck` / `ruff` / `go`: command not found | `dev-setup.sh`, потім `source` у поточному терміналі |
| `ensurepip is not available` | Встановіть `python3-venv` для використаної версії Python |
| `curl`, pip або Go install не завантажують залежності | Інтернет, DNS, CA-сертифікати, проксі; збережіть точний текст помилки |
| Немає `lab-03/bin/organizer` | `check.sh` не дійшов до збірки; усуньте попередню помилку або зберіть окремо |
| `Error: file/system operation failed` | Батьківська тека звіту/журналу існує та доступна для запису |
| Бот мовчить після тестового повідомлення | Запустіть звичайний polling-процес; перевірте власний chat ID |
| Telegram unauthorized / forbidden | Правильний токен, `/start` у своєму чаті, бот не заблокований |
| Telegram conflict або duplicate instance | Зупиніть інші polling-процеси/служби з тим самим токеном |
| Інтервал не змінився після перезапуску | Збережений state має пріоритет; `/interval 15` або новий `--state` |
| Немає повторних однакових alert | Бот приглушує дублікати; дивіться `/status` і `/check` |
| Cron поки нічого не записав | Дочекайтеся наступної хвилини; перевірте Supercronic і абсолютні шляхи |

Після завершення зупиніть запущені сервер, бота та Supercronic через Ctrl+C.
Тимчасові звіти залишаються в надрукованій `$DEMO_DIR`, локальні інструменти —
у `.venv`, бінарник — у `lab-03/bin`. Секрети залишаються в середовищі
термінала; за потреби виконайте `unset TELEGRAM_BOT_TOKEN TELEGRAM_CHAT_ID`.

## Перевірено в цьому середовищі

27 жовтня 2026 року: Python 3.14.4, Go 1.27.3, Ruff 0.17.1,
ShellCheck 0.11.0. Штатні `dev-setup.sh` та `check.sh` успішні:
54 Python-тести, 3 Go-тести, статичний organizer.
Окремо виконано демонстраційні команди: ротація до трьох архівів,
SHA-256 до/після dry-run, збереження стороннього файла, код 3 для відсутнього
джерела, чотири типи API-збоїв із перевіркою кількості спроб, ізольований
RAM-alert із кодом 11, точні результати аналізатора, dry-run і перенесення
чотирьох категорій organizer, benchmark із 30 запусками.
Supercronic пройшов `-test` і виконав один реальний хвилинний запуск
системного монітора з кодом 0; очікування п'яти запусків не виконувалося.
Telegram end-to-end тест перевіряє команди, alert та recovery через локальний
HTTPS-стенд. Це **не** підтвердження доставки у справжній Telegram:
її треба перевірити своїм токеном через `--test-message` та розділ 7.
