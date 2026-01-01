# Chief of Staff Server

Cloud-ready server für Amplenote Tasks + Gmail Integration.

## Railway Deployment

### 1. Repository erstellen

```bash
cd ~/code/chief-of-staff-server
git init
git add .
git commit -m "Initial commit"
gh repo create chief-of-staff-server --private --push
```

### 2. Railway Setup

1. [railway.app](https://railway.app) → New Project → Deploy from GitHub
2. Repository auswählen: `chief-of-staff-server`
3. Add Volume: `/data` (für persistente Daten)

### 3. Environment Variables setzen

In Railway Dashboard → Variables:

```
GMAIL_CLIENT_ID=70385995456-xxxxx.apps.googleusercontent.com
GMAIL_CLIENT_SECRET=GOCSPX-xxxxx
GMAIL_ACCOUNTS=rknoerk@binaryminds.com,robert@knoerk.com
DATA_DIR=/data
```

### 4. Gmail Tokens hochladen

Nach dem ersten Deploy:

```bash
./upload-tokens.sh https://your-app.railway.app
```

### 5. Amplenote Plugin anpassen

Server URL ändern von `http://localhost:3333` zu `https://your-app.railway.app`

## Endpoints

| Endpoint | Beschreibung |
|----------|--------------|
| GET /health | Server Status |
| GET /tasks | Alle Tasks |
| GET /tasks/open | Offene Tasks |
| GET /tasks/today | Heutige Tasks (nach Score) |
| POST /tasks | Tasks empfangen |
| GET /notes | Alle Notizen |
| GET /notes/werkbank | Werkbank Notiz |
| GET /notes/projects | Projekt-Notizen |
| POST /notes | Notizen empfangen |
| GET /emails/unread | Ungelesene Emails |
| GET /emails/recent | Letzte 24h Emails |
| GET /gmail/status | Gmail Auth Status |
| POST /gmail/token | Token hochladen |

## Lokal testen

```bash
export GMAIL_CLIENT_ID="..."
export GMAIL_CLIENT_SECRET="..."
export GMAIL_ACCOUNTS="email1@example.com,email2@example.com"
export DATA_DIR="./data"
python server.py
```
