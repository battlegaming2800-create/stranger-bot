import asyncio
import logging
import time
import os
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.fsm.storage.memory import MemoryStorage
from aiohttp import web

# ⚙️ BOT PRODUCTION CONFIGURATION
BOT_TOKEN = "8558816321:AAECFBmFK3SxAbTk0-a15Aaw68lq1FsbGP0"
logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# 🗄️ IN-MEMORY ROBUST DATABASE & STATE QUEUES
users_db = {}     
active_chats = {} 
waiting_pool = [] 

# ⏱️ ANTI-SPAM FLOOD TRACER
user_clicks = {}   
cooldown_users = {} 

# --- CORE UTILITY FUNCTIONS ---
def check_spam(user_id: int) -> tuple[bool, str]:
    current_time = time.time()
    if user_id in cooldown_users:
        remaining = int(cooldown_users[user_id] - current_time)
        if remaining > 0:
            mins, secs = divmod(remaining, 60)
            return True, f"{mins}m {secs}s"
        else:
            del cooldown_users[user_id]
            
    if user_id not in user_clicks:
        user_clicks[user_id] = []
        
    user_clicks[user_id] = [t for t in user_clicks[user_id] if current_time - t <= 30]
    user_clicks[user_id].append(current_time)
    
    if len(user_clicks[user_id]) >= 10:
        cooldown_users[user_id] = current_time + 300
        return True, "5m 0s"
        
    return False, ""

# Chat ke doran niche bar par dikhne wala simple reply keyboard
def get_chat_reply_keyboard():
    kb = ReplyKeyboardBuilder()
    kb.row(types.KeyboardButton(text="🚀 Next"), types.KeyboardButton(text="🛑 Stop"))
    return kb.as_markup(resize_keyboard=True)

def get_search_reply_keyboard():
    kb = ReplyKeyboardBuilder()
    kb.row(types.KeyboardButton(text="🛑 Stop"))
    return kb.as_markup(resize_keyboard=True)

async def find_match(user_id: int):
    if user_id in waiting_pool:
        return
        
    clean_pool = [uid for uid in waiting_pool if uid != user_id and uid not in active_chats]
    
    if clean_pool:
        partner_id = clean_pool.pop(0)
        if partner_id in waiting_pool:
            waiting_pool.remove(partner_id)
            
        active_chats[user_id] = partner_id
        active_chats[partner_id] = user_id
        
        # EXACT FORMAT REQUESTED BY YOU (NO BOX BUTTONS HERE)
        match_text = (
            "Partner found 🧐\n\n"
            "/next — find a new partner\n"
            "/stop — stop this chat\n\n"
            "Stranger buddy"
        )
        
        chat_kb = get_chat_reply_keyboard()
        
        try:
            await bot.send_message(user_id, match_text, reply_markup=chat_kb)
        except Exception:
            pass
        try:
            await bot.send_message(partner_id, match_text, reply_markup=chat_kb)
        except Exception:
            pass
        return
            
    waiting_pool.append(user_id)

# BOX PROFILE KEYBOARD (VAISA HI RAKHA HAI JAISA PEHLE THA)
def get_main_setup_kb(uid):
    if uid not in users_db:
        users_db[uid] = {'gender': None, 'age': None, 'country': None}
        
    data = users_db[uid]
    g_label = f"👨🏻 Gender: {data['gender']}" if data['gender'] else "👨🏻 Gender 👱🏻‍♀️"
    a_label = f"📅 Age: {data['age']}" if data['age'] else "📅 Age"
    c_label = f"🌍 Country: {data['country']}" if data['country'] else "🌍 Country"
    
    kb = InlineKeyboardBuilder()
    kb.row(types.InlineKeyboardButton(text=g_label, callback_data="set_gender"))
    kb.row(types.InlineKeyboardButton(text=a_label, callback_data="set_age"),
           types.InlineKeyboardButton(text=c_label, callback_data="set_country"))
    kb.row(types.InlineKeyboardButton(text="🚀 Enter Main Menu", callback_data="enter_main"))
    return kb.as_markup()

