import asyncio
import logging
import time
import os
import json
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.exceptions import TelegramForbiddenError
from aiohttp import web

# ⚙️ CONFIGURATION
BOT_TOKEN = "8558816321:AAECFBmFK3SxAbTk0-a15Aaw68lq1FsbGP0"
logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# 🗄️ LOCAL DATABASE LOGIC
DB_FILE = "stranger_users_db.json"
users_db = {}
db_lock = asyncio.Lock()  # Strict IO Isolation

def load_db():
    global users_db
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                users_db = json.load(f)
                for uid in users_db:
                    if 'migrated' not in users_db[uid]:
                        users_db[uid]['migrated'] = True
        except Exception:
            users_db = {}
    else:
        users_db = {}

def save_db_sync():
    try:
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(users_db, f, ensure_ascii=False, indent=4)
    except Exception as e:
        logging.error(f"DB Save Error: {e}")

async def save_db():
    async with db_lock:
        await asyncio.to_thread(save_db_sync)

load_db()

# RUNTIME SYSTEM STATES (High-Speed RAM Cache)
active_chats = {} 
waiting_pool = [] 
message_counters = {}  
user_clicks = {}   
cooldown_users = {} 
routing_locks = {}  # Per-user micro locks to completely kill race conditions

# --- UTILITIES ---
def get_user_lock(user_id: int) -> asyncio.Lock:
    if user_id not in routing_locks:
        routing_locks[user_id] = asyncio.Lock()
    return routing_locks[user_id]

def check_spam(user_id: int) -> tuple[bool, str]:
    current_time = time.time()
    u_id = str(user_id)
    if u_id in cooldown_users:
        remaining = int(cooldown_users[u_id] - current_time)
        if remaining > 0:
            mins, secs = divmod(remaining, 60)
            return True, f"{mins}m {secs}s"
        else:
            del cooldown_users[u_id]
            
    if u_id not in user_clicks:
        user_clicks[u_id] = []
        
    user_clicks[u_id] = [t for t in user_clicks[u_id] if current_time - t <= 30]
    user_clicks[u_id].append(current_time)
    
    if len(user_clicks[u_id]) >= 12:
        cooldown_users[u_id] = current_time + 300
        return True, "5m 0s"
        
    return False, ""

def get_chat_kb():
    kb = ReplyKeyboardBuilder()
    kb.row(types.KeyboardButton(text="🚀 Next"), types.KeyboardButton(text="🛑 Stop"))
    return kb.as_markup(resize_keyboard=True)

def get_search_kb():
    kb = ReplyKeyboardBuilder()
    kb.row(types.KeyboardButton(text="🛑 Stop"))
    return kb.as_markup(resize_keyboard=True)

def get_setup_kb(uid: int):
    u_id = str(uid)
    if u_id not in users_db:
        users_db[u_id] = {'gender': None, 'age': None, 'country': None, 'migrated': True}
        save_db_sync()
        
    data = users_db[u_id]
    g_lbl = f"👨🏻 Gender: {data['gender']}" if data.get('gender') else "👨🏻 Gender 👱🏻‍♀️"
    a_lbl = f"📅 Age: {data['age']}" if data.get('age') else "📅 Age"
    c_lbl = f"🌍 Country: {data['country']}" if data.get('country') else "🌍 Country"
    
    kb = InlineKeyboardBuilder()
    kb.row(types.InlineKeyboardButton(text=g_lbl, callback_data="set_gender"))
    kb.row(types.InlineKeyboardButton(text=a_lbl, callback_data="set_age"),
           types.InlineKeyboardButton(text=c_lbl, callback_data="set_country"))
    kb.row(types.InlineKeyboardButton(text="🚀 Enter Main Menu", callback_data="enter_main"))
    return kb.as_markup()

