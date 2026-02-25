# JEMAIL Design Document

## Overview

**JEMAIL** is an interactive terminal-based email management tool for auditing and
cleaning up large email backlogs (100k+) efficiently. It provides:

- **Local IMAP sync** to Maildir format for low-latency browsing
- **Declarative filter system** (YAML-based) for categorizing emails
- **Interactive TUI** with keyboard-driven navigation & shortcuts
- **Batch actions** (delete, move, archive) with configurable confidence levels
- **Statistics & buckets** for understanding email patterns
- **Provider-agnostic filter format** for future server-side sync (Phase 2+)

## Goals & Principles

1. **Efficiency first:** Minimize keystrokes, maximize context, no mouse required
2. **Human-readable config:** YAML filters can be edited, shared, versioned
3. **Reversible operations:** Keep Maildir archive intact; all actions are logged
4. **Extensible:** Support multiple accounts, providers, and actions without rewrite
5. **Offline-first:** Downloaded emails can be searched/filtered without network
6. **Verbose logging:** Abundant logs with slf4.sh format and locations

---

## Directory Structure

```tree
baal/
├── doc/
│   └── jemail/                  # This design doc
│       └── DESIGN.md
├── test/
│   └── jemail/                  # Unit & integration tests
│       ├── test_imap_sync.py
│       ├── test_filter.py
│       └── test_store.py
├── tool/
│   └── jemail                   # Executable entry point (bash wrapper)
├── src/
│   └── jemail/
│       ├── __init__.py
│       ├── main.py              # TUI app (Textual)
│       ├── screens/
│       │   ├── __init__.py
│       │   ├── main_screen.py   # Status & menu (startup)
│       │   ├── stats_screen.py  # Sender/filter buckets
│       │   ├── filter_screen.py # Filter browser/editor
│       │   ├── preview_screen.py# Email preview & pagination
│       │   └── actions_screen.py # Review & confirm actions
│       ├── imap_sync.py         # IMAP download & incremental sync
│       ├── filter.py            # Filter parsing & matching
│       ├── store.py             # Maildir storage & queries
│       ├── action.py            # Batch actions (delete, move, archive)
│       ├── config.py            # Config loading & validation
│       ├── utils.py             # Helpers (dedup, hashing, etc)
│       ├── Dockerfile
│       └── requirements.txt
├── .config/
│   └── jemail/
│       ├── settings.yaml        # Global settings (encrypted via SOPS+AGE)
│       ├── filters.yaml         # Global filters (plaintext)
│       └── accounts/            # Account-specific configs
│           ├── outlook_personal.settings.yaml  # Account settings (encrypted)
│           ├── outlook_personal.filters.yaml   # Account filters (plaintext)
│           └── ...
```

---

## Configuration Schema

### Global Settings

Global settings are documented and validated via the JSON schema file:

`doc/jemail/global.settings.schema.json`

### Account Settings

Account settings are documented and validated via the JSON schema file:

`doc/jemail/account.settings.schema.json`

Jemail will process all accounts it finds a configuration file , under `.config/jemail/accounts/`

### Global Filters: `.config/jemail/filters.yaml` (plaintext)

```yaml
# Global filters (apply to all accounts)
filters:
  - id: newsletter_global
    name: "All Newsletters (Global)"
    enabled: true
    conditions:
      - type: from
        pattern: "newsletters@*"
        case_sensitive: false
    action: archive
    confidence: auto
    tags: [newsletter, automated]

  - id: system_notifications
    name: "System Notifications (Global)"
    enabled: true
    conditions:
      - type: from
        pattern: "noreply@*"
        case_sensitive: false
      - type: from
        pattern: "*-notification*"
        case_sensitive: false
    operator: OR  # Match if ANY condition is true (default: AND)
    action: archive
    confidence: auto
    tags: [system, notifications]
```

### Account Settings: `.config/jemail/accounts/outlook_personal.settings.yaml` (encrypted)