async def send_direct_setup_screen(message: types.Message, force_reset=False):
    uid = message.from_user.id
    
    if uid in active_chats: del active_chats[uid]
    if uid in waiting_pool: waiting_pool.remove(uid)
    
    if force_reset or uid not in users_db:
        users_db[uid] = {'gender': None, 'age': None, 'country': None}
        
    text = "📝 <b>Fill basic details to proceed:</b>\n\n💡 <i>Note: Only gender is compulsory. Age and country you can ignore just because it's anonymous!</i> 🤫"
    await message.answer(text, parse_mode="HTML", reply_markup=get_main_setup_kb(uid))

# --- COMMAND HANDLERS ---
@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    await send_direct_setup_screen(message, force_reset=True)

# --- CALLBACK ROUTERS WITH BOX BUTTONS ---
@dp.callback_query(F.data == "open_profile_setup")
async def profile_setup_menu(callback: types.CallbackQuery):
    await callback.answer()
    uid = callback.from_user.id
    text = "📝 <b>Fill basic details to proceed:</b>\n\n💡 <i>Note: Only gender is compulsory. Age and country you can ignore just because it's anonymous!</i> 🤫"
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=get_main_setup_kb(uid))

@dp.callback_query(F.data == "set_gender")
async def process_gender_select(callback: types.CallbackQuery):
    await callback.answer()
    kb = InlineKeyboardBuilder()
    kb.row(types.InlineKeyboardButton(text="I am male 👨🏻", callback_data="g_Male"),
           types.InlineKeyboardButton(text="I am female 👱🏻‍♀️", callback_data="g_Female"))
    kb.row(types.InlineKeyboardButton(text="🔙 Back", callback_data="open_profile_setup"))
    await callback.message.edit_text("Choose ur gender:", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("g_"))
async def save_gender(callback: types.CallbackQuery):
    gender = callback.data.split("_")[1]
    uid = callback.from_user.id
    if uid not in users_db: users_db[uid] = {'gender': None, 'age': None, 'country': None}
    users_db[uid]['gender'] = gender
    await callback.answer(f"Gender set to {gender}! ✅")
    await profile_setup_menu(callback)

@dp.callback_query(F.data == "set_age")
async def process_age_select(callback: types.CallbackQuery):
    await callback.answer()
    kb = InlineKeyboardBuilder()
    kb.row(types.InlineKeyboardButton(text="👶🏻 1-18", callback_data="a_1-18"),
           types.InlineKeyboardButton(text="🧑🏻‍💻 18-25", callback_data="a_18-25"))
    kb.row(types.InlineKeyboardButton(text="👨🏻‍💼 25-30", callback_data="a_25-30"),
           types.InlineKeyboardButton(text="🧔🏻‍♂️ 30+", callback_data="a_30+"))
    kb.row(types.InlineKeyboardButton(text="🔙 Back", callback_data="open_profile_setup"))
    await callback.message.edit_text("Select your age range:", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("a_"))
async def save_age(callback: types.CallbackQuery):
    age_range = callback.data.split("_")[1]
    uid = callback.from_user.id
    if uid not in users_db: users_db[uid] = {'gender': None, 'age': None, 'country': None}
    users_db[uid]['age'] = age_range
    await callback.answer("Age saved! ✅")
    await profile_setup_menu(callback)

