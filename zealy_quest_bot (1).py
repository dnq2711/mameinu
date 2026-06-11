#!/usr/bin/env python3
"""
Zealy new-quest watcher for the Mame Inu community.

It checks the Mame Inu Zealy questboard for quests that weren't seen
on the previous run, and sends a Telegram message for each new one.

State (the list of already-seen quest IDs) is kept in seen_quests.json
so the GitHub Action can commit it back to the repo between runs.

Zealy sits behind Cloudflare and renders the questboard with
client-side JavaScript, so plain `requests` calls get 401/403 and the
raw HTML doesn't contain the quest data. To work around that, this
script uses a headless browser (Playwright) to actually load the page
like a normal visitor, and listens for the background network
responses the page makes, picking out whichever one contains the
quest list.
"""

import json
import os
import sys
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

SUBDOMAIN = "mameinu"
QUESTBOARD_URL = f"https://zealy.io/cw/{SUBDOMAIN}/questboard"
STATE_FILE = Path(__file__).parent / "seen_quests.json"

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html;q=0.9,*/*;q=0.8",
}


def load_seen():
    if STATE_FILE.exists():
        try:
            return set(json.loads(STATE_FILE.read_text()))
        except (json.JSONDecodeError, OSError):
            return set()
    return set()


def save_seen(ids):
    STATE_FILE.write_text(json.dumps(sorted(ids), indent=2))


def normalize_quest(q):
    """Pull out a stable id, a name and a category/module name from a raw quest dict."""
    qid = q.get("id") or q.get("_id") or q.get("questId")
    name = q.get("name") or q.get("title") or "Untitled quest"
    return qid, name


def fetch_via_browser():
    """
    Load the questboard with a real (headless) browser and capture the
    background network responses the page itself makes while loading.
    Whichever response contains a "quests"-shaped list is what we want.

    This avoids Cloudflare blocking plain `requests` calls, and doesn't
    depend on knowing Zealy's exact internal API URLs.
    """
    found_quests = {}
    debug_responses = []

    def handle_response(response):
        try:
            ctype = response.headers.get("content-type", "")
        except Exception:
            return
        if "json" not in ctype:
            return

        url = response.url
        try:
            data = response.json()
        except Exception:
            return

        quests = _find_quests_in_json(data)
        if quests:
            for q in quests:
                qid, name = normalize_quest(q)
                if qid:
                    found_quests[qid] = name
            debug_responses.append((url, len(quests)))

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=HEADERS["User-Agent"],
            locale="en-US",
        )
        page = context.new_page()
        page.on("response", handle_response)

        try:
            page.goto(QUESTBOARD_URL, wait_until="domcontentloaded", timeout=45000)
            # Give the SPA time to fire its data requests and render.
            page.wait_for_timeout(8000)
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass
        except Exception as e:
            print(f"[browser] navigation error: {e}")

        page_title = page.title()
        browser.close()

    print(f"[browser] page title: {page_title!r}")
    for url, count in debug_responses:
        print(f"[browser] found {count} quest-like entries in: {url}")

    if not found_quests:
        return None

    # Convert back to the (id, name) shape the rest of the script expects.
    return [{"id": qid, "name": name} for qid, name in found_quests.items()]


QUEST_HINT_KEYS = {"tasks", "rewards", "categoryId", "conditions", "recurrence", "questId"}


def _looks_like_quest(item):
    if not isinstance(item, dict):
        return False
    has_name = "name" in item or "title" in item
    has_id = "id" in item or "_id" in item or "questId" in item
    has_hint = any(k in item for k in QUEST_HINT_KEYS)
    return has_name and has_id and has_hint


def _find_quests_in_json(obj, depth=0):
    """Recursively search a parsed JSON object for a list that looks like quests."""
    if depth > 12:
        return None

    if isinstance(obj, dict):
        for key in ("quests", "data", "items", "results"):
            val = obj.get(key)
            if isinstance(val, list) and val and _looks_like_quest(val[0]):
                return val
        for v in obj.values():
            found = _find_quests_in_json(v, depth + 1)
            if found:
                return found

    elif isinstance(obj, list):
        if obj and _looks_like_quest(obj[0]):
            return obj
        for item in obj:
            found = _find_quests_in_json(item, depth + 1)
            if found:
                return found

    return None


def send_telegram(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram credentials missing, skipping notification:")
        print(text)
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        r = requests.post(url, json=payload, timeout=20)
        if r.status_code != 200:
            print(f"Telegram error {r.status_code}: {r.text}")
    except requests.RequestException as e:
        print(f"Telegram request error: {e}")


def main():
    quests = fetch_via_browser()

    if not quests:
        print(
            "Could not find any quest data in the page's network traffic. "
            "Zealy may have changed how the questboard loads its data, or "
            "Cloudflare blocked the headless browser. See README for tips."
        )
        sys.exit(1)

    print(f"Fetched {len(quests)} quests")

    seen = load_seen()
    is_first_run = len(seen) == 0

    new_quests = []
    current_ids = set()

    for q in quests:
        qid, name = normalize_quest(q)
        if qid is None:
            continue
        current_ids.add(qid)
        if qid not in seen:
            new_quests.append((qid, name))

    if is_first_run:
        # Don't spam on the very first run: just record the baseline.
        print(f"First run: recording {len(current_ids)} existing quests as baseline.")
    else:
        for qid, name in new_quests:
            msg = (
                f"🆕 <b>New Mame Inu Zealy quest!</b>\n"
                f"{name}\n"
                f"{QUESTBOARD_URL}"
            )
            send_telegram(msg)
            print(f"Notified about new quest: {name} ({qid})")

    save_seen(current_ids)


if __name__ == "__main__":
    main()