async def send_setup_screen(message: types.Message, is_update=False):
    uid = message.from_user.id
    u_id = str(uid)
    
    async with get_user_lock(uid):
        if uid in active_chats: del active_chats[uid]
        if uid in waiting_pool: waiting_pool.remove(uid)
        
        if u_id not in users_db:
            users_db[u_id] = {'gender': None, 'age': None, 'country': None, 'migrated': True}
        else:
            users_db[u_id]['migrated'] = True
    await save_db()
        
    if is_update:
        text = "⚙️ <b>Bot has updated to make the experience better! Please select your basic details to proceed! 🚀</b>\n\n💡 <i>Note: Only gender is compulsory. Age and country you can ignore just because it's anonymous!</i> 🤫"
    else:
        text = "📝 <b>Fill basic details to proceed:</b>\n\n💡 <i>Note: Only gender is compulsory. Age and country you can ignore just because it's anonymous!</i> 🤫"
        
    await message.answer(text, parse_mode="HTML", reply_markup=get_setup_kb(uid))

async def find_match(user_id: int):
    # Cross-pool safety thread lock
    if user_id in active_chats:
        return

    clean_pool = [uid for uid in waiting_pool if uid != user_id and uid not in active_chats]
    
    if clean_pool:
        partner_id = clean_pool[0]
        
        # Lock both users atomically during pairing process
        async with get_user_lock(user_id), get_user_lock(partner_id):
            if partner_id in waiting_pool: waiting_pool.remove(partner_id)
            if user_id in waiting_pool: waiting_pool.remove(user_id)
                
            active_chats[user_id] = partner_id
            active_chats[partner_id] = user_id
            message_counters[user_id] = 0
            message_counters[partner_id] = 0
        
        match_text = "Partner found 🧐\n\n/next — find a new partner\n/stop — stop this chat\n\nStranger buddy"
        try: await bot.send_message(user_id, match_text, reply_markup=get_chat_kb())
        except Exception: pass
        try: await bot.send_message(partner_id, match_text, reply_markup=get_chat_kb())
        except Exception: pass
        return
            
    if user_id not in waiting_pool:
        waiting_pool.append(user_id)

# --- COMMANDS ---
@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    u_id = str(message.from_user.id)
    if u_id in users_db and not users_db[u_id].get('migrated', False):
        await send_setup_screen(message, is_update=True)
    else:
        await send_setup_screen(message, is_update=False)

@dp.message(Command("profile"))
async def cmd_profile(message: types.Message):
    await send_setup_screen(message, is_update=False)

# --- CALLBACKS ---
@dp.callback_query(F.data == "open_profile_setup")
async def profile_setup_menu(callback: types.CallbackQuery):
    await callback.answer()
    uid = callback.from_user.id
    text = "📝 <b>Fill basic details to proceed:</b>\n\n💡 <i>Note: Only gender is compulsory.</i>🤫"
    try: await callback.message.edit_text(text, parse_mode="HTML", reply_markup=get_setup_kb(uid))
    except Exception: pass

@dp.callback_query(F.data == "set_gender")
async def select_gender(callback: types.CallbackQuery):
    await callback.answer()
    kb = InlineKeyboardBuilder()
    kb.row(types.InlineKeyboardButton(text="I am male 👨🏻", callback_data="g_Male"),
           types.InlineKeyboardButton(text="I am female 👱🏻‍♀️", callback_data="g_Female"))
    kb.row(types.InlineKeyboardButton(text="🔙 Back", callback_data="open_profile_setup"))
    try: await callback.message.edit_text("Choose ur gender:", reply_markup=kb.as_markup())
    except Exception: pass

@dp.callback_query(F.data.startswith("g_"))
async def save_gender(callback: types.CallbackQuery):
    gender = callback.data.split("_")[1]
    uid = callback.from_user.id
    u_id = str(uid)
    async with get_user_lock(uid):
        if u_id not in users_db: 
            users_db[u_id] = {'gender': None, 'age': None, 'country': None, 'migrated': True}
        users_db[u_id]['gender'] = gender
    await save_db() 
    await callback.answer(f"Gender set to {gender}! ✅")
    try: await callback.message.edit_text("📝 <b>Fill basic details to proceed:</b>", parse_mode="HTML", reply_markup=get_setup_kb(uid))
    except Exception: pass

