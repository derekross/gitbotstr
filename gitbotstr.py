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
    Tag, Kind, Event, Filter, PublicKey, Timestamp, RelayUrl
)


@dataclass
class Config:
    """Bot configuration"""
    repo_url: str
    nsec: str
    community_relay: str
    community_id: str
    poll_interval: int = 60  # seconds
    repo_type: str = "github"  # github, gitlab, or generic

    @classmethod
    def from_file(cls, config_path: str) -> 'Config':
        """Load configuration from JSON file"""
        with open(config_path, 'r') as f:
            data = json.load(f)
        return cls(**data)

    def to_file(self, config_path: str):
        """Save configuration to JSON file"""
        with open(config_path, 'w') as f:
            json.dump({
                'repo_url': self.repo_url,
                'nsec': self.nsec,
                'community_relay': self.community_relay,
                'community_id': self.community_id,
                'poll_interval': self.poll_interval,
                'repo_type': self.repo_type
            }, f, indent=2)


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


class GitBotstr:
    """Main bot class"""

    def __init__(self, config: Config):
        self.config = config
        self.git_monitor = GitMonitor(config.repo_url, config.repo_type)
        self.nostr_publisher = NostrPublisher(
            config.nsec,
            config.community_relay,
            config.community_id
        )
        self.logger = logging.getLogger(__name__)
        self.state_file = Path("gitbotstr_state.json")
        self.last_commit_hash = self._load_state()

    def _load_state(self) -> Optional[str]:
        """Load the last processed commit hash"""
        if self.state_file.exists():
            with open(self.state_file, 'r') as f:
                state = json.load(f)
                return state.get('last_commit_hash')
        return None

    def _save_state(self, commit_hash: str):
        """Save the last processed commit hash"""
        with open(self.state_file, 'w') as f:
            json.dump({'last_commit_hash': commit_hash}, f)

    async def check_and_publish(self):
        """Check for new commits and publish them"""
        try:
            commits = self.git_monitor.get_latest_commits(self.last_commit_hash)

            if not commits:
                self.logger.info("No new commits found")
                return

            self.logger.info(f"Found {len(commits)} new commit(s)")

            for commit in commits:
                success = await self.nostr_publisher.publish_commit(commit)
                if success:
                    self.last_commit_hash = commit['hash']
                    self._save_state(self.last_commit_hash)
                    # Small delay between posts
                    await asyncio.sleep(2)
                else:
                    self.logger.error(f"Failed to publish commit {commit['hash']}")
                    break

        except Exception as e:
            self.logger.error(f"Error checking commits: {e}")

    async def run(self):
        """Main bot loop"""
        self.logger.info("Starting GitBotstr...")
        self.logger.info(f"Monitoring: {self.config.repo_url}")
        self.logger.info(f"Community: {self.config.community_id}")
        self.logger.info(f"Relay: {self.config.community_relay}")

        try:
            await self.nostr_publisher.connect()

            while True:
                await self.check_and_publish()
                self.logger.info(f"Sleeping for {self.config.poll_interval} seconds...")
                await asyncio.sleep(self.config.poll_interval)

        except KeyboardInterrupt:
            self.logger.info("Shutting down...")
        finally:
            await self.nostr_publisher.disconnect()
            self.git_monitor.cleanup()


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
