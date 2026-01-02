# Chief of Staff Server

A personal productivity server that gives Claude (or any AI assistant) access to your tasks, calendar, emails, and a persistent memory system. Works on both desktop and mobile.

## What It Does

```
┌─────────────────────────────────────────────────────────────┐
│                    Your Server (VPS)                        │
│                                                             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│  │   Tasks     │  │   Gmail     │  │  Calendar   │         │
│  │ (Amplenote) │  │             │  │             │         │
│  └─────────────┘  └─────────────┘  └─────────────┘         │
│                                                             │
│  ┌─────────────────────────────────────────────────┐       │
│  │              Memory Scaffold                     │       │
│  │  CLAUDE.md | PROJECTS.md | WAITING_FOR.md       │       │
│  │  INBOX.md  | DECISIONS.md                        │       │
│  └─────────────────────────────────────────────────┘       │
└─────────────────────────────────────────────────────────────┘
         ▲                              ▲
         │ Token Auth                   │ Token Auth
         │                              │
    ┌────┴────┐                    ┌────┴────┐
    │ Desktop │                    │ Mobile  │
    │ Claude  │                    │Claude.ai│
    │  Code   │                    │  App    │
    └─────────┘                    └─────────┘
```

**The idea:** Your AI assistant needs persistent memory and access to your actual productivity data. This server provides both via a simple REST API that Claude can access through WebFetch.

## Features

- **Tasks**: Synced from your task manager (I use Amplenote, but adaptable)
- **Email**: Gmail integration (unread, recent emails)
- **Calendar**: Google Calendar (today, week view)
- **Memory Scaffold**: 5 markdown files that persist between sessions
- **Mobile + Desktop**: Same data, same memory, any device
- **Google Sign-In**: Secure device tokens (90-day validity)

## The 8 Workflows

