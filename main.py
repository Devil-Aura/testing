# main.py
import asyncio
import json
import logging
import os
import time
import secrets
from typing import List

from aiohttp import web
from pyrogram import Client, filters, idle
from pyrogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from tinydb import TinyDB, Query as TinyQuery

import config

# --- Time / env patch to reduce msg_id time issues ---
os.environ.setdefault("TZ", "UTC")
try:
    time.tzset()
except Exception:
    pass

# --- Logging ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Pyrogram client ---
app = Client(
    "linkprovider_bot",
    api_id=config.API_ID,
    api_hash=config.API_HASH,
    bot_token=config.BOT_TOKEN,
)

# --- DB selection: MongoDB if MONGO_URI set, else TinyDB ---
USE_MONGO = config.MONGO_URI and config.MONGO_URI != "YOUR_MONGO_URI"
if USE_MONGO:
    from pymongo import MongoClient
    mongo = MongoClient(config.MONGO_URI)
    mdb = mongo[config.MONGO_DBNAME]
    redirects_col = mdb[config.MONGO_COLLECTION]
    admins_col = mdb["admins"]
    logger.info("Using MongoDB for storage.")
else:
    db = TinyDB("database.json")
    redirects_table = db.table("redirects")
    admin_table = db.table("admins")
    logger.info("Using TinyDB (database.json) for storage.")

# --- Helper functions for storage ---
def ensure_owner_admin():
    if USE_MONGO:
        if admins_col.count_documents({"user_id": config.OWNER_ID}) == 0:
            admins_col.insert_one({"user_id": config.OWNER_ID})
    else:
        if not admin_table.contains(TinyQuery().user_id == config.OWNER_ID):
            admin_table.insert({"user_id": config.OWNER_ID})

ensure_owner_admin()

def is_admin(user_id: int) -> bool:
    if USE_MONGO:
        return admins_col.count_documents({"user_id": user_id}) > 0
    else:
        return admin_table.contains(TinyQuery().user_id == user_id)

def add_admin_db(user_id: int) -> bool:
    if is_admin(user_id):
        return False
    if USE_MONGO:
        admins_col.insert_one({"user_id": user_id})
    else:
        admin_table.insert({"user_id": user_id})
    return True

def remove_admin_db(user_id: int) -> bool:
    if not is_admin(user_id):
        return False
    if USE_MONGO:
        admins_col.delete_one({"user_id": user_id})
    else:
        admin_table.remove(TinyQuery().user_id == user_id)
    return True

def create_token() -> str:
    return "req_" + secrets.token_urlsafe(9)

def create_redirect_db(url: str, creator_id: int) -> str:
    token = create_token()
    doc = {"token": token, "url": url, "creator": creator_id, "created_at": int(time.time())}
    if USE_MONGO:
        redirects_col.insert_one(doc)
    else:
        redirects_table.insert(doc)
    return token

def get_redirect_by_token(token: str):
    if USE_MONGO:
        return redirects_col.find_one({"token": token})
    else:
        return redirects_table.get(TinyQuery().token == token)

def remove_redirect_by_token(token: str) -> bool:
    if USE_MONGO:
        res = redirects_col.delete_one({"token": token})
        return res.deleted_count > 0
    else:
        removed = redirects_table.remove(TinyQuery().token == token)
        return len(removed) > 0

def list_all_redirects() -> List[dict]:
    if USE_MONGO:
        return list(redirects_col.find({}, {"_id": 0}).sort("created_at", -1))
    else:
        return redirects_table.all()

# --- Pagination constants ---
PAGE_SIZE = 10

# --- Bot commands ---

@app.on_message(filters.command(["start", "help"]) & filters.private)
async def start_handler(client: Client, message: Message):
    uid = message.from_user.id
    if not is_admin(uid):
        await message.reply_text("🚫 Access Denied. This bot's commands are for owner/admins only. The Mini-App link still redirects for everyone.")
        return
    text = (
        "👋 **LinkProvider Redirect Bot**\n\n"
        "Available commands:\n"
        "• /create <url>            - Create redirect link (admin only)\n"
        "• /listredirects           - Show saved redirects (paginated)\n"
        "• /removeredirect <token>  - Remove redirect (admin only)\n"
        "• /addadmin <user_id>      - Add admin (owner only)\n"
        "• /removeadmin <user_id>   - Remove admin (owner only)\n"
        "• /backup                  - Send DB backup to owner\n"
    )
    await message.reply_text(text)