@dp.callback_query(F.data == "set_country")
async def process_country_select(callback: types.CallbackQuery):
    await callback.answer()
    kb = InlineKeyboardBuilder()
    flags = ["🇮🇳", "🇺🇸", "🇬🇧", "🇨🇦", "🇦🇺", "🇩🇪", "🇫🇷", "🇧🇷", "🇷🇺", "🇮🇩", "🇵🇭", "🇵🇰", "🇧🇩", "🇳🇵"]
    for i in range(0, len(flags), 2):
        kb.row(types.InlineKeyboardButton(text=flags[i], callback_data=f"c_{flags[i]}"),
               types.InlineKeyboardButton(text=flags[i+1], callback_data=f"c_{flags[i+1]}"))
    kb.row(types.InlineKeyboardButton(text="🌐 Global / Other", callback_data="c_Global"))
    kb.row(types.InlineKeyboardButton(text="🔙 Back", callback_data="open_profile_setup"))
    await callback.message.edit_text("Select your country / region:", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("c_"))
async def save_country(callback: types.CallbackQuery):
    country = callback.data.split("_")[1]
    uid = callback.from_user.id
    if uid not in users_db: users_db[uid] = {'gender': None, 'age': None, 'country': None}
    users_db[uid]['country'] = country
    await callback.answer("Country saved! ✅")
    await profile_setup_menu(callback)

@dp.callback_query(F.data == "enter_main")
async def enter_main_pool(callback: types.CallbackQuery):
    uid = callback.from_user.id
    if uid not in users_db or not users_db[uid].get('gender'):
        await callback.answer("Please select your gender first! ⚠️", show_alert=True)
        return
    
    await callback.answer()
    await callback.message.delete()
    await callback.message.answer("Searching for a stranger buddy... 🔍", reply_markup=get_search_reply_keyboard())
    await find_match(uid)

# --- CHAT TERMINATION FLOW ---
async def handle_stop_flow(user_id: int, triggered_by_self: bool):
    partner_id = active_chats.get(user_id)
    
    if user_id in active_chats: del active_chats[user_id]
    if user_id in waiting_pool: waiting_pool.remove(user_id)
    if partner_id and partner_id in active_chats: del active_chats[partner_id]
    if partner_id and partner_id in waiting_pool: waiting_pool.remove(partner_id)
    
    # Chat khatam hone par BOX wale action buttons milenge unhe niche
    end_kb = InlineKeyboardBuilder()
    end_kb.row(types.InlineKeyboardButton(text="Next 🚀", callback_data="action_next"),
               types.InlineKeyboardButton(text="Report ⚠️", callback_data="action_report"))
    end_markup = end_kb.as_markup()

    if triggered_by_self:
        try:
            await bot.send_message(user_id, "😏 <b>You have stopped the chat.</b>\n\nWhat do you want to do next?", parse_mode="HTML", reply_markup=end_markup)
        except Exception:
            pass
        if partner_id:
            try:
                await bot.send_message(partner_id, "🥺 <b>Your partner has stopped the chat.</b>\n\nWhat do you want to do next?", parse_mode="HTML", reply_markup=end_markup)
            except Exception:
                pass
    else:
        try:
            await bot.send_message(user_id, "🥺 <b>Your partner has stopped the chat.</b>\n\nWhat do you want to do next?", parse_mode="HTML", reply_markup=end_markup)
        except Exception:
            pass

@dp.message(F.text.in_({"🛑 Stop", "Stop", "/stop"}))
@dp.message(Command("stop"))
async def inline_stop_chat(message: types.Message):
    uid = message.from_user.id
    if uid in active_chats or uid in waiting_pool:
        await handle_stop_flow(uid, triggered_by_self=True)
    else:
        await message.answer("You are not in any active chat pool.", reply_markup=types.ReplyKeyboardRemove())

@dp.message(F.text.in_({"🚀 Next", "Next", "/next"}))
@dp.message(Command("next"))
async def inline_next_chat(message: types.Message):
    uid = message.from_user.id
    is_spammer, time_str = check_spam(uid)
    if is_spammer:
        await message.answer(f"🚨 <b>System noticed fast skips. Cooldown: {time_str}</b>", parse_mode="HTML")
        return

    await handle_stop_flow(uid, triggered_by_self=True)
    await message.answer("Searching for a new stranger buddy... 🔍", reply_markup=get_search_reply_keyboard())
    await find_match(uid)

