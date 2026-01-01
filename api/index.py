"""
Chief of Staff Server - Vercel Serverless Version
"""
import json
import os
import secrets
import hashlib
from datetime import datetime, timedelta
from urllib.parse import urlparse, parse_qs, urlencode
from flask import Flask, request, jsonify, redirect, Response
import requests as http_requests

# Upstash Redis for storage
from upstash_redis import Redis

# Google API imports
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

app = Flask(__name__)

# =============================================================================
# Configuration
# =============================================================================

GMAIL_CLIENT_ID = os.environ.get("GMAIL_CLIENT_ID", "")
GMAIL_CLIENT_SECRET = os.environ.get("GMAIL_CLIENT_SECRET", "")
GMAIL_ACCOUNTS = [e.strip() for e in os.environ.get("GMAIL_ACCOUNTS", "").split(",") if e.strip()]
API_KEY = os.environ.get("API_KEY", "")
SERVER_URL = os.environ.get("SERVER_URL", "")

# Initialize Redis (Upstash)
redis = None
KV_URL = os.environ.get("KV_REST_API_URL") or os.environ.get("UPSTASH_REDIS_REST_URL")
KV_TOKEN = os.environ.get("KV_REST_API_TOKEN") or os.environ.get("UPSTASH_REDIS_REST_TOKEN")
if KV_URL and KV_TOKEN:
    redis = Redis(url=KV_URL, token=KV_TOKEN)

# =============================================================================
# Storage Functions (Upstash Redis)
# =============================================================================

def get_data(key, default=None):
    """Get data from Redis."""
    if not redis:
        return default
    try:
        data = redis.get(key)
        return json.loads(data) if data else default
    except:
        return default

def set_data(key, value):
    """Set data in Redis."""
    if not redis:
        return False
    try:
        redis.set(key, json.dumps(value))
        return True
    except:
        return False

# =============================================================================
# Device Token Functions
# =============================================================================

def hash_token(token):
    return hashlib.sha256(token.encode()).hexdigest()

def validate_device_token(token):
    if not token:
        return None
    devices = get_data("devices", {"devices": []})
    token_hash = hash_token(token)
    for device in devices.get("devices", []):
        if device.get("token_hash") == token_hash:
            expires_at = device.get("expires_at")
            if expires_at and datetime.fromisoformat(expires_at) < datetime.now():
                return None
            device["last_used"] = datetime.now().isoformat()
            set_data("devices", devices)
            return device
    return None

def create_device(email, device_name="Unknown Device"):
    token = secrets.token_urlsafe(32)
    devices = get_data("devices", {"devices": []})
    device = {
        "token_hash": hash_token(token),
        "email": email,
        "device_name": device_name,
        "created_at": datetime.now().isoformat(),
        "expires_at": (datetime.now() + timedelta(days=90)).isoformat(),
        "last_used": datetime.now().isoformat()
    }
    devices["devices"].append(device)
    set_data("devices", devices)
    return token

# =============================================================================
# Auth Helper
# =============================================================================

def check_auth(allow_api_key=False):
    """Check authentication."""
    # Check device token
    token = request.args.get("token")
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
    if token and validate_device_token(token):
        return True

    # Check API key (for POST only)
    if allow_api_key and API_KEY:
        if request.args.get("key") == API_KEY:
            return True
        if request.headers.get("X-API-Key") == API_KEY:
            return True

    return False

def cors_response(data, status=200):
    """Return JSON response with CORS headers."""
    response = jsonify(data)
    response.status_code = status
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-API-Key"
    return response

def html_response(html, status=200):
    """Return HTML response."""
    return Response(html, status=status, mimetype="text/html")

# =============================================================================
# Gmail Functions
# =============================================================================

SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

