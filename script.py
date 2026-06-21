import os
from datetime import datetime, timezone
from urllib.parse import quote

import requests

API_KEY = os.environ.get("RIOT_API_KEY", "")
ACCOUNT_REGION = "americas"
MATCH_REGION = "americas"
# GAME_NAME = "your sona mommy"
# TAG_LINE = "uwu"

GAME_NAME = "utv"
TAG_LINE = "na1"
RECENT_ACTIVITY_MINUTES = 45
MATCH_QUEUE = 420


def riot_get(url):
    return requests.get(
        url,
        headers={
            "X-Riot-Token": API_KEY,
            "User-Agent": "twitchSquatsBot/1.0",
            "Accept": "application/json",
        },
        timeout=15,
    )


def format_minutes(minutes):
    if minutes < 60:
        return f"{minutes}m ago"

    hours = minutes // 60
    remaining_minutes = minutes % 60
    if remaining_minutes == 0:
        return f"{hours}h ago"
    return f"{hours}h {remaining_minutes}m ago"


def main():
    if not API_KEY:
        print("false")
        return

    account_url = (
        f"https://{ACCOUNT_REGION}.api.riotgames.com/riot/account/v1/accounts/by-riot-id/"
        f"{quote(GAME_NAME, safe='')}/{quote(TAG_LINE, safe='')}"
    )
    account_response = riot_get(account_url)
    if account_response.status_code != 200:
        print("false")
        return

    puuid = account_response.json().get("puuid")
    if not puuid:
        print("false")
        return

    match_ids_url = (
        f"https://{MATCH_REGION}.api.riotgames.com/lol/match/v5/matches/by-puuid/"
        f"{quote(puuid, safe='')}/ids?start=0&count=1&queue={MATCH_QUEUE}"
    )
    match_ids_response = riot_get(match_ids_url)
    if match_ids_response.status_code != 200:
        print("false")
        return

    match_ids = match_ids_response.json()
    if not match_ids:
        print("false")
        return

    match_url = (
        f"https://{MATCH_REGION}.api.riotgames.com/lol/match/v5/matches/"
        f"{quote(match_ids[0], safe='')}"
    )
    match_response = riot_get(match_url)
    if match_response.status_code != 200:
        print("false")
        return

    match_data = match_response.json()
    info = match_data.get("info", {})
    participants = info.get("participants", [])
    participant = next(
        (entry for entry in participants if entry.get("puuid") == puuid),
        None,
    )
    if not participant:
        print("false")
        return

    game_end_timestamp = info.get("gameEndTimestamp")
    game_duration_seconds = info.get("gameDuration")
    if not game_end_timestamp or game_duration_seconds is None:
        print("false")
        return

    ended_at = datetime.fromtimestamp(game_end_timestamp / 1000, tz=timezone.utc)
    now = datetime.now(timezone.utc)
    minutes_since_end = max(0, int((now - ended_at).total_seconds() // 60))
    if minutes_since_end <= RECENT_ACTIVITY_MINUTES:
        print("true")
    else:
        print("false")


if __name__ == "__main__":
    main()