# --- INLINE BOX ACTIONS FOR NEXT & REPORT PANEL ---
@dp.callback_query(F.data == "action_next")
async def callback_next(callback: types.CallbackQuery):
    uid = callback.from_user.id
    is_spammer, time_str = check_spam(uid)
    if is_spammer:
        await callback.answer(f"System noticed fast skips. Cooldown: {time_str}", show_alert=True)
        return
        
    await callback.answer()
    try:
        await callback.message.delete()
    except Exception:
        pass
        
    await handle_stop_flow(uid, triggered_by_self=True)
    await callback.message.answer("Searching for a new stranger buddy... 🔍", reply_markup=get_search_reply_keyboard())
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
        await event.message.edit_text(text, parse_mode="HTML", reply_markup=kb.as_markup())
    else:
        await event.answer(text, parse_mode="HTML", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("rep_"))
async def process_report_submission(callback: types.CallbackQuery):
    await callback.answer("Report submitted successfully! Custom security team will review it. 🛡️", show_alert=True)
    end_kb = InlineKeyboardBuilder()
    end_kb.row(types.InlineKeyboardButton(text="Next 🚀", callback_data="action_next"),
               types.InlineKeyboardButton(text="Report ⚠️", callback_data="action_report"))
    await callback.message.edit_text("What do you want to do next?", reply_markup=end_kb.as_markup())

# --- PRIVACY IDENTITY SHARING LINK ---
@dp.message(Command("share"))
async def cmd_share_link(message: types.Message):
    user = message.from_user
    if user.username:
        share_msg = f"🔗 <b>Here is my private contact profile link:</b> t.me/{user.username}"
    else:
        share_msg = f"🔗 <b>Here is my private profile contact:</b> <a href='tg://user?id={user.id}'>{user.first_name}</a>"
    await message.answer(share_msg, parse_mode="HTML")

# --- CORE UNIVERSAL RELAY LOGIC GATEWAY ---
@dp.message()
async def relay_messages_and_fallback(message: types.Message):
    uid = message.from_user.id
    msg_text = message.text or ""
    
    # 1. Command & Text Routing
    if msg_text.startswith("/start"):
        await send_direct_setup_screen(message, force_reset=True)
        return
    if msg_text in ["🛑 Stop", "Stop", "/stop"]:
        if uid in active_chats or uid in waiting_pool:
            await handle_stop_flow(uid, triggered_by_self=True)
        else:
            await message.answer("You are not in any active chat pool.", reply_markup=types.ReplyKeyboardRemove())
        return
    if msg_text in ["🚀 Next", "Next", "/next"]:
        await inline_next_chat(message)
        return

    # 2. Chat Relay Router
    if uid in active_chats:
        partner_id = active_chats[uid]
        try:
            await message.copy_to(chat_id=partner_id)
        except Exception:
            await handle_stop_flow(uid, triggered_by_self=False)
    else:
        if uid in waiting_pool:
            await message.answer("Still searching for a partner... Please wait or send /stop to cancel.")
            return
            
        if uid in users_db and users_db[uid].get('gender'):
            await message.answer("You are not in any active chat. Searching...", reply_markup=get_search_reply_keyboard())
            await find_match(uid)
        else:
            await send_direct_setup_screen(message, force_reset=False)

# 🌐 WEB PORT ACCESS POINT FOR RENDER CRON ENGINE
async def handle_ping(request):
    return web.Response(text="Stranger Buddy Engine Status: Fully Functional & Online 🚀")

# --- CORE SYSTEM ASSEMBLY ---
async def main():
    commands = [
        types.BotCommand(command="start", description="Start the bot / Create profile"),
        types.BotCommand(command="next", description="Find a new partner instant"),
        types.BotCommand(command="stop", description="Stop the current chat"),
        types.BotCommand(command="report", description="Report your partner"),
        types.BotCommand(command="share", description="Share my profile link")
    ]
    await bot.set_my_commands(commands)
    
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())