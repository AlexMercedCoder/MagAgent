# Setting Up the Slack Gateway

MagAgent's Slack gateway uses **Socket Mode** — the bot connects *out* to Slack's servers, so you don't need a public URL, domain, or any hosting. Works on free Slack workspaces.

## Step 1: Create a Slack App

1. Go to [api.slack.com/apps](https://api.slack.com/apps) and click **Create New App → From scratch**
2. Name it `MagAgent` and select your workspace
3. Click **Create App**

## Step 2: Enable Socket Mode

1. In the left sidebar, click **Socket Mode**
2. Toggle **Enable Socket Mode** to ON
3. Click **Generate an app-level token**
   - Name: `magent-socket`
   - Scopes: add `connections:write`
   - Click **Generate**
4. Copy the token — it starts with `xapp-` — this is your **app_token**

## Step 3: Configure Bot Permissions

1. In the left sidebar, click **OAuth & Permissions**
2. Under **Bot Token Scopes**, add these scopes:
   - `chat:write` — send messages
   - `chat:write.public` — post in channels without being invited
   - `channels:history` — read channel messages
   - `im:history` — read DMs
   - `users:read` — resolve display names
3. Click **Install App to Workspace** at the top of that page
4. Copy the **Bot User OAuth Token** — starts with `xoxb-` — this is your **bot_token**

## Step 4: Enable Events

1. In the left sidebar, click **Event Subscriptions**
2. Toggle **Enable Events** to ON
3. Under **Subscribe to bot events**, add:
   - `message.channels` — messages in public channels
   - `message.im` — direct messages
   - `app_mention` — @mentions

## Step 5: Find Your User ID

You need your Slack **user ID** (not username) for the allowlist:

1. Open Slack → click your profile picture → **Profile**
2. Click the `⋮` (more) button → **Copy member ID**
3. It looks like `U01234ABCDE`

## Step 6: Configure MagAgent

Run `magent gateway init` to see the config template, then add to `~/.config/magent/config.toml`:

```toml
[gateway]
username = "your_magent_username"
allowed_user_ids = ["U01234ABCDE"]   # Your Slack user ID
rate_limit_per_minute = 10
max_task_duration_seconds = 300

[gateway.slack]
bot_token = "xoxb-your-bot-token-here"
app_token = "xapp-your-app-token-here"
```

## Step 7: Invite Bot to Channels

In Slack, type `/invite @MagAgent` in any channel you want it to monitor.
For DMs, just open a direct message with MagAgent.

## Step 8: Start the Gateway

```bash
# Background daemon (recommended)
magent gateway start slack

# Foreground for debugging
magent gateway start slack --foreground
```

## Using the Gateway

**In a DM to MagAgent:**
```
Write me a Python script that reads a CSV and outputs a summary
```

**In a channel (requires @mention):**
```
@MagAgent explain what this code does: [paste code]
```

MagAgent will immediately reply with `⏳ Working on it...` then edit that message with the result.

## Checking Status / Logs

```bash
magent gateway status         # Is it running?
magent gateway logs           # Last 50 log lines
magent gateway logs --follow  # Live log stream
magent gateway stop           # Stop daemon
```

## Troubleshooting

| Problem | Solution |
|---|---|
| Bot doesn't respond | Check `allowed_user_ids` includes your Slack user ID |
| `xapp-` token error | Ensure Socket Mode is enabled and token has `connections:write` scope |
| `xoxb-` token error | Re-install the app to workspace and copy fresh token |
| Bot responds but errors | Check `magent gateway logs` for the full error |
| Rate limited | Increase `rate_limit_per_minute` in config |