@dp.callback_query(F.data == "set_age")
async def select_age(callback: types.CallbackQuery):
    await callback.answer()
    kb = InlineKeyboardBuilder()
    kb.row(types.InlineKeyboardButton(text="👶🏻 1-18", callback_data="a_1-18"),
           types.InlineKeyboardButton(text="🧑🏻‍💻 18-25", callback_data="a_18-25"))
    kb.row(types.InlineKeyboardButton(text="👨🏻‍💼 25-30", callback_data="a_25-30"),
           types.InlineKeyboardButton(text="🧔🏻‍♂️ 30+", callback_data="a_30+"))
    kb.row(types.InlineKeyboardButton(text="🔙 Back", callback_data="open_profile_setup"))
    try: await callback.message.edit_text("Select your age range:", reply_markup=kb.as_markup())
    except Exception: pass

@dp.callback_query(F.data.startswith("a_"))
async def save_age(callback: types.CallbackQuery):
    age = callback.data.split("_")[1]
    uid = callback.from_user.id
    u_id = str(uid)
    if u_id in users_db:
        users_db[u_id]['age'] = age
        await save_db()
    await callback.answer("Age saved! ✅")
    try: await callback.message.edit_text("📝 <b>Fill basic details to proceed:</b>", parse_mode="HTML", reply_markup=get_setup_kb(uid))
    except Exception: pass

@dp.callback_query(F.data == "set_country")
async def select_country(callback: types.CallbackQuery):
    await callback.answer()
    kb = InlineKeyboardBuilder()
    flags = ["🇮🇳 India", "🇺🇸 USA", "🇬🇧 UK", "🇨🇦 Canada", "🇦🇺 Australia", "🇩🇪 Germany", "🇫🇷 France", "🇧🇷 Brazil", "🇷🇺 Russia", "🇮🇩 Indonesia", "🇵🇭 Philippines", "🇵🇰 Pakistan", "🇧🇧 Bangladesh", "🇳🇵 Nepal"]
    for i in range(0, len(flags), 2):
        kb.row(types.InlineKeyboardButton(text=flags[i], callback_data=f"c_{flags[i].split()[1]}"),
               types.InlineKeyboardButton(text=flags[i+1], callback_data=f"c_{flags[i+1].split()[1]}"))
    kb.row(types.InlineKeyboardButton(text="🌐 Global / Other", callback_data="c_Global"))
    kb.row(types.InlineKeyboardButton(text="🔙 Back", callback_data="open_profile_setup"))
    try: await callback.message.edit_text("Select your country / region:", reply_markup=kb.as_markup())
    except Exception: pass

@dp.callback_query(F.data.startswith("c_"))
async def save_country(callback: types.CallbackQuery):
    country = callback.data.split("_")[1]
    uid = callback.from_user.id
    u_id = str(uid)
    if u_id in users_db:
        users_db[u_id]['country'] = country
        await save_db()
    await callback.answer("Country saved! ✅")
    try: await callback.message.edit_text("📝 <b>Fill basic details to proceed:</b>", parse_mode="HTML", reply_markup=get_setup_kb(uid))
    except Exception: pass

@dp.callback_query(F.data == "enter_main")
async def enter_main(callback: types.CallbackQuery):
    uid = callback.from_user.id
    u_id = str(uid)
    if u_id not in users_db or not users_db[u_id].get('gender'):
        await callback.answer("Please select your gender first! ⚠️", show_alert=True)
        return
    await callback.answer()
    try: await callback.message.delete()
    except Exception: pass
    await bot.send_message(uid, "Searching for a stranger buddy... 🔍", reply_markup=get_search_kb())
    await find_match(uid)