def get_gmail_service(email):
    """Get Gmail service for an account."""
    token_data = get_data(f"gmail_token_{email}")
    if not token_data:
        return None

    creds = Credentials.from_authorized_user_info(token_data, SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        set_data(f"gmail_token_{email}", json.loads(creds.to_json()))

    if creds and creds.valid:
        return build('gmail', 'v1', credentials=creds)
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
            userId='me', maxResults=max_results, q=full_query
        ).execute()

        messages = results.get('messages', [])
        emails = []

        for msg in messages:
            msg_data = service.users().messages().get(
                userId='me', id=msg['id'], format='metadata',
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
# Routes
# =============================================================================

@app.route("/", methods=["GET"])
def root():
    return cors_response({"service": "Chief of Staff", "login": f"{SERVER_URL}/login"})

@app.route("/health", methods=["GET"])
def health():
    tasks = get_data("tasks", {"tasks": []})
    notes = get_data("notes", {"notes": []})
    devices = get_data("devices", {"devices": []})
    return cors_response({
        "status": "ok",
        "storage": "connected" if redis else "not configured",
        "tasks": len(tasks.get("tasks", [])),
        "notes": len(notes.get("notes", [])),
        "gmail_accounts": len(GMAIL_ACCOUNTS),
        "devices": len(devices.get("devices", []))
    })

# === Google Sign-In ===

@app.route("/login", methods=["GET"])
def login():
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
    return redirect(google_auth_url)

@app.route("/callback", methods=["GET"])
def callback():
    code = request.args.get("code")
    error = request.args.get("error")

    if error:
        return html_response(f"<h1>Login Failed</h1><p>{error}</p>", 400)
    if not code:
        return html_response("<h1>Login Failed</h1><p>No authorization code</p>", 400)

    try:
        # Exchange code for tokens
        token_response = http_requests.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": GMAIL_CLIENT_ID,
                "client_secret": GMAIL_CLIENT_SECRET,
                "redirect_uri": f"{SERVER_URL}/callback",
                "grant_type": "authorization_code"
            }
        ).json()

        # Verify ID token
        id_info = id_token.verify_oauth2_token(
            token_response["id_token"],
            google_requests.Request(),
            GMAIL_CLIENT_ID
        )

        user_email = id_info.get("email", "")
        user_name = id_info.get("name", "Unknown")

        if user_email not in GMAIL_ACCOUNTS:
            return html_response(f"""
            <html><head><title>Access Denied</title>
            <style>body {{ font-family: -apple-system, sans-serif; padding: 40px; max-width: 500px; margin: 0 auto; }}</style>
            </head><body>
            <h1>Access Denied</h1>
            <p>Email <strong>{user_email}</strong> is not authorized.</p>
            <p><a href="/login">Try another account</a></p>
            </body></html>
            """, 403)

        # Create device token
        device_token = create_device(user_email, "Web Browser")

        return html_response(f"""
        <html><head><title>Login Successful</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body {{ font-family: -apple-system, sans-serif; padding: 40px; max-width: 500px; margin: 0 auto; background: #f5f5f5; }}
            .card {{ background: white; padding: 30px; border-radius: 12px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
            h1 {{ color: #1a73e8; margin-top: 0; }}
            .token {{ background: #f0f0f0; padding: 15px; border-radius: 8px; word-break: break-all; font-family: monospace; font-size: 12px; margin: 20px 0; }}
            .copy-btn {{ background: #1a73e8; color: white; border: none; padding: 12px 24px; border-radius: 6px; font-size: 16px; cursor: pointer; width: 100%; }}
        </style>
        </head><body>
        <div class="card">
            <h1>Welcome, {user_name}!</h1>
            <p>Your device token (valid for 90 days):</p>
            <div class="token" id="token">{device_token}</div>
            <button class="copy-btn" onclick="navigator.clipboard.writeText('{device_token}').then(() => this.textContent = 'Copied!')">
                Copy Token
            </button>
        </div>
        </body></html>
        """)
    except Exception as e:
        return html_response(f"<h1>Login Error</h1><p>{str(e)}</p>", 500)

@app.route("/auth/status", methods=["GET"])
def auth_status():
    token = request.args.get("token")
    device = validate_device_token(token) if token else None
    if device:
        return cors_response({
            "authenticated": True,
            "email": device.get("email"),
            "expires_at": device.get("expires_at")
        })
    return cors_response({"authenticated": False})

# === Protected Routes ===

@app.route("/tasks", methods=["GET", "POST"])
def tasks():
    if request.method == "POST":
        if not check_auth(allow_api_key=True):
            return cors_response({"error": "Unauthorized"}, 401)
        data = request.get_json()
        tasks_data = {
            "tasks": data.get("tasks", []),
            "syncedAt": data.get("syncedAt", datetime.now().timestamp() * 1000)
        }
        set_data("tasks", tasks_data)
        return cors_response({"success": True, "count": len(tasks_data["tasks"])})

    if not check_auth():
        return cors_response({"error": "Unauthorized", "login_url": f"{SERVER_URL}/login"}, 401)
    return cors_response(get_data("tasks", {"tasks": [], "syncedAt": None}))

@app.route("/tasks/open", methods=["GET"])
def tasks_open():
    if not check_auth():
        return cors_response({"error": "Unauthorized"}, 401)
    tasks_data = get_data("tasks", {"tasks": []})
    open_tasks = [t for t in tasks_data.get("tasks", [])
                  if not t.get("completedAt") and not t.get("dismissedAt")]
    return cors_response({"tasks": open_tasks, "syncedAt": tasks_data.get("syncedAt")})

