# Bloti Bot

[![Pipeline](https://github.com/rserag/bloti-bot/actions/workflows/pipeline.yml/badge.svg)](https://github.com/rserag/bloti-bot/actions/workflows/pipeline.yml)

Bloti Bot is a Telegram group utility for mentioning members, listing administrators and bots,
and removing deleted accounts. This repository is a maintained modernization of the original
Ping All Bot by TeLe TiPs.

The migration branch replaces the unmaintained Pyrogram client with Telethon and separates
Telegram transport code from command behavior. Admin checks, per-chat jobs, cancellation,
HTML escaping, and cleanup are covered by offline tests.

## Commands

| Command | Who can use it | Purpose |
| --- | --- | --- |
| `/ping [message]`, `/all` | Everyone | Mention non-bot, non-deleted members in batches |
| `/group create NAME`, `/group delete NAME` | Chat admins | Create or delete a named group in this chat |
| `/group add NAME @user [@user …]` | Chat admins | Add current human chat members to a saved group |
| `/group remove NAME @user [@user …]` | Chat admins | Remove members from a saved group (does not remove them from the chat) |
| `/group show NAME`, `/groups` | Everyone | View saved members or list this chat's groups |
| `/NAME [message]`, `/pinggroup NAME [message]` | Everyone | Mention current chat members belonging to the named group |
| `/remove`, `/clean` | Chat admins; bot must be admin | Remove deleted accounts |
| `/stop`, `/cancel` | Chat admins | Cancel only this chat's active job |
| `/admins`, `/staff` | Everyone | List visible administrators |
| `/bots` | Everyone | List bots |
| `/help` | Everyone | Show command help |
| `/source` | Everyone | Link to this repository |
| `/version` | Everyone | Show the running version |

### Named groups

For example, create a group for people who play Bloti:

```text
/group create bloti
/group add bloti @alice @bob
/bloti Time to play!
/group remove bloti @bob
```

To add or remove someone without a username, reply to their message with
`/group add bloti` or `/group remove bloti`. You can also use numeric Telegram user IDs;
`/group show bloti` lists saved names and IDs without notifying anyone. Explicit targets take
precedence over the replied-to sender. Adding multiple people is atomic: if anyone cannot be
matched to an active human in this chat, no members are added. Repeated additions do not duplicate
members. A person can belong to multiple groups.

Once a group exists, use its name as a command: `/bloti` or `/bloti Time to play!`.
`/bloti@YourBotUsername` also works. `/pinggroup bloti` remains available.
Built-in command names and aliases (such as `help`, `ping`, `all` and `stop`) are reserved,
so saved groups cannot override the bot's commands. Unknown commands are ignored.

Names are case-insensitive, contain 1–32 letters, numbers, underscores or hyphens, and are scoped
to the current chat. Each chat can have up to 50 groups, each with up to 500 members; membership
commands accept up to 50 targets at a time. Only admins can change groups; anyone can mention them.
Groups work in group chats, not private chats or broadcast channels.

Membership is saved by Telegram user ID. At mention time the bot checks current chat membership
and skips people who left, bots and deleted accounts. Group mentions use batches of ten, share
the existing per-chat job limit, and can be cancelled by an admin with `/stop`. An optional
message can be up to 512 characters. Group membership does not change Telegram chat membership.
For removals by username, use the username saved when the member was added; a reply or the saved
ID still works after a username changes or a member leaves the chat.

Groups persist in a SQLite database in the existing session volume, so container restarts and
updates retain them. Back up the database along with the session volume; rolling back to an older
bot version leaves the database intact. Chat migrations to a new Telegram chat ID do not
automatically transfer saved groups.

## Configuration

Create Telegram application credentials at [my.telegram.org](https://my.telegram.org) and a bot
token through BotFather. Copy `.env.example` for the complete list of settings, but never commit a
populated `.env` file.

Required settings:

- `API_ID`
- `API_HASH`
- `BOT_TOKEN`

Each required secret also supports a file-based form: `API_ID_FILE`, `API_HASH_FILE`, and
`BOT_TOKEN_FILE`. File-mounted secrets are preferred for production deployments.

Optional settings:

- `SESSION_PATH` (default `/var/lib/blotibot/blotibot`)
- `GROUPS_PATH` (default `groups.sqlite3` next to `SESSION_PATH`; keep it on persistent storage)
- `SOURCE_URL`
- `APP_VERSION`
- `MAX_ACTIVE_CHATS` (default `4`)
- `MESSAGE_DELAY_SECONDS` (default `1`)

## Local development

Python 3.12 or newer and [uv](https://docs.astral.sh/uv/) are recommended.

```console
uv sync --all-groups
uv run ruff check .
uv run mypy
uv run pytest
```

To run the bot locally, export the required settings and use:

```console
uv run blotibot
```

Tests use a fake Telegram gateway and never require real credentials or network access.

## Container deployment

The production-oriented Compose definition builds a digest-pinned Python 3.12/Alpine image for
`linux/amd64`.
The bot runs as UID/GID 1000 with no Linux capabilities, a read-only root filesystem, bounded
resources and logs, a persistent session volume, and an event-loop heartbeat health check. It
publishes no network ports.

Compose loads credentials from three files that are excluded from the build context and Git:

```text
secrets/api_id
secrets/api_hash
secrets/bot_token
```

On the deployment host, create `secrets/` with mode `0700` and each secret file with mode `0600`,
owned by UID/GID 1000. Put only the raw credential value in each corresponding file. Validate and
build without displaying their contents:

```console
docker compose config --quiet
docker compose build --pull
docker compose up --detach --wait
```

The health check is based on a heartbeat written only while Telethon reports an active connection.
It detects a blocked event loop or disconnected client; an interactive Telegram command remains the
final end-to-end verification.

The `main` pipeline tests the application, validates deployment configuration, builds and scans the
container, publishes an immutable GHCR digest with provenance, and pauses at the protected
`production` environment before deployment. Padval accepts only the forced deployment command and
automatically restores the prior healthy release if verification fails. See
[deploy/README.md](deploy/README.md) for the operational model.

The initial Padval cutover temporarily references its existing mode-`0600` legacy `.env` file in
place, without sending credential values through GitHub or baking them into the image. This
migration-only bridge should be replaced by the file-secret model above when the credentials are
rotated.

## Source layout

- `src/blotibot/service.py` contains command behavior.
- `src/blotibot/groups.py` stores chat-scoped named groups in SQLite.
- `src/blotibot/telethon_gateway.py` contains Telegram API operations.
- `src/blotibot/router.py` maps messages to commands.
- `tests/` contains offline behavioral tests.
- `pingallbot.py` remains as a compatibility entry point during the deployment migration.

## Credits

- [Ping All Bot by TeLe TiPs](https://github.com/teletips/PingAllBot-TeLeTiPs)
- [Telethon](https://github.com/LonamiWebs/Telethon)

## License

Licensed under the [GNU Affero General Public License v3.0](LICENSE), consistent with the
upstream project. The original attribution and modification notice are preserved in
[NOTICE](NOTICE).