```yaml
# Account-specific settings

account:
  # Display name
  name: "Outlook Personal"

  # IMAP server details
  imap:
    host: imap-mail.outlook.com
    port: 993
    username: user@outlook.com
    # Stored via SOPS+AGE or env var reference
    # Reference: ${JEMAIL_OUTLOOK_PERSONAL_PASSWORD}
    use_tls: true

  # Maildir storage location for this account
  maildir_path: ~/.local/share/jemail/outlook_personal

  # Folder mapping (IMAP → local Maildir)
  # Default: sync INBOX and keep folder structure
  folders:
    - name: "INBOX"
      local: "INBOX"
      sync: true
    - name: "[Gmail]/Drafts"  # Note: Gmail uses non-standard folder names
      local: "Drafts"
      sync: false
    - name: "[Gmail]/Sent Mail"
      local: "Sent"
      sync: false
    - name: "[Gmail]/Trash"
      local: "Trash"
      sync: false
    - name: "[Gmail]/Spam"
      local: "Spam"
      sync: false

```

### Account Filters: `.config/jemail/accounts/outlook_personal.filters.yaml` (plaintext)

```yaml
# Account-specific filters (override global filters; ID takes precedence)
filters:
  - id: work_emails_outlook
    name: "Work Emails (outlook_personal)"
    enabled: true
    conditions:
      - type: from
        pattern: "*@company.com"
    action: keep  # Do not auto-archive; review manually
    confidence: review
    tags: [work, important]

  - id: amazon_orders
    name: "Amazon Order Notifications (outlook_personal)"
    enabled: true
    conditions:
      - type: from
        pattern: "order-update@amazon.com"
      - type: subject
        pattern: "Your Amazon.com order"
        case_sensitive: false
    action: archive
    confidence: auto
    tags: [ecommerce, orders]
    # Meta for Phase 2 (server-side rule generation)
    provider_rules:
      outlook: "from:(order-update@amazon.com) subject:(Amazon order)
        => MoveTo(Archive)"
```

### Filter Syntax Details

#### Conditions

```yaml
conditions:
  - type: from              # Sender email address
    pattern: "user@example.com"
    case_sensitive: false

  - type: from_name         # Sender display name
    pattern: "John*"
    case_sensitive: false

  - type: to                # Recipient (primary)
    pattern: "me@*"
    case_sensitive: false

  - type: cc                # Recipient (CC)
    pattern: "list@*"
    case_sensitive: false

  - type: subject           # Email subject line
    pattern: "invoice"
    case_sensitive: false

  - type: body              # Email body text
    pattern: "unsubscribe"
    case_sensitive: false

  - type: size              # Email size (bytes)
    operator: ">"           # <, >, =, <=, >=
    value: 1000000          # 1MB

  - type: date              # Received date
    operator: ">"
    value: "2024-01-01"     # ISO 8601

  - type: has_attachment    # Has attachments
    value: true

  - type: flag              # IMAP flag
    value: "SEEN"           # SEEN, UNSEEN, FLAGGED, DRAFT, DELETED, etc.
```

**Pattern Matching:**

- `*` = wildcard (zero or more characters)
- `?` = single character
- Plain text = exact substring match (case depends on `case_sensitive`)

#### Actions

```yaml
action: archive             # Valid actions:
                           # - keep (no action, just mark as reviewed)
                           # - archive (flag locally; delete on server in batch)
                           # - delete (hard delete locally and on server in batch)
                           # - move (move to specific folder)
                           # - flag (add/remove IMAP flag)
```

#### Operators & Chaining

```yaml
conditions:
  - type: from
    pattern: "spam@*"
  - type: subject
    pattern: "urgent*"

operator: AND   # Match if ALL conditions true (default)
# OR: Match if ANY condition true
# NOT: Negate the entire filter

# Filter chaining by ID (Phase 1):
# - allow nesting for complex filters
refs:
  - id: newsletter_global
  - id: system_notifications
ref_operator: OR

# Exclusions (Phase 2):
exclusions:
  - type: from
    pattern: "whitelisted@*"  # Even if matches main filter, skip
```

#### Confidence Levels

```yaml
confidence: auto              # Trust this filter; apply action without review
confidence: review            # Show matching emails for manual approval before action
confidence: dry_run           # Show what would happen; don't apply (testing)
```

---

## IMAP Sync Logic

### Incremental Sync Strategy

**Goal:** Download only new/modified emails, avoid redundant transfers.

**Approach:**

1. **Track sync state per account/folder (stored with Maildir):**

   ```json
   ~/.local/share/jemail/{account}/.jemail_sync_state.json
   {
     "INBOX": {
       "last_uid": 45678,
       "last_modseq": 123456,
       "sync_time": "2025-02-16T09:55:43Z",
       "message_count": 12345
     }
   }
   ```

2. **Pre-sync SMB (Phase 1):**
   - Two-way sync local Maildir with SMB backup root
   - Fail early if SMB is unavailable

3. **On sync:**
   - Query IMAP for new UIDs since `last_uid`
   - If server supports CONDSTORE, use `MODSEQ` to detect changes
   - Download new & changed messages
   - Update `last_uid`, `last_modseq`

4. **Deduplication:**
   - Hash emails by `Message-ID` (unique identifier)
   - If `Message-ID` already in local Maildir, skip
   - Handle accidental re-downloads gracefully

5. **Two-way sync (Phase 1):**
   - Keep local flags in sync with IMAP flags
   - Local delete => delete on server (batch execution or next sync)
   - Local archive => delete on server, keep locally (batch execution or next sync)
   - Server delete => remove locally

6. **LAN backup sync (Phase 1):**
   - Two-way sync local Maildir with SMB backup root after each batch execution
   - Fail early if SMB is unavailable

### IMAP Flag Mapping

```text
IMAP Flags → Local markers:
  \Seen      → Mark as read in preview
  \Flagged   → Show star icon
  \Draft     → Show draft indicator
  \Deleted   → Mark for purge (soften delete)
  \Answered  → (Archive after reply, Phase 2)

Local action → Server behavior:
  Archive    → Delete on server, keep locally (on batch execution or next sync)
  Delete     → Hard delete locally and on server (on batch execution or next sync)
  Keep       → Ensure \Seen if reviewed
```

---

## Maildir Storage Format

### Structure

```tree
~/.local/share/jemail/{account}/
├── cur/                # Finalized, read messages
│   ├── 1707824543.001.eml
│   ├── 1707824544.002.eml
│   └── ...
├── new/                # New, unread messages
│   ├── 1707824545.003.eml
│   └── ...
├── tmp/                # Temporary (uploading, corruption recovery)
├── .jemail_index.json  # Optional: fast lookup index (added if perf needed)
├── INBOX/              # Subfolders mirror server folder structure
│   ├── cur/
│   ├── new/
│   └── tmp/
├── Archive/
├── Trash/
└── Spam/

# LAN backup mirror
/mnt/lan/jemail/{account}/
```

### Filename Convention

```text
{timestamp}.{sequence}.eml

timestamp  = seconds since epoch (sortable)
sequence   = incremental counter per timestamp (handle collisions)
.eml       = RFC 5322 format (raw email with headers + body)
```

**Example:** `1707824543.001.eml`

### Optional Index (Phase 2)

```json
{
  "version": 1,
  "indexed_at": "2025-02-16T09:55:43Z",
  "emails": [
    {
      "filename": "1707824543.001.eml",
      "message_id": "<abc123@example.com>",
      "from": "user@example.com",
      "from_name": "John Doe",
      "subject": "Test Email",
      "date": "2025-02-16T09:55:00Z",
      "size": 5432,
      "has_attachment": false,
      "flags": ["SEEN", "FLAGGED"]
    }
  ]
}
```

If index exists, use it for fast filtering. On sync, rescan changed files &
update index incrementally.

---

## Filter Views & Toggles

- Filters are enabled/disabled per view with shortcuts (all on, all off, undo)
- View can switch between matching filters and inverse (show non-matching)

---

## Logging

- Logging is verbose and aligns with slf4.sh format and locations
- All sync and action operations emit structured logs

---

## Filter Matching & Execution

### Matching Flow

```text
1. Load account config + global filters
2. Two-way sync local Maildir with SMB backup (fail early if unavailable)
3. For each email in local Maildir:
   a. Parse headers (From, To, Subject, Date, etc)
   b. For each active filter:
      - Evaluate ALL conditions
      - Apply operator (AND/OR)
      - Check exclusions
      - If match:
        * Store match + filter ID
        * Break (don't match multiple filters)
4. Group emails by matched filter
5. Present summary to user (stats, buckets)
6. User previews & confirms action (optional review)
7. Execute action batch (delete/archive only after confirmation)
8. Two-way sync local Maildir with SMB backup
```

### Action Execution

```python
# Pseudo-code
def apply_action(emails, filter_config):
    action = filter_config['action']

    if action == 'archive':
      set_local_flag(emails, 'ARCHIVED')
      delete_on_server(emails)

    elif action == 'delete':
      delete_local(emails)
      delete_on_server(emails)

    elif action == 'move':
        move_emails(emails, folder=filter_config['target_folder'])

    elif action == 'keep':
        set_imap_flag(emails, 'SEEN')  # Mark reviewed

    elif action == 'flag':
        set_imap_flag(emails, filter_config['flag'])

    # Log action for audit
    log_action(action, len(emails), filter_id)
```

---

## TUI Design

### Screen Hierarchy

```text
Main Screen (startup)
  ├─ Status: Accounts, counts, sync time
  ├─ Top Senders: click/navigate to stats
  ├─ Recent Actions: log of applied filters
  └─ Menu shortcuts

Stats Screen (account selected)
  ├─ Sender buckets: sorted by email count
  ├─ Filter buckets: show current filters + match count
  ├─ Date histogram: emails over time
  └─ Navigate to preview or edit filter

Filter Screen (filter selected or creating new)
  ├─ Condition editor: add/remove/edit conditions
  ├─ Action selector: dropdowns for action, folder, confidence
  ├─ Live preview: show X matching emails
  └─ Save / Apply / Cancel

Preview Screen (emails selected)
  ├─ Email list: from, subject, date, size
  ├─ Pagination: show 10-20 per screen
  ├─ Email body: full render (rich text)
  ├─ Action buttons: Archive Now / Delete / Move / Skip
  └─ Batch action review before commit

Action Review Screen (confirm batch)
  ├─ Summary: "Delete 234 emails from 'spam@*'"
  ├─ Undo window: "Changes are reversible; undo with [u]"
  └─ Confirm / Cancel

Account Selector
  ├─ List of configured accounts
  ├─ Sync status per account
  └─ Select to browse
```

### Keyboard Shortcuts

#### Main Screen

```text
[s]     Sync all accounts (background)
[a]     Select account to browse
[f]     Create new filter
[q]     Quit
[?]     Help (show all shortcuts)
[c]     Config editor (open in $EDITOR)
```

#### Stats Screen

```text
[1-9]   Jump to top N senders / filters
[↑↓]    Navigate buckets
[Enter] Preview emails in bucket
[n]     Create filter from this sender
[f]     Filter/search buckets
[s]     Sort by: count, name, date
[b]     Back to main
[?]     Help
```

#### Filter Screen

```text
[c]     Add condition
[d]     Delete selected condition
[e]     Edit selected condition
[a]     Change action
[o]     Change operator (AND/OR)
[p]     Toggle preview
[r]     Reset to defaults
[space] Toggle enabled/disabled
[s]     Save filter
[q]     Cancel (discard changes)
[?]     Help
```

#### Preview Screen

```text
[↑↓]    Previous/next email in list
[PgUp]  Scroll up (in email body)
[PgDn]  Scroll down (in email body)
[n]     Next 10 emails
[p]     Prev 10 emails
[1-9]   Jump to page N
[d]     Mark for delete
[a]     Mark for archive
[m]     Mark for move (choose folder)
[r]     Remove from batch action
[x]     Review batch & execute
[b]     Back to filter/stats
[?]     Help
```

#### Action Review Screen

```text
[Enter] Confirm & apply actions
[u]     Undo last action (if available)
[e]     Edit action (go back)
[q]     Cancel (discard actions)
[?]     Help
```

---

## Data Flow

### Sync Flow

```text
┌─────────────────────────────────────────────────────┐
│ User: [s]ync                                        │
└─────────────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────────────┐
│ Load account configs (.config/jemail/accounts/*.yaml│
└─────────────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────────────┐
│ Connect to IMAP (imap_sync.py)                      │
│  - Retrieve new UIDs since last sync                │
│  - Download new/modified email bodies               │
└─────────────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────────────┐
│ Store in Maildir (store.py)                         │
│  - Save .eml files to cur/new                       │
│  - Deduplicate by Message-ID                        │
│  - Update .sync_state.json                          │
└─────────────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────────────┐
│ (Optional) Update index (.jemail_index.json)        │
└─────────────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────────────┐
│ Update status display (main_screen.py)              │
│  - Show sync time, new counts, stats refresh        │
└─────────────────────────────────────────────────────┘
```

### Filter & Action Flow