@app.route("/tasks/today", methods=["GET"])
def tasks_today():
    if not check_auth():
        return cors_response({"error": "Unauthorized"}, 401)
    tasks_data = get_data("tasks", {"tasks": []})
    now = datetime.now().timestamp()
    today_tasks = [t for t in tasks_data.get("tasks", [])
                   if not t.get("completedAt") and not t.get("dismissedAt")
                   and (not t.get("startAt") or t.get("startAt") <= now)
                   and (not t.get("hideUntil") or t.get("hideUntil") <= now)]
    today_tasks.sort(key=lambda t: t.get("score", 0), reverse=True)
    return cors_response({"tasks": today_tasks, "syncedAt": tasks_data.get("syncedAt")})

@app.route("/notes", methods=["GET", "POST"])
def notes():
    if request.method == "POST":
        if not check_auth(allow_api_key=True):
            return cors_response({"error": "Unauthorized"}, 401)
        data = request.get_json()
        notes_data = {
            "notes": data.get("notes", []),
            "syncedAt": data.get("syncedAt", datetime.now().timestamp() * 1000)
        }
        set_data("notes", notes_data)
        return cors_response({"success": True, "count": len(notes_data["notes"])})

    if not check_auth():
        return cors_response({"error": "Unauthorized"}, 401)
    return cors_response(get_data("notes", {"notes": [], "syncedAt": None}))

@app.route("/notes/werkbank", methods=["GET"])
def notes_werkbank():
    if not check_auth():
        return cors_response({"error": "Unauthorized"}, 401)
    notes_data = get_data("notes", {"notes": []})
    werkbank = [n for n in notes_data.get("notes", []) if n.get("type") == "werkbank"]
    return cors_response({"notes": werkbank, "syncedAt": notes_data.get("syncedAt")})

@app.route("/notes/projects", methods=["GET"])
def notes_projects():
    if not check_auth():
        return cors_response({"error": "Unauthorized"}, 401)
    notes_data = get_data("notes", {"notes": []})
    projects = [n for n in notes_data.get("notes", []) if n.get("type") == "project"]
    return cors_response({"notes": projects, "syncedAt": notes_data.get("syncedAt")})

@app.route("/context", methods=["GET", "POST"])
def context():
    if request.method == "POST":
        if not check_auth(allow_api_key=True):
            return cors_response({"error": "Unauthorized"}, 401)
        data = request.get_json()
        context_data = {
            "files": data.get("files", {}),
            "syncedAt": data.get("syncedAt", datetime.now().timestamp() * 1000)
        }
        set_data("context", context_data)
        return cors_response({"success": True, "files": list(context_data["files"].keys())})

    if not check_auth():
        return cors_response({"error": "Unauthorized"}, 401)
    return cors_response(get_data("context", {"files": {}, "syncedAt": None}))

@app.route("/emails/unread", methods=["GET"])
def emails_unread():
    if not check_auth():
        return cors_response({"error": "Unauthorized"}, 401)
    all_emails = []
    for email in GMAIL_ACCOUNTS:
        all_emails.extend(fetch_emails(email, max_results=10, query="is:unread"))
    all_emails.sort(key=lambda x: x.get('date', ''), reverse=True)
    return cors_response({"emails": all_emails, "fetchedAt": datetime.now().isoformat()})

@app.route("/emails/recent", methods=["GET"])
def emails_recent():
    if not check_auth():
        return cors_response({"error": "Unauthorized"}, 401)
    all_emails = []
    for email in GMAIL_ACCOUNTS:
        all_emails.extend(fetch_emails(email, max_results=20, query="", hours_back=24))
    all_emails.sort(key=lambda x: x.get('date', ''), reverse=True)
    return cors_response({"emails": all_emails, "fetchedAt": datetime.now().isoformat()})

@app.route("/gmail/token", methods=["POST"])
def gmail_token():
    if not check_auth(allow_api_key=True):
        return cors_response({"error": "Unauthorized"}, 401)
    data = request.get_json()
    email = data.get("email")
    token_data = data.get("token")
    if email and token_data:
        set_data(f"gmail_token_{email}", token_data)
        return cors_response({"success": True})
    return cors_response({"error": "Missing email or token"}, 400)

@app.route("/gmail/status", methods=["GET"])
def gmail_status():
    if not check_auth():
        return cors_response({"error": "Unauthorized"}, 401)
    status = {}
    for email in GMAIL_ACCOUNTS:
        token = get_data(f"gmail_token_{email}")
        status[email] = "authenticated" if token else "not_authenticated"
    return cors_response(status)

# === OPTIONS for CORS ===

@app.route("/<path:path>", methods=["OPTIONS"])
def options(path):
    response = Response()
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-API-Key"
    return response

# For local testing
if __name__ == "__main__":
    app.run(debug=True, port=3333)
