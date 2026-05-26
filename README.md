# Discord Ticket Staff Bot

A Python Discord ticket management bot built with `discord.py`. It handles ticket claiming, staff permissions, point rewards, biweekly quota tracking, leaderboards, and ticket close logs.

## Features

- Slash command based ticket workflow
- Five configurable ticket categories
- Role hierarchy:
  - Support: Support Tickets only
  - Moderator: Support Tickets and Ban Appeals
  - Admin: all categories and point management
- `/claim` locks a ticket to one support member
- `/add` adds a user to the current ticket
- `/close` deletes the ticket after 10 seconds
- Auto-awards points and quota on ticket close
- Biweekly quota setup and checks
- Leaderboard and staff stats embeds
- Reward claiming with configurable rewards
- Close logs sent to a configured log channel
- `.env` based configuration

## Requirements

- Python 3.12+
- Discord bot token
- A Discord server with role IDs, category IDs, and a log channel ID

## Installation

```powershell
git clone https://github.com/YOUR_USERNAME/YOUR_REPO.git
cd YOUR_REPO
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python bot.py
```

## Configuration

Edit `.env` after copying `.env.example`.

```env
DISCORD_TOKEN=your_bot_token_here
GUILD_ID=123456789012345678
SUPPORT_ROLE_ID=123456789012345678
MODERATOR_ROLE_ID=123456789012345678
ADMIN_ROLE_ID=123456789012345678
LOG_CHANNEL_ID=123456789012345678

# 1st category = Support Tickets
first_category_id=123456789012345678
first_category_name=Support Tickets

# 2nd category = Donations
second_category_id=123456789012345678
second_category_name=Donations

# 3rd category = Ban Appeals
third_category_id=123456789012345678
third_category_name=Ban Appeals

# Optional categories
fourth_category_id=123456789012345678
fourth_category_name=Partner Tickets
fifth_category_id=123456789012345678
fifth_category_name=Other Tickets

QUOTA_POINTS=1
POINTS_PER_CLAIM=1
COMMAND_PREFIX=!
```

## Commands

| Command | Access | Description |
| --- | --- | --- |
| `/ticket_panel` | Staff | Sends the ticket panel |
| `/claim` | Staff | Claims the current ticket |
| `/add user:<member>` | Staff | Adds a user to the current ticket |
| `/close reason:<text?>` | Staff | Closes and deletes the current ticket |
| `/points user:<member?>` | Everyone | Shows points |
| `/quota user:<member?>` | Everyone | Shows quota progress |
| `/stats user:<member?>` | Everyone | Shows ticket stats |
| `/leaderboard sort:<biweekly\|lifetime>` | Everyone | Shows ticket leaderboard |
| `/biweekly-check` | Everyone | Shows quota completion |
| `/setup-biweekly goal:<int>` | Admin | Resets biweekly period and sets goal |
| `/give_points user:<member> points:<int> reason:<text?>` | Admin | Adds points |
| `/remove_points user:<member> points:<int> reason:<text?>` | Admin | Removes points |
| `/rewards` | Everyone | Shows point rewards |
| `/claim_reward reward_id:<id>` | Everyone | Claims a reward |

## Data Files

Runtime data is created automatically in `data/`.

```txt
data/store.json    # users, tickets, quota period, biweekly goal
data/rewards.json  # reward list
```

`data/*.json` is ignored by git so production data is not committed.

## Security

Never commit `.env` or a real Discord bot token. If a token was ever posted publicly or pushed to GitHub, reset it in the Discord Developer Portal.