```text
┌─────────────────────────────────────────────────────┐
│ User: Browse stats → select sender/filter           │
└─────────────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────────────┐
│ Load filters (config.py)                            │
│  - Global filters + account-specific filters        │
│  - Validate YAML schema                             │
└─────────────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────────────┐
│ Match emails (filter.py)                            │
│  - Query Maildir for emails                         │
│  - Evaluate conditions (from, subject, body, etc)   │
│  - Group by matched filter                          │
└─────────────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────────────┐
│ Display preview (preview_screen.py)                 │
│  - Paginate emails, show from/subject/date          │
│  - Allow user to browse & mark for action           │
└─────────────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────────────┐
│ User: Confirm action                                │
└─────────────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────────────┐
│ Review batch (actions_screen.py)                    │
│  - Show summary of changes                          │
│  - Warn if high-count action                        │
│  - Offer undo window                                │
└─────────────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────────────┐
│ Execute actions (action.py)                         │
│  - Move files in Maildir (cur/Archive, Trash, etc)  │
│  - Update server flags via IMAP (Phase 2)           │
│  - Log action for audit                             │
└─────────────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────────────┐
│ Display confirmation & return to stats/main         │
└─────────────────────────────────────────────────────┘
```

---

## Dependencies & Technologies

### Core Libraries

- **imaplib** (stdlib): IMAP protocol
- **email** (stdlib): Parse RFC 5322 emails
- **mailbox** (stdlib): Maildir support
- **pathlib** (stdlib): Path handling
- **yaml**: Config parsing (PyYAML)
- **textual**: Terminal UI framework
- **rich**: Terminal formatting & tables
- **keyring**: Secure credential storage

### Optional (Future)

- **sqlalchemy**: Indexing & fast queries (Phase 2)
- **requests**: OAuth provider APIs (Phase 2)
- **asyncio**: Async IMAP (Phase 2+)

### Docker

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Mount config & data volumes at runtime
VOLUME ["/root/.config/jemail", "/root/.local/share/jemail"]

ENTRYPOINT ["python", "-m", "jemail.main"]
```

### Container Management (Phase 1)

`tool/jemail` is the primary entry point and can launch the TUI directly.

```bash
jemail                   # Start TUI (requires Docker; build/start container)
jemail container stop    # Stop the container
jemail container delete  # Delete the container and image
```

Notes:

- Uses Docker (no docker compose unless needed later)
- `jemail` exits if Docker is unavailable
- Logs follow slf4.sh format and locations

---

## Security & Privacy Considerations

1. **Credentials:**
   - Never store passwords in plaintext YAML
   - Use `keyring` library (system keychain/pass store)
   - Or reference env vars: `${JEMAIL_OUTLOOK_PERSONAL_PASSWORD}`

2. **Data at Rest:**
   - Maildir .eml files are plaintext (same as locally stored emails anywhere)
   - Consider disk encryption if sensitive

3. **IMAP Connection:**
   - Always use TLS (port 993)
   - Validate certificates

4. **Audit Logging:**
   - Log all filter actions with timestamp, filter ID, email count
   - Store in `~/.cache/jemail/actions.log` (append-only)

---

## Future Phases (Out of MVP Scope)

### Phase 2: Server-Side Rules

- Generate provider-specific filter rules (Outlook Graph API, Gmail API)
- OAuth-based auth instead of app passwords
- Sync local filters ↔ server rules

### Phase 2: Advanced Querying

- SQLite index for fast full-text search
- Query language: `from:user@* subject:invoice date:>2024-01-01`
- Saved searches / smart folders

### Phase 2: Multi-Folder Sync

- Sync subfolders recursively
- Respect folder ignore lists
- Move emails between folders (not just Archive/Trash)

### Phase 3: Collaborative

- Share filter config across teams
- Filter marketplace / community configs
- OAuth for hosted filter sync

---

## Testing Strategy

### Unit Tests (`test/jemail/`)

- `test_imap_sync.py`: Mock IMAP, test incremental sync, dedup
- `test_filter.py`: Filter matching (conditions, operators, chaining)
- `test_store.py`: Maildir read/write, file format
- `test_config.py`: YAML parsing, schema validation
- `test_action.py`: Action execution (moves, flags, etc)

### Integration Tests

- Full sync + filter + action on mock IMAP server
- TUI navigation & state transitions

### Manual Testing

- Real Outlook account (controlled, throwaway inbox)
- Verify incremental sync, dedup, sorting

---

## Success Criteria

- ✅ Download 10k+ emails in <5 minutes
- ✅ Filter matching is sub-100ms for typical filters
- ✅ TUI is responsive & intuitive (keyboard-only)
- ✅ All actions are reversible or logged
- ✅ Config YAML is human-readable & can be version-controlled
- ✅ Docker image builds & runs standalone
