import asyncio
import logging
from pyrogram import Client, filters
from pyrogram.types import Message
from tinydb import TinyDB, Query
from datetime import datetime
from aiohttp import web
import os
from config import API_ID, API_HASH, BOT_TOKEN, OWNER_ID, PORT

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize bot
app = Client("linkprovider_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# Database
db = TinyDB("database.json")
redirects_table = db.table("redirects")
admin_table = db.table("admins")

# Add owner as default admin if missing
if not admin_table.contains(Query().user_id == OWNER_ID):
    admin_table.insert({"user_id": OWNER_ID})

# ========== Helper Functions ==========
def is_admin(user_id: int) -> bool:
    admins = [a["user_id"] for a in admin_table.all()]
    return user_id in admins

def create_redirect_token(url: str) -> str:
    token = f"req_{abs(hash(url + str(datetime.now())))}"
    redirects_table.insert({"token": token, "url": url})
    return token

def get_redirect_url(token: str):
    entry = redirects_table.get(Query().token == token)
    return entry["url"] if entry else None

# ========== Bot Commands ==========
@app.on_message(filters.command("start") & filters.private)
async def start(client, message: Message):
    user_id = message.from_user.id
    if not is_admin(user_id):
        await message.reply_text("🚫 Access Denied.\nThis bot is only for the owner and admins.")
        return
    await message.reply_text("👋 Welcome to **LinkProvider Redirect Bot**\n\n"
                             "Commands:\n"
                             "• /create <url> - Create redirect link\n"
                             "• /addadmin <id>\n"
                             "• /removeadmin <id>\n"
                             "• /backup - Manual backup")

@app.on_message(filters.command("addadmin") & filters.user(OWNER_ID))
async def add_admin(client, message: Message):
    try:
        new_admin = int(message.command[1])
        if admin_table.contains(Query().user_id == new_admin):
            await message.reply_text("⚠️ Already an admin.")
        else:
            admin_table.insert({"user_id": new_admin})
            await message.reply_text(f"✅ Added {new_admin} as admin.")
    except:
        await message.reply_text("Usage: /addadmin <user_id>")

@app.on_message(filters.command("removeadmin") & filters.user(OWNER_ID))
async def remove_admin(client, message: Message):
    try:
        target = int(message.command[1])
        admin_table.remove(Query().user_id == target)
        await message.reply_text(f"🗑 Removed {target} from admins.")
    except:
        await message.reply_text("Usage: /removeadmin <user_id>")

@app.on_message(filters.command("create") & filters.private)
async def create_redirect(client, message: Message):
    if not is_admin(message.from_user.id):
        await message.reply_text("🚫 You are not allowed to create links.")
        return

    if len(message.command) < 2:
        await message.reply_text("Usage: /create <url>")
        return

    url = message.text.split(" ", 1)[1].strip()
    token = create_redirect_token(url)
    miniapp_link = f"https://t.me/testlink000167_bot/linkprovider?startapp={token}"
    await message.reply_text(f"✅ Redirect created:\n\n🌐 **URL:** {url}\n🔗 **Mini App Link:** {miniapp_link}")

@app.on_message(filters.command("backup") & filters.user(OWNER_ID))
async def manual_backup(client, message: Message):
    await client.send_document(OWNER_ID, "database.json", caption="📦 Manual Backup File")
    await message.reply_text("✅ Manual backup sent successfully.")

# ========== Web App for redirect ==========
async def handle_webapp(request):
    html = """<!doctype html>
<html>
<head><meta charset="utf-8"/><title>linkprovider</title></head>
<body>
<div id="info">Redirecting...</div>
<script>
(async function(){
  function fallbackRedirect(url) {
    window.location.href = url;
  }
  const params = new URLSearchParams(window.location.search);
  const token = params.get('startapp');
  if(token){
    const response = await fetch(`/r/${token}`);
    if(response.ok){
      const data = await response.json();
      if(data.url) window.location.href = data.url;
      else document.getElementById("info").innerText = "Invalid or expired link.";
    } else {
      document.getElementById("info").innerText = "Invalid link.";
    }
  } else {
    document.getElementById("info").innerText = "No redirect token.";
  }
})();
</script>
</body>
</html>"""
    return web.Response(text=html, content_type="text/html")

async def handle_redirect(request):
    token = request.match_info.get("token")
    url = get_redirect_url(token)
    if url:
        return web.json_response({"url": url})
    return web.json_response({"error": "Invalid token"}, status=404)

# ========== Main Entry ==========
async def main():
    webapp = web.Application()
    webapp.add_routes([
        web.get("/", handle_webapp),
        web.get("/r/{token}", handle_redirect)
    ])
    runner = web.AppRunner(webapp)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info(f"🌐 Web server started at http://0.0.0.0:{PORT}")

    await app.start()
    logger.info("🤖 Bot started!")
    await idle()

if __name__ == "__main__":
    from pyrogram import idle
    asyncio.run(main())
