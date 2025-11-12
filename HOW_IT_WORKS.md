# How GitBotstr Works

This document explains the bot's operation, state management, and guarantees against duplicate posts.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                        GitBotstr Bot                         │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌──────────────┐      ┌──────────────┐    ┌──────────────┐│
│  │ Git Monitor  │──────│  Main Loop   │────│   Nostr      ││
│  │              │      │              │    │  Publisher   ││
│  └──────────────┘      └──────────────┘    └──────────────┘│
│         │                     │                    │         │
└─────────┼─────────────────────┼────────────────────┼─────────┘
          │                     │                    │
          ▼                     ▼                    ▼
   ┌────────────┐      ┌──────────────┐    ┌─────────────┐
   │ Git Repo   │      │ State File   │    │ NIP-29      │
   │ (GitLab)   │      │ (JSON)       │    │ Relay       │
   └────────────┘      └──────────────┘    └─────────────┘
```

## Operation Flow

### First Run

```
1. Bot starts
   └─> Loads config.json

2. Checks for gitbotstr_state.json
   └─> File doesn't exist (first run)

3. Clones repository
   └─> GET latest commit only (not all history)

4. Posts latest commit to Nostr
   └─> Formatted as friendly message with h tag

5. Saves commit hash to state file
   └─> {"last_commit_hash": "abc123..."}

6. Sleeps for poll_interval seconds
   └─> Default: 60 seconds

7. Loop back to step 3 (but pulls instead of clones)
```

### Subsequent Runs

```
1. Bot starts
   └─> Loads config.json

2. Loads gitbotstr_state.json
   └─> last_commit_hash = "abc123..."

3. Pulls repository updates
   └─> git pull

4. Gets commits since "abc123..."
   └─> git log abc123..HEAD

5. For each new commit:
   ├─> Format as Nostr message
   ├─> Post to NIP-29 relay
   ├─> Wait for success confirmation
   └─> Save new hash to state file

6. Sleeps for poll_interval seconds

7. Loop back to step 3
```

### After Restart/Crash

```
1. Bot starts (after crash/restart)
   └─> Loads config.json

2. Loads gitbotstr_state.json
   └─> last_commit_hash = "xyz789..." (last successful post)

3. Pulls repository updates
   └─> Any commits pushed during downtime are detected

4. Gets commits since "xyz789..."
   └─> Only NEW commits, never old ones

5. Posts all new commits (in order)
   └─> Each saves state after success

6. Continues normal operation
```

## State Management Details

### State File Format

```json
{
  "last_commit_hash": "35a85c18bdedfeb959cf702c015984c857096974"
}
```

This simple file ensures:
- **Persistence**: Survives restarts, crashes, system reboots
- **Atomicity**: Updated immediately after each successful post
- **Recovery**: Always knows exactly where to resume

### State Update Strategy

```python
for commit in new_commits:
    success = publish_commit(commit)
    if success:
        save_state(commit['hash'])  # ← Saved IMMEDIATELY
        await sleep(2)
    else:
        break  # ← Stop on failure, don't update state
```

**Key guarantees:**
1. State is saved ONLY after successful Nostr post
2. If posting fails, state is NOT updated (safe to retry)
3. Each commit is saved individually (not batch)
4. On restart, bot knows exactly which commits were successfully posted

## Continuous Monitoring

The bot runs an infinite loop:

```python
while True:
    1. Pull repository updates
    2. Check for new commits
    3. Post any new commits found
    4. Sleep for poll_interval seconds
    5. Repeat
```

**As a systemd service:**
- Runs 24/7 in the background
- Automatically restarts on failure (RestartSec=10)
- Logs to journalctl
- Survives system reboots (if enabled)

## Duplicate Prevention

### Multiple Safeguards

1. **Git Log Range Query**
   ```bash
   git log <last_hash>..HEAD
   ```
   Only returns commits AFTER the last processed hash

2. **State File Check**
   - Bot never processes same hash twice
   - State updated before moving to next commit

3. **Chronological Order**
   - Commits processed oldest-first
   - If middle commit fails, earlier commits don't retry

4. **No Historical Posting**
   - First run: Only latest commit
   - Never posts old history
   - Prevents channel spam

## Example Timeline

```
Time    Event                           State File           Action
────────────────────────────────────────────────────────────────────────
10:00   Bot starts (first run)          (none)               Post commit A
                                         ↓
