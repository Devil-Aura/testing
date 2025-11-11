# main.py
import asyncio
import logging
import os
import secrets
import time
from datetime import datetime, timedelta
from typing import Optional

import pytz
from aiohttp import web
from dateutil import tz
from pyrogram import Client, filters
from pyrogram.types import Message
from tinydb import TinyDB, Query

import config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- DB setup ---
db = TinyDB(config.DB_FILE)
redirects_table = db.table("redirects")
meta_table = db.table("meta")  # store admins list etc

# ensure owner exists in meta
if not meta_table.contains(Query().k == "owner"):
    meta_table.insert({"k": "owner", "v": config.OWNER_ID})
if not meta_table.contains(Query().k == "admins"):
    meta_table.insert({"k": "admins", "v": []})

def get_owner_id() -> int:
    rec = meta_table.get(Query().k == "owner")
    return rec["v"]

def get_admins() -> list:
    rec = meta_table.get(Query().k == "admins")
    return rec["v"]

def add_admin(uid: int) -> bool:
    admins = get_admins()
    if uid in admins:
        return False
    admins.append(uid)
    meta_table.upsert({"k": "admins", "v": admins}, Query().k == "admins")
    return True

def remove_admin(uid: int) -> bool:
    admins = get_admins()
    if uid not in admins:
        return False
    admins.remove(uid)
    meta_table.upsert({"k": "admins", "v": admins}, Query().k == "admins")
    return True

def make_token() -> str:
    return "req_" + secrets.token_urlsafe(12)

def create_redirect(token: str, url: str, creator_id: int):
    now = int(time.time())
    redirects_table.insert({
        "token": token,
        "url": url,
        "creator": creator_id,
        "created_at": now,
        "uses": 0
    })

def find_redirect(token: str) -> Optional[dict]:
    rec = redirects_table.get(Query().token == token)
    return rec

def inc_use(token: str):
    rec = redirects_table.get(Query().token == token)
    if rec:
        redirects_table.update({"uses": rec.get("uses", 0) + 1}, Query().token == token)

# --- Pyrogram bot ---
app = Client("redirect_bot", bot_token=config.BOT_TOKEN)


def is_owner_or_admin(user_id: int) -> bool:
    if user_id == get_owner_id():
        return True
    return user_id in get_admins()

@app.on_message(filters.command("start") & filters.private)
async def start_handler(client: Client, message: Message):
    # Accept /start or /start TOKEN style
    args = message.text.split(maxsplit=1)
    if len(args) == 1:
        # no payload; if owner/admin, show panel; else show unauthorized
        if is_owner_or_admin(message.from_user.id):
            text = (
                "👋 Hello Admin.\n\n"
                "Commands:\n"
                "/create <url> - create redirect link\n"
                "/list - list tokens\n"
                "/addadmin <user_id> - add admin (owner only)\n"
                "/removeadmin <user_id> - remove admin (owner only)\n"
                "/backup - send DB file now\n"
            )
            await message.reply_text(text)
        else:
            await message.reply_text("You are not authorized to use commands here. The mini-app link will still redirect you.")
        return

    # payload present
    payload = args[1].strip()
    logger.info("Received start payload: %s from %s", payload, message.from_user.id)
    # If owner/admin typed start with payload, treat as admin (but usually admin uses /create)
    if payload.startswith("req_"):
        rec = find_redirect(payload)
        if not rec:
            await message.reply_text("This link is invalid or expired.")
            return
        url = rec["url"]
        inc_use(payload)
        # Reply with direct URL (fallback). For mini-app, the web app will auto-redirect.
        await message.reply_text(f"Redirecting: {url}\nIf you are seeing this, your client did not auto-redirect. Open the link: {url}")

