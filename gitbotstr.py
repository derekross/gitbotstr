#!/usr/bin/env python3
"""
GitBotstr - A bot that monitors git repositories and posts commits to Nostr as NIP-29 community notes
"""

import json
import time
import hashlib
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any
from pathlib import Path
import requests
import subprocess
import tempfile
import shutil
from dataclasses import dataclass

# Nostr imports
from nostr_sdk import (
    Keys, Client, NostrSigner, EventBuilder,
    Tag, Kind, Event, Filter, PublicKey, Timestamp, RelayUrl, SingleLetterTag, Alphabet, Duration
)


@dataclass
class GitMonitorConfig:
    """Git monitor configuration"""
    enabled: bool
    repo_url: str
    community_id: str
    poll_interval: int = 60
    repo_type: str = "github"


@dataclass
class ShowcaseMonitorConfig:
    """Showcase monitor configuration"""
    enabled: bool
    moderator_npub: str
    channel_id: str
    nostr_relays: List[str]
    poll_interval: int = 300


@dataclass
class Config:
    """Bot configuration"""
    nsec: str
    community_relay: str
    git_monitor: Optional[GitMonitorConfig] = None
    showcase_monitor: Optional[ShowcaseMonitorConfig] = None

    @classmethod
    def from_file(cls, config_path: str) -> 'Config':
        """Load configuration from JSON file"""
        with open(config_path, 'r') as f:
            data = json.load(f)

        # Parse nested configs
        git_config = None
        if 'git_monitor' in data and data['git_monitor'].get('enabled'):
            git_config = GitMonitorConfig(**data['git_monitor'])

        showcase_config = None
        if 'showcase_monitor' in data and data['showcase_monitor'].get('enabled'):
            showcase_config = ShowcaseMonitorConfig(**data['showcase_monitor'])

        return cls(
            nsec=data['nsec'],
            community_relay=data['community_relay'],
            git_monitor=git_config,
            showcase_monitor=showcase_config
        )

    def to_file(self, config_path: str):
        """Save configuration to JSON file"""
        data = {
            'nsec': self.nsec,
            'community_relay': self.community_relay
        }
        if self.git_monitor:
            data['git_monitor'] = {
                'enabled': self.git_monitor.enabled,
                'repo_url': self.git_monitor.repo_url,
                'community_id': self.git_monitor.community_id,
                'poll_interval': self.git_monitor.poll_interval,
                'repo_type': self.git_monitor.repo_type
            }
        if self.showcase_monitor:
            data['showcase_monitor'] = {
                'enabled': self.showcase_monitor.enabled,
                'moderator_npub': self.showcase_monitor.moderator_npub,
                'channel_id': self.showcase_monitor.channel_id,
                'nostr_relays': self.showcase_monitor.nostr_relays,
                'poll_interval': self.showcase_monitor.poll_interval
            }
        with open(config_path, 'w') as f:
            json.dump(data, f, indent=2)


