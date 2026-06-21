# twitchSquatsBot

Small Riot/Twitch utility repo with:

- a Riot script that returns whether a player was recently active based on public match data
- a Twitch EventSub webhook listener for channel point redemptions on `nannersowo`

## What it does

The script uses public Riot APIs that still work server-side:

1. `account-v1` resolves `GameName#TagLine` into a `puuid`.
2. `match-v5` fetches the latest ranked match ID for that `puuid`.
3. `match-v5` fetches the full match details and reports when it ended.

Because Riot's public responses may not include the encrypted summoner ID required by `spectator-v5`, this project now reports recent activity instead of live-game status.

## Riot Setup

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

This repo includes [twitch_eventsub_listener.py](/Users/li/github/twitchSquatsBot/twitch_eventsub_listener.py), a webhook listener for Twitch channel point redemptions on `nannersowo`.

It listens for:

- `channel.channel_points_custom_reward_redemption.add`

The listener:

- verifies Twitch webhook signatures
- handles the EventSub verification challenge
- logs every incoming redemption event
- prints a simple line like `viewername redeemed reward-title` when the reward matches
- serves a local squat popup page with webcam-based counting
- can auto-open the popup page when a matching redemption arrives
- can gate the popup through `script.py` so redeems only count when the Riot check returns `false`

## Twitch Prereqs

You need:

- a Twitch app `client_id`
- a Twitch app `client_secret`
- a broadcaster user access token for `nannersowo`
- an app access token for creating webhook subscriptions
- a public HTTPS callback URL, such as an `ngrok` tunnel
- an EventSub signing secret that you choose yourself

## Twitch App Setup

Create a Twitch app at:

- [https://dev.twitch.tv/console/apps](https://dev.twitch.tv/console/apps)

Set the OAuth redirect URL to:

```text
http://localhost:3000
```

After the app is created, save:

- `client_id`
- `client_secret`

## Broadcaster User Token

Log into Twitch as `nannersowo`, then open this authorize URL in your browser, replacing `YOUR_CLIENT_ID`:

```text
https://id.twitch.tv/oauth2/authorize?response_type=code&client_id=YOUR_CLIENT_ID&redirect_uri=http%3A%2F%2Flocalhost%3A3000&scope=channel%3Aread%3Aredemptions&state=abc123
```

Twitch will redirect to `http://localhost:3000/?code=...`. Copy the `code` from the URL and exchange it immediately:

```bash
curl -X POST 'https://id.twitch.tv/oauth2/token' \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  -d 'client_id=YOUR_CLIENT_ID' \
  -d 'client_secret=YOUR_CLIENT_SECRET' \
  -d 'code=YOUR_FRESH_CODE' \
  -d 'grant_type=authorization_code' \
  -d 'redirect_uri=http://localhost:3000'
```

That returns:

- `access_token`
- `refresh_token`

This user token grants your app `channel:read:redemptions` for `nannersowo`.

## Broadcaster User ID

Use the broadcaster token to get `nannersowo`'s user ID:

```bash
curl -s 'https://api.twitch.tv/helix/users?login=nannersowo' \
  -H 'Client-Id: YOUR_CLIENT_ID' \
  -H 'Authorization: Bearer YOUR_BROADCASTER_ACCESS_TOKEN'
```

The response contains the broadcaster user ID. At the time this README was updated, `nannersowo` resolved to:

```text
124351362
```

## App Access Token

Create an app access token with your client ID and client secret:

```bash
curl -X POST 'https://id.twitch.tv/oauth2/token' \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  -d 'client_id=YOUR_CLIENT_ID' \
  -d 'client_secret=YOUR_CLIENT_SECRET' \
  -d 'grant_type=client_credentials'
```

Use the returned `access_token` when creating or deleting EventSub webhook subscriptions.

## ngrok Setup

Install ngrok with Homebrew if needed:

```bash
brew install ngrok/ngrok/ngrok
```

Add your ngrok auth token once:

```bash
ngrok config add-authtoken YOUR_NGROK_AUTHTOKEN
```

Start the tunnel:

```bash
ngrok http 8080
```

This gives you a public HTTPS URL like:

```text
https://your-ngrok-url.ngrok-free.dev
```

Your Twitch callback URL will be:

```text
https://your-ngrok-url.ngrok-free.dev/eventsub
```

## Start The Listener

Choose an EventSub secret yourself. It can be any long random string. A good way to generate one is:

```bash
openssl rand -hex 32
```

Then start the listener:

```bash
cd /Users/li/github/twitchSquatsBot
export TWITCH_EVENTSUB_SECRET='YOUR_EVENTSUB_SECRET'
export TARGET_REWARD_TITLE='immediately do 10 squats (in queue only'
export AUTO_OPEN_POPUP='1'
export RIOT_CHECK_ENABLED='1'
python3 twitch_eventsub_listener.py
```

Keep that terminal running.

When the listener starts, it also serves a local popup page at:

```text
http://127.0.0.1:8080/squat-popup
```

The popup page:

- asks for webcam access in the browser
- waits for matching Twitch redemptions
- counts squat reps locally in-browser using pose landmarks
- auto-focuses when the listener opens it after a redeem

## Create The EventSub Subscription

With the listener already running and ngrok already running, create the webhook subscription:

```bash
curl -X POST 'https://api.twitch.tv/helix/eventsub/subscriptions' \
  -H 'Client-Id: YOUR_CLIENT_ID' \
  -H 'Authorization: Bearer YOUR_APP_ACCESS_TOKEN' \
  -H 'Content-Type: application/json' \
  --data-raw '{"type":"channel.channel_points_custom_reward_redemption.add","version":"1","condition":{"broadcaster_user_id":"124351362"},"transport":{"method":"webhook","callback":"https://your-ngrok-url.ngrok-free.dev/eventsub","secret":"YOUR_EVENTSUB_SECRET"}}'
```

Notes:

- webhook subscriptions use the app access token, not the broadcaster user token
- the secret in the subscription must exactly match `TWITCH_EVENTSUB_SECRET`
- the listener must already be running when you create the subscription

## Check Subscription Status

Check current EventSub subscriptions:

```bash
curl -s 'https://api.twitch.tv/helix/eventsub/subscriptions' \
  -H 'Client-Id: YOUR_CLIENT_ID' \
  -H 'Authorization: Bearer YOUR_APP_ACCESS_TOKEN'
```

Useful statuses:

- `enabled` means Twitch is actively sending events
- `webhook_callback_verification_pending` means Twitch is trying to verify the webhook
- `webhook_callback_verification_failed` means the webhook setup failed and should be deleted/recreated

## Delete A Failed Subscription

Delete a failed subscription by ID:

```bash
curl -X DELETE 'https://api.twitch.tv/helix/eventsub/subscriptions?id=SUBSCRIPTION_ID_HERE' \
  -H 'Client-Id: YOUR_CLIENT_ID' \
  -H 'Authorization: Bearer YOUR_APP_ACCESS_TOKEN'
```

Then recreate it while the listener is already running.

## Expected Output

When Twitch verifies the webhook, the listener should accept the verification request and stay running.

When someone redeems the matching reward in `nannersowo` chat, the listener prints:

```text
viewername redeemed immediately do 10 squats (in queue only
```

It also prints JSON logs for incoming redemption events.

If `AUTO_OPEN_POPUP='1'`, the listener also opens:

```text
http://127.0.0.1:8080/squat-popup
```

On that page, allow camera access and keep your full body in frame.

## Riot-Gated Redeem Flow

The current command-line wiring is:

1. A viewer redeems the matching Twitch reward
2. `twitch_eventsub_listener.py` runs `script.py`
3. If `script.py` prints `false`, the listener treats the Riot player as idle and adds the squat reward to the popup queue
4. If `script.py` prints `true`, the listener skips the redeem and logs a `riot_gate` JSON line with `"allowed": false`

By default, the listener runs:

```bash
python3 script.py
```

You can override that command if needed:

```bash
export RIOT_CHECK_COMMAND='python3 script.py'
```

If you want to disable the Riot gate entirely:

```bash
export RIOT_CHECK_ENABLED='0'
```

Important:

- `script.py` currently uses recent public match data as a proxy
- `false` means "allow squats popup"
- `true` means "skip because the Riot check thinks the player is still active"
- this is not a guaranteed live in-game detector, because Riot's public API no longer exposes everything needed for a true spectator check in this setup

Default local callback:

- `http://localhost:8080/eventsub`

For real Twitch delivery, the callback must be publicly reachable over `https`. `ngrok` is the easiest local-development option.

Relevant docs:

- [Handling webhook events](https://dev.twitch.tv/docs/eventsub/handling-webhook-events/)
- [EventSub subscription types](https://dev.twitch.tv/docs/eventsub/eventsub-subscription-types/)
- [API reference](https://dev.twitch.tv/docs/api/reference)