@app.on_message(filters.command("addadmin") & filters.user(config.OWNER_ID) & filters.private)
async def addadmin_handler(client, message: Message):
    if len(message.command) < 2:
        await message.reply_text("Usage: /addadmin <user_id>")
        return
    try:
        new_id = int(message.command[1])
    except:
        await message.reply_text("Invalid user id.")
        return
    ok = add_admin_db(new_id)
    if ok:
        await message.reply_text(f"✅ Added admin `{new_id}`.")
    else:
        await message.reply_text("⚠️ User is already an admin.")

@app.on_message(filters.command("removeadmin") & filters.user(config.OWNER_ID) & filters.private)
async def removeadmin_handler(client, message: Message):
    if len(message.command) < 2:
        await message.reply_text("Usage: /removeadmin <user_id>")
        return
    try:
        target = int(message.command[1])
    except:
        await message.reply_text("Invalid user id.")
        return
    if target == config.OWNER_ID:
        await message.reply_text("❌ Cannot remove owner from admins.")
        return
    ok = remove_admin_db(target)
    if ok:
        await message.reply_text(f"🗑 Removed admin `{target}`.")
    else:
        await message.reply_text("⚠️ That user was not an admin.")

@app.on_message(filters.command(["create", "addredirect"]) & filters.private)
async def create_handler(client: Client, message: Message):
    if not is_admin(message.from_user.id):
        await message.reply_text("🚫 You are not authorized to create redirects.")
        return
    if len(message.command) < 2:
        await message.reply_text("Usage: /create <url>")
        return
    url = message.text.split(" ", 1)[1].strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        await message.reply_text("Please provide a valid URL starting with http:// or https://")
        return
    token = create_redirect_db(url, message.from_user.id)
    bot_username = (await app.get_me()).username
    mini = f"https://t.me/{bot_username}/linkprovider?startapp={token}"
    await message.reply_text(f"✅ Redirect created.\n\nToken: `{token}`\nMini-App link:\n{mini}", parse_mode="markdown")

@app.on_message(filters.command(["removeredirect", "remove"]) & filters.private)
async def removeredirect_handler(client: Client, message: Message):
    if not is_admin(message.from_user.id):
        await message.reply_text("🚫 You are not authorized to remove redirects.")
        return
    if len(message.command) < 2:
        await message.reply_text("Usage: /removeredirect <token>")
        return
    token = message.command[1].strip()
    ok = remove_redirect_by_token(token)
    if ok:
        await message.reply_text(f"🗑 Redirect `{token}` removed.")
    else:
        await message.reply_text("⚠️ No redirect found with that token.")

@app.on_message(filters.command("backup") & filters.user(config.OWNER_ID) & filters.private)
async def backup_handler(client: Client, message: Message):
    # Owner-only manual backup. If using MongoDB export collection to JSON; otherwise send TinyDB file.
    try:
        if USE_MONGO:
            items = list_all_redirects()
            fname = f"redirects_backup_{int(time.time())}.json"
            with open(fname, "w", encoding="utf-8") as f:
                json.dump(items, f, ensure_ascii=False, indent=2)
            await client.send_document(config.OWNER_ID, fname, caption="📦 Manual MongoDB export backup")
            os.remove(fname)
        else:
            # TinyDB file name
            path = "database.json"
            if os.path.exists(path):
                await client.send_document(config.OWNER_ID, path, caption="📦 Manual TinyDB backup")
            else:
                await message.reply_text("⚠️ No database file found.")
                return
        await message.reply_text("✅ Backup sent to owner.")
    except Exception as e:
        await message.reply_text(f"❌ Backup failed: {e}")

