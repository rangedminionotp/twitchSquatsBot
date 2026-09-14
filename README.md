# twitchSquatsBot

Small Riot/Twitch utility repo with:

- a fail-closed Riot gate that checks whether all configured League accounts are out of game
- a Twitch EventSub listener for channel point redemptions on the connected broadcaster account
- persistent owed and completed squat counters shown in the control page, capture page, and OBS overlay

## Windows quick start (recommended)

The app now supports Twitch EventSub over WebSocket, so a local desktop user does
not need ngrok, a public callback, or an EventSub signing secret.

1. Install Python 3.
2. Squat Capture includes its public Twitch Client ID. No developer setup is needed.
3. Run:

```powershell
.\start_windows.ps1
```

4. Open [http://127.0.0.1:8080/control](http://127.0.0.1:8080/control).
5. Click **Connect with Twitch**, authorize the app on Twitch, and select
   the channel point reward to watch.
6. Open the capture page and add the displayed overlay URL as an OBS Browser Source.

The first run creates `.venv` and installs the packages in `requirements.txt`.
Settings and the Twitch session are stored locally in
`%USERPROFILE%\.squat-capture\config.json`; keep that file private. The older
webhook/ngrok setup below is still available for compatibility.

### WSL

From a WSL/bash terminal, use the Linux launcher instead of the PowerShell script:

```bash
chmod +x start_wsl.sh
./start_wsl.sh
```

Then open `http://127.0.0.1:8080/control` in the Windows browser. If Python's venv
module is missing, install it with `sudo apt install python3-venv` and run the
launcher again.

## What it does

The League all-idle gate is optional and disabled by default. When enabled, it uses Riot's public APIs:

1. `account-v1` resolves every configured `GameName#TagLine` into a PUUID.
2. `spectator-v5` checks every PUUID for an active League game.
3. The redeem is accepted only when every configured account is confirmed idle.

The gate fails closed: an active account, expired API key, invalid Riot ID, network
failure, or unexpected API response blocks the redeem instead of accidentally
allowing it.

## Riot Setup

Open `/control`, enable **League all-idle gate**, paste a Riot development API key,
and enter one Riot ID per line. Use **Test League gate now** before streaming.

`script.py` prints `false` only when all accounts are idle (allow redeem), and
prints `true` for active or unknown state (block redeem).

## Routing notes

- `ACCOUNT_REGION` is `americas`, `asia`, or `europe`
- `PLATFORM_REGION` is the League shard, such as `na1`, `euw1`, or `kr`

Examples:

- North America: routing `americas`, platform `na1`
- EU West: routing `europe`, platform `euw1`
- Korea: routing `asia`, platform `kr`

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
# Auto-add squats from support

## Diagnostics and safe testing

The control panel now includes **Connection health**, with separate Channel Points,
Subs/gifts and Bits listener readiness. **Check again** refreshes the status; it
does not reconnect or change permissions. Use Connect with Twitch for reauthorization.
**Recent activity** retains the last 100 counter records across restarts. Its
received-support-event diagnostics keep the last 30 decisions in memory, including
duplicate events and ignored amounts. History starts with this version; old events
cannot be reconstructed. Raw payloads, donor messages and credentials are not logged.
**Safe rule test** previews saved source rules only, without payments, real counter
updates or event ingestion. A passing rule preview does not verify provider delivery.

## Counter scopes

Owed is the overall remaining debt across broadcasts. Completed now represents
the current Twitch broadcast (the last broadcast while offline), not lifetime reps.
The app checks [Twitch Get Streams](https://dev.twitch.tv/docs/api/reference#get-streams)
every 15 seconds while connected. A different broadcast ID starts Completed at zero;
restarting the app, refreshing OBS, or reconnecting to the same ID does not reset it.
Detection can lag Twitch by the polling interval/API latency. If Twitch is offline
or its status is unavailable, reps still reduce Owed and increase the internally
retained lifetime total, but do not increase stream Completed. No retroactive
attribution is made for reps completed while stream status was unknown.
Previous all-time counts are preserved internally (`lifetime_squats` in the stats
API); they are not guessed to belong to the first detected stream. Manual Completed
corrections now apply only to the stream counter.

In **Auto-add squats**, independently enable Twitch subs, Twitch Bits, Streamlabs,
and/or StreamElements. Set a squat amount for each source. All are off by default.
Save rules, then reconnect Twitch after first enabling Sub or Bits so it can grant
`channel:read:subscriptions` / `bits:read` permissions.

- Subs: each new or gifted subscription adds the configured amount. Gift bundles
  count each gift once. Automatic renewals / resub chat messages are not counted.
- Bits: every configured whole unit adds the configured squats.
- Streamlabs / StreamElements: choose an amount, currency and squat increment for
  each provider. E.g. per USD 2.50 → 4 squats; USD 5.01 adds 8. Remainders are
  discarded per event. Other currencies are ignored (no exchange conversion).
- Streamlabs needs a [Socket API token](https://dev.streamlabs.com/v1/docs/socket-api).
- StreamElements needs its channel ID and channel JWT, documented under
  [WebSocket authentication](https://docs.streamelements.com/websockets).
  The adapter listens to successful `channel.tips` events.

Only **owed** increases; completed stays unchanged. The League gate does not block
accrual and support does not launch capture. Keep the app running: these are live
listeners, not an offline payment-history sync. Refunds are not reversed automatically.
Provider event IDs are saved with counters to prevent replay after restarts.
Streamlabs/StreamElements mirrored Twitch events are ignored; Twitch handles subs/Bits.
Do not relay the same payment between donation providers or enable provider test
alerts against production counters: not all providers mark simulated events.

Tokens are stored in the local config file, masked in the settings API, and never
included in connection error messages. Keep the control panel local/trusted; do not
expose its unauthenticated server to the internet. Blank token fields keep saved tokens.