@app.on_message(filters.command("create") & filters.private)
async def create_handler(client: Client, message: Message):
    if not is_owner_or_admin(message.from_user.id):
        await message.reply_text("You are not authorized to create links.")
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.reply_text("Usage: /create <url>")
        return
    url = parts[1].strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        await message.reply_text("Please provide a valid URL starting with http:// or https://")
        return
    token = make_token()
    create_redirect(token, url, message.from_user.id)
    # Mini-app link
    mini_link = f"https://t.me/{config.BOT_USERNAME}/{config.MINIAPP_NAME}?startapp={token}"
    # Direct web redirect link (you will host the web app on your VPS domain)
    web_redirect = f"https://<YOUR_DOMAIN_OR_IP>:{config.WEB_PORT}/r/{token}"
    await message.reply_text(
        f"✅ Redirect created.\n\nToken: `{token}`\nMini-App Link (Telegram):\n{mini_link}\n\nDirect web redirect (useful if you host web app):\n{web_redirect}\n\nMake sure you set your Bot WebApp (via @BotFather) to point to:\nhttps://<YOUR_DOMAIN_OR_IP>:{config.WEB_PORT}/{config.MINIAPP_NAME}\n\n(note: replace <YOUR_DOMAIN_OR_IP> with your HTTPS domain/IP and ensure TLS).",
        parse_mode="markdown"
    )

@app.on_message(filters.command("list") & filters.private)
async def list_handler(client: Client, message: Message):
    if not is_owner_or_admin(message.from_user.id):
        await message.reply_text("You are not authorized.")
        return
    all_items = redirects_table.all()
    if not all_items:
        await message.reply_text("No redirects created yet.")
        return
    text_lines = []
    for i, it in enumerate(all_items, 1):
        created = datetime.fromtimestamp(it["created_at"]).isoformat()
        text_lines.append(f"{i}. {it['token']} -> {it['url']} (uses: {it.get('uses',0)}) created:{created}")
    text = "\n".join(text_lines)
    # If length large, send as file
    if len(text) > 3500:
        path = "redirects_list.txt"
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        await message.reply_document(path)
        os.remove(path)
    else:
        await message.reply_text(text)

@app.on_message(filters.command("addadmin") & filters.private)
async def addadmin_handler(client: Client, message: Message):
    if message.from_user.id != get_owner_id():
        await message.reply_text("Only owner can add admins.")
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.reply_text("Usage: /addadmin <user_id>")
        return
    try:
        uid = int(parts[1].strip())
    except ValueError:
        await message.reply_text("Invalid user id.")
        return
    ok = add_admin(uid)
    if ok:
        await message.reply_text(f"Added admin: {uid}")
    else:
        await message.reply_text("User is already admin.")

@app.on_message(filters.command("removeadmin") & filters.private)
async def removeadmin_handler(client: Client, message: Message):
    if message.from_user.id != get_owner_id():
        await message.reply_text("Only owner can remove admins.")
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.reply_text("Usage: /removeadmin <user_id>")
        return
    try:
        uid = int(parts[1].strip())
    except ValueError:
        await message.reply_text("Invalid user id.")
        return
    ok = remove_admin(uid)
    if ok:
        await message.reply_text(f"Removed admin: {uid}")
    else:
        await message.reply_text("User wasn't an admin.")

@app.on_message(filters.command("backup") & filters.private)
async def manual_backup_handler(client: Client, message: Message):
    if not is_owner_or_admin(message.from_user.id):
        await message.reply_text("Not authorized.")
        return
    # send DB file
    path = config.DB_FILE
    if not os.path.exists(path):
        await message.reply_text("No database file found.")
        return
    await message.reply_document(path, caption="Here is your database backup")

# --- Web server (aiohttp) ---
# - / linkprovider => serves a small HTML that uses Telegram WebApp JS to read start_param then call /api/resolve/<token>
# - /api/resolve/{token} => returns {"url": "..."} if exists, else 404
# - /r/{token} => direct server-side redirect (useful if Telegram passes token in query or you share direct link).

