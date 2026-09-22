"""Fail-closed multi-account League active-game gate."""

import concurrent.futures
import json
import sys
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from squat_capture.app_config import APP_CONFIG


def riot_get(url, api_key):
    request = Request(url, headers={
        "X-Riot-Token": api_key,
        "User-Agent": "SquatCapture/2.0",
        "Accept": "application/json",
    })
    try:
        with urlopen(request, timeout=12) as response:
            return response.status, json.loads(response.read().decode("utf-8") or "{}")
    except HTTPError as error:
        return error.code, None


def parse_accounts(raw):
    accounts = []
    for line in (raw or "").replace(",", "\n").splitlines():
        riot_id = line.strip()
        if not riot_id:
            continue
        game_name, separator, tag_line = riot_id.rpartition("#")
        if not separator or not game_name.strip() or not tag_line.strip():
            raise ValueError(f"Invalid Riot ID: {riot_id!r}; expected Game Name#TAG")
        accounts.append((game_name.strip(), tag_line.strip()))
    return accounts


def check_account(account, api_key, routing_region, platform_region):
    game_name, tag_line = account
    label = f"{game_name}#{tag_line}"
    account_url = (
        f"https://{routing_region}.api.riotgames.com/riot/account/v1/accounts/by-riot-id/"
        f"{quote(game_name, safe='')}/{quote(tag_line, safe='')}"
    )
    status, payload = riot_get(account_url, api_key)
    if status != 200 or not payload or not payload.get("puuid"):
        return label, "unknown", f"account lookup HTTP {status}"

    spectator_url = (
        f"https://{platform_region}.api.riotgames.com/lol/spectator/v5/active-games/by-summoner/"
        f"{quote(payload['puuid'], safe='')}"
    )
    status, _ = riot_get(spectator_url, api_key)
    if status == 200:
        return label, "in_game", "active game found"
    if status == 404:
        return label, "idle", "no active game"
    return label, "unknown", f"spectator lookup HTTP {status}"


def main():
    api_key = APP_CONFIG.get("riot_api_key")
    routing_region = APP_CONFIG.get("riot_routing_region") or "americas"
    platform_region = APP_CONFIG.get("riot_platform_region") or "na1"
    try:
        accounts = parse_accounts(APP_CONFIG.get("riot_accounts"))
    except ValueError as error:
        print(error, file=sys.stderr)
        print("true")
        return

    if not api_key or not accounts:
        print("Riot gate needs an API key and at least one Riot ID", file=sys.stderr)
        print("true")
        return

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(5, len(accounts))) as pool:
            results = list(pool.map(
                lambda account: check_account(account, api_key, routing_region, platform_region),
                accounts,
            ))
    except Exception as error:
        print(f"Riot gate failure: {error}", file=sys.stderr)
        print("true")
        return

    for label, state, detail in results:
        print(f"{label}: {state} ({detail})", file=sys.stderr)

    # Only a fully confirmed all-idle result allows the Twitch redemption.
    print("false" if all(state == "idle" for _, state, _ in results) else "true")


if __name__ == "__main__":
    main()
