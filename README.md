# twitchSquatsBot

Small Riot API starter for checking how recently a League of Legends player finished a public match.

## What it does

The script uses public Riot APIs that still work server-side:

1. `account-v1` resolves `GameName#TagLine` into a `puuid`.
2. `match-v5` fetches the latest ranked match ID for that `puuid`.
3. `match-v5` fetches the full match details and reports when it ended.

Because Riot's public responses may not include the encrypted summoner ID required by `spectator-v5`, this project now reports recent activity instead of live-game status.

## Setup

Export your Riot API key:

```bash
export RIOT_API_KEY='your-riot-api-key'
```

Edit the top of `script.py` to set:

- `ACCOUNT_REGION`
- `MATCH_REGION`
- `GAME_NAME`
- `TAG_LINE`
- `RECENT_ACTIVITY_MINUTES`
- `MATCH_QUEUE`

Run the script:

```bash
python3 script.py
```

## Output

- `RECENTLY ACTIVE` means the latest public match ended within `RECENT_ACTIVITY_MINUTES`
- `IDLE` means the latest public match is older than that threshold

The script also prints the last match ID, champion, result, duration, and how long ago the match ended.

## Routing notes

- `ACCOUNT_REGION` is `americas`, `asia`, or `europe`
- `MATCH_REGION` is also `americas`, `asia`, or `europe`

Examples:

- North America: `ACCOUNT_REGION = "americas"` and `MATCH_REGION = "americas"`
- EU West: `ACCOUNT_REGION = "europe"` and `MATCH_REGION = "europe"`
- Korea: `ACCOUNT_REGION = "asia"` and `MATCH_REGION = "asia"`

## Important

- Do not hardcode your Riot API key in source files.
- Development keys expire, so if requests suddenly fail, generate a fresh one in the Riot Developer Portal.

## Twitch EventSub

This repo also includes [twitch_eventsub_listener.py](/Users/li/github/twitchSquatsBot/twitch_eventsub_listener.py), a minimal webhook listener for Twitch channel point redemptions on `nannersowo`.

It listens for:

- `channel.channel_points_custom_reward_redemption.add`
- `channel.channel_points_automatic_reward_redemption.add`

Configure and run it:

```bash
export TWITCH_EVENTSUB_SECRET='a-long-random-secret'
export TARGET_REWARD_TITLE='Hydrate'
python3 twitch_eventsub_listener.py
```

Default callback:

- `http://localhost:8080/eventsub`

For local testing, Twitch recommends the Twitch CLI for webhook verification and mock events. For real Twitch delivery, the webhook callback must use SSL and port 443.

Relevant docs:

- [Handling webhook events](https://dev.twitch.tv/docs/eventsub/handling-webhook-events/)
- [EventSub subscription types](https://dev.twitch.tv/docs/eventsub/eventsub-subscription-types/)
- [API reference](https://dev.twitch.tv/docs/api/reference)