# --- Pagination helper for /listredirects ---
def build_redirects_page(redirects: List[dict], page: int, bot_username: str):
    total = len(redirects)
    pages = (total + PAGE_SIZE - 1) // PAGE_SIZE if total else 1
    page = max(1, min(page, pages))
    start = (page - 1) * PAGE_SIZE
    end = start + PAGE_SIZE
    items = redirects[start:end]

    lines = []
    for r in items:
        token = r["token"]
        url = r["url"]
        mini = f"https://t.me/{bot_username}/linkprovider?startapp={token}"
        lines.append(f"`{token}` → {url}")
    text = f"📜 Redirects (Page {page}/{pages})\n\n" + ("\n".join(lines) if lines else "No redirects on this page.")
    # Buttons
    buttons = []
    if page > 1:
        buttons.append(InlineKeyboardButton("⏪ Prev", callback_data=f"lr:{page-1}"))
    if page < pages:
        buttons.append(InlineKeyboardButton("Next ⏩", callback_data=f"lr:{page+1}"))

    # add a help button to show removal usage
    buttons2 = [
        InlineKeyboardButton("Usage: /removeredirect <token>", callback_data="noop")
    ]
    kb = InlineKeyboardMarkup([buttons, buttons2]) if buttons else InlineKeyboardMarkup([buttons2])
    return text, kb

@app.on_message(filters.command("listredirects") & filters.private)
async def listredirects_handler(client: Client, message: Message):
    if not is_admin(message.from_user.id):
        await message.reply_text("🚫 You are not authorized to view redirects.")
        return
    redirects = list_all_redirects()
    bot_username = (await app.get_me()).username
    text, kb = build_redirects_page(redirects, 1, bot_username)
    await message.reply_text(text, reply_markup=kb, disable_web_page_preview=True)

# Callback query for page navigation
@app.on_callback_query(filters.regex(r"^lr:\d+$"))
async def on_lr_callback(client: Client, cq: CallbackQuery):
    await cq.answer()  # acknowledge
    page = int(cq.data.split(":", 1)[1])
    redirects = list_all_redirects()
    bot_username = (await app.get_me()).username
    text, kb = build_redirects_page(redirects, page, bot_username)
    try:
        await cq.message.edit_text(text, reply_markup=kb, disable_web_page_preview=True)
    except Exception:
        # fallback: send new message
        await cq.message.reply_text(text, reply_markup=kb, disable_web_page_preview=True)

# noop callback to avoid errors
@app.on_callback_query(filters.regex(r"^noop$"))
async def on_noop(c: CallbackQuery):
    await c.answer("Use commands to remove items.", show_alert=False)

# --- Web app endpoints for instant redirect ---
async def web_index(request):
    # very small HTML that extracts startapp token and redirects client via /r/{token}
    html = """<!doctype html>
<html>
<head><meta charset="utf-8"/><title>linkprovider</title></head>
<body>
<div id="info">Redirecting...</div>
<script>
(async function(){
  const params = new URLSearchParams(window.location.search);
  const token = params.get('startapp');
  if(!token){
    document.getElementById('info').innerText = 'No token.';
    return;
  }
  try{
    const resp = await fetch('/r/' + encodeURIComponent(token));
    if(resp.ok){
      const j = await resp.json();
      if(j.url) window.location.replace(j.url);
      else document.getElementById('info').innerText = 'Invalid token.';
    } else {
      document.getElementById('info').innerText = 'Invalid token.';
    }
  }catch(e){
    document.getElementById('info').innerText = 'Error.';
  }
})();
</script>
</body>
</html>"""
    return web.Response(text=html, content_type="text/html")

async def web_resolve(request):
    token = request.match_info.get("token")
    rec = get_redirect_by_token(token)
    if not rec:
        return web.json_response({"error": "not found"}, status=404)
    return web.json_response({"url": rec["url"]})

# --- Startup / main ---
async def main():
    # start web app
    webapp = web.Application()
    webapp.add_routes([
        web.get("/", web_index),
        web.get("/r/{token}", web_resolve),
    ])
    runner = web.AppRunner(webapp)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", config.PORT)
    await site.start()
    logger.info(f"🌐 Web server started at http://0.0.0.0:{config.PORT}")

    # slight delay then start bot
    await asyncio.sleep(2)
    await app.start()
    logger.info("🤖 Bot started and running!")
    await idle()

if __name__ == "__main__":
    asyncio.run(main())
