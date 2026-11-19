# Chess.amy — две сборки

Локальные шахматы на Flask и python-chess: партии с ботами Stockfish, турниры, разбор с 13 ярлыками, тренер, импорт PGN/FEN, тренировка и резервные копии.

В репозитории две сборки:

- `ChessAmy/` — основная: игра, турниры, разбор, тренировка, темы доски.
- `ChessAmyCH/` — та же игра с чит-панелью: стрелка лучшего хода с ярлыками (`amethyst`, `brilliant`, `ideal`), глубокая подсказка и авто-подсказка.

Подробное описание, фишки и установка — в [ChessAmy/README.md](ChessAmy/README.md).

## Запуск

```bat
python -m pip install -r ChessAmy\requirements.txt
python ChessAmy\app.py
```

`ChessAmy/app.py` поднимает сразу два сервера:

- основная игра — http://127.0.0.1:5000
- чит-версия — http://127.0.0.1:5001

Отключить второй сервер: `set CHESSAMY_NO_CHEAT=1`. Другой порт чита: `set CHEAT_PORT=5002`.

Чит-версию можно запустить и отдельно:

```bat
python ChessAmyCH\app.py
```

## Тесты

```bat
python -m pip install -r ChessAmy\requirements-dev.txt
cd ChessAmy
python -m pytest
```

Браузерные сценарии: `python -m playwright install chromium`, затем `python -m pytest -m e2e tests/e2e`.

## Данные

База и секретный ключ лежат вне репозитория: `%LOCALAPPDATA%\ChessAmy\` и `%LOCALAPPDATA%\ChessAmyCH\`. Резервные копии — в подпапке `backups`.

## Лицензия

MIT, см. [ChessAmy/LICENSE](ChessAmy/LICENSE).
## Публикация на GitHub

```bat
cd C:\Users\User\Desktop\ChessAmy1
git init
git add .
git commit -m "Chess.amy: игра, разбор и чит-сборка"
git branch -M main
git remote add origin https://github.com/USER/REPO.git
git push -u origin main
```

Перед первым коммитом проверь `git status`: `*.db`, `.secret_key`, `server.out` и `stockfish/*.exe` должны быть проигнорированы.
