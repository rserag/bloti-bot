# Contributing to Bloti Bot

Thank you for helping improve Bloti Bot. Small, focused changes with tests are easiest to review.

## Development setup

Install Python 3.12 or newer and `uv`, then run:

```console
uv sync --all-groups
uv run ruff check .
uv run mypy
uv run pytest
```

Container changes should also pass:

```console
docker build --check --platform linux/amd64 .
docker compose config --quiet
docker compose build
```

The test suite is offline and must not use real Telegram credentials.

## Pull requests

1. Open an issue first for large behavior or deployment changes.
2. Branch from the latest `main` and keep the change focused.
3. Add or update tests for behavior changes.
4. Update documentation when commands, configuration, or operations change.
5. Complete the pull-request checklist and resolve all review discussions.

Do not commit populated `.env` files, secret files, Telegram sessions, private chat content, or
production logs. Report security issues using [SECURITY.md](SECURITY.md), not a public issue.

By contributing, you agree that your contribution is licensed under the repository's GNU Affero
General Public License v3.0.
