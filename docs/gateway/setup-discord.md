# Setting Up the Discord Gateway

MagAgent's Discord gateway uses `discord.py` with a persistent bot connection. Completely free — you just need a Discord account.

## Step 1: Create a Discord Application

1. Go to [discord.com/developers/applications](https://discord.com/developers/applications)
2. Click **New Application** → name it `MagAgent` → **Create**
3. Click **Bot** in the left sidebar
4. Click **Add Bot** → **Yes, do it!**

## Step 2: Get the Bot Token

1. Under **Token**, click **Reset Token** → **Yes, do it!**
2. Click **Copy** — this is your **bot_token**
3. Store it safely — you can only view it once (reset again if lost)

## Step 3: Enable Privileged Intents

Still on the **Bot** page, scroll down to **Privileged Gateway Intents** and enable:

- ✅ **Message Content Intent** — required to read message text
- ✅ **Direct Message Intent** (enabled by default)

Click **Save Changes**.

## Step 4: Find Your Discord User ID

Enable Developer Mode to copy user IDs:

1. **Settings → Advanced → Developer Mode** → ON
2. Right-click your own username anywhere → **Copy User ID**
3. It's a long number like `123456789012345678`

## Step 5: Invite the Bot to Your Server

1. Go to **OAuth2 → URL Generator** in the left sidebar
2. Under **Scopes**, check `bot`
3. Under **Bot Permissions**, check:
   - `Read Messages/View Channels`
   - `Send Messages`
   - `Read Message History`
4. Copy the generated URL → paste in browser → invite to your server

## Step 6: Configure MagAgent

Add to `~/.config/magent/config.toml`:

```toml
[gateway]
username = "your_magent_username"
allowed_user_ids = ["123456789012345678"]  # Your Discord user ID
rate_limit_per_minute = 10
max_task_duration_seconds = 300

[gateway.discord]
bot_token = "your-discord-bot-token"
respond_to_dms = true
respond_in_guilds = true
# command_prefix = "!agent "   # Optional: trigger without @mention
```

## Step 7: Start the Gateway

```bash
# Background daemon
magent gateway start discord

# Foreground for debugging
magent gateway start discord --foreground
```

## Using the Gateway

**In a DM to MagAgent:**
```
Write a FastAPI endpoint that accepts a POST request with a JSON body
```

**In a server channel (requires @mention):**
```
@MagAgent what's the difference between asyncio.gather and asyncio.wait?
```

**With command prefix (if configured):**
```
!agent create a Dockerfile for a Python 3.11 FastAPI app
```

MagAgent replies `⏳ Working on it...` instantly, then edits that message with the result. Long responses are split into multiple messages automatically.

## Tips

- **Keep MagAgent DMs open** — the easiest way to use it privately
- **One session per channel** — MagAgent maintains conversation context per channel, so it remembers earlier messages in that channel
- **Works in threads too** — MagAgent can see thread replies

## Checking Status / Logs

```bash
magent gateway status
magent gateway logs --follow  # Live stream
magent gateway stop
```

## Troubleshooting

| Problem | Solution |
|---|---|
| Bot online but not responding in channels | Check `respond_in_guilds = true` and that you @mentioned it |
| `Privileged intent` error | Enable Message Content Intent in Developer Portal |
| `Invalid token` | Reset token in Developer Portal and update config |
| Bot not reading DMs | Check `respond_to_dms = true` and `Direct Message Intent` is enabled |
| `User not in allowlist` | Verify your user ID (18-digit number, not username) |
