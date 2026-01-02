#!/usr/bin/env python3
"""
Chief of Staff Server
Combined Amplenote + Gmail server with Google Sign-In authentication.
"""
import json
import os
import secrets
import hashlib
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timedelta
from urllib.parse import urlparse, parse_qs, urlencode
import base64

# Google API imports
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

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

# Server URL for OAuth callback
SERVER_URL = os.environ.get("SERVER_URL", "http://localhost:8080")

# Create data directory
os.makedirs(DATA_DIR, exist_ok=True)

TASKS_FILE = os.path.join(DATA_DIR, "tasks.json")
NOTES_FILE = os.path.join(DATA_DIR, "notes.json")
DEVICES_FILE = os.path.join(DATA_DIR, "devices.json")
CONTEXT_FILE = os.path.join(DATA_DIR, "context.json")

# =============================================================================
# Device Token Storage
# =============================================================================

devices_data = {"devices": []}

def load_devices():
    global devices_data
    if os.path.exists(DEVICES_FILE):
        try:
            with open(DEVICES_FILE, "r") as f:
                devices_data = json.load(f)
        except: pass

def save_devices():
    with open(DEVICES_FILE, "w") as f:
        json.dump(devices_data, f, indent=2)

def generate_device_token():
    """Generate a secure random device token."""
    return secrets.token_urlsafe(32)

def hash_token(token):
    """Hash a token for storage (we only store hashes)."""
    return hashlib.sha256(token.encode()).hexdigest()

def validate_device_token(token):
    """Check if a device token is valid. Returns device info or None."""
    if not token:
        return None
    token_hash = hash_token(token)
    for device in devices_data.get("devices", []):
        if device.get("token_hash") == token_hash:
            # Check expiry
            expires_at = device.get("expires_at")
            if expires_at and datetime.fromisoformat(expires_at) < datetime.now():
                return None
            # Update last used
            device["last_used"] = datetime.now().isoformat()
            save_devices()
            return device
    return None

def create_device(email, device_name="Unknown Device"):
    """Create a new device token for an authenticated user."""
    token = generate_device_token()
    device = {
        "token_hash": hash_token(token),
        "email": email,
        "device_name": device_name,
        "created_at": datetime.now().isoformat(),
        "expires_at": (datetime.now() + timedelta(days=90)).isoformat(),
        "last_used": datetime.now().isoformat()
    }
    devices_data["devices"].append(device)
    save_devices()
    return token  # Return the unhashed token to give to user

# =============================================================================
# Data Storage
# =============================================================================

tasks_data = {"tasks": [], "syncedAt": None}
notes_data = {"notes": [], "syncedAt": None}
context_data = {"files": {}, "syncedAt": None}

def load_data():
    global tasks_data, notes_data, context_data
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
    if os.path.exists(CONTEXT_FILE):
        try:
            with open(CONTEXT_FILE, "r") as f:
                context_data = json.load(f)
        except: pass

def save_tasks():
    with open(TASKS_FILE, "w") as f:
        json.dump(tasks_data, f, indent=2)

def save_notes():
    with open(NOTES_FILE, "w") as f:
        json.dump(notes_data, f, indent=2)

def save_context():
    with open(CONTEXT_FILE, "w") as f:
        json.dump(context_data, f, indent=2)

# =============================================================================
# Gmail Functions
# =============================================================================

SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/calendar.readonly'
]
gmail_services = {}
calendar_services = {}

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

    try:
        # Load without specifying scopes - use scopes from token file
        creds = Credentials.from_authorized_user_file(token_file)

        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(token_file, 'w') as f:
                f.write(creds.to_json())

        if creds and creds.valid:
            gmail_services[email] = build('gmail', 'v1', credentials=creds)
            return gmail_services[email]
    except Exception as e:
        print(f"Gmail service error for {email}: {e}")

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
# Calendar Functions
# =============================================================================

def get_calendar_service(email):
    """Get Calendar service for an account (must be pre-authenticated)."""
    global calendar_services

    if email in calendar_services:
        return calendar_services[email]

    token_file = get_token_file(email)
    if not os.path.exists(token_file):
        return None

    try:
        # Load without specifying scopes - use scopes from token file
        creds = Credentials.from_authorized_user_file(token_file)

        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(token_file, 'w') as f:
                f.write(creds.to_json())

        if creds and creds.valid:
            calendar_services[email] = build('calendar', 'v3', credentials=creds)
            return calendar_services[email]
    except Exception as e:
        print(f"Calendar service error for {email}: {e}")

    return None

