import logging
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Logging setup
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

BOT_TOKEN = "8558816321:AAECFBmFK3SxAbTk0-a15Aaw68lq1FsbGP0"

# Global data
waiting_pool = []
active_chats = {}

# Keyboards
search_keyboard = ReplyKeyboardMarkup([['🔍 Find a Stranger']], resize_keyboard=True)
stop_keyboard = ReplyKeyboardMarkup([['❌ Stop Chat']], resize_keyboard=True)

# 🌐 Dummy Web Server Render ko khush rakhne ke liye (Free tier ke liye)
class DummyServer(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(b"Bot is Running Alive!")

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), DummyServer)
    server.serve_forever()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in active_chats: await disconnect_users(user_id, active_chats[user_id], context)
    if user_id in waiting_pool: waiting_pool.remove(user_id)
    await update.message.reply_text("Welcome to Stranger Buddy! 🚀\n\nClick the button below or type /next to find someone.", reply_markup=search_keyboard)

async def find_stranger(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in active_chats:
        await update.message.reply_text("You are already in a chat! Type /stop first.")
        return
    if user_id in waiting_pool:
        await update.message.reply_text("Looking for a partner... Please wait. 🔍")
        return
    if waiting_pool:
        partner_id = waiting_pool.pop(0)
        active_chats[user_id] = partner_id
        active_chats[partner_id] = user_id
        msg = "Partner found 😺\n\n/next — find a new partner\n/stop — stop this chat"
        await context.bot.send_message(chat_id=user_id, text=msg, reply_markup=stop_keyboard)
        await context.bot.send_message(chat_id=partner_id, text=msg, reply_markup=stop_keyboard)
    else:
        waiting_pool.append(user_id)
        await update.message.reply_text("Looking for a partner... Please wait. 🔍", reply_markup=ReplyKeyboardRemove())

async def stop_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in waiting_pool:
        waiting_pool.remove(user_id)
        await update.message.reply_text("Search stopped.", reply_markup=search_keyboard)
        return
    if user_id not in active_chats:
        await update.message.reply_text("You are not connected to anyone.", reply_markup=search_keyboard)
        return
    partner_id = active_chats[user_id]
    await disconnect_users(user_id, partner_id, context)

async def next_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in active_chats: await disconnect_users(user_id, active_chats[user_id], context)
    if user_id in waiting_pool: waiting_pool.remove(user_id)
    if waiting_pool:
        partner_id = waiting_pool.pop(0)
        active_chats[user_id] = partner_id
        active_chats[partner_id] = user_id
        msg = "Partner found 😺\n\n/next — find a new partner\n/stop — stop this chat"
        await context.bot.send_message(chat_id=user_id, text=msg, reply_markup=stop_keyboard)
        await context.bot.send_message(chat_id=partner_id, text=msg, reply_markup=stop_keyboard)
    else:
        waiting_pool.append(user_id)
        await update.message.reply_text("Looking for a partner... Please wait. 🔍", reply_markup=ReplyKeyboardRemove())

async def disconnect_users(user1, user2, context):
    if user1 in active_chats: del active_chats[user1]
    if user2 in active_chats: del active_chats[user2]
    msg_you = "You stopped the chat ❌\n\nType /next to find a new partner."
    msg_partner = "Stranger left the chat ❌\n\nType /next to find a new partner."
    try: await context.bot.send_message(chat_id=user1, text=msg_you, reply_markup=search_keyboard)
    except: pass
    try: await context.bot.send_message(chat_id=user2, text=msg_partner, reply_markup=search_keyboard)
    except: pass

async def forward_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in active_chats:
        await update.message.reply_text("Type /next to find a partner first!", reply_markup=search_keyboard)
        return
    partner_id = active_chats[user_id]
    if update.message.text: await context.bot.send_message(chat_id=partner_id, text=update.message.text)
    elif update.message.photo: await context.bot.send_photo(chat_id=partner_id, photo=update.message.photo[-1].file_id, caption=update.message.caption)
    elif update.message.sticker: await context.bot.send_sticker(chat_id=partner_id, sticker=update.message.sticker.file_id)
    elif update.message.voice: await context.bot.send_voice(chat_id=partner_id, voice=update.message.voice.file_id)

def main():
    # Web server ko alag thread me chalu karo
    threading.Thread(target=run_web_server, daemon=True).start()
    
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("next", next_command))
    app.add_handler(CommandHandler("stop", stop_chat))
    app.add_handler(MessageHandler(filters.Text(['🔍 Find a Stranger']), find_stranger))
    app.add_handler(MessageHandler(filters.Text(['❌ Stop Chat']), stop_chat))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, forward_message))
    
    print("Bot chalu ho gaya hai bhai...")
    app.run_polling()

if __name__ == '__main__':
    main()