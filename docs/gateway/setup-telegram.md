# Setting Up the Telegram Gateway

MagAgent's Telegram gateway uses polling mode — no public URL, webhook, or hosting required. Completely free. Setup takes about 2 minutes.

## Step 1: Create a Telegram Bot

1. Open Telegram and search for **@BotFather** (the official bot creation bot)
2. Send `/start`
3. Send `/newbot`
4. Choose a **name** (display name, e.g. `MagAgent`)
5. Choose a **username** (must end in `bot`, e.g. `my_magagent_bot`)
6. BotFather replies with your **bot token** — looks like `1234567890:ABCDEfghij...`

That's it for bot creation. Save the token.

## Step 2: Find Your Telegram User ID

Your Telegram **user ID** is a numeric ID (not your username).

**Method 1 — @userinfobot:**
1. Search for `@userinfobot` in Telegram
2. Send it `/start`
3. It replies with your ID: `Your ID: 123456789`

**Method 2 — @RawDataBot:**
1. Forward any message to `@RawDataBot`
2. Look for `"from": {"id": 123456789, ...}` in the response

## Step 3: Configure MagAgent

Add to `~/.config/magent/config.toml`:

```toml
[gateway]
username = "your_magent_username"
allowed_user_ids = ["123456789"]   # Your Telegram numeric user ID (as string)
rate_limit_per_minute = 10
max_task_duration_seconds = 300

[gateway.telegram]
bot_token = "1234567890:ABCDEfghijKLMNOpqrstu..."
respond_to_dms = true
respond_to_groups = false          # Set true to also respond in group chats
# command_prefix = "/agent"        # Trigger prefix in groups
```

> **Tip:** Keep `respond_to_groups = false` unless you specifically want the bot active in group chats. In private DMs it responds to everything; in groups it only responds to `/ask`, `/agent`, or messages with `@your_bot_username`.

## Step 4: Start the Gateway

```bash
# Background daemon
magent gateway start telegram

# Foreground for debugging
magent gateway start telegram --foreground
```

## Using the Gateway

**Private DM with your bot:**
```
Create a Python script that monitors a directory for new files and prints their names
```

**Using commands (work in DMs and groups):**
```
/ask explain what a binary search tree is
/agent write a Dockerfile for a Node.js app
```

**In a group (if enabled):**
```
@your_magagent_bot what's wrong with this SQL query: SELECT * FROM users WHERE id = ?
```

MagAgent immediately sends `⏳ Working on it...` with a typing indicator, then edits that message with the full response when done. Long responses are split into multiple messages automatically.

## Group Chat Setup (Optional)

If you want MagAgent in a group:

1. Add your bot to the group
2. Send `/start` in the group to wake the bot
3. Make sure `respond_to_groups = true` in config
4. Use `/ask <question>` or `@your_bot_username <question>` to interact

### Disable Group Privacy Mode

By default, Telegram bots in groups only see messages starting with `/`. To let MagAgent see all messages:

1. Message **@BotFather**
2. Send `/mybots` → select your bot
3. **Bot Settings → Group Privacy → Turn off**

## Bot Commands Menu (Optional Polish)

Tell BotFather to show a commands menu:

1. Send `/mybots` to @BotFather
2. Select your bot → **Edit Bot → Edit Commands**
3. Paste:
   ```
   ask - Ask MagAgent a question
   agent - Give MagAgent a task
   ```

## Checking Status / Logs

```bash
magent gateway status
magent gateway logs           # Last 50 lines
magent gateway logs --follow  # Live stream  
magent gateway stop
```

## Troubleshooting

| Problem | Solution |
|---|---|
| Bot doesn't respond | Verify your numeric user ID is in `allowed_user_ids` |
| `Unauthorized` error | Bot token is invalid — get a new one from @BotFather with `/token` |
| Bot responds to wrong users | Check `allowed_user_ids` — use numeric IDs not usernames |
| Bot doesn't see group messages | Disable Group Privacy Mode via @BotFather (see above) |
| `/ask` works but text doesn't | Bot can't read non-command messages — disable Group Privacy Mode |
| Polling conflict error | Only one gateway instance can run at a time — stop existing one first |

## Security Notes

- The allowlist (`allowed_user_ids`) is your primary security layer — only listed users can send instructions
- Anyone who gets your bot link can DM it but will be blocked if not on the allowlist
- Set `respond_to_groups = false` unless you trust everyone in the group
- Your bot token is equivalent to full bot access — keep it private
