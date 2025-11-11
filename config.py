# config.py
# Put your real values here before running.

BOT_TOKEN = "PASTE_YOUR_BOT_TOKEN_HERE"
OWNER_ID = 7626220527  # your Telegram user id
BOT_USERNAME = "testlink000167_bot"  # without @
MINIAPP_NAME = "linkprovider"

# Web server config (the domain must be HTTPS for Telegram WebApp to work)
# If you do not have a domain, you can still use the direct web redirect URL at:
# https://<your_vps_ip>:<port>/r/<token>  (but it'd require TLS for WebApp)
WEB_HOST = "0.0.0.0"
WEB_PORT = 8237

# Path to TinyDB file
DB_FILE = "database.json"

# Daily backup time in 24h format in Asia/Kolkata timezone
BACKUP_HOUR = 23
BACKUP_MINUTE = 30

# Optional: if you want to restrict admin additions to owner only (True recommended)
OWNER_ONLY_ADMIN_MANAGE = True
