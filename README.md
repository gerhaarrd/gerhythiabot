# Gerhythia

Gerhythia is a Discord bot for browsing Rhythia data from Discord. It exposes a `/gerhythia` slash-command group for player search, profiles, leaderboards, beatmaps, and map suggestions.

The bot uses Rhythia's public API surface and does not store Rhythia access tokens. Users can optionally link a Discord account to a public Rhythia profile by proving they can edit that profile's `about_me`, so commands like `/gerhythia profile` and `/gerhythia suggest` know which player to use by default.

## Features

- `/gerhythia search` searches Rhythia players and beatmaps without account linking.
- `/gerhythia profile` shows your linked profile or another player's profile.
- `/gerhythia leaderboard` shows global, country, or spin skill leaderboards.
- `/gerhythia maps` browses beatmaps with title, mapper, status, star rating, page, and limit filters.
- `/gerhythia beatmap` shows a specific beatmap by id or title, including cover art and details.
- `/gerhythia recent` shows the latest public score for your linked profile or another player.
- `/gerhythia suggest` suggests Ranked maps based on a user's top scores.
- `/gerhythia link`, `/gerhythia verify`, `/gerhythia unlink`, and `/gerhythia account` manage the Discord-to-Rhythia link.
- Links store only the public Rhythia user id and username.

## Requirements

- Python 3.13 or newer
- A Discord bot token
- `uv` or `pip`

## Setup

Clone the project and install dependencies:

```bash
uv sync
```

Or with `pip`:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create your environment file:

```bash
cp .env.example .env
```

Edit `.env` and set at least:

```env
DISCORD_TOKEN=your_discord_bot_token
```

Optional settings:

```env
# Sync slash commands to one Discord server for faster development.
DISCORD_GUILD_ID=your_test_server_id

# Disable command sync on startup.
SKIP_COMMAND_SYNC=1

```

## Running

With `uv`:

```bash
uv run python main.py
```

With an activated virtual environment:

```bash
python main.py
```

On startup, the bot registers the `/gerhythia` slash commands and rotates its Discord presence every 60 seconds.

## Account Linking

Linking uses public profile search plus an `about_me` verification code:

1. The user runs `/gerhythia link <username>`.
2. The bot searches Rhythia for that public username.
3. The user confirms the matched profile in an ephemeral message.
4. The bot generates a short code, such as `GERHYTHIA-AB12CD34`.
5. The user temporarily adds that code to their Rhythia `about_me`.
6. The user runs `/gerhythia verify`.
7. The bot reads the public profile, confirms the code, and stores only `discord_id`, `rhythia_user_id`, `rhythia_username`, and `linked_at`.

Users can delete their stored link at any time with:

```text
/gerhythia unlink
```

## Security Notes

Profile links are verified by checking for a temporary code in public profile text. This project is not an official Rhythia or Capo Games bot.

Hosting, access control, backups, logs, and server security are the operator's responsibility.

## Project Structure

```text
bot/
  discord_bot.py       Discord bot setup, command sync, and rotating presence
  slash_commands.py    /gerhythia command implementations
  link_account_ui.py   Ephemeral public account-link confirmation UI

rhythia/
  api_client.py        Rhythia API client and public search helper
  account_link.py      Public profile search and ownership verification
  linked_accounts.py   SQLite storage for linked public accounts
  discord_embeds.py    Discord embed builders
  config.py            Environment and path configuration

main.py                Bot entry point
data/                  Runtime database
```

## Notes

This bot uses Rhythia's production API at `https://production.rhythia.com/api`.

During development, set `DISCORD_GUILD_ID` so command updates sync quickly to a single test server. Without it, commands are synced globally and may take longer to appear.