class GitMonitor:
    """Monitors a git repository for new commits"""

    def __init__(self, repo_url: str, repo_type: str = "github"):
        self.repo_url = repo_url
        self.repo_type = repo_type
        self.temp_dir = None
        self.last_commit_hash = None
        self.logger = logging.getLogger(__name__)

    def clone_or_update_repo(self) -> Path:
        """Clone repository or update if already cloned"""
        if self.temp_dir is None:
            self.temp_dir = tempfile.mkdtemp(prefix="gitbotstr_")
            self.logger.info(f"Cloning repository to {self.temp_dir}")
            subprocess.run(
                ["git", "clone", self.repo_url, self.temp_dir],
                check=True,
                capture_output=True
            )
        else:
            self.logger.info(f"Pulling updates in {self.temp_dir}")
            subprocess.run(
                ["git", "-C", self.temp_dir, "pull"],
                check=True,
                capture_output=True
            )
        return Path(self.temp_dir)

    def get_latest_commits(self, since_hash: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get commits since the last check"""
        repo_path = self.clone_or_update_repo()

        # Get commit log
        if since_hash:
            cmd = ["git", "-C", str(repo_path), "log", f"{since_hash}..HEAD",
                   "--pretty=format:%H|%an|%ae|%at|%s|%b", "--no-merges"]
        else:
            # Get only the latest commit on first run
            cmd = ["git", "-C", str(repo_path), "log", "-1",
                   "--pretty=format:%H|%an|%ae|%at|%s|%b"]

        result = subprocess.run(cmd, capture_output=True, text=True, check=True)

        commits = []
        if result.stdout.strip():
            for line in result.stdout.strip().split('\n'):
                if not line:
                    continue
                parts = line.split('|', 5)
                if len(parts) >= 5:
                    commit_hash, author_name, author_email, timestamp, subject = parts[:5]
                    body = parts[5] if len(parts) > 5 else ""

                    commits.append({
                        'hash': commit_hash,
                        'author_name': author_name,
                        'author_email': author_email,
                        'timestamp': int(timestamp),
                        'subject': subject,
                        'body': body.strip(),
                        'url': self._get_commit_url(commit_hash)
                    })

        # Reverse to get oldest first
        commits.reverse()
        return commits

    def _get_commit_url(self, commit_hash: str) -> str:
        """Generate a URL for the commit based on repo type"""
        if self.repo_type == "github":
            # Convert git@github.com:user/repo.git to https://github.com/user/repo/commit/hash
            url = self.repo_url.replace("git@github.com:", "https://github.com/")
            url = url.replace(".git", "")
            return f"{url}/commit/{commit_hash}"
        elif self.repo_type == "gitlab":
            url = self.repo_url.replace("git@gitlab.com:", "https://gitlab.com/")
            url = url.replace(".git", "")
            return f"{url}/-/commit/{commit_hash}"
        else:
            # Generic - try to infer from URL
            if "github.com" in self.repo_url:
                url = self.repo_url.replace("git@github.com:", "https://github.com/")
                url = url.replace(".git", "")
                return f"{url}/commit/{commit_hash}"
            elif "gitlab.com" in self.repo_url:
                url = self.repo_url.replace("git@gitlab.com:", "https://gitlab.com/")
                url = url.replace(".git", "")
                return f"{url}/-/commit/{commit_hash}"
            else:
                return f"{self.repo_url} - {commit_hash}"

    def cleanup(self):
        """Clean up temporary directory"""
        if self.temp_dir and Path(self.temp_dir).exists():
            shutil.rmtree(self.temp_dir)
            self.logger.info(f"Cleaned up {self.temp_dir}")


class NostrPublisher:
    """Publishes commits to Nostr as NIP-29 community notes"""

    def __init__(self, nsec: str, community_relay: str, community_id: str):
        self.community_relay = community_relay
        self.community_id = community_id
        self.logger = logging.getLogger(__name__)

        # Initialize Nostr client
        self.keys = Keys.parse(nsec)
        self.signer = NostrSigner.keys(self.keys)
        self.client = Client(self.signer)

    async def connect(self):
        """Connect to the community relay"""
        self.logger.info(f"Connecting to relay: {self.community_relay}")
        relay_url = RelayUrl.parse(self.community_relay)
        await self.client.add_relay(relay_url)
        await self.client.connect()

    async def publish_commit(self, commit: Dict[str, Any]) -> bool:
        """Publish a commit as a NIP-29 community note"""
        try:
            # Format the commit message
            content = self._format_commit_message(commit)

            # Create the event with NIP-29 h tag
            # Using kind 9 (chat message) for group chat messages
            h_tag = Tag.parse(["h", self.community_id])

            # Build and sign the event
            builder = EventBuilder(Kind(9), content)
            builder = builder.tags([h_tag])
            event = builder.sign_with_keys(self.keys)

            # Publish to the community relay
            self.logger.info(f"Publishing commit {commit['hash'][:8]} to Nostr")
            output = await self.client.send_event(event)

            self.logger.info(f"Published event: {output}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to publish commit: {e}")
            return False

    def _format_commit_message(self, commit: Dict[str, Any]) -> str:
        """Format a commit into a Nostr message"""
        message_parts = [
            f"New commit by {commit['author_name']}",
            "",
            f"📝 {commit['subject']}",
        ]

        if commit['body']:
            message_parts.extend(["", commit['body']])

        message_parts.extend([
            "",
            f"🔗 {commit['url']}"
        ])

        return "\n".join(message_parts)

    async def disconnect(self):
        """Disconnect from relay"""
        await self.client.disconnect()


class ShowcaseMonitor:
    """Monitors Nostr for featured app approvals"""

    def __init__(self, config: ShowcaseMonitorConfig, nsec: str, community_relay: str):
        self.config = config
        self.community_relay = community_relay
        self.logger = logging.getLogger(__name__)

        # Initialize Nostr client for monitoring
        keys = Keys.parse(nsec)
        signer = NostrSigner.keys(keys)
        self.client = Client(signer)
        self.keys = keys

        # Convert moderator npub to hex
        self.moderator_hex = PublicKey.parse(config.moderator_npub).to_hex()
        self.logger.info(f"Monitoring moderator: {config.moderator_npub} ({self.moderator_hex})")

        self.state_file = Path("showcase_state.json")
        self.last_featured_apps = self._load_state()

    def _load_state(self) -> set:
        """Load the last known featured apps"""
        if self.state_file.exists():
            with open(self.state_file, 'r') as f:
                state = json.load(f)
                return set(state.get('last_featured_apps', []))
        return set()

    def _save_state(self, featured_apps: set):
        """Save the current featured apps set"""
        with open(self.state_file, 'w') as f:
            json.dump({
                'last_featured_apps': list(featured_apps),
                'last_check_timestamp': int(time.time())
            }, f)

    async def connect(self):
        """Connect to Nostr relays"""
        self.logger.info(f"Connecting to Nostr relays for showcase monitoring...")

        # Add all configured relays
        for relay_url in self.config.nostr_relays:
            try:
                await self.client.add_relay(RelayUrl.parse(relay_url))
                self.logger.info(f"Added relay: {relay_url}")
            except Exception as e:
                self.logger.error(f"Failed to add relay {relay_url}: {e}")

        # Also add community relay for posting
        try:
            await self.client.add_relay(RelayUrl.parse(self.community_relay))
            self.logger.info(f"Added community relay: {self.community_relay}")
        except Exception as e:
            self.logger.error(f"Failed to add community relay: {e}")

        await self.client.connect()

    async def check_for_new_apps(self) -> List[Dict[str, Any]]:
        """Check for newly featured apps"""
        try:
            # Query for moderator's featured apps list (kind 30267)
            filter_list = Filter() \
                .kind(Kind(30267)) \
                .author(PublicKey.parse(self.moderator_hex)) \
                .custom_tag(SingleLetterTag.lowercase(Alphabet.D), 'soapbox-featured-apps') \
                .limit(10)

            self.logger.info("Querying for featured apps list...")
            timeout = Duration.from_secs(10)
            events = await self.client.fetch_events(filter_list, timeout)

            if not events:
                self.logger.info("No featured apps list found")
                return []

            # Get the most recent list
            latest_list = sorted(events, key=lambda e: e.created_at(), reverse=True)[0]
            self.logger.info(f"Found featured apps list with {len(latest_list.tags())} tags")

            # Extract app coordinates from 'a' tags
            current_featured = set()
            a_tags = []
            for tag in latest_list.tags():
                tag_list = tag.as_vec()
                if len(tag_list) >= 2 and tag_list[0] == 'a':
                    app_coord = tag_list[1]
                    current_featured.add(app_coord)
                    a_tags.append(app_coord)

            self.logger.info(f"Current featured apps: {len(current_featured)}")
            self.logger.info(f"Previously known apps: {len(self.last_featured_apps)}")

            # Find new apps
            new_apps = current_featured - self.last_featured_apps

            if not new_apps:
                self.logger.info("No new featured apps")
                return []

            self.logger.info(f"Found {len(new_apps)} new featured app(s)")

            # Fetch details for new apps
            app_details = []
            for app_coord in new_apps:
                try:
                    # Parse coordinate: "31733:pubkey:d-tag"
                    parts = app_coord.split(':')
                    if len(parts) != 3:
                        self.logger.warning(f"Invalid app coordinate: {app_coord}")
                        continue

                    kind_num, author_hex, d_tag = parts

                    # Query for the app event
                    filter_app = Filter() \
                        .kind(Kind(int(kind_num))) \
                        .author(PublicKey.parse(author_hex)) \
                        .custom_tag(SingleLetterTag.lowercase(Alphabet.D), d_tag) \
                        .limit(1)

                    timeout = Duration.from_secs(10)
                    app_events = await self.client.fetch_events(filter_app, timeout)

                    if app_events:
                        app_event = app_events[0]
                        app_data = self._parse_app_event(app_event)
                        app_data['coordinate'] = app_coord
                        app_details.append(app_data)
                        self.logger.info(f"Fetched app: {app_data.get('title', 'Unknown')}")
                    else:
                        self.logger.warning(f"Could not fetch app event for {app_coord}")

                except Exception as e:
                    self.logger.error(f"Error fetching app {app_coord}: {e}")

            # Update state
            self._save_state(current_featured)
            self.last_featured_apps = current_featured

            return app_details

        except Exception as e:
            self.logger.error(f"Error checking for new apps: {e}")
            return []

    def _parse_app_event(self, event: Event) -> Dict[str, Any]:
        """Parse app submission event into a dict"""
        app_data = {
            'title': '',
            'description': event.content(),
            'website': '',
            'repository': '',
            'icon': '',
            'screenshot': '',
            'author': event.author().to_bech32(),
            'tags': []
        }

        for tag in event.tags():
            tag_list = tag.as_vec()
            if len(tag_list) < 2:
                continue

            tag_name = tag_list[0]
            tag_value = tag_list[1]

            if tag_name == 'title':
                app_data['title'] = tag_value
            elif tag_name == 'website':
                app_data['website'] = tag_value
            elif tag_name == 'repository':
                app_data['repository'] = tag_value
            elif tag_name == 'icon':
                app_data['icon'] = tag_value
            elif tag_name == 'screenshot':
                app_data['screenshot'] = tag_value
            elif tag_name == 'app-tag':
                app_data['tags'].append(tag_value)

        return app_data

    async def publish_app_announcement(self, app: Dict[str, Any]) -> bool:
        """Publish a featured app announcement"""
        try:
            content = self._format_app_announcement(app)

            # Create the event with NIP-29 h tag
            h_tag = Tag.parse(["h", self.config.channel_id])

            # Build and sign the event
            builder = EventBuilder(Kind(9), content)
            builder = builder.tags([h_tag])
            event = builder.sign_with_keys(self.keys)

            # Publish to the community relay
            self.logger.info(f"Publishing showcase announcement for: {app.get('title', 'Unknown')}")
            output = await self.client.send_event(event)

            self.logger.info(f"Published event: {output}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to publish announcement: {e}")
            return False

    def _format_app_announcement(self, app: Dict[str, Any]) -> str:
        """Format an app announcement message"""
        message_parts = [
            f"🌟 New Featured App!",
            "",
            f"📱 {app.get('title', 'Untitled App')}"
        ]

        if app.get('description'):
            message_parts.extend(["", app['description']])

        if app.get('tags'):
            tags_str = ", ".join(app['tags'])
            message_parts.extend(["", f"🏷️ {tags_str}"])

        if app.get('website'):
            message_parts.extend(["", f"🔗 {app['website']}"])

        if app.get('repository'):
            message_parts.append(f"📦 Repository: {app['repository']}")

        message_parts.extend(["", "✨ Check it out at: https://soapbox.pub/showcase/"])

        return "\n".join(message_parts)

    async def disconnect(self):
        """Disconnect from relays"""
        await self.client.disconnect()


class GitBotstr:
    """Main bot class with support for multiple monitors"""

    def __init__(self, config: Config):
        self.config = config
        self.logger = logging.getLogger(__name__)

        # Initialize git monitor if enabled
        self.git_monitor = None
        self.git_publisher = None
        self.last_commit_hash = None
        self.git_state_file = Path("gitbotstr_state.json")

        if config.git_monitor and config.git_monitor.enabled:
            self.git_monitor = GitMonitor(
                config.git_monitor.repo_url,
                config.git_monitor.repo_type
            )
            self.git_publisher = NostrPublisher(
                config.nsec,
                config.community_relay,
                config.git_monitor.community_id
            )
            self.last_commit_hash = self._load_git_state()
            self.logger.info("Git monitor enabled")

        # Initialize showcase monitor if enabled
        self.showcase_monitor = None
        if config.showcase_monitor and config.showcase_monitor.enabled:
            self.showcase_monitor = ShowcaseMonitor(
                config.showcase_monitor,
                config.nsec,
                config.community_relay
            )
            self.logger.info("Showcase monitor enabled")

    def _load_git_state(self) -> Optional[str]:
        """Load the last processed commit hash"""
        if self.git_state_file.exists():
            with open(self.git_state_file, 'r') as f:
                state = json.load(f)
                return state.get('last_commit_hash')
        return None

    def _save_git_state(self, commit_hash: str):
        """Save the last processed commit hash"""
        with open(self.git_state_file, 'w') as f:
            json.dump({'last_commit_hash': commit_hash}, f)

    async def check_git_commits(self):
        """Check for new commits and publish them"""
        if not self.git_monitor or not self.git_publisher:
            return

        try:
            commits = self.git_monitor.get_latest_commits(self.last_commit_hash)

            if not commits:
                self.logger.info("Git: No new commits found")
                return

            self.logger.info(f"Git: Found {len(commits)} new commit(s)")

            for commit in commits:
                success = await self.git_publisher.publish_commit(commit)
                if success:
                    self.last_commit_hash = commit['hash']
                    self._save_git_state(self.last_commit_hash)
                    await asyncio.sleep(2)
                else:
                    self.logger.error(f"Git: Failed to publish commit {commit['hash']}")
                    break

        except Exception as e:
            self.logger.error(f"Git: Error checking commits: {e}")

    async def check_showcase_apps(self):
        """Check for new featured apps and announce them"""
        if not self.showcase_monitor:
            return

        try:
            new_apps = await self.showcase_monitor.check_for_new_apps()

            if not new_apps:
                self.logger.info("Showcase: No new featured apps")
                return

            self.logger.info(f"Showcase: Found {len(new_apps)} new featured app(s)")

            for app in new_apps:
                success = await self.showcase_monitor.publish_app_announcement(app)
                if success:
                    await asyncio.sleep(2)
                else:
                    self.logger.error(f"Showcase: Failed to publish app {app.get('title')}")

        except Exception as e:
            self.logger.error(f"Showcase: Error checking apps: {e}")

    async def run(self):
        """Main bot loop"""
        self.logger.info("Starting GitBotstr...")

        if self.git_monitor:
            self.logger.info(f"Git monitoring: {self.config.git_monitor.repo_url}")
            self.logger.info(f"Git channel: {self.config.git_monitor.community_id}")

        if self.showcase_monitor:
            self.logger.info(f"Showcase monitoring: {self.config.showcase_monitor.moderator_npub}")
            self.logger.info(f"Showcase channel: {self.config.showcase_monitor.channel_id}")

        self.logger.info(f"Community relay: {self.config.community_relay}")

        try:
            # Connect monitors
            if self.git_publisher:
                await self.git_publisher.connect()

            if self.showcase_monitor:
                await self.showcase_monitor.connect()

            # Track last check times
            last_git_check = 0
            last_showcase_check = 0

            while True:
                current_time = time.time()

                # Check git commits
                if self.git_monitor and (current_time - last_git_check >= self.config.git_monitor.poll_interval):
                    await self.check_git_commits()
                    last_git_check = current_time

                # Check showcase apps
                if self.showcase_monitor and (current_time - last_showcase_check >= self.config.showcase_monitor.poll_interval):
                    await self.check_showcase_apps()
                    last_showcase_check = current_time

                # Sleep for a short interval
                await asyncio.sleep(10)

        except KeyboardInterrupt:
            self.logger.info("Shutting down...")
        finally:
            if self.git_publisher:
                await self.git_publisher.disconnect()
            if self.git_monitor:
                self.git_monitor.cleanup()
            if self.showcase_monitor:
                await self.showcase_monitor.disconnect()


async def main():
    """Main entry point"""
    import argparse
    import asyncio

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    parser = argparse.ArgumentParser(description='GitBotstr - Git to Nostr NIP-29 bot')
    parser.add_argument('--config', default='config.json', help='Path to configuration file')
    parser.add_argument('--create-config', action='store_true', help='Create a sample configuration file')

    args = parser.parse_args()

    if args.create_config:
        sample_config = Config(
            repo_url="https://github.com/user/repo.git",
            nsec="nsec1...",
            community_relay="wss://relay.example.com",
            community_id="your-group-id",
            poll_interval=60,
            repo_type="github"
        )
        sample_config.to_file(args.config)
        print(f"Sample configuration created at {args.config}")
        print("Please edit the configuration file with your actual values")
        return

    # Load config and run bot
    config = Config.from_file(args.config)
    bot = GitBotstr(config)
    await bot.run()


if __name__ == '__main__':
    import asyncio
    asyncio.run(main())
