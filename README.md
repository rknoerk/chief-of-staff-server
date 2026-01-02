# Chief of Staff Server

Personal productivity server that integrates Amplenote Tasks, Gmail, Google Calendar, and a Memory Scaffold.

**Server:** https://46-224-126-212.nip.io
**Host:** Hetzner VPS (46.224.126.212)

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Hetzner VPS                              │
│              46-224-126-212.nip.io                          │
│                                                             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│  │   Tasks     │  │   Gmail     │  │  Calendar   │         │
│  │ (Amplenote) │  │ (2 Accounts)│  │ (2 Accounts)│         │
│  └─────────────┘  └─────────────┘  └─────────────┘         │
│                                                             │
│  ┌─────────────────────────────────────────────────┐       │
│  │              Memory Scaffold                     │       │
│  │  CLAUDE.md | PROJECTS.md | WAITING_FOR.md       │       │
│  │  INBOX.md  | DECISIONS.md                        │       │
│  └─────────────────────────────────────────────────┘       │
└─────────────────────────────────────────────────────────────┘
         ▲                              ▲
         │ Device Token                 │ Device Token
         │                              │
    ┌────┴────┐                    ┌────┴────┐
    │ Desktop │                    │ Mobile  │
    │ Claude  │                    │Claude.ai│
    │  Code   │                    │  Chat   │
    └─────────┘                    └─────────┘
```

## Authentication

Uses Google Sign-In with device tokens (valid 90 days).

1. Visit `/login` → Google Sign-In
2. Receive device token
3. Use `?token=TOKEN` on all API requests

## API Endpoints

### Public (no auth)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Server status |
| `/login` | GET | Google Sign-In flow |
| `/auth/services` | GET | Gmail + Calendar OAuth |
| `/skill` | GET | Skill instructions (JSON) |

### Protected (requires `?token=TOKEN`)

#### Tasks (from Amplenote)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/tasks` | GET | All tasks |
| `/tasks/open` | GET | Open tasks only |
| `/tasks/today` | GET | Today's tasks, sorted by score |

#### Emails (Gmail)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/emails/unread` | GET | Unread emails (both accounts) |
| `/emails/recent` | GET | Recent emails (last 24h) |

#### Calendar (Google Calendar)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/calendar/today` | GET | Today's events (both accounts) |
| `/calendar/week` | GET | Next 7 days |

#### Notes (from Amplenote)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/notes` | GET | All synced notes |
| `/notes/werkbank` | GET | Werkbank note |
| `/notes/projects` | GET | Project notes |

#### Memory/Context

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/context` | GET | All memory files |
| `/context/FILENAME.md` | GET | Single file |
| `/context/FILENAME.md` | POST | Update file (`{"content": "..."}`) |

### Sync Endpoints (requires API key)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/tasks?key=KEY` | POST | Sync tasks from Amplenote |
| `/notes?key=KEY` | POST | Sync notes from Amplenote |
| `/context?key=KEY` | POST | Bulk sync memory files |

## Memory Scaffold

Five markdown files stored on server:

| File | Purpose |
|------|---------|
| `CLAUDE.md` | Who I am, how I work, current context |
| `PROJECTS.md` | Active projects with next actions |
| `WAITING_FOR.md` | Delegated items, pending responses |
| `INBOX.md` | Quick captures, unprocessed items |
| `DECISIONS.md` | Decision log with rationale |

## Local Skills (Claude Code)

Located in `~/.claude/commands/`:

| Skill | Description |
|-------|-------------|
| `/cos` | Chief of Staff - main entry point |
| `/briefing` | Morning briefing |
| `/review` | Weekly review |
| `/eod` | End of day reconciliation |

## Server Setup (Hetzner)

### Files on Server

```
/opt/chief-of-staff/
├── server.py
├── venv/
└── data/
    ├── tasks.json
    ├── notes.json
    ├── context.json
    ├── devices.json
    └── tokens/
        ├── token_rknoerk@binaryminds.com.json
        └── token_robert@knoerk.com.json
```

### Systemd Service

```
/etc/systemd/system/chief-of-staff.service
```

### Commands

```bash
# Status
ssh root@46.224.126.212 "systemctl status chief-of-staff"

# Restart
ssh root@46.224.126.212 "systemctl restart chief-of-staff"

# Logs
ssh root@46.224.126.212 "journalctl -u chief-of-staff -f"

# Deploy
scp server.py root@46.224.126.212:/opt/chief-of-staff/
ssh root@46.224.126.212 "systemctl restart chief-of-staff"
```

### Sync Scripts (local)

```bash
# Sync memory files to server
./sync-context.sh

# Upload Gmail tokens
./upload-tokens.sh https://46-224-126-212.nip.io cos-2026-mobile
```

## Environment Variables

```bash
PORT=8080
DATA_DIR=/data
GMAIL_CLIENT_ID=...
GMAIL_CLIENT_SECRET=...
GMAIL_ACCOUNTS=rknoerk@binaryminds.com,robert@knoerk.com
API_KEY=cos-2026-mobile
SERVER_URL=https://46-224-126-212.nip.io
```

## Gmail Accounts

- rknoerk@binaryminds.com
- robert@knoerk.com

Both configured for Gmail (readonly) and Calendar (readonly).