async def handle_webapp(request):
    # serve a tiny HTML + JS that:
    # 1) tries to read start_param from window.TelegramWebApp (tg)
    # 2) if start_param exists, fetch /api/resolve/{token}
    # 3) redirect to resolved url
    # 4) fallback: parse ?startapp=token from query string
    html = f"""<!doctype html>
<html>
<head>
<meta charset="utf-8" />
<title>linkprovider</title>
</head>
<body>
<div id="info">Preparing redirect...</div>
<script>
(async function(){
  function fallbackRedirect(url){
    window.location.href = url;
  }

  try {{
    const TG = window.Telegram ? window.Telegram.WebApp : window.TelegramWebApp || null;
  }} catch(e) {{
    // ignore
  }}

  // Try to get start_param via tgWebApp API
  let token = null;
  try {{
    if (window.Telegram && Telegram.WebApp && Telegram.WebApp.initData) {{
      // some clients expose this
      token = Telegram.WebApp.initData.start_param || Telegram.WebApp.startParam || null;
    }}
    if (!token && window.TelegramWebApp) {{
      token = TelegramWebApp.startParam || null;
    }}
  }} catch(e) {{
    // ignore
  }}

  // fallback: get from URL query ?startapp=TOKEN
  if(!token){{
    const u = new URL(window.location.href);
    token = u.searchParams.get("startapp") || null;
  }}

  if(!token){{
    document.getElementById('info').innerText = "No token found to redirect.";
    return;
  }}

  document.getElementById('info').innerText = "Resolving token " + token + "...";

  try {{
    const resp = await fetch('/api/resolve/' + encodeURIComponent(token));
    if(resp.status !== 200) {{
      const txt = await resp.text();
      document.getElementById('info').innerText = "Invalid token or expired.";
      return;
    }}
    const data = await resp.json();
    if(data.url){{
      // instant redirect
      window.location.replace(data.url);
      return;
    }} else {{
      document.getElementById('info').innerText = "No URL found.";
    }}
  }} catch(e) {{
    document.getElementById('info').innerText = "Error resolving token.";
    console.error(e);
  }}

})();
</script>
</body>
</html>
"""
    return web.Response(text=html, content_type="text/html")

async def api_resolve(request):
    token = request.match_info.get("token")
    rec = find_redirect(token)
    if not rec:
        return web.Response(text="Not found", status=404)
    # increment uses
    inc_use(token)
    return web.json_response({"url": rec["url"]})

async def direct_r(request):
    token = request.match_info.get("token")
    rec = find_redirect(token)
    if not rec:
        return web.Response(text="Not found", status=404)
    inc_use(token)
    raise web.HTTPFound(rec["url"])


# --- Scheduler for daily backup at configured time (Asia/Kolkata) ---
async def daily_backup_loop(bot: Client):
    tzinfo = pytz.timezone("Asia/Kolkata")
    while True:
        now = datetime.now(tz=tzinfo)
        target = now.replace(hour=config.BACKUP_HOUR, minute=config.BACKUP_MINUTE, second=0, microsecond=0)
        if target <= now:
            target = target + timedelta(days=1)
        wait_seconds = (target - now).total_seconds()
        logger.info("Next backup scheduled at %s (in %.0f seconds)", target.isoformat(), wait_seconds)
        await asyncio.sleep(wait_seconds)
        # send DB file to owner
        try:
            path = config.DB_FILE
            if os.path.exists(path):
                logger.info("Sending daily backup to owner id %s", get_owner_id())
                await bot.send_document(get_owner_id(), path, caption=f"Daily DB backup {datetime.now(tz=tzinfo).isoformat()}")
            else:
                logger.warning("DB file not found, skipping backup.")
        except Exception as e:
            logger.exception("Failed to send daily backup: %s", e)
        # small sleep to avoid accidental double-run
        await asyncio.sleep(5)

# --- Main run: start bot, web server and scheduler ---
async def main():
    # Start web app
    app_web = web.Application()
    app_web.add_routes([
        web.get(f"/{config.MINIAPP_NAME}", handle_webapp),   # /linkprovider
        web.get("/api/resolve/{token}", api_resolve),
        web.get("/r/{token}", direct_r),
    ])
    runner = web.AppRunner(app_web)
    await runner.setup()
    site = web.TCPSite(runner, config.WEB_HOST, config.WEB_PORT)
    await site.start()
    logger.info("Web server started at http://%s:%s", config.WEB_HOST, config.WEB_PORT)

    # Start pyrogram bot
    await app.start()
    logger.info("Bot started as %s", config.BOT_USERNAME)

    # Start backup loop
    backup_task = asyncio.create_task(daily_backup_loop(app))

    # keep running
    try:
        while True:
            await asyncio.sleep(1)
    finally:
        backup_task.cancel()
        await app.stop()
        await runner.cleanup()

if __name__ == "__main__":
    asyncio.run(main())
