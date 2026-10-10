# AI code-review бот в GitHub Actions

Учебный проект: бот, который при каждом открытии или обновлении pull request'а читает его diff,
отправляет языковой модели вместе с чек-листом и публикует ревью комментарием в PR.
Пайплайн собран вручную, готовых AI-review Action не используется.

## Как это устроено

```
pull_request (opened, synchronize)
        │
        ▼
.github/workflows/ai-review.yml
  1. checkout (fetch-depth: 0)
  2. git diff origin/<base>...<head>        ← three-dot diff всего PR, без *.lock, dist/, generated/
  3. python .github/scripts/review.py       ← сам бот
        ├─ режет diff на файлы, выкидывает lock/dist/generated/бинарники
        ├─ считает размер; если больше порога — модель не зовёт, пишет «PR слишком большой…»
        ├─ берёт чек-лист .github/review-instructions.md (из базовой ветки PR) и кладёт в промпт
        ├─ зовёт модель, ждёт JSON {"comments": [...]}
        └─ при любой ошибке пишет понятный fallback, но не падает
  4. actions/github-script                  ← публикует review.md комментарием в PR
```

| Файл | Зачем |
|---|---|
| `.github/workflows/ai-review.yml` | триггер, права (`contents: read`, `pull-requests: write`), шаги |
| `.github/scripts/review.py` | логика бота (только стандартная библиотека Python) |
| `.github/review-instructions.md` | чек-лист: на что ругаться и что НЕ считать проблемой |
| `.github/scripts/test_review.py` | тесты бота без реальной модели |
| `app/`, `tests/` | демо-приложение (клиенты и заказы), объект ревью |
| `eval/ground-truth.json`, `eval/score.py` | эталон заложенных проблем и подсчёт precision/recall |

## Настройка

Секреты (Settings → Secrets and variables → Actions → **Secrets** → New repository secret):

| Секрет | Когда нужен |
|---|---|
| `CLAUDE_CODE_OAUTH_TOKEN` | режим по умолчанию (`claude`): токен из `claude setup-token`, вход по подписке Claude |
| `LLM_API_KEY` | режим `openai`: ключ любого OpenAI-совместимого API (Gemini, OpenRouter, Groq…) |

Переменные (там же, вкладка **Variables**), все необязательные:

| Переменная | По умолчанию | Смысл |
|---|---|---|
| `LLM_BACKEND` | `claude` | `claude` или `openai` |
| `CLAUDE_MODEL` | `sonnet` | `sonnet`, `haiku` и т. д. (режим `claude`) |
| `LLM_BASE_URL` | Gemini OpenAI-endpoint | адрес API (режим `openai`) |
| `LLM_MODEL` | `gemini-2.5-flash` | имя модели (режим `openai`) |
| `MAX_DIFF_LINES` | `500` | порог по строкам изменений |
| `MAX_FILES` | `20` | порог по числу файлов |

Ключи нигде не хранятся в коде и не печатаются в логи.

## Безопасность

* Права `GITHUB_TOKEN` в workflow минимальные: чтение кода и запись комментария в PR.
* Триггер `pull_request`, а не `pull_request_target`: PR из чужих форков не получают секреты.
* Значения из события (`base.ref`, `head.sha`) передаются через `env`, а не подставляются в shell-команду.
* Claude Code запускается в пустой временной папке, без инструментов и с урезанным окружением:
  код PR не может подложить свои настройки, хуки или MCP-серверы и не может ничего выполнить.
* Чек-лист читается из базовой ветки PR, поэтому автор PR не может подменить правила ревью.
* Diff в промпте помечен как данные, а не инструкции (защита от prompt injection из кода PR).
* Упоминания `@имя` в ответе модели обезвреживаются, чтобы бот не пинговал людей.

## Локальные проверки

```
python -m unittest discover -s tests -t .                              # тесты приложения
python -m unittest discover -s .github/scripts -p "test_review.py"     # тесты бота
```

## Оценка качества ревью

1. Создать PR с заранее заложенными проблемами (см. `eval/ground-truth.json`).
2. Сохранить комментарий бота в файл (`gh pr view <номер> --comments > bot-comment.txt`).
3. Посчитать метрики: `python eval/score.py bot-comment.txt`.
