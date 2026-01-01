#!/usr/bin/env python3
"""
Chief of Staff Server - Railway Edition
Combined Amplenote + Gmail server for cloud deployment.
"""
import json
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timedelta
from urllib.parse import urlparse, parse_qs
import base64

# Google API imports
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

# =============================================================================
# Configuration from Environment Variables
# =============================================================================

PORT = int(os.environ.get("PORT", 8080))
DATA_DIR = os.environ.get("DATA_DIR", "/data")

# Gmail OAuth (from environment)
GMAIL_CLIENT_ID = os.environ.get("GMAIL_CLIENT_ID", "")
GMAIL_CLIENT_SECRET = os.environ.get("GMAIL_CLIENT_SECRET", "")
GMAIL_ACCOUNTS = os.environ.get("GMAIL_ACCOUNTS", "").split(",")

# Simple API Key (optional, for Claude WebFetch)
API_KEY = os.environ.get("API_KEY", "")

# Create data directory
os.makedirs(DATA_DIR, exist_ok=True)

TASKS_FILE = os.path.join(DATA_DIR, "tasks.json")
NOTES_FILE = os.path.join(DATA_DIR, "notes.json")

# =============================================================================
# Data Storage
# =============================================================================

tasks_data = {"tasks": [], "syncedAt": None}
notes_data = {"notes": [], "syncedAt": None}

def load_data():
    global tasks_data, notes_data
    if os.path.exists(TASKS_FILE):
        try:
            with open(TASKS_FILE, "r") as f:
                tasks_data = json.load(f)
        except: pass
    if os.path.exists(NOTES_FILE):
        try:
            with open(NOTES_FILE, "r") as f:
                notes_data = json.load(f)
        except: pass

def save_tasks():
    with open(TASKS_FILE, "w") as f:
        json.dump(tasks_data, f, indent=2)

def save_notes():
    with open(NOTES_FILE, "w") as f:
        json.dump(notes_data, f, indent=2)

# =============================================================================
# Gmail Functions
# =============================================================================

SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']
gmail_services = {}

def get_gmail_credentials_config():
    """Build credentials config from environment."""
    return {
        "installed": {
            "client_id": GMAIL_CLIENT_ID,
            "client_secret": GMAIL_CLIENT_SECRET,
            "redirect_uris": ["http://localhost"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token"
        }
    }

def get_token_file(email):
    safe_email = email.replace("@", "_at_").replace(".", "_")
    return os.path.join(DATA_DIR, f"gmail_token_{safe_email}.json")

def get_gmail_service(email):
    """Get Gmail service for an account (must be pre-authenticated)."""
    global gmail_services

    if email in gmail_services:
        return gmail_services[email]

    token_file = get_token_file(email)
    if not os.path.exists(token_file):
        return None

    creds = Credentials.from_authorized_user_file(token_file, SCOPES)

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(token_file, 'w') as f:
            f.write(creds.to_json())

    if creds and creds.valid:
        gmail_services[email] = build('gmail', 'v1', credentials=creds)
        return gmail_services[email]

    return None

def fetch_emails(email, max_results=10, query="is:unread", hours_back=24):
    """Fetch emails from an account."""
    service = get_gmail_service(email)
    if not service:
        return [{"error": f"Not authenticated: {email}", "account": email}]

    try:
        after_date = (datetime.now() - timedelta(hours=hours_back)).strftime("%Y/%m/%d")
        full_query = f"{query} after:{after_date}" if query else f"after:{after_date}"

        results = service.users().messages().list(
            userId='me',
            maxResults=max_results,
            q=full_query
        ).execute()

        messages = results.get('messages', [])
        emails = []

        for msg in messages:
            msg_data = service.users().messages().get(
                userId='me',
                id=msg['id'],
                format='metadata',
                metadataHeaders=['Subject', 'From', 'Date']
            ).execute()

            headers = {h['name']: h['value'] for h in msg_data.get('payload', {}).get('headers', [])}

            emails.append({
                'id': msg['id'],
                'subject': headers.get('Subject', '(no subject)'),
                'from': headers.get('From', 'Unknown'),
                'date': headers.get('Date', ''),
                'snippet': msg_data.get('snippet', ''),
                'account': email
            })

        return emails
    except Exception as e:
        return [{"error": str(e), "account": email}]

# =============================================================================
# HTTP Handler
# =============================================================================

class ChiefOfStaffHandler(BaseHTTPRequestHandler):
    def _set_headers(self, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-API-Key")
        self.end_headers()

    def _check_api_key(self):
        """Check API key from query param or header. Returns True if valid or no key required."""
        if not API_KEY:
            return True  # No API key configured, allow all

        # Check query param ?key=xxx
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        if params.get("key", [None])[0] == API_KEY:
            return True

        # Check header X-API-Key or Authorization
        if self.headers.get("X-API-Key") == API_KEY:
            return True
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer ") and auth[7:] == API_KEY:
            return True

        return False

    def do_OPTIONS(self):
        self._set_headers(204)

    def do_GET(self):
        global tasks_data, notes_data
        parsed = urlparse(self.path)
        path = parsed.path

        # Health check (always allowed)
        if path == "/health":
            self._set_headers()
            self.wfile.write(json.dumps({
                "status": "ok",
                "tasks": len(tasks_data.get("tasks", [])),
                "notes": len(notes_data.get("notes", [])),
                "gmail_accounts": [e for e in GMAIL_ACCOUNTS if e],
                "api_key_required": bool(API_KEY)
            }).encode())
            return

        # Check API key for all other endpoints
        if not self._check_api_key():
            self._set_headers(401)
            self.wfile.write(json.dumps({"error": "Unauthorized. Add ?key=YOUR_API_KEY to URL"}).encode())
            return

        # === TASKS ===
        if path == "/tasks":
            self._set_headers()
            self.wfile.write(json.dumps(tasks_data).encode())

        elif path == "/tasks/open":
            open_tasks = [t for t in tasks_data.get("tasks", [])
                         if not t.get("completedAt") and not t.get("dismissedAt")]
            self._set_headers()
            self.wfile.write(json.dumps({
                "tasks": open_tasks,
                "syncedAt": tasks_data.get("syncedAt")
            }).encode())

        elif path == "/tasks/today":
            now = datetime.now().timestamp()
            today_tasks = [t for t in tasks_data.get("tasks", [])
                          if not t.get("completedAt")
                          and not t.get("dismissedAt")
                          and (not t.get("startAt") or t.get("startAt") <= now)
                          and (not t.get("hideUntil") or t.get("hideUntil") <= now)]
            today_tasks.sort(key=lambda t: t.get("score", 0), reverse=True)
            self._set_headers()
            self.wfile.write(json.dumps({
                "tasks": today_tasks,
                "syncedAt": tasks_data.get("syncedAt")
            }).encode())

        # === NOTES ===
        elif path == "/notes":
            self._set_headers()
            self.wfile.write(json.dumps(notes_data).encode())

        elif path == "/notes/werkbank":
            werkbank = [n for n in notes_data.get("notes", []) if n.get("type") == "werkbank"]
            self._set_headers()
            self.wfile.write(json.dumps({
                "notes": werkbank,
                "syncedAt": notes_data.get("syncedAt")
            }).encode())

        elif path == "/notes/projects":
            projects = [n for n in notes_data.get("notes", []) if n.get("type") == "project"]
            self._set_headers()
            self.wfile.write(json.dumps({
                "notes": projects,
                "syncedAt": notes_data.get("syncedAt")
            }).encode())

        # === GMAIL ===
        elif path == "/emails/unread":
            all_emails = []
            for email in GMAIL_ACCOUNTS:
                if email:
                    all_emails.extend(fetch_emails(email, max_results=10, query="is:unread"))
            all_emails.sort(key=lambda x: x.get('date', ''), reverse=True)
            self._set_headers()
            self.wfile.write(json.dumps({
                "emails": all_emails,
                "fetchedAt": datetime.now().isoformat()
            }).encode())

        elif path == "/emails/recent":
            all_emails = []
            for email in GMAIL_ACCOUNTS:
                if email:
                    all_emails.extend(fetch_emails(email, max_results=20, query="", hours_back=24))
            all_emails.sort(key=lambda x: x.get('date', ''), reverse=True)
            self._set_headers()
            self.wfile.write(json.dumps({
                "emails": all_emails,
                "fetchedAt": datetime.now().isoformat()
            }).encode())

        elif path == "/gmail/status":
            status = {}
            for email in GMAIL_ACCOUNTS:
                if email:
                    token_file = get_token_file(email)
                    status[email] = "authenticated" if os.path.exists(token_file) else "not_authenticated"
            self._set_headers()
            self.wfile.write(json.dumps(status).encode())

        else:
            self._set_headers(404)
            self.wfile.write(json.dumps({"error": "Not found"}).encode())

    def do_POST(self):
        global tasks_data, notes_data
        path = urlparse(self.path).path
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        if path == "/tasks":
            try:
                data = json.loads(body)
                tasks_data = {
                    "tasks": data.get("tasks", []),
                    "syncedAt": data.get("syncedAt", datetime.now().timestamp() * 1000)
                }
                save_tasks()
                self._set_headers()
                self.wfile.write(json.dumps({
                    "success": True,
                    "count": len(tasks_data["tasks"])
                }).encode())
                print(f"Received {len(tasks_data['tasks'])} tasks")
            except json.JSONDecodeError:
                self._set_headers(400)
                self.wfile.write(json.dumps({"error": "Invalid JSON"}).encode())

        elif path == "/notes":
            try:
                data = json.loads(body)
                notes_data = {
                    "notes": data.get("notes", []),
                    "syncedAt": data.get("syncedAt", datetime.now().timestamp() * 1000)
                }
                save_notes()
                self._set_headers()
                self.wfile.write(json.dumps({
                    "success": True,
                    "count": len(notes_data["notes"])
                }).encode())
                print(f"Received {len(notes_data['notes'])} notes")
            except json.JSONDecodeError:
                self._set_headers(400)
                self.wfile.write(json.dumps({"error": "Invalid JSON"}).encode())

        elif path == "/gmail/token":
            # Receive OAuth token from local auth flow
            try:
                data = json.loads(body)
                email = data.get("email")
                token_data = data.get("token")
                if email and token_data:
                    token_file = get_token_file(email)
                    with open(token_file, 'w') as f:
                        json.dump(token_data, f)
                    # Clear cached service to reload
                    if email in gmail_services:
                        del gmail_services[email]
                    self._set_headers()
                    self.wfile.write(json.dumps({"success": True}).encode())
                else:
                    self._set_headers(400)
                    self.wfile.write(json.dumps({"error": "Missing email or token"}).encode())
            except Exception as e:
                self._set_headers(400)
                self.wfile.write(json.dumps({"error": str(e)}).encode())

        else:
            self._set_headers(404)
            self.wfile.write(json.dumps({"error": "Not found"}).encode())

    def log_message(self, format, *args):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {args[0]}")


# =============================================================================
# Main
# =============================================================================

def main():
    load_data()

    server = HTTPServer(("0.0.0.0", PORT), ChiefOfStaffHandler)
    print(f"Chief of Staff Server running on port {PORT}")
    print(f"Tasks: {len(tasks_data.get('tasks', []))} | Notes: {len(notes_data.get('notes', []))}")
    print(f"Gmail accounts: {', '.join(a for a in GMAIL_ACCOUNTS if a)}")
    print(f"Data directory: {DATA_DIR}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()
