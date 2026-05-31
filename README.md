# Gerhythia

Gerhythia is a Discord bot for browsing Rhythia data from Discord. It exposes a `/gerhythia` slash-command group for player search, profiles, leaderboards, beatmaps, and map suggestions.

The bot can run public searches without a linked account. Commands that call authenticated Rhythia endpoints require users to link their Rhythia account through Discord login and a private Discord modal.

## Features

- `/gerhythia search` searches Rhythia players and beatmaps without account linking.
- `/gerhythia profile` shows your linked profile or another player's profile.
- `/gerhythia leaderboard` shows global, country, or spin skill leaderboards.
- `/gerhythia maps` browses beatmaps with title, mapper, status, star rating, page, and limit filters.
- `/gerhythia suggest` suggests Ranked maps based on a user's top scores.
- `/gerhythia link`, `/gerhythia unlink`, and `/gerhythia account` manage the Discord-to-Rhythia link.
- Linked session tokens are stored in SQLite and encrypted with Fernet.
- Expired Rhythia session tokens are cleaned up automatically.

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

# Encrypt linked users' Rhythia session tokens.
# If omitted, the bot creates data/.link_key automatically.
TOKEN_ENCRYPTION_KEY=

```

To generate a stable encryption key:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
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

Rhythia does not currently provide a redirect URL controlled by this bot, so linking uses a private paste flow:

1. The user runs `/gerhythia link`.
2. The bot sends an ephemeral message with a Rhythia Discord login button.
3. After login, the browser lands on a localhost callback URL that is expected to fail loading.
4. The user copies the full address-bar URL containing `access_token`.
5. The user pastes that URL into the private Discord modal.
6. The bot verifies that the Rhythia session belongs to the same Discord account, fetches the profile, and stores the encrypted session token.

Users can delete their stored token at any time with:

```text
/gerhythia unlink
```

## Security Notes

Rhythia session URLs and `access_token` values are sensitive. While valid, they may allow access to a user's Rhythia session. The bot warns users to paste them only into the private Discord modal.

Tokens are encrypted before being saved to `data/links.db`, but the server operator still controls the machine, bot files, environment variables, and encryption key. This project is not an official Rhythia or Capo Games bot.

The code does not intentionally share stored tokens with third parties. Hosting, access control, backups, logs, and server security are the operator's responsibility.

## Project Structure

```text
bot/
  discord_bot.py       Discord bot setup, command sync, and rotating presence
  slash_commands.py    /gerhythia command implementations
  link_account_ui.py   Ephemeral account-link embed, buttons, and modal

rhythia/
  api_client.py        Rhythia API client and public search helper
  account_link.py      Session URL parsing and link verification
  linked_accounts.py   SQLite storage for encrypted linked accounts
  oauth_login.py       Rhythia/Supabase login URL and JWT helpers
  discord_embeds.py    Discord embed builders
  config.py            Environment and path configuration

main.py                Bot entry point
data/                  Runtime database and generated encryption key
```

## Notes

This bot uses Rhythia's production API at `https://production.rhythia.com/api`.

During development, set `DISCORD_GUILD_ID` so command updates sync quickly to a single test server. Without it, commands are synced globally and may take longer to appear.
