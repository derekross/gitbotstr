# GitBotstr Quick Start Guide

Get your Git-to-Nostr bot running in 5 minutes!

## Prerequisites

- Python 3.8 or higher
- Git installed (`git --version` to check)
- A Nostr private key (nsec)
- Access to a NIP-29 group on a compatible relay

## Step 1: Install Dependencies

```bash
pip install -r requirements.txt
```

## Step 2: Create Configuration

```bash
python gitbotstr.py --create-config
```

This creates `config.json`. Edit it with your details:

```json
{
  "repo_url": "https://gitlab.com/soapbox-pub/shakespeare.git",
  "nsec": "nsec1your-actual-private-key-here",
  "community_relay": "wss://community.shakespeare.diy",
  "community_id": "9512155132705925",
  "poll_interval": 60,
  "repo_type": "gitlab"
}
```

### Getting Your Configuration Values

#### 1. Repository URL (`repo_url`)
- GitHub: `https://github.com/username/repository.git`
- GitLab: `https://gitlab.com/username/repository.git`
- Or any Git URL (HTTPS or SSH)

#### 2. Nostr Private Key (`nsec`)
- If you don't have one, generate it using a Nostr client
- NEVER share your nsec with anyone
- Consider creating a dedicated key just for the bot

#### 3. Community Relay (`community_relay`)
- Must be a relay that supports NIP-29
- Format: `wss://relay.example.com`
- Examples:
  - `wss://community.shakespeare.diy`
  - `wss://groups.fiatjaf.com`
  - `wss://relay.damus.io`

#### 4. Community ID (`community_id`)
- The group/channel ID you want to post to
- This is the numeric or string identifier for the specific channel
- From the Flotilla URL `https://app.flotilla.social/spaces/community.shakespeare.diy/9512155132705925`:
  - The community ID would be `9512155132705925`
- Ask your group admin for this, or find it in your NIP-29 client URL

#### 5. Repository Type (`repo_type`)
- `"github"` for GitHub repositories
- `"gitlab"` for GitLab repositories
- `"generic"` for other Git hosts

## Step 3: Get Your Bot's npub and Add to Group

**IMPORTANT:** Before running the bot, you must add it to the NIP-29 group!

```bash
python3 -c "from nostr_sdk import Keys; import json; config = json.load(open('config.json')); keys = Keys.parse(config['nsec']); print('Bot npub:', keys.public_key().to_bech32())"
```

Copy the npub and:
1. Contact your NIP-29 group administrator
2. Ask them to add this npub as a member
3. Wait for confirmation that the bot has been added

## Step 4: Run the Bot

```bash
python gitbotstr.py
```

You should see output like:

```
2025-11-11 20:00:00 - __main__ - INFO - Starting GitBotstr...
2025-11-11 20:00:00 - __main__ - INFO - Monitoring: https://gitlab.com/soapbox-pub/shakespeare.git
2025-11-11 20:00:00 - __main__ - INFO - Community: 9512155132705925
2025-11-11 20:00:00 - __main__ - INFO - Relay: wss://community.shakespeare.diy
2025-11-11 20:00:01 - __main__ - INFO - Connecting to relay: wss://community.shakespeare.diy
2025-11-11 20:00:02 - __main__ - INFO - Publishing commit 35a85c18 to Nostr
2025-11-11 20:00:03 - __main__ - INFO - Published event: ...success...
```

## Step 5: Verify It's Working

1. Check the bot logs for "Published event" messages
2. Open your Nostr client and navigate to the group
3. You should see commit notifications appearing

## Common Issues

### "Failed to connect to relay"
- Check that the relay URL is correct and starts with `wss://`
- Verify the relay is online
- Ensure your network allows WebSocket connections

### "restricted: you are not a member of this relay"
- Your bot's npub must be a member of the NIP-29 group
- Get your bot's npub using the command from Step 3
- Ask the group admin to add your bot's public key to the group
- This is the most common issue on first run!

### "Repository not found"
- Verify the repository URL is correct
- For private repos, you may need SSH authentication
- Test manually: `git clone <repo_url>`

### No commits appearing
- The bot only posts NEW commits after it starts
- On first run, it posts only the latest commit
- Wait for a new commit to be pushed to verify

## Tips

1. **Test with a small repo first** to make sure everything works
2. **Use a low poll_interval** (like 60 seconds) for active repos
3. **Monitor the logs** initially to catch any issues
4. **Set up as a service** (see README.md) for production use

## Need Help?

See the full README.md for:
- Detailed configuration options
- Running as a systemd service
- Security best practices
- Troubleshooting guide

Happy botting! 🤖⚡