Based on [Joe's Chief of Staff Prompt Suite](https://every.to/):

| Command | Purpose |
|---------|---------|
| `/cos` or `/briefing` | Daily morning briefing |
| `/eod` | End of day reconciliation |
| `/review` | Weekly review |
| `/clarify` | Turn fuzzy ideas into clear intentions |
| `/translate` | Brain dump → structured tasks |
| `/taskspec` | Create specs for delegating to sub-agents |
| `/meeting` | Pre/post meeting processing |

## Quick Example

**You (on mobile):** `/briefing`

**Claude (after fetching your data):**
```
## Good Morning! Friday, January 3rd
Light calendar day - good for deep work.

### Calendar
- 11:00 Team standup (Zoom)

### Top 3 Priorities
1. **Finish proposal draft** — Score 12.3 / Client waiting
2. **Review PR #42** — Score 11.1 / Blocking release
3. **Call accountant** — Score 10.8 / Tax deadline

### Emails (5 unread)
- **Sarah:** Re: Project timeline — needs response
- **AWS:** Your bill is ready

### This Week
- Thu: Client presentation
- Fri: Team retrospective

---
**If you could only do ONE thing today:**
Finish proposal draft — Because the client meeting is Monday.
```

---

# Installation

## Prerequisites

- A VPS (I use Hetzner, ~€4/month) or any server with Python 3.10+
- Domain or use [nip.io](https://nip.io) for free SSL (e.g., `1-2-3-4.nip.io`)
- Google Cloud project for OAuth (Gmail + Calendar)
- Task manager with API (optional - Amplenote, Todoist, etc.)

## Step 1: Server Setup

### On your VPS:

```bash
# Install dependencies
apt update && apt install -y python3 python3-pip python3-venv caddy

# Create app directory
mkdir -p /opt/chief-of-staff
cd /opt/chief-of-staff

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install Python packages
pip install google-auth google-auth-oauthlib google-api-python-client
```

### Upload server.py:

```bash
# From your local machine
scp server.py root@YOUR_SERVER_IP:/opt/chief-of-staff/
```

### Create systemd service:

```bash
cat > /etc/systemd/system/chief-of-staff.service << 'EOF'
[Unit]
Description=Chief of Staff Server
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/chief-of-staff
Environment="PORT=8080"
Environment="DATA_DIR=/opt/chief-of-staff/data"
Environment="SERVER_URL=https://YOUR_DOMAIN"
Environment="GMAIL_CLIENT_ID=your-client-id.apps.googleusercontent.com"
Environment="GMAIL_CLIENT_SECRET=your-client-secret"
Environment="GMAIL_ACCOUNTS=your@email.com"
Environment="API_KEY=your-secret-api-key"
ExecStart=/opt/chief-of-staff/venv/bin/python3 server.py
Restart=always

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable chief-of-staff
systemctl start chief-of-staff
```

### Configure Caddy (reverse proxy with auto-SSL):

```bash
cat > /etc/caddy/Caddyfile << 'EOF'
YOUR_DOMAIN {
    reverse_proxy localhost:8080
}
EOF

systemctl restart caddy
```

## Step 2: Google OAuth Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project
3. Enable APIs:
   - Gmail API
   - Google Calendar API
4. Configure OAuth consent screen
5. Create OAuth 2.0 credentials:
   - Application type: Web application
   - Authorized redirect URI: `https://YOUR_DOMAIN/callback`
6. Copy Client ID and Client Secret to your systemd service

## Step 3: Authenticate

1. Visit `https://YOUR_DOMAIN/login`
2. Sign in with Google
3. Copy the device token shown
4. Save it for use with the skill

For Gmail + Calendar access:
1. Visit `https://YOUR_DOMAIN/auth/services`
2. Grant permissions for Gmail and Calendar

## Step 4: Install the Skill

### For Claude.ai (Desktop + Mobile):

1. Build the skill package:
   ```bash
   cd skill && ./build.sh
   ```
2. Upload `chief-of-staff.skill` to Claude.ai
3. The skill will be available in all your Claude conversations

### For Claude Code (Desktop):

Copy the skill files to your Claude commands directory:
```bash
cp skill/chief-of-staff/SKILL.md ~/.claude/commands/cos.md
```

---

# API Reference

## Authentication

All protected endpoints require `?token=YOUR_DEVICE_TOKEN`

Get a token by visiting `/login` and signing in with Google.

## Endpoints

### Public

| Endpoint | Description |
|----------|-------------|
| `GET /health` | Server status |
| `GET /login` | Google Sign-In |
| `GET /auth/services` | Gmail + Calendar OAuth |

### Tasks

| Endpoint | Description |
|----------|-------------|
| `GET /tasks` | All tasks |
| `GET /tasks/open` | Open tasks only |
| `GET /tasks/today` | Today's tasks, sorted by score |
| `POST /tasks?key=API_KEY` | Sync tasks (from your task manager) |

### Email (Gmail)

| Endpoint | Description |
|----------|-------------|
| `GET /emails/unread` | Unread emails |
| `GET /emails/recent` | Last 24 hours |

### Calendar

| Endpoint | Description |
|----------|-------------|
| `GET /calendar/today` | Today's events |
| `GET /calendar/week` | Next 7 days |

### Memory/Context

| Endpoint | Description |
|----------|-------------|
| `GET /context` | All memory files |
| `GET /context/FILENAME.md` | Single file |
| `POST /context/FILENAME.md` | Update file |

**POST body for updating:**
```json
{"content": "New markdown content..."}
```

### Notes (Optional - Amplenote)

| Endpoint | Description |
|----------|-------------|
| `GET /notes` | All synced notes |
| `GET /notes/werkbank` | Workbench note |
| `POST /notes?key=API_KEY` | Sync notes |

---

# Memory Scaffold

The server stores 5 markdown files that persist your context:

| File | Purpose |
|------|---------|
| `CLAUDE.md` | Who you are, how you work, current context |
| `PROJECTS.md` | Active projects with next actions |
| `WAITING_FOR.md` | Delegated items, waiting on others |
| `INBOX.md` | Quick captures, unprocessed items |
| `DECISIONS.md` | Decision log with rationale |

These files are read/written by Claude during workflows. Your memory "travels with you" between devices.

---

# Adapting for Your Setup

## Task Manager

I use **Amplenote** which has a plugin system. The plugin syncs tasks to the server via `POST /tasks`.

**To adapt for other tools:**

- **Todoist**: Use their API to fetch tasks, POST to your server
- **Things 3**: Export via Shortcuts, POST to server
- **Notion**: Use Notion API, transform and POST
- **Plain text**: Just POST a JSON array of tasks

**Task format expected:**
```json
{
  "tasks": [
    {
      "uuid": "unique-id",
      "content": "Task description",
      "score": 12.5,
      "startAt": 1704067200,
      "completedAt": null
    }
  ]
}
```

The `score` field is optional but useful for prioritization. Amplenote calculates this automatically.

## Email Provider

Currently Gmail only. To add others:
- Modify `fetch_emails()` in server.py
- Add appropriate OAuth flow

## Notes

The `/notes` endpoints are Amplenote-specific. Remove or adapt as needed.

---

# Troubleshooting

### 401 Unauthorized
- Token expired (valid 90 days) → Get new token via `/login`
- Wrong token → Check for copy/paste errors

### 403 Forbidden
- Gmail/Calendar not authorized → Visit `/auth/services`
- API not enabled in Google Cloud Console

### 502 Bad Gateway
- Server crashed → Check logs: `journalctl -u chief-of-staff -f`
- Python error → Check syntax in server.py

### Skill not working on mobile
- Close and reopen Claude app to refresh skill cache
- Re-upload skill if recently updated

---

# Why This Architecture?

**Why a VPS instead of cloud functions?**
- Cloud providers (Vercel, Cloudflare) often block Claude's WebFetch
- A VPS gives you full control and consistent access

**Why Google Sign-In?**
- Device tokens are more secure than static API keys
- Same auth works for Gmail and Calendar access

**Why separate from local files?**
- Memory needs to travel between devices
- Mobile Claude can't access your local filesystem

**Why REST instead of MCP?**
- MCP doesn't work on mobile Claude.ai
- REST + WebFetch works everywhere

---

# Credits

Based on the Chief of Staff Prompt Suite concept. Built with Claude Code.

---

# License

MIT - Use however you like.
