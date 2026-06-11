# Mame Inu Zealy Quest Watcher

Checks https://zealy.io/cw/mameinu/questboard every 15 minutes and
sends you a Telegram message whenever a new quest appears.

## 1. Create a Telegram bot

1. Open Telegram, message **@BotFather**, send `/newbot`, follow the
   prompts. You'll get a **bot token** like `123456789:AAExample-Token`.
2. Start a chat with your new bot (search its username, hit Start) so
   it's allowed to message you.
3. Get your **chat ID**:
   - Send any message to your bot.
   - Visit `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in a
     browser.
   - Find `"chat":{"id": ...}` in the JSON — that number is your chat ID.

## 2. Put the code in a GitHub repo

1. Create a new (can be private) GitHub repository.
2. Add these files to it:
   - `zealy_quest_bot.py`
   - `requirements.txt`
   - `seen_quests.json`
   - `.github/workflows/zealy-quest-watch.yml`

## 3. Add your secrets

In the repo: **Settings → Secrets and variables → Actions → New repository secret**

- `TELEGRAM_BOT_TOKEN` = your bot token
- `TELEGRAM_CHAT_ID` = your chat ID

## 4. Run it

- Go to the **Actions** tab, open "Zealy Mame Inu Quest Watcher", and
  click **Run workflow** to test it manually first.
- The first run only records the current quests as a baseline (no
  notification spam). Every run after that, any new quest triggers a
  Telegram message.
- After that it runs automatically every 15 minutes (edit the cron
  schedule in the workflow file to change frequency).

## How it works / notes

- Zealy is protected by Cloudflare and loads quest data via JavaScript
  after the page loads, so plain HTTP requests get blocked (401/403)
  and the raw HTML is empty of quest data.
- This script uses a headless Chromium browser (Playwright) to load
  the questboard like a real visitor, and listens for the background
  data request the page itself makes, automatically picking out the
  one that contains the quest list. This means it doesn't depend on
  knowing Zealy's exact internal API.
- Because of the headless browser, each run takes roughly 30-60
  seconds (mostly installing/launching Chromium) — that's normal.
- State (`seen_quests.json`) is committed back to the repo by the
  workflow so the bot remembers what it already announced.
- If a run fails, check the "Run quest watcher" step logs:
  - `[browser] page title: ...` shows what page actually loaded
    (if it's a Cloudflare challenge page, the title will say so).
  - `[browser] found N quest-like entries in: <url>` shows which
    network request the quest data came from.
  - If neither line appears with quest data, paste the full log here
    and the detection logic in `_looks_like_quest()` /
    `_find_quests_in_json()` can be adjusted.
