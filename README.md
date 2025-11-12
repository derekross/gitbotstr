# GitBotstr

A Python bot that monitors Git repositories (GitHub, GitLab, or any Git repo) and posts new commits to Nostr as NIP-29 community notes.

## Features

- Monitors any Git repository for new commits
- Posts commits to Nostr as NIP-29 relay-based group messages
- Supports GitHub, GitLab, and generic Git repositories
- Configurable polling interval
- Persistent state tracking to avoid duplicate posts
- Automatic commit URL generation

## Requirements

- Python 3.8+
- Git command-line tools
- Nostr keypair (nsec)
- Access to a NIP-29 compatible relay and group

## Installation

1. Clone this repository:
```bash
git clone <repository-url>
cd gitbotstr
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

## Configuration

1. Create a configuration file:
```bash
python gitbotstr.py --create-config --config config.json
```

2. Edit `config.json` with your settings:
```json
{
  "repo_url": "https://github.com/user/repo.git",
  "nsec": "nsec1your-private-key-here",
  "community_relay": "wss://relay.example.com",
  "community_id": "your-group-id",
  "poll_interval": 60,
  "repo_type": "github"
}
```

### Configuration Parameters

- `repo_url`: The Git repository URL to monitor (HTTPS or SSH)
- `nsec`: Your Nostr private key in nsec format (keep this secret!)
- `community_relay`: The WebSocket URL of the NIP-29 relay hosting your group
- `community_id`: The group ID for the NIP-29 community
- `poll_interval`: How often to check for new commits (in seconds)
- `repo_type`: Repository type - `"github"`, `"gitlab"`, or `"generic"`

### Understanding NIP-29 Groups

NIP-29 groups are identified by a combination of relay and group ID. For example:
- Relay: `wss://groups.nostr.com`
- Group ID: `bitcoin-dev`
- Full identifier: `groups.nostr.com'bitcoin-dev`

#### Finding Your Community Relay and ID

If you're using a NIP-29 client like Flotilla, you can extract the values from the URL:

Example: `https://app.flotilla.social/spaces/community.shakespeare.diy/9512155132705925`
- **Community Relay**: `wss://community.shakespeare.diy`
- **Community ID**: `9512155132705925`

The relay is the domain part (add `wss://` prefix), and the community ID is the final path segment (can be numeric or alphanumeric).

To use this bot:
1. You need to be a member of the NIP-29 group
2. The bot's npub (derived from your nsec) must have posting permissions in the group
3. The relay must support NIP-29 group functionality

### Getting Your Bot's npub

After creating your config, get the bot's public key using the Nostr SDK:

```bash
python3 -c "from nostr_sdk import Keys; import json; config = json.load(open('config.json')); keys = Keys.parse(config['nsec']); print('Bot npub:', keys.public_key().to_bech32())"
```

Give this npub to your group administrator so they can add the bot as a member of the NIP-29 group.

## Usage

Run the bot:
```bash
python gitbotstr.py --config config.json
```

The bot will:
1. Clone the repository (or pull updates if already cloned)
2. Check for new commits since the last run
3. Post each new commit to the Nostr group
4. Wait for the poll interval and repeat

### First Run

On the first run, the bot will only post the latest commit to avoid flooding your group with historical commits. Subsequent runs will post all new commits since the last check.

### Running as a Service

#### Using systemd (Linux)

Create a service file at `/etc/systemd/system/gitbotstr.service`:

```ini
[Unit]
Description=GitBotstr - Git to Nostr Bot
After=network.target

[Service]
Type=simple
User=your-username
WorkingDirectory=/path/to/gitbotstr
ExecStart=/usr/bin/python3 /path/to/gitbotstr/gitbotstr.py --config /path/to/config.json
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start the service:
```bash
sudo systemctl enable gitbotstr
sudo systemctl start gitbotstr
sudo systemctl status gitbotstr
```

View logs:
```bash
sudo journalctl -u gitbotstr -f
```

## Commit Message Format

Each commit is posted to Nostr with the following format:

```
New commit by Author Name

📝 Commit subject line

Commit body (if present)

🔗 https://github.com/user/repo/commit/abc123
```

## State Management & Continuous Monitoring

The bot maintains state in `gitbotstr_state.json` to track the last processed commit. This provides:

**✅ No Duplicate Posts**
- Each commit is posted exactly once
- State is saved immediately after successful posting
- Restarts are safe - bot resumes from last successful commit

**✅ Continuous Monitoring**
- Bot runs in an infinite loop, checking for new commits every `poll_interval` seconds
- When run as a systemd service, it monitors 24/7
- New commits are detected and posted automatically

**✅ Resilience**
- If the bot crashes or is restarted, it picks up where it left off
- Old commits are never reposted
- Only new commits since the last posted commit are published

**How it works:**
1. On first run: Posts only the latest commit (to avoid spam)
2. Saves that commit hash to `gitbotstr_state.json`
3. Every `poll_interval` seconds: Checks for commits newer than saved hash
4. Posts any new commits found
5. Updates state file after each successful post
6. On restart: Loads saved hash and continues from there

## Security Considerations

1. **Protect your nsec**: Never commit your `config.json` with the nsec to version control
2. **Use a dedicated key**: Consider creating a dedicated Nostr keypair for the bot
3. **Repository access**: The bot needs read access to the repository
4. **Group permissions**: Ensure the bot account has posting permissions in the NIP-29 group

## Troubleshooting

### Bot not connecting to relay

- Verify the relay URL starts with `wss://` or `ws://`
- Check if the relay is online and accessible
- Ensure the relay supports NIP-29 groups

### Commits not appearing in group

- Verify you're using the correct group ID
- Check that the bot's npub is a member of the group
- Ensure the group allows posting from members
- Look at bot logs for error messages

### Repository access issues

- For private repos, use SSH URLs with proper SSH key configuration
- For public repos, HTTPS URLs should work without authentication
- Ensure Git is installed and accessible: `git --version`

### Permission denied errors

- Make sure the bot has write permissions to create `gitbotstr_state.json`
- Verify the bot can create temporary directories for cloning

## Development

To modify the bot:

1. The main bot logic is in `gitbotstr.py`
2. Key classes:
   - `GitMonitor`: Handles repository cloning and commit detection
   - `NostrPublisher`: Manages Nostr client and event publishing
   - `GitBotstr`: Main bot orchestrator
   - `Config`: Configuration management

## Contributing

Contributions are welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## License

MIT License - See LICENSE file for details

## Resources

- [NIP-29 Specification](https://github.com/nostr-protocol/nips/blob/master/29.md)
- [Nostr SDK Python](https://github.com/rust-nostr/nostr-sdk-python)
- [Nostr Protocol](https://nostr.com)

## Support

For issues and questions:
- Open an issue on GitHub
- Contact via Nostr: [your-npub-here]