10:01   Commit A posted                 hash: A              Sleep 60s

11:00   Check for new commits           hash: A              No new commits
11:01   Sleep                           hash: A              Sleep 60s

12:00   Developer pushes commit B       hash: A              Detect B
12:01   Post commit B                   hash: B              Success!

12:30   Bot crashes                     hash: B              (offline)

12:35   Developer pushes commit C       hash: B              (bot offline)
12:40   Developer pushes commit D       hash: B              (bot offline)

12:45   Bot restarts                    hash: B              Load state
12:46   Pull repository                 hash: B              Detect C, D
12:47   Post commit C                   hash: C              Success!
12:48   Post commit D                   hash: D              Success!

        ↓ No duplicates! ↓
        B was not reposted
        C and D were posted exactly once
```

## Failure Scenarios

### Scenario 1: Network Failure During Post

```
State before: hash: A
Action: Try to post commit B
Result: Network error
State after: hash: A (unchanged)

Next run: Will retry commit B (safe!)
```

### Scenario 2: Relay Rejects Message

```
State before: hash: A
Action: Try to post commit B
Result: "not a member of relay" error
State after: hash: A (unchanged)

Next run: Will retry commit B until successful
User action: Add bot to relay, then it succeeds
```

### Scenario 3: Bot Killed Mid-Post

```
State before: hash: A
Action: Posting commit B...
Result: Process killed (SIGKILL)
State after: hash: A (not written yet)

Next run: Will retry commit B (safe!)
```

### Scenario 4: Multiple Commits, One Fails

```
New commits: B, C, D

Post B → Success → Save hash B
Post C → Failed → Stop, keep hash B
(D is not attempted)

Next run: Will retry C and D
```

## Configuration Parameters

### poll_interval

Controls how often the bot checks for new commits:

- **Low (30-60s)**: Near real-time updates, higher resource usage
- **Medium (120-300s)**: Good balance for most projects
- **High (600-3600s)**: Batch updates, lower resource usage

**Recommended:**
- Active development: 60 seconds
- Stable projects: 300 seconds (5 minutes)
- Low-activity repos: 3600 seconds (1 hour)

## Performance & Resources

### Repository Cloning

- First run: Full clone (takes time for large repos)
- Subsequent runs: `git pull` only (very fast)
- Storage: Temp directory cleaned on bot shutdown

### Memory Usage

- Minimal: ~50-100 MB
- Scales with commit size (descriptions)
- No memory leaks (proper cleanup)

### Network Usage

- Poll interval: Small git fetch
- New commit: Nostr event post (~1-5 KB)
- Total: Very minimal for typical repos

## Best Practices

1. **Start with higher poll_interval** (300s) and adjust down if needed
2. **Monitor logs initially** to ensure proper operation
3. **Keep state file in same directory** as bot script
4. **Don't manually edit state file** unless recovering from issue
5. **Use systemd service** for production deployments

## Troubleshooting State Issues

### Reset State (Force Repost Latest)

```bash
rm gitbotstr_state.json
# Next run will post latest commit only
```

### Set Custom Starting Point

```bash
# Edit state file to start from specific commit
echo '{"last_commit_hash": "abc123..."}' > gitbotstr_state.json
```

### View Current State

```bash
cat gitbotstr_state.json
# Shows last successfully posted commit
```

## Summary

✅ **Continuous monitoring**: Runs forever, checks every poll_interval
✅ **No duplicates**: Each commit posted exactly once
✅ **Restart safe**: Picks up where it left off
✅ **Crash safe**: State saved immediately after success
✅ **Order preserved**: Commits posted chronologically
✅ **No spam**: Never posts old history
