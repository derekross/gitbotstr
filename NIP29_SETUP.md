# NIP-29 Setup Guide for GitBotstr

This guide helps you configure GitBotstr to work with NIP-29 relay-based groups.

## What is NIP-29?

NIP-29 defines relay-based groups - communities hosted on specific Nostr relays where:
- Groups are identified by a unique ID
- Only members can post messages
- All group messages include an `h` tag with the group ID
- Groups can be public (anyone can read) or private (only members can read)

## Finding Your NIP-29 Community Information

### Method 1: Using Flotilla (or similar NIP-29 client)

1. Open your NIP-29 community in your client
2. Look at the URL in your browser

Example URL: `https://app.flotilla.social/spaces/community.shakespeare.diy/9512155132705925`

Extract the values:
- **Domain**: `community.shakespeare.diy` (the part after `/spaces/`)
- **Channel ID**: `9512155132705925` (the final path segment)

Convert to config values:
- **community_relay**: `wss://community.shakespeare.diy` (add `wss://` prefix)
- **community_id**: `9512155132705925` (use as-is)

### Method 2: Ask Your Group Admin

If you're not sure about the relay or group ID:
1. Contact your group administrator
2. Ask for:
   - The relay WebSocket URL (should start with `wss://`)
   - The group/channel ID

### Method 3: Using a Nostr Client

1. Open your Nostr client that supports NIP-29
2. Navigate to the group settings or info page
3. Look for:
   - Relay URL
   - Group ID or Channel ID

## Configuring GitBotstr

Once you have your relay and group ID, create your `config.json`:

```json
{
  "repo_url": "https://github.com/your-org/your-repo.git",
  "nsec": "nsec1your-secret-key-here",
  "community_relay": "wss://community.shakespeare.diy",
  "community_id": "9512155132705925",
  "poll_interval": 60,
  "repo_type": "github"
}
```

## Bot Account Setup

### Step 1: Generate or Use a Nostr Key

You can either:
- **Use an existing key**: Use your personal nsec (not recommended for production)
- **Create a dedicated bot key**: Generate a new keypair just for the bot (recommended)

To generate a new key, use any Nostr client or key generator:
- Alby extension
- nak CLI tool: `nak key generate`
- Any Nostr client's account creation flow

Save the **nsec** (private key) securely - this goes in your config.

### Step 2: Get the Bot's npub

From your nsec, derive the npub (public key):
- Use a Nostr client
- Use nak: `nak key public <nsec>`
- Use an online converter (be careful with nsec security!)

### Step 3: Add Bot to the NIP-29 Group

The bot must be a member of the group before it can post:

1. Contact your group administrator
2. Provide them with the bot's **npub** (NOT the nsec!)
3. Ask them to add the bot as a member

The admin will need to send a `kind:9000` event to add your bot to the group.

### Step 4: Verify Bot Membership

Before running the bot, verify it's a member:
1. Use your Nostr client to connect with the bot's nsec
2. Navigate to the group
3. Confirm you can see the group and its messages
4. Try posting a test message manually

If you can post manually, the bot should be able to post too.

## Testing Your Configuration

### Quick Test

1. Start the bot: `python gitbotstr.py`
2. Check the logs for:
   - "Connecting to relay: wss://..."
   - "Found X new commit(s)"
   - "Publishing commit..."
   - "Published event: ..."

3. If you see errors, check the troubleshooting section below

### Manual Test

Test that your bot can connect and publish to the relay:

```python
import asyncio
from nostr_sdk import Keys, Client, NostrSigner, EventBuilder, Tag

async def test():
    keys = Keys.parse("nsec1...")
    signer = NostrSigner.keys(keys)
    client = Client(signer)

    await client.add_relay("wss://community.shakespeare.diy")
    await client.connect()

    # Create a test message
    builder = EventBuilder.text_note("Test message from GitBotstr bot")
    builder = builder.add_tags([Tag.parse(["h", "9512155132705925"])])
    event = await builder.to_event(keys)

    result = await client.send_event(event)
    print(f"Published: {result}")

    await client.disconnect()

asyncio.run(test())
```

## Common Issues and Solutions

### "Failed to connect to relay"

**Possible causes:**
- Relay URL is incorrect
- Relay is offline
- Network/firewall blocking WebSocket connections

**Solutions:**
- Verify relay URL starts with `wss://` (or `ws://` for local testing)
- Check if relay is online: use a Nostr client to connect
- Try a different network or disable firewall temporarily

### "Permission denied" or "Event rejected"

**Possible causes:**
- Bot is not a member of the group
- Group is closed and bot wasn't properly added
- Bot doesn't have posting permissions

**Solutions:**
- Verify bot's npub is in the group member list
- Ask admin to re-add the bot with proper permissions
- Check if group requires special roles for posting

### "Wrong group ID"

**Possible causes:**
- Group ID is incorrect
- Using the wrong channel within a community

**Solutions:**
- Double-check the group ID from your client URL
- Verify with group admin
- Try fetching group metadata with a Nostr client

### Events Not Appearing in Group

**Possible causes:**
- Events are being published but to wrong group
- Client not showing bot messages
- Delay in relay propagation

**Solutions:**
- Check bot logs for published event IDs
- Use a different Nostr client to verify
- Query the relay directly for events with the group's `h` tag
- Wait a few moments and refresh

## Advanced Configuration

### Using AUTH for Private Groups

Some private groups require AUTH. The nostr-sdk library handles this automatically, but ensure:
- Your relay supports NIP-42 AUTH
- Your bot's key is authorized for the group

### Multiple Channels in Same Relay

If you want to post to multiple channels:
1. Run multiple bot instances with different configs
2. Or modify the bot to support multiple group IDs

### Rate Limiting

Some relays may rate-limit posting. If you have a very active repository:
- Increase `poll_interval` to reduce check frequency
- Add delays between posts (already implemented: 2 seconds)
- Contact relay admin about rate limits

## NIP-29 Resources

- [NIP-29 Specification](https://github.com/nostr-protocol/nips/blob/master/29.md)
- [Flotilla - NIP-29 Client](https://flotilla.social)
- [Nostr Protocol Documentation](https://nostr.com)

## Getting Help

If you're still having issues:
1. Check the bot logs for specific error messages
2. Verify your setup step-by-step with this guide
3. Test with a simpler, public group first
4. Reach out to your group admin for assistance
5. Open an issue on the GitBotstr repository with logs

## Example Working Configuration

Here's a verified working example (with placeholder credentials):

```json
{
  "repo_url": "https://gitlab.com/soapbox-pub/shakespeare.git",
  "nsec": "nsec1xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "community_relay": "wss://community.shakespeare.diy",
  "community_id": "9512155132705925",
  "poll_interval": 120,
  "repo_type": "gitlab"
}
```

Expected behavior:
- Bot checks every 120 seconds (2 minutes)
- Posts appear in the specified channel with commit details
- Messages include the `h` tag for NIP-29 compliance