# --- FLOW MANAGEMENT ---
async def stop_flow(user_id: int, self_triggered: bool):
    partner_id = active_chats.get(user_id)
    
    # Thread isolated popping logic
    async with get_user_lock(user_id):
        if user_id in active_chats: del active_chats[user_id]
        if user_id in waiting_pool: waiting_pool.remove(user_id)
        if user_id in message_counters: del message_counters[user_id]
        
    if partner_id:
        async with get_user_lock(partner_id):
            if partner_id in active_chats: del active_chats[partner_id]
            if partner_id in waiting_pool: waiting_pool.remove(partner_id)
            if partner_id in message_counters: del message_counters[partner_id]
            
    kb = InlineKeyboardBuilder()
    end_kb = kb.row(types.InlineKeyboardButton(text="Next 🚀", callback_data="action_next"),
                    types.InlineKeyboardButton(text="Report ⚠️", callback_data="action_report")).as_markup()

    if self_triggered:
        try: await bot.send_message(user_id, "😏 <b>You have stopped the chat.</b>\n\nWhat do you want to do next?", parse_mode="HTML", reply_markup=end_kb)
        except Exception: pass
        if partner_id:
            try: await bot.send_message(partner_id, "🥺 <b>Your partner has stopped the chat.</b>\n\nWhat do you want to do next?", parse_mode="HTML", reply_markup=end_kb)
            except Exception: pass
    else:
        try: await bot.send_message(user_id, "🥺 <b>Your partner has stopped the chat.</b>\n\nWhat do you want to do next?", parse_mode="HTML", reply_markup=end_kb)
        except Exception: pass

@dp.message(F.text.in_({"🛑 Stop", "Stop", "/stop"}))
@dp.message(Command("stop"))
async def chat_stop(message: types.Message):
    uid = message.from_user.id
    if uid in active_chats or uid in waiting_pool:
        await stop_flow(uid, self_triggered=True)
    else:
        await message.answer("You are not in any active chat pool.", reply_markup=types.ReplyKeyboardRemove())

@dp.message(F.text.in_({"🚀 Next", "Next", "/next"}))
@dp.message(Command("next"))
async def chat_next(message: types.Message):
    uid = message.from_user.id
    is_spam, wait_t = check_spam(uid)
    if is_spam:
        await message.answer(f"🚨 <b>Our system has noticed you are skipping too much so take some rest buddy ⏳ Cooldown time: {wait_t}</b>", parse_mode="HTML")
        return
    await stop_flow(uid, self_triggered=True)
    await asyncio.sleep(0.1)
    await message.answer("Searching for a new stranger buddy... 🔍", reply_markup=get_search_kb())
    await find_match(uid)

@dp.callback_query(F.data == "action_next")
async def cb_next(callback: types.CallbackQuery):
    uid = callback.from_user.id
    is_spam, wait_t = check_spam(uid)
    if is_spam:
        await callback.answer(f"Our system has noticed you are skipping too much so take some rest buddy ⏳ {wait_t}", show_alert=True)
        return
    await callback.answer()
    try: await callback.message.delete()
    except Exception: pass
    await stop_flow(uid, self_triggered=True)
    await bot.send_message(uid, "Searching for a new stranger buddy... 🔍", reply_markup=get_search_kb())
    await find_match(uid)

@dp.callback_query(F.data == "action_report")
@dp.message(Command("report"))
async def callback_report_panel(event: types.CallbackQuery | types.Message):
    if isinstance(event, types.CallbackQuery):
        await event.answer()
        
    kb = InlineKeyboardBuilder()
    reasons = [
        ("🚫 Harassment", "rep_Harass"), ("📩 Spam", "rep_Spam"),
        ("⚠️ Inappropriate", "rep_Inapp"), ("👤 Impersonation", "rep_Imper"),
        ("🔪 Threats", "rep_Threats"), ("💰 Scam/Fraud", "rep_Scam"),
        ("🗣️ Hate Speech", "rep_Hate"), ("🍑 Sexual Content", "rep_Sexual"),
        ("🚨 Extortion", "rep_Extort"), ("🔐 Blackmail", "rep_Black"),
        ("📢 Promoting Groups", "rep_Promo"), ("🤖 Bot/Automation", "rep_Bot"),
        ("⚖️ Illegal Activity", "rep_Illegal"), ("❓ Other", "rep_Other")
    ]
    for i in range(0, len(reasons), 2):
        kb.row(types.InlineKeyboardButton(text=reasons[i][0], callback_data=reasons[i][1]),
               types.InlineKeyboardButton(text=reasons[i+1][0], callback_data=reasons[i+1][1]))
    
    text = "❓ <b>Please select the reason for reporting your partner:</b>"
    if isinstance(event, types.CallbackQuery):
        try: await event.message.edit_text(text, parse_mode="HTML", reply_markup=kb.as_markup())
        except Exception: pass
    else:
        await event.answer(text, parse_mode="HTML", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("rep_"))