def fetch_calendar_events(email, days_ahead=7, max_results=20):
    """Fetch upcoming calendar events from an account."""
    service = get_calendar_service(email)
    if not service:
        return [{"error": f"Not authenticated for calendar: {email}", "account": email}]

    try:
        now = datetime.utcnow()
        time_min = now.isoformat() + 'Z'
        time_max = (now + timedelta(days=days_ahead)).isoformat() + 'Z'

        # Get list of calendars
        calendar_list = service.calendarList().list().execute()
        all_events = []

        for cal in calendar_list.get('items', []):
            cal_id = cal['id']
            cal_name = cal.get('summary', cal_id)

            try:
                events_result = service.events().list(
                    calendarId=cal_id,
                    timeMin=time_min,
                    timeMax=time_max,
                    maxResults=max_results,
                    singleEvents=True,
                    orderBy='startTime'
                ).execute()

                for event in events_result.get('items', []):
                    start = event.get('start', {})
                    end = event.get('end', {})

                    # Handle all-day vs timed events
                    start_str = start.get('dateTime', start.get('date', ''))
                    end_str = end.get('dateTime', end.get('date', ''))
                    is_all_day = 'date' in start and 'dateTime' not in start

                    all_events.append({
                        'id': event.get('id'),
                        'summary': event.get('summary', '(Kein Titel)'),
                        'description': event.get('description', ''),
                        'location': event.get('location', ''),
                        'start': start_str,
                        'end': end_str,
                        'all_day': is_all_day,
                        'calendar': cal_name,
                        'account': email,
                        'status': event.get('status', 'confirmed'),
                        'html_link': event.get('htmlLink', '')
                    })
            except Exception as e:
                # Skip calendars with errors (e.g., no access)
                continue

        # Sort by start time
        all_events.sort(key=lambda x: x.get('start', ''))
        return all_events

    except Exception as e:
        return [{"error": str(e), "account": email}]

def fetch_todays_events(email):
    """Fetch only today's events."""
    service = get_calendar_service(email)
    if not service:
        return [{"error": f"Not authenticated for calendar: {email}", "account": email}]

    try:
        now = datetime.utcnow()
        # Start of today (UTC)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        # End of today (UTC)
        today_end = today_start + timedelta(days=1)

        time_min = today_start.isoformat() + 'Z'
        time_max = today_end.isoformat() + 'Z'

        calendar_list = service.calendarList().list().execute()
        all_events = []

        for cal in calendar_list.get('items', []):
            cal_id = cal['id']
            cal_name = cal.get('summary', cal_id)

            try:
                events_result = service.events().list(
                    calendarId=cal_id,
                    timeMin=time_min,
                    timeMax=time_max,
                    maxResults=50,
                    singleEvents=True,
                    orderBy='startTime'
                ).execute()

                for event in events_result.get('items', []):
                    start = event.get('start', {})
                    end = event.get('end', {})
                    start_str = start.get('dateTime', start.get('date', ''))
                    end_str = end.get('dateTime', end.get('date', ''))
                    is_all_day = 'date' in start and 'dateTime' not in start

                    all_events.append({
                        'id': event.get('id'),
                        'summary': event.get('summary', '(Kein Titel)'),
                        'start': start_str,
                        'end': end_str,
                        'all_day': is_all_day,
                        'location': event.get('location', ''),
                        'calendar': cal_name,
                        'account': email
                    })
            except:
                continue

        all_events.sort(key=lambda x: x.get('start', ''))
        return all_events

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

    def _check_auth(self, allow_api_key=False):
        """Check authentication via device token (and optionally API key for POST).

        Args:
            allow_api_key: If True, also accept API key (for Amplenote sync POST requests)
        """
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        # Check device token first (always accepted)
        token = params.get("token", [None])[0]
        if not token:
            auth = self.headers.get("Authorization", "")
            if auth.startswith("Bearer "):
                token = auth[7:]
        if token and validate_device_token(token):
            return True

        # API key only allowed for specific endpoints (POST for sync)
        if allow_api_key and API_KEY:
            if params.get("key", [None])[0] == API_KEY:
                return True
            if self.headers.get("X-API-Key") == API_KEY:
                return True

        return False

    def _set_html_headers(self, status=200):
        """Set headers for HTML response."""
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()

    def do_OPTIONS(self):
        self._set_headers(204)

    def do_GET(self):
        global tasks_data, notes_data
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        # === PUBLIC ENDPOINTS (no auth required) ===

        # Health check
        if path == "/health":
            self._set_headers()
            self.wfile.write(json.dumps({
                "status": "ok",
                "tasks": len(tasks_data.get("tasks", [])),
                "notes": len(notes_data.get("notes", [])),
                "gmail_accounts": len([e for e in GMAIL_ACCOUNTS if e]),
                "devices": len(devices_data.get("devices", []))
            }).encode())
            return

        # === GOOGLE SIGN-IN FLOW ===

        # Login page - redirects to Google
        if path == "/login":
            # Build Google OAuth URL
            state = secrets.token_urlsafe(16)
            oauth_params = {
                "client_id": GMAIL_CLIENT_ID,
                "redirect_uri": f"{SERVER_URL}/callback",
                "response_type": "code",
                "scope": "openid email profile",
                "state": state,
                "access_type": "online",
                "prompt": "select_account"
            }
            google_auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(oauth_params)}"

            # Redirect to Google
            self.send_response(302)
            self.send_header("Location", google_auth_url)
            self.end_headers()
            return

        # Auth services - Gmail + Calendar OAuth (uses same /callback endpoint)
        if path == "/auth/services":
            # Build Google OAuth URL with Gmail + Calendar scopes
            state = "services_" + secrets.token_urlsafe(16)
            oauth_params = {
                "client_id": GMAIL_CLIENT_ID,
                "redirect_uri": f"{SERVER_URL}/callback",  # Use same callback
                "response_type": "code",
                "scope": "openid email profile https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/calendar.readonly",
                "state": state,
                "access_type": "offline",
                "prompt": "consent"  # Force consent to get refresh token
            }
            google_auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(oauth_params)}"

            # Redirect to Google
            self.send_response(302)
            self.send_header("Location", google_auth_url)
            self.end_headers()
            return

        # OAuth callback from Google
        if path == "/callback":
            code = params.get("code", [None])[0]
            error = params.get("error", [None])[0]
            state = params.get("state", [""])[0]
            is_services_auth = state.startswith("services_")

            if error:
                self._set_html_headers(400)
                self.wfile.write(f"<h1>Login Failed</h1><p>{error}</p>".encode())
                return

            if not code:
                self._set_html_headers(400)
                self.wfile.write(b"<h1>Login Failed</h1><p>No authorization code received</p>")
                return

            try:
                # Exchange code for tokens
                import urllib.request
                token_data = urlencode({
                    "code": code,
                    "client_id": GMAIL_CLIENT_ID,
                    "client_secret": GMAIL_CLIENT_SECRET,
                    "redirect_uri": f"{SERVER_URL}/callback",
                    "grant_type": "authorization_code"
                }).encode()

                req = urllib.request.Request(
                    "https://oauth2.googleapis.com/token",
                    data=token_data,
                    headers={"Content-Type": "application/x-www-form-urlencoded"}
                )
                with urllib.request.urlopen(req) as response:
                    token_response = json.loads(response.read())

                # Verify the ID token and get user info
                id_info = id_token.verify_oauth2_token(
                    token_response["id_token"],
                    google_requests.Request(),
                    GMAIL_CLIENT_ID
                )

                user_email = id_info.get("email", "")
                user_name = id_info.get("name", "Unknown")

                # Check if user is allowed (must be one of the Gmail accounts)
                if user_email not in GMAIL_ACCOUNTS:
                    self._set_html_headers(403)
                    self.wfile.write(f"""
                    <html><head><title>Access Denied</title>
                    <style>body {{ font-family: -apple-system, sans-serif; padding: 40px; max-width: 500px; margin: 0 auto; }}</style>
                    </head><body>
                    <h1>Access Denied</h1>
                    <p>Email <strong>{user_email}</strong> is not authorized.</p>
                    <p>Allowed accounts: {', '.join(GMAIL_ACCOUNTS)}</p>
                    <p><a href="/login">Try another account</a></p>
                    </body></html>
                    """.encode())
                    return

                # Handle services auth (Gmail + Calendar OAuth tokens)
                if is_services_auth:
                    # Save the OAuth token for Gmail/Calendar access
                    token_to_save = {
                        "token": token_response.get("access_token"),
                        "refresh_token": token_response.get("refresh_token"),
                        "token_uri": "https://oauth2.googleapis.com/token",
                        "client_id": GMAIL_CLIENT_ID,
                        "client_secret": GMAIL_CLIENT_SECRET,
                        "scopes": SCOPES,
                        "account": user_email
                    }

                    token_file = get_token_file(user_email)
                    with open(token_file, 'w') as f:
                        json.dump(token_to_save, f)

                    # Clear cached services to reload with new token
                    if user_email in gmail_services:
                        del gmail_services[user_email]
                    if user_email in calendar_services:
                        del calendar_services[user_email]

                    self._set_html_headers()
                    self.wfile.write(f"""
                    <html><head><title>Services Connected</title>
                    <meta name="viewport" content="width=device-width, initial-scale=1">
                    <style>
                        body {{ font-family: -apple-system, sans-serif; padding: 40px; max-width: 500px; margin: 0 auto; background: #f5f5f5; }}
                        .card {{ background: white; padding: 30px; border-radius: 12px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
                        h1 {{ color: #34a853; margin-top: 0; }}
                        .check {{ font-size: 48px; text-align: center; }}
                        .next {{ margin-top: 20px; padding: 15px; background: #e8f5e9; border-radius: 8px; }}
                    </style>
                    </head><body>
                    <div class="card">
                        <div class="check">✅</div>
                        <h1>Gmail + Kalender verbunden!</h1>
                        <p><strong>{user_email}</strong></p>
                        <div class="next">
                            <p>Nächster Account? <a href="/auth/services">Weiteren Account verbinden</a></p>
                        </div>
                        <p style="color: #666; margin-top: 20px;">Du kannst dieses Fenster schließen wenn alle Accounts verbunden sind.</p>
                    </div>
                    </body></html>
                    """.encode())
                    return

                # Normal login - Create device token
                device_name = params.get("device", ["Web Browser"])[0]
                device_token = create_device(user_email, device_name)

                # Show success page with token
                self._set_html_headers()
                self.wfile.write(f"""
                <html><head><title>Login Successful</title>
                <meta name="viewport" content="width=device-width, initial-scale=1">
                <style>
                    body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; padding: 40px; max-width: 500px; margin: 0 auto; background: #f5f5f5; }}
                    .card {{ background: white; padding: 30px; border-radius: 12px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
                    h1 {{ color: #1a73e8; margin-top: 0; }}
                    .token {{ background: #f0f0f0; padding: 15px; border-radius: 8px; word-break: break-all; font-family: monospace; font-size: 12px; margin: 20px 0; }}
                    .copy-btn {{ background: #1a73e8; color: white; border: none; padding: 12px 24px; border-radius: 6px; font-size: 16px; cursor: pointer; width: 100%; }}
                    .copy-btn:hover {{ background: #1557b0; }}
                    .info {{ color: #666; font-size: 14px; margin-top: 20px; }}
                </style>
                </head><body>
                <div class="card">
                    <h1>Welcome, {user_name}!</h1>
                    <p>Your device token (valid for 90 days):</p>
                    <div class="token" id="token">{device_token}</div>
                    <button class="copy-btn" onclick="navigator.clipboard.writeText('{device_token}').then(() => this.textContent = 'Copied!')">
                        Copy Token
                    </button>
                    <p class="info">
                        Use this token with Claude:<br>
                        <code>?token=YOUR_TOKEN</code>
                    </p>
                </div>
                </body></html>
                """.encode())
                return

            except Exception as e:
                self._set_html_headers(500)
                self.wfile.write(f"<h1>Login Error</h1><p>{str(e)}</p>".encode())
                return

        # Auth status - check if a token is valid
        if path == "/auth/status":
            token = params.get("token", [None])[0]
            device = validate_device_token(token) if token else None
            self._set_headers()
            if device:
                self.wfile.write(json.dumps({
                    "authenticated": True,
                    "email": device.get("email"),
                    "device": device.get("device_name"),
                    "expires_at": device.get("expires_at")
                }).encode())
            else:
                self.wfile.write(json.dumps({"authenticated": False}).encode())
            return

        # === PROTECTED ENDPOINTS (auth required) ===

        if not self._check_auth():
            self._set_headers(401)
            self.wfile.write(json.dumps({
                "error": "Unauthorized",
                "login_url": f"{SERVER_URL}/login"
            }).encode())
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

        # === CONTEXT (MD Files) ===
        elif path == "/context":
            self._set_headers()
            self.wfile.write(json.dumps(context_data).encode())

        elif path.startswith("/context/"):
            # Get specific file: /context/CLAUDE.md
            filename = path.replace("/context/", "")
            files = context_data.get("files", {})
            if filename in files:
                self._set_headers()
                self.wfile.write(json.dumps({
                    "filename": filename,
                    "content": files[filename],
                    "syncedAt": context_data.get("syncedAt")
                }).encode())
            else:
                self._set_headers(404)
                self.wfile.write(json.dumps({
                    "error": f"File not found: {filename}",
                    "available": list(files.keys())
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

        # === CALENDAR ===
        elif path == "/calendar/today":
            all_events = []
            for email in GMAIL_ACCOUNTS:
                if email:
                    all_events.extend(fetch_todays_events(email))
            all_events.sort(key=lambda x: x.get('start', ''))
            self._set_headers()
            self.wfile.write(json.dumps({
                "events": all_events,
                "date": datetime.now().strftime("%Y-%m-%d"),
                "fetchedAt": datetime.now().isoformat()
            }).encode())

        elif path == "/calendar/upcoming":
            days = int(params.get("days", [7])[0])
            all_events = []
            for email in GMAIL_ACCOUNTS:
                if email:
                    all_events.extend(fetch_calendar_events(email, days_ahead=days))
            all_events.sort(key=lambda x: x.get('start', ''))
            self._set_headers()
            self.wfile.write(json.dumps({
                "events": all_events,
                "days_ahead": days,
                "fetchedAt": datetime.now().isoformat()
            }).encode())

        elif path == "/calendar/week":
            all_events = []
            for email in GMAIL_ACCOUNTS:
                if email:
                    all_events.extend(fetch_calendar_events(email, days_ahead=7))
            all_events.sort(key=lambda x: x.get('start', ''))
            self._set_headers()
            self.wfile.write(json.dumps({
                "events": all_events,
                "fetchedAt": datetime.now().isoformat()
            }).encode())

        # === HTML BRIEFING PAGE ===
        elif path == "/briefing":
            # Get today's tasks
            now = datetime.now()
            today_tasks = [t for t in tasks_data.get("tasks", [])
                          if not t.get("completedAt")
                          and not t.get("dismissedAt")
                          and (not t.get("startAt") or t.get("startAt") <= now.timestamp())
                          and (not t.get("hideUntil") or t.get("hideUntil") <= now.timestamp())]
            today_tasks.sort(key=lambda t: t.get("score", 0), reverse=True)
            top_tasks = today_tasks[:10]

            # Get unread emails
            all_emails = []
            for email in GMAIL_ACCOUNTS:
                if email:
                    all_emails.extend(fetch_emails(email, max_results=10, query="is:unread"))
            all_emails.sort(key=lambda x: x.get('date', ''), reverse=True)

            # Get context
            context_files = context_data.get("files", {})
            claude_md = context_files.get("CLAUDE.md", "")

            # Build HTML
            tasks_html = ""
            for i, t in enumerate(top_tasks, 1):
                score = t.get("score", 0)
                content = t.get("content", "")[:80]
                tasks_html += f'<div class="task"><span class="num">{i}.</span> <span class="score">{score}</span> {content}</div>'

            emails_html = ""
            for e in all_emails[:5]:
                sender = e.get("from", "")[:30]
                subject = e.get("subject", "")[:50]
                if "error" not in e:
                    emails_html += f'<div class="email"><b>{sender}</b><br>{subject}</div>'

            self._set_html_headers()
            self.wfile.write(f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Chief of Staff Briefing</title>
    <style>
        * {{ box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, sans-serif;
            background: #1a1a2e; color: #eee;
            margin: 0; padding: 20px;
            max-width: 600px; margin: 0 auto;
        }}
        h1 {{ color: #4fc3f7; margin-bottom: 5px; }}
        .date {{ color: #888; margin-bottom: 20px; }}
        h2 {{ color: #81c784; border-bottom: 1px solid #333; padding-bottom: 5px; margin-top: 25px; }}
        .task {{
            background: #252540; padding: 12px; margin: 8px 0;
            border-radius: 8px; border-left: 3px solid #4fc3f7;
        }}
        .task .num {{ color: #4fc3f7; font-weight: bold; }}
        .task .score {{
            background: #4fc3f7; color: #000;
            padding: 2px 6px; border-radius: 4px;
            font-size: 12px; margin-left: 5px;
        }}
        .email {{
            background: #252540; padding: 12px; margin: 8px 0;
            border-radius: 8px; border-left: 3px solid #ff8a65;
        }}
        .context {{
            background: #252540; padding: 15px;
            border-radius: 8px; white-space: pre-wrap;
            font-size: 14px; line-height: 1.5;
        }}
        .refresh {{
            position: fixed; bottom: 20px; right: 20px;
            background: #4fc3f7; color: #000;
            border: none; padding: 15px 20px;
            border-radius: 50px; font-size: 16px;
            cursor: pointer;
        }}
    </style>
</head>
<body>
    <h1>Guten Morgen!</h1>
    <div class="date">{now.strftime("%A, %d. %B %Y")}</div>

    <h2>Top Tasks ({len(today_tasks)} offen)</h2>
    {tasks_html if tasks_html else '<div class="task">Keine Tasks für heute</div>'}

    <h2>Emails ({len(all_emails)} ungelesen)</h2>
    {emails_html if emails_html else '<div class="email">Keine ungelesenen Emails</div>'}

    <h2>Kontext</h2>
    <div class="context">{claude_md[:500] if claude_md else 'Kein Kontext gespeichert'}</div>

    <button class="refresh" onclick="location.reload()">↻</button>
</body>
</html>
            """.encode())

        else:
            self._set_headers(404)
            self.wfile.write(json.dumps({"error": "Not found"}).encode())

    def do_POST(self):
        global tasks_data, notes_data
        path = urlparse(self.path).path
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        # Check auth (allow API key for POST - needed for Amplenote sync)
        if not self._check_auth(allow_api_key=True):
            self._set_headers(401)
            self.wfile.write(json.dumps({
                "error": "Unauthorized",
                "login_url": f"{SERVER_URL}/login"
            }).encode())
            return

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

        elif path == "/context":
            # Receive context files (MD files from local machine)
            global context_data
            try:
                data = json.loads(body)
                context_data = {
                    "files": data.get("files", {}),
                    "syncedAt": data.get("syncedAt", datetime.now().timestamp() * 1000)
                }
                save_context()
                self._set_headers()
                self.wfile.write(json.dumps({
                    "success": True,
                    "files": list(context_data["files"].keys())
                }).encode())
                print(f"Received context files: {list(context_data['files'].keys())}")
            except json.JSONDecodeError:
                self._set_headers(400)
                self.wfile.write(json.dumps({"error": "Invalid JSON"}).encode())

        elif path.startswith("/context/"):
            # Update a single context file: POST /context/CLAUDE.md
            # Requires device token auth
            if not self._check_auth():
                self._set_headers(401)
                self.wfile.write(json.dumps({"error": "Unauthorized"}).encode())
                return

            filename = path.replace("/context/", "")
            if not filename.endswith(".md"):
                self._set_headers(400)
                self.wfile.write(json.dumps({"error": "Only .md files allowed"}).encode())
                return

            try:
                data = json.loads(body)
                content = data.get("content")
                if content is None:
                    self._set_headers(400)
                    self.wfile.write(json.dumps({"error": "Missing content"}).encode())
                    return

                # Update the file in context_data
                if "files" not in context_data:
                    context_data["files"] = {}
                context_data["files"][filename] = content
                context_data["syncedAt"] = datetime.now().timestamp() * 1000
                save_context()

                self._set_headers()
                self.wfile.write(json.dumps({
                    "success": True,
                    "file": filename,
                    "updatedAt": context_data["syncedAt"]
                }).encode())
                print(f"Updated context file: {filename}")
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
    load_devices()

    server = HTTPServer(("0.0.0.0", PORT), ChiefOfStaffHandler)
    print(f"Chief of Staff Server running on port {PORT}")
    print(f"Tasks: {len(tasks_data.get('tasks', []))} | Notes: {len(notes_data.get('notes', []))}")
    print(f"Devices: {len(devices_data.get('devices', []))}")
    print(f"Gmail accounts: {', '.join(a for a in GMAIL_ACCOUNTS if a)}")
    print(f"Data directory: {DATA_DIR}")
    print(f"Login URL: {SERVER_URL}/login")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()