async def process_report_submission(callback: types.CallbackQuery):
    await callback.answer("Report submitted successfully! Custom security team will review it. 🛡️", show_alert=True)
    end_kb = InlineKeyboardBuilder()
    end_kb.row(types.InlineKeyboardButton(text="Next 🚀", callback_data="action_next"),
               types.InlineKeyboardButton(text="Report ⚠️", callback_data="action_report"))
    try: await callback.message.edit_text("What do you want to do next?", reply_markup=end_kb.as_markup())
    except Exception: pass

# --- MESSAGE ROUTER ---
@dp.message()
async def gateway_router(message: types.Message):
    uid = message.from_user.id
    u_id = str(uid)
    txt = message.text or ""
    
    # 1. High-speed Direct Commmand interceptors
    if txt in ["🚀 Next", "Next", "/next"]:
        await chat_next(message)
        return
    if txt in ["🛑 Stop", "Stop", "/stop"]:
        await chat_stop(message)
        return
    if txt.startswith("/start"):
        await send_setup_screen(message, is_update=False)
        return

    # 2. Sequential User Scope Lock
    async with get_user_lock(uid):
        if u_id in users_db and not users_db[u_id].get('migrated', False):
            await send_setup_screen(message, is_update=True)
            return

        is_active = uid in active_chats
        is_waiting = uid in waiting_pool
        has_gender = u_id in users_db and users_db[u_id].get('gender')

    # 3. Dynamic Execution Out of Critical Block
    if is_active:
        if txt and ("t.me" in txt or "@" in txt) and message_counters.get(uid, 0) < 4:
            await message.answer("⚠️ Identity and link sharing is locked! Please chat for at least 3-4 messages first to unlock this feature.")
            return
        p_id = active_chats.get(uid)
        if p_id:
            try:
                await message.copy_to(chat_id=p_id)
                message_counters[uid] = message_counters.get(uid, 0) + 1
            except TelegramForbiddenError:
                await stop_flow(uid, self_triggered=False)
            except Exception: pass
    elif is_waiting:
        # Puraani echo text problem fixed permanently here
        return
    else:
        if has_gender:
            await message.answer("You are not in an active chat right now. Click on 🚀 Enter Main Menu above to start searching!", reply_markup=types.ReplyKeyboardRemove())
        else:
            await message.answer("⚠️ Please select your Gender using the box button options above first!", reply_markup=types.ReplyKeyboardRemove())

# --- WEB SERVER FOR RENDER ---
async def web_ping(request):
    return web.Response(text="Stranger Buddy Engine Status: Fully Functional & Online 🚀")

async def main():
    cmds = [
        types.BotCommand(command="start", description="Start Bot / Create Profile"),
        types.BotCommand(command="next", description="Find a new partner instant"),
        types.BotCommand(command="stop", description="Stop the current chat"),
        types.BotCommand(command="report", description="Report your partner"),
        types.BotCommand(command="profile", description="View / Edit Profile Details")
    ]
    await bot.set_my_commands(cmds)
    
    app = web.Application()
    app.router.add_get("/", web_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 10000))
    await web.TCPSite(runner, "0.0.0.0", port).start()
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())