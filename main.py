import os
from flask import Flask
import threading
import json
import logging
import random
import time
import qrcode
import io
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    CallbackQueryHandler
)
import httpx
from datetime import datetime
from typing import List, Dict, Optional

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Bot Configuration
class BotConfig:
    def __init__(self):
        self.config = self.load_config()
        self.bot_name = self.config.get('BOT_NAME', '𝙷𝚒𝚗𝚊𝚝𝚊')
        self.owner_name = self.config.get('OWNER_NAME', '𝙰𝚜𝚑')
        self.language = self.config.get('LANGUAGE', '𝙷𝚒𝚗𝚍𝚒')
        self.support_group = self.config.get('SUPPORT_GROUP', 'https://t.me/vcpeople')
        self.bot_username = self.config.get('BOT_USERNAME', '@thehintaprobot')
        self.owner_id = 7269251740  # Your user ID
        self.maintenance_mode = False
        
    def load_config(self):
        config = {}
        try:
            with open('config.txt', 'r') as f:
                for line in f:
                    if '=' in line:
                        key, value = line.strip().split('=', 1)
                        config[key.strip()] = value.strip()
        except FileNotFoundError:
            logger.error("ᴄᴏɴꜰɪɢ.ᴛxᴛ ꜰɪʟᴇ ɴᴏᴛ ꜰᴏᴜɴᴅ")
            raise
        except Exception as e:
            logger.error(f"ᴇʀʀᴏʀ ʀᴇᴀᴅɪɴɢ ᴄᴏɴꜰɪɢ.ᴛxᴛ: {e}")
            raise
        
        required_keys = ['TELEGRAM_BOT_TOKEN', 'HINGLISH_PROMPT']
        for key in required_keys:
            if key not in config:
                raise ValueError(f"ᴍɪꜱꜱɪɴɢ ʀᴇQᴜɪʀᴇᴅ ᴋᴇʏ ɪɴ ᴄᴏɴꜰɪɢ: {key}")
        
        return config

# Initialize config
config = BotConfig()

# Banned users storage
BANNED_USERS_FILE = "banned_users.json"

def load_banned_users():
    try:
        if os.path.exists(BANNED_USERS_FILE):
            with open(BANNED_USERS_FILE, 'r') as f:
                return json.load(f)
        return []
    except Exception as e:
        logger.error(f"ᴇʀʀᴏʀ ʟᴏᴀᴅɪɴɢ ʙᴀɴɴᴇᴅ ᴜꜱᴇʀꜱ: {e}")
        return []

def save_banned_users(banned_users):
    try:
        with open(BANNED_USERS_FILE, 'w') as f:
            json.dump(banned_users, f, indent=2)
    except Exception as e:
        logger.error(f"ᴇʀʀᴏʀ ꜱᴀᴠɪɴɢ ʙᴀɴɴᴇᴅ ᴜꜱᴇʀꜱ: {e}")

class GeminiAPI:
    def __init__(self):
        self.api_keys = self.parse_api_keys()
        self.current_key_index = 0
        self.model_priority = [
            "gemini-2.5-flash-lite",
            "gemini-2.5-flash"
        ]
        self.current_model_index = 0
        self.key_usage = {key: 0 for key in self.api_keys}
        self.max_retries = 3
        
    def parse_api_keys(self) -> List[str]:
        """Parse API keys from config"""
        keys = []
        if 'GEMINI_API_KEY' in config.config:
            keys.append(config.config['GEMINI_API_KEY'])
        
        i = 1
        while f'GEMINI_API_KEY_{i}' in config.config:
            keys.append(config.config[f'GEMINI_API_KEY_{i}'])
            i += 1
        
        if not keys:
            raise ValueError("ɴᴏ ɢᴇᴍɪɴɪ ᴀᴘɪ ᴋᴇʏꜱ ꜰᴏᴜɴᴅ ɪɴ ᴄᴏɴꜰɪɢ")
        
        return keys
    
    def get_current_key(self) -> str:
        return self.api_keys[self.current_key_index]
    
    def get_current_model(self) -> str:
        return self.model_priority[self.current_model_index]
    
    def rotate_key(self):
        self.current_key_index = (self.current_key_index + 1) % len(self.api_keys)
        logger.info(f"ʀᴏᴛᴀᴛᴇᴅ ᴛᴏ ᴀᴘɪ ᴋᴇʏ ɪɴᴅᴇx {self.current_key_index}")
    
    def downgrade_model(self):
        if self.current_model_index < len(self.model_priority) - 1:
            self.current_model_index += 1
            logger.info(f"ᴅᴏᴡɴɢʀᴀᴅᴇᴅ ᴛᴏ ᴍᴏᴅᴇʟ: {self.get_current_model()}")
    
    def upgrade_model(self):
        if self.current_model_index > 0:
            self.current_model_index -= 1
            logger.info(f"ᴜᴘɢʀᴀᴅᴇᴅ ᴛᴏ ᴍᴏᴅᴇʟ: {self.get_current_model()}")
    
    def get_api_url(self) -> str:
        return f"https://generativelanguage.googleapis.com/v1beta/models/{self.get_current_model()}:generateContent?key={self.get_current_key()}"
    
    async def call_api(self, payload: Dict) -> Dict:
        """Make API call with automatic key rotation and model fallback"""
        headers = {"Content-Type": "application/json"}
        last_error = None
        
        for attempt in range(self.max_retries):
            url = self.get_api_url()
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.post(url, json=payload, headers=headers)
                    
                    if response.status_code == 429:
                        logger.warning(f"ʀᴀᴛᴇ ʟɪᴍɪᴛᴇᴅ ᴏɴ ᴋᴇʏ {self.current_key_index}")
                        self.rotate_key()
                        continue
                    
                    response.raise_for_status()
                    self.key_usage[self.get_current_key()] += 1
                    return response.json()
                    
            except httpx.HTTPStatusError as e:
                last_error = e
                if e.response.status_code == 429:
                    if self.get_current_model() != "gemini-2.5-flash-lite":
                        self.downgrade_model()
                    else:
                        self.rotate_key()
                continue
            except Exception as e:
                last_error = e
                continue
        
        raise last_error if last_error else Exception("ᴍᴀx ʀᴇᴛʀɪᴇꜱ ʀᴇᴀᴄʜᴇᴅ")

# Initialize Gemini API handler
gemini = GeminiAPI()

# Conversation history storage
CONVERSATION_HISTORY_FILE = "conversation_history.json"

def load_conversation_history():
    try:
        if os.path.exists(CONVERSATION_HISTORY_FILE):
            with open(CONVERSATION_HISTORY_FILE, 'r') as f:
                return json.load(f)
        return {}
    except Exception as e:
        logger.error(f"ᴇʀʀᴏʀ ʟᴏᴀᴅɪɴɢ ᴄᴏɴᴠᴇʀꜱᴀᴛɪᴏɴ ʜɪ�ᴛᴏʀʏ: {e}")
        return {}

def save_conversation_history(history):
    try:
        with open(CONVERSATION_HISTORY_FILE, 'w') as f:
            json.dump(history, f, indent=2)
    except Exception as e:
        logger.error(f"ᴇʀʀᴏʀ ꜱᴀᴠɪɴɢ ᴄᴏɴᴠᴇʀꜱᴀᴛɪᴏɴ ʜɪꜱᴛᴏʀʏ: {e}")

def update_conversation_history(chat_id, role, message):
    history = load_conversation_history()
    
    if str(chat_id) not in history:
        history[str(chat_id)] = []
    
    if len(history[str(chat_id)]) >= 10:
        history[str(chat_id)] = history[str(chat_id)][-9:]
    
    history[str(chat_id)].append({
        "role": role,
        "message": message,
        "timestamp": datetime.now().isoformat()
    })
    
    save_conversation_history(history)

async def generate_response(chat_id: int, user_message: str) -> str:
    history = load_conversation_history()
    chat_history = history.get(str(chat_id), [])
    
    contents = []
    contents.append({
        "role": "user",
        "parts": [{"text": config.config['HINGLISH_PROMPT']}]
    })
    
    for msg in chat_history:
        contents.append({
            "role": msg["role"],
            "parts": [{"text": msg["message"]}]
        })
    
    contents.append({
        "role": "user",
        "parts": [{"text": user_message}]
    })
    
    payload = {
        "contents": contents,
        "systemInstruction": {
            "parts": [{
                "text": f"ʏᴏᴜ ᴀʀᴇ {config.bot_name}, ᴀ ꜰʀɪᴇɴᴅʟʏ ᴀɪ ᴄʜᴀᴛʙᴏᴛ ꜱᴘᴇᴀᴋɪɴɢ ɪɴ {config.language}. "
                        "ʀᴇᴍᴇᴍʙᴇʀ ᴄᴏɴᴠᴇʀꜱᴀᴛɪᴏɴ ʜɪꜱᴛᴏʀʏ ᴀɴᴅ ʀᴇꜱᴘᴏɴᴅ ᴀᴄᴄᴏʀᴅɪɴɢʟʏ. "
                        "ᴋᴇᴇᴘ ʀᴇꜱᴘᴏɴꜱᴇꜱ ᴄᴀꜱᴜᴀʟ ᴀɴᴅ ꜰᴜɴ ᴡɪᴛʜ ᴇᴍᴏᴊɪꜱ."
            }]
        }
    }
    
    try:
        response = await gemini.call_api(payload)
        
        if 'candidates' in response and response['candidates']:
            parts = response['candidates'][0]['content']['parts']
            if parts:
                return parts[0]['text']
        
        return "ᴏᴏᴘꜱ! ɢᴇᴍɪɴɪ ɴᴇ ᴋᴜᴄʜ ɴᴀʜɪ ʙᴏʟᴀ. ꜰɪʀ ꜱᴇ ᴛʀʏ ᴋᴀʀᴏ ʏᴀ ʙᴀᴀᴅ ᴍᴇ ᴄʜᴇᴄᴋ ᴋᴀʀᴏ. 😅"
        
    except httpx.HTTPStatusError as e:
        logger.error(f"ʜᴛᴛᴘ ᴇʀʀᴏʀ ᴄᴀʟʟɪɴɢ ɢᴇᴍɪɴɪ ᴀᴘɪ: {e}")
        return f"ᴀᴘɪ ᴇʀʀᴏʀ ʜᴜᴀ (ꜱᴛᴀᴛᴜꜱ {e.response.status_code})"
    except Exception as e:
        logger.error(f"ᴇʀʀᴏʀ ᴄᴀʟʟɪɴɢ ɢᴇᴍɪɴɪ ᴀᴘɪ: {e}")
        return f"ᴇʀʀᴏʀ ʜᴜᴀ ɢᴇᴍɪɴɪ ᴀᴘɪ ᴄᴀʟʟ ᴍᴇ: {str(e)}"

# Menu and Button Handlers
def get_main_menu_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("✦ʜᴇʟᴘ✦", callback_data='help'),
            InlineKeyboardButton("✦ᴀᴅᴅ ᴍᴇ✦", callback_data='add_to_group'),
        ],
        [
            InlineKeyboardButton("✦ᴄᴏᴍᴍᴀɴᴅꜱ✦", callback_data='commands'),
            InlineKeyboardButton("✦ᴏᴡɴᴇʀ✦", callback_data='owner'),
        ],
        [
            InlineKeyboardButton("✦ᴄʜᴀɴɢᴇ ʟᴀɴɢᴜᴀɢᴇ✦", callback_data='change_language'),
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_message = (
        f"✨ ➤ ʜɪ, ɪ'ᴍ {config.bot_name} ! ɪ'ᴍ ʏᴏᴜʀ ꜰᴜɴ ᴀɴᴅ ꜰʀɪᴇɴᴅʟʏ ᴄᴏᴍᴘᴀɴɪᴏɴ ᴡʜᴏ ʟᴏᴠᴇꜱ ᴄʜᴀᴛᴛɪɴɢ ɪɴ ʜɪɴᴅɪ. "
        f"ᴡʜᴇᴛʜᴇʀ ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ʟᴀᴜɢʜ, ꜱʜᴀʀᴇ ʏᴏᴜʀ ᴛʜᴏᴜɢʜᴛꜱ, ᴏʀ ᴊᴜꜱᴛ ᴋɪʟʟ ꜱᴏᴍᴇ ᴛɪᴍᴇ, "
        f"ɪ'ᴍ ᴀʟᴡᴀʏꜱ ʜᴇʀᴇ ᴛᴏ ᴍᴀᴋᴇ ᴛʜᴇ ᴄᴏɴᴠᴇʀꜱᴀᴛɪᴏɴ ʟɪɢʜᴛ ᴀɴᴅ ᴊᴏʏꜰᴜʟ. "
        f"ᴛʜɪɴᴋ ᴏꜰ ᴍᴇ ᴀꜱ ᴀ ᴅᴏꜱᴛ ᴡʜᴏ ɴᴇᴠᴇʀ ʟᴇᴛꜱ ʏᴏᴜ ꜰᴇᴇʟ ᴀʟᴏɴᴇ. 🌸💬"
    )
    
    await update.message.reply_text(
        welcome_message,
        reply_markup=get_main_menu_keyboard(),
        parse_mode='Markdown'
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == 'help':
        response = (
            f"🆘 **{config.bot_name} ʜᴇʟᴘ** 🆘\n\n"
            "✦ /start - ꜱʜᴏᴡ ᴡᴇʟᴄᴏᴍᴇ ᴍᴇꜱꜱᴀɢᴇ\n"
            "✦ /clearmemory - ᴄʟᴇᴀʀ ᴄʜᴀᴛ ʜɪꜱᴛᴏʀʏ\n"
            "✦ /status - ꜱʜᴏᴡ ʙᴏᴛ ꜱᴛᴀᴛᴜꜱ\n\n"
            "ᴊᴜꜱᴛ ᴛʏᴘᴇ ᴀɴʏᴛʜɪɴɢ ᴛᴏ ᴄʜᴀᴛ ᴡɪᴛʜ ᴍᴇ!\n"
            "ɪ ʀᴇᴍᴇᴍʙᴇʀ ᴏᴜʀ ʟᴀꜱᴛ 10 ᴍᴇꜱꜱᴀɢᴇꜱ."
        )
    elif query.data == 'add_to_group':
        response = (
            f"📢 **ᴀᴅᴅ {config.bot_name} ᴛᴏ ʏᴏᴜʀ ɢʀᴏᴜᴘ!**\n\n"
            f"ᴄʟɪᴄᴋ [ʜᴇʀᴇ]({config.bot_username}?startgroup=true) ᴛᴏ ᴀᴅᴅ ᴍᴇ ᴛᴏ ʏᴏᴜʀ ɢʀᴏᴜᴘ.\n\n"
            "ɪ'ʟʟ ʙʀɪɴɢ ꜰᴜɴ ᴄᴏɴᴠᴇʀꜱᴀᴛɪᴏɴꜱ ᴛᴏ ʏᴏᴜʀ ɢʀᴏᴜᴘ ᴍᴇᴍʙᴇʀꜱ!"
        )
    elif query.data == 'commands':
        response = (
            "🔧 **ᴀᴠᴀɪʟᴀʙʟᴇ ᴄᴏᴍᴍᴀɴᴅꜱ** 🔧\n\n"
            "✦ /start - ꜱʜᴏᴡ ᴡᴇʟᴄᴏᴍᴇ ᴍᴇꜱꜱᴀɢᴇ\n"
            "✦ /clearmemory - ᴄʟᴇᴀʀ ᴄʜᴀᴛ ʜɪꜱᴛᴏʀʏ\n"
            "✦ /status - ꜱʜᴏᴡ ʙᴏᴛ ꜱᴛᴀᴛᴜꜱ\n"
            "✦ /help - ꜱʜᴏᴡ ᴛʜɪꜱ ʜᴇʟᴘ ᴍᴇꜱꜱᴀɢᴇ\n\n"
            "ᴊᴜꜱᴛ ᴄʜᴀᴛ ɴᴀᴛᴜʀᴀʟʟʏ ꜰᴏʀ ᴄᴏɴᴠᴇʀꜱᴀᴛɪᴏɴꜱ!"
        )
    elif query.data == 'owner':
        response = (
            f"👑 **ʙᴏᴛ ᴏᴡɴᴇʀ** 👑\n\n"
            f"ʙᴏᴛ ᴄʀᴇᴀᴛᴇᴅ ᴀɴᴅ ᴍᴀɪɴᴛᴀɪɴᴇᴅ ʙʏ: {config.owner_name}\n\n"
            f"ꜰᴏʀ ᴀɴʏ ɪꜱꜱᴜᴇꜱ ᴏʀ ꜱᴜɢɢᴇꜱᴛɪᴏɴꜱ, ᴄᴏɴᴛᴀᴄᴛ {config.owner_name}."
        )
    elif query.data == 'change_language':
        response = (
            f"🌐 **ʟᴀɴɢᴜᴀɢᴇ ꜱᴇᴛᴛɪɴɢꜱ** 🌐\n\n"
            f"ᴄᴜʀʀᴇɴᴛ ʟᴀɴɢᴜᴀɢᴇ: {config.language}\n\n"
            "ᴀᴠᴀɪʟᴀʙʟᴇ ʟᴀɴɢᴜᴀɢᴇꜱ:\n"
            "✦ ʜɪɴɢʟɪꜱʜ (ᴅᴇꜰᴀᴜʟᴛ)\n"
            "✦ �ɴɢʟɪꜱʜ\n"
            "✦ ʜɪɴᴅɪ\n\n"
            "ᴛᴏ ᴄʜᴀɴɢᴇ ʟᴀɴɢᴜᴀɢᴇ, ᴄᴏɴᴛᴀᴄᴛ ᴍʏ ᴏᴡɴᴇʀ!"
        )
    else:
        response = "ɪɴᴠᴀʟɪᴅ ᴏᴘᴛɪᴏɴ ꜱᴇʟᴇᴄᴛᴇᴅ."
    
    await query.edit_message_text(
        text=response,
        reply_markup=get_main_menu_keyboard(),
        parse_mode='Markdown'
    )

# ======================
# Owner-only commands
# ======================

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != config.owner_id:
        await update.message.reply_text("❌ ᴛʜɪꜱ ᴄᴏᴍᴍᴀɴᴅ ɪꜱ ᴏɴʟʏ ꜰᴏʀ �ʏ ᴏᴡɴᴇʀ!")
        return
    
    if not context.args:
        await update.message.reply_text("ᴜꜱᴀɢᴇ: /broadcast <ᴍᴇꜱꜱᴀɢᴇ>")
        return
    
    message = ' '.join(context.args)
    history = load_conversation_history()
    count = 0
    
    for chat_id in history.keys():
        try:
            await context.bot.send_message(chat_id=int(chat_id), text=message)
            count += 1
        except Exception as e:
            logger.error(f"ꜰᴀɪʟᴇᴅ ᴛᴏ ꜱᴇɴᴅ ʙʀᴏᴀᴅᴄᴀꜱᴛ ᴛᴏ {chat_id}: {e}")
    
    await update.message.reply_text(f"📢 ʙʀᴏᴀᴅᴄᴀꜱᴛ ꜱᴇɴᴛ ᴛᴏ {count} ᴜꜱᴇʀꜱ!")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != config.owner_id:
        await update.message.reply_text("❌ ᴛʜɪꜱ ᴄᴏᴍᴍᴀɴᴅ ɪꜱ ᴏɴʟʏ ꜰᴏʀ ᴍʏ ᴏᴡɴᴇʀ!")
        return
    
    history = load_conversation_history()
    banned_users = load_banned_users()
    
    stats_msg = (
        f"📊 **ʙᴏᴛ ꜱᴛᴀᴛɪꜱᴛɪᴄꜱ** 📊\n\n"
        f"✦ ᴀᴄᴛɪᴠᴇ ᴜꜱᴇʀꜱ: {len(history)}\n"
        f"✦ ʙᴀɴɴᴇᴅ ᴜꜱᴇʀꜱ: {len(banned_users)}\n"
        f"✦ ᴀᴘɪ ᴋᴇʏꜱ: {len(gemini.api_keys)}\n"
        f"✦ ᴄᴜʀʀᴇɴᴛ ᴍᴏᴅᴇʟ: {gemini.get_current_model()}\n\n"
        "🔢 **ᴋᴇʏ ᴜꜱᴀɢᴇ**:\n"
    )
    
    for i, key in enumerate(gemini.api_keys):
        stats_msg += f"  ▸ ᴋᴇʏ {i+1}: {gemini.key_usage[key]} ʀᴇQᴜᴇꜱᴛꜱ\n"
    
    await update.message.reply_text(stats_msg, parse_mode='Markdown')

async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != config.owner_id:
        await update.message.reply_text("❌ ᴛʜɪꜱ ᴄᴏᴍᴍᴀɴᴅ ɪꜱ ᴏɴʟʏ ꜰᴏʀ ᴍʏ ᴏᴡɴᴇʀ!")
        return
    
    if not context.args:
        await update.message.reply_text("ᴜꜱᴀɢᴇ: /ban <ᴜꜱᴇʀ_ɪᴅ>")
        return
    
    try:
        user_id = int(context.args[0])
        banned_users = load_banned_users()
        
        if user_id in banned_users:
            await update.message.reply_text(f"ᴜꜱᴇʀ {user_id} ɪꜱ ᴀʟʀᴇᴀᴅʏ ʙᴀɴɴᴇᴅ.")
        else:
            banned_users.append(user_id)
            save_banned_users(banned_users)
            await update.message.reply_text(f"✅ ᴜꜱᴇʀ {user_id} ʜᴀꜱ ʙᴇᴇɴ ʙᴀɴɴᴇᴅ.")
    except ValueError:
        await update.message.reply_text("ɪɴᴠᴀʟɪᴅ ᴜꜱᴇʀ ɪᴅ. ᴘʟᴇᴀꜱᴇ ᴘʀᴏᴠɪᴅᴇ ᴀ ɴᴜᴍᴇʀɪᴄ ɪᴅ.")

async def unban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != config.owner_id:
        await update.message.reply_text("❌ ᴛʜɪꜱ ᴄᴏᴍᴍᴀɴᴅ ɪꜱ ᴏɴʟʏ ꜰᴏʀ ᴍʏ ᴏᴡɴᴇʀ!")
        return
    
    if not context.args:
        await update.message.reply_text("ᴜꜱᴀɢᴇ: /unban <ᴜꜱᴇʀ_ɪᴅ>")
        return
    
    try:
        user_id = int(context.args[0])
        banned_users = load_banned_users()
        
        if user_id in banned_users:
            banned_users.remove(user_id)
            save_banned_users(banned_users)
            await update.message.reply_text(f"✅ ᴜꜱᴇʀ {user_id} ʜᴀꜱ ʙᴇᴇɴ ᴜɴʙᴀɴɴᴇᴅ.")
        else:
            await update.message.reply_text(f"ᴜꜱᴇʀ {user_id} ɪꜱ ɴᴏᴛ ʙᴀɴɴᴇᴅ.")
    except ValueError:
        await update.message.reply_text("ɪɴᴠᴀʟɪᴅ ᴜꜱᴇʀ ɪᴅ. ᴘʟᴇᴀꜱᴇ ᴘʀᴏᴠɪᴅᴇ ᴀ ɴᴜᴍᴇʀɪᴄ ɪᴅ.")

async def maintenance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != config.owner_id:
        await update.message.reply_text("❌ ᴛʜɪꜱ ᴄᴏᴍᴍᴀɴᴅ ɪꜱ ᴏɴʟʏ ꜰᴏʀ ᴍʏ ᴏᴡɴᴇʀ!")
        return
    
    if not context.args:
        await update.message.reply_text(f"ᴍᴀɪɴᴛᴇɴᴀɴᴄᴇ ᴍᴏᴅᴇ ɪꜱ ᴄᴜʀʀᴇɴᴛʟʏ {'ᴏɴ' if config.maintenance_mode else 'ᴏꜰꜰ'}")
        return
    
    mode = context.args[0].lower()
    if mode in ['on', 'true', 'enable']:
        config.maintenance_mode = True
        await update.message.reply_text("🛠 ᴍᴀɪɴᴛᴇɴᴀɴᴄᴇ ᴍᴏᴅᴇ ɪꜱ ɴᴏᴡ ᴏɴ")
    elif mode in ['off', 'false', 'disable']:
        config.maintenance_mode = False
        await update.message.reply_text("✅ ᴍᴀɪɴᴛᴇɴᴀɴᴄᴇ ᴍᴏᴅᴇ ɪꜱ ɴᴏᴡ ᴏꜰꜰ")
    else:
        await update.message.reply_text("ᴜꜱᴀɢᴇ: /maintenance <ᴏɴ/ᴏꜰꜰ>")

async def get_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != config.owner_id:
        await update.message.reply_text("❌ ᴛʜɪꜱ ᴄᴏᴍᴍᴀɴᴅ ɪꜱ ᴏɴʟʏ ꜰᴏʀ ᴍʏ ᴏᴡɴᴇʀ!")
        return
    
    if not context.args:
        await update.message.reply_text("ᴜꜱᴀɢᴇ: /getuser <ᴜꜱᴇʀ_ɪᴅ>")
        return
    
    try:
        user_id = int(context.args[0])
        user = await context.bot.get_chat(user_id)
        
        user_info = (
            f"👤 **ᴜꜱᴇʀ ɪɴꜰᴏ** 👤\n\n"
            f"✦ ɪᴅ: `{user.id}`\n"
            f"✦ ɴᴀᴍᴇ: {user.full_name}\n"
            f"✦ ᴜꜱᴇʀɴᴀᴍᴇ: @{user.username if user.username else 'ɴ/ᴀ'}\n"
            f"✦ ɪꜱ ʙᴏᴛ: {user.is_bot}\n"
        )
        
        await update.message.reply_text(user_info, parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text(f"ᴇʀʀᴏʀ: {str(e)}")

async def backup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != config.owner_id:
        await update.message.reply_text("❌ ᴛʜɪꜱ ᴄᴏᴍᴍᴀɴᴅ ɪꜱ ᴏɴʟʏ ꜰᴏʀ �ʏ ᴏᴡɴᴇʀ!")
        return
    
    try:
        with open(CONVERSATION_HISTORY_FILE, 'rb') as f:
            await update.message.reply_document(document=f, filename="conversation_history_backup.json")
        await update.message.reply_text("✅ ʙᴀᴄᴋᴜᴘ ᴄᴏᴍᴘʟᴇᴛᴇᴅ!")
    except Exception as e:
        await update.message.reply_text(f"ʙᴀᴄᴋᴜᴘ ꜰᴀɪʟᴇᴅ: {str(e)}")

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != config.owner_id:
        await update.message.reply_text("❌ ᴛʜɪꜱ ᴄᴏᴍᴍᴀɴᴅ ɪꜱ ᴏɴʟʏ ꜰᴏʀ ᴍʏ ᴏᴡɴᴇʀ!")
        return
    
    start_time = time.time()
    message = await update.message.reply_text("🏓 ᴘᴏɴɢ!")
    end_time = time.time()
    latency = round((end_time - start_time) * 1000, 2)
    
    await message.edit_text(f"🏓 ᴘᴏɴɢ! ʟᴀᴛᴇɴᴄʏ: {latency}ᴍꜱ")

# ======================
# Utility commands
# ======================

async def dice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sides = 6
    if context.args and context.args[0].isdigit():
        sides = int(context.args[0])
        if sides < 2:
            sides = 2
        elif sides > 100:
            sides = 100
    
    result = random.randint(1, sides)
    await update.message.reply_text(f"🎲 ʏᴏᴜ ʀᴏʟʟᴇᴅ ᴀ {result} (ᴅ{sides})")

async def flip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = random.choice(["ʜᴇᴀᴅꜱ", "ᴛᴀɪls"])
    await update.message.reply_text(f"🪙 It's {result}!")

async def password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    length = 12
    if context.args and context.args[0].isdigit():
        length = int(context.args[0])
        if length < 6:
            length = 6
        elif length > 32:
            length = 32
    
    chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!@#$%^&*()"
    password = ''.join(random.choice(chars) for _ in range(length))
    await update.message.reply_text(f"🔑 Generated password:\n`{password}`", parse_mode='Markdown')

async def qr_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /qr <text>")
        return
    
    text = ' '.join(context.args)
    qr = qrcode.QRCode()
    qr.add_data(text)
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="black", back_color="white")
    bio = io.BytesIO()
    img.save(bio, "PNG")
    bio.seek(0)
    
    await update.message.reply_photo(photo=bio, caption=f"QR Code for: {text}")

async def countdown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Usage: /countdown <seconds>")
        return
    
    seconds = int(context.args[0])
    if seconds < 1 or seconds > 60:
        await update.message.reply_text("Please choose between 1-60 seconds")
        return
    
    message = await update.message.reply_text(f"⏳ Countdown: {seconds}")
    
    for remaining in range(seconds-1, -1, -1):
        time.sleep(1)
        await message.edit_text(f"⏳ Countdown: {remaining}")
    
    await message.edit_text("🎉 Countdown finished!")

async def timer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Usage: /timer <minutes>")
        return
    
    minutes = int(context.args[0])
    if minutes < 1 or minutes > 120:
        await update.message.reply_text("Please choose between 1-120 minutes")
        return
    
    message = await update.message.reply_text(f"⏳ Timer set for {minutes} minute(s)")
    time.sleep(minutes * 60)
    await message.edit_text(f"⏰ Timer for {minutes} minute(s) is up!")

async def rate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /rate <thing>")
        return
    
    thing = ' '.join(context.args)
    rating = random.randint(1, 10)
    await update.message.reply_text(f"I'd rate {thing} a {rating}/10 🌟")

async def decide(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or '|' not in ' '.join(context.args):
        await update.message.reply_text("Usage: /decide <option1|option2>")
        return
    
    options = ' '.join(context.args).split('|')
    if len(options) < 2:
        await update.message.reply_text("Please provide at least 2 options separated by |")
        return
    
    choice = random.choice(options).strip()
    await update.message.reply_text(f"I choose: {choice}")

async def color_preview(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /color <hex_code> (e.g., /color FF5733)")
        return
    
    hex_color = context.args[0].lstrip('#')
    if len(hex_color) != 6:
        await update.message.reply_text("Invalid hex color. Please provide a 6-character hex code (e.g., FF5733)")
        return
    
    try:
        # Create a simple color image
        from PIL import Image, ImageDraw
        img = Image.new('RGB', (200, 200), color=f"#{hex_color}")
        draw = ImageDraw.Draw(img)
        draw.text((10, 10), f"#{hex_color}", fill="black")
        
        bio = io.BytesIO()
        img.save(bio, "PNG")
        bio.seek(0)
        
        await update.message.reply_photo(photo=bio, caption=f"Color preview for #{hex_color}")
    except Exception as e:
        await update.message.reply_text(f"Error generating color preview: {str(e)}")

async def fancy_font(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /font <text>")
        return
    
    text = ' '.join(context.args)
    # A simple font transformation (you can expand this)
    fancy_text = text.upper().translate(str.maketrans(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ",
        "𝔄𝔅ℭ𝔇𝔈𝔉𝔊ℌℑ𝔍𝔎𝔏𝔐𝔑𝔒𝔓𝔔ℜ𝔖𝔗𝔘𝔙𝔚𝔛𝔜ℨ"
    ))
    await update.message.reply_text(fancy_text)

async def temp_convert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or len(context.args) != 2:
        await update.message.reply_text("Usage: /temp <value> <C/F/K> (e.g., /temp 32 F)")
        return
    
    try:
        value = float(context.args[0])
        unit = context.args[1].upper()
        
        if unit == 'C':
            f = (value * 9/5) + 32
            k = value + 273.15
            await update.message.reply_text(
                f"🌡 Temperature Conversion:\n"
                f"{value}°C = {f:.1f}°F\n"
                f"{value}°C = {k:.1f}K"
            )
        elif unit == 'F':
            c = (value - 32) * 5/9
            k = c + 273.15
            await update.message.reply_text(
                f"🌡 Temperature Conversion:\n"
                f"{value}°F = {c:.1f}°C\n"
                f"{value}°F = {k:.1f}K"
            )
        elif unit == 'K':
            c = value - 273.15
            f = (c * 9/5) + 32
            await update.message.reply_text(
                f"🌡 Temperature Conversion:\n"
                f"{value}K = {c:.1f}°C\n"
                f"{value}K = {f:.1f}°F"
            )
        else:
            await update.message.reply_text("Invalid unit. Use C, F, or K")
    except ValueError:
        await update.message.reply_text("Invalid temperature value")

async def currency_convert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 3:
        await update.message.reply_text("Usage: /currency <amount> <from> <to> (e.g., /currency 100 USD INR)")
        return
    
    try:
        amount = float(context.args[0])
        from_curr = context.args[1].upper()
        to_curr = context.args[2].upper()
        
        # In a real implementation, you would call a currency API here
        # This is just a placeholder with mock conversion rates
        rates = {
            'USD': {'INR': 83.5, 'EUR': 0.93, 'GBP': 0.80},
            'EUR': {'USD': 1.08, 'INR': 90.2, 'GBP': 0.86},
            'GBP': {'USD': 1.25, 'EUR': 1.16, 'INR': 104.5},
            'INR': {'USD': 0.012, 'EUR': 0.011, 'GBP': 0.0096}
        }
        
        if from_curr in rates and to_curr in rates[from_curr]:
            converted = amount * rates[from_curr][to_curr]
            await update.message.reply_text(
                f"💱 Currency Conversion:\n"
                f"{amount} {from_curr} = {converted:.2f} {to_curr}\n\n"
                f"Note: Using mock rates. For real rates, integrate with a currency API."
            )
        else:
            await update.message.reply_text("Unsupported currency pair")
    except ValueError:
        await update.message.reply_text("Invalid amount")

async def unit_convert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /units <value> <unit1→unit2> (e.g., /units 10 km→m)")
        return
    
    try:
        value = float(context.args[0])
        conversion = context.args[1]
        
        if '→' not in conversion:
            await update.message.reply_text("Invalid format. Use unit1→unit2")
            return
        
        from_unit, to_unit = conversion.split('→')
        
        # Define conversion factors
        conversions = {
            'length': {
                'm→km': 0.001,
                'km→m': 1000,
                'cm→m': 0.01,
                'm→cm': 100,
                'in→cm': 2.54,
                'cm→in': 0.3937,
                'ft→m': 0.3048,
                'm→ft': 3.28084
            },
            'weight': {
                'g→kg': 0.001,
                'kg→g': 1000,
                'lb→kg': 0.453592,
                'kg→lb': 2.20462,
                'oz→g': 28.3495,
                'g→oz': 0.035274
            },
            'volume': {
                'ml→l': 0.001,
                'l→ml': 1000,
                'gal→l': 3.78541,
                'l→gal': 0.264172,
                'cup→ml': 236.588,
                'ml→cup': 0.00422675
            }
        }
        
        found = False
        for category in conversions.values():
            if conversion in category:
                converted = value * category[conversion]
                await update.message.reply_text(
                    f"📏 Unit Conversion:\n"
                    f"{value} {from_unit} = {converted:.4f} {to_unit}"
                )
                found = True
                break
        
        if not found:
            await update.message.reply_text("Unsupported unit conversion")
    except ValueError:
        await update.message.reply_text("Invalid value")

async def emoji_suggest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /emoji <text>")
        return
    
    text = ' '.join(context.args).lower()
    emoji_map = {
        'happy': '😊 😄 😃 😁',
        'sad': '😢 😭 😞 😔',
        'angry': '😠 😡 🤬 👿',
        'love': '❤️ 💕 💘 😍',
        'food': '🍔 🍕 🍟 🌮',
        'animal': '🐶 🐱 🦁 🐯',
        'weather': '☀️ 🌧 ⚡ ❄️',
        'time': '⏰ ⌛ ⏳ 🕰',
        'music': '🎵 🎶 🎧 🎼',
        'sport': '⚽ 🏀 🎾 🏈'
    }
    
    matches = []
    for word, emojis in emoji_map.items():
        if word in text:
            matches.append(emojis)
    
    if matches:
        await update.message.reply_text(" ".join(matches))
    else:
        await update.message.reply_text("🤔 No matching emojis found. Try words like happy, sad, food, etc.")

async def bmi_calc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /bmi <height in cm> <weight in kg>")
        return
    
    try:
        height = float(context.args[0])
        weight = float(context.args[1])
        
        if height <= 0 or weight <= 0:
            await update.message.reply_text("Height and weight must be positive values")
            return
        
        height_m = height / 100
        bmi = weight / (height_m ** 2)
        
        if bmi < 18.5:
            category = "Underweight"
        elif 18.5 <= bmi < 25:
            category = "Normal weight"
        elif 25 <= bmi < 30:
            category = "Overweight"
        else:
            category = "Obese"
        
        await update.message.reply_text(
            f"⚖️ BMI Calculation:\n"
            f"Height: {height} cm\n"
            f"Weight: {weight} kg\n"
            f"BMI: {bmi:.1f}\n"
            f"Category: {category}"
        )
    except ValueError:
        await update.message.reply_text("Invalid height or weight")

async def get_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    
    if chat.type == "private":
        response = f"👤 Your ID: `{user.id}`"
    else:
        response = (
            f"👥 Chat ID: `{chat.id}`\n"
            f"👤 Your ID: `{user.id}`"
        )
    
    if update.message.reply_to_message:
        replied_user = update.message.reply_to_message.from_user
        response += f"\n🔄 Replied to user ID: `{replied_user.id}`"
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Copy ID", callback_data=f"copy_{user.id}")]
    ])
    
    await update.message.reply_text(response, reply_markup=keyboard, parse_mode='Markdown')

async def copy_id_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data.startswith("copy_"):
        user_id = query.data.split("_")[1]
        await query.answer(f"Copied ID: {user_id}", show_alert=True)

# ======================
# Message handlers
# ======================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if config.maintenance_mode and update.effective_user.id != config.owner_id:
        await update.message.reply_text("🛠 Bot is under maintenance. Please try again later.")
        return
    
    banned_users = load_banned_users()
    if update.effective_user.id in banned_users:
        await update.message.reply_text("🚫 You are banned from using this bot.")
        return
    
    user_message = update.message.text
    chat_id = update.effective_chat.id
    
    # Check if message starts with any command (skip processing)
    if user_message.startswith('/'):
        return
    
    # Show typing action
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    
    # Update conversation history
    update_conversation_history(chat_id, "user", user_message)
    
    # Generate response
    response = await generate_response(chat_id, user_message)
    
    # Update conversation history with bot's response
    update_conversation_history(chat_id, "model", response)
    
    await update.message.reply_text(response)

async def clear_memory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    history = load_conversation_history()
    
    if str(chat_id) in history:
        del history[str(chat_id)]
        save_conversation_history(history)
        await update.message.reply_text("🧹 Chat history cleared!")
    else:
        await update.message.reply_text("No chat history to clear.")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status_msg = (
        f"🤖 **{config.bot_name} Status** 🤖\n\n"
        f"✦ Owner: {config.owner_name}\n"
        f"✦ Language: {config.language}\n"
        f"✦ Maintenance: {'🛠 ON' if config.maintenance_mode else '✅ OFF'}\n"
        f"✦ Support: {config.support_group}\n\n"
        "All systems operational! 🚀"
    )
    await update.message.reply_text(status_msg, parse_mode='Markdown')

async def apistats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != config.owner_id:
        await update.message.reply_text("❌ This command is only for my owner!")
        return
    
    stats_msg = "🔌 **API Statistics** 🔌\n\n"
    stats_msg += f"✦ Current Model: {gemini.get_current_model()}\n"
    stats_msg += "🔢 **Key Usage**:\n"
    
    for i, key in enumerate(gemini.api_keys):
        stats_msg += f"  ▸ Key {i+1}: {gemini.key_usage[key]} requests\n"
    
    await update.message.reply_text(stats_msg, parse_mode='Markdown')

async def eval_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != config.owner_id:
        await update.message.reply_text("❌ This command is only for my owner!")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: /eval <python code>")
        return
    
    code = ' '.join(context.args)
    try:
        # Restricted environment for safety
        local_vars = {
            'update': update,
            'context': context,
            'config': config,
            'gemini': gemini
        }
        
        # Remove any import statements for security
        if 'import ' in code:
            raise ValueError("Import statements are not allowed")
            
        # Execute the code
        exec(f"result = {code}", globals(), local_vars)
        result = local_vars.get('result', 'No result returned')
        
        await update.message.reply_text(f"✅ Execution successful:\n```\n{result}\n```", parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text(f"❌ Error:\n```\n{str(e)}\n```", parse_mode='Markdown')

async def server(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != config.owner_id:
        await update.message.reply_text("❌ This command is only for my owner!")
        return
    
    try:
        import psutil
        cpu = psutil.cpu_percent()
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        
        stats_msg = (
            "🖥 **Server Status** 🖥\n\n"
            f"✦ CPU Usage: {cpu}%\n"
            f"✦ Memory: {memory.percent}% used ({memory.used/1024/1024:.1f}MB/{memory.total/1024/1024:.1f}MB)\n"
            f"✦ Disk: {disk.percent}% used ({disk.used/1024/1024:.1f}MB/{disk.total/1024/1024:.1f}MB)\n"
            f"✦ Uptime: {psutil.boot_time()}"
        )
        
        await update.message.reply_text(stats_msg)
    except ImportError:
        await update.message.reply_text("psutil module not installed")
    except Exception as e:
        await update.message.reply_text(f"Error getting server stats: {str(e)}")

# ======================
# Error handler
# ======================

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update {update} caused error {context.error}")
    
    if update.effective_message:
        await update.effective_message.reply_text(
            "Oops! Kuch to gadbad hai... 😅\n"
            "Error ho gaya. Thodi der baad try karo ya owner ko batado."
        )

# ======================
# Main function
# ======================

def main():
    # Create the Application
    application = Application.builder().token(config.config['TELEGRAM_BOT_TOKEN']).build()
    
    # Add command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", button_handler))
    application.add_handler(CommandHandler("clearmemory", clear_memory))
    application.add_handler(CommandHandler("status", status))
    
    # Owner commands
    application.add_handler(CommandHandler("broadcast", broadcast))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("ban", ban_user))
    application.add_handler(CommandHandler("unban", unban_user))
    application.add_handler(CommandHandler("maintenance", maintenance))
    application.add_handler(CommandHandler("getuser", get_user))
    application.add_handler(CommandHandler("apistats", apistats))
    application.add_handler(CommandHandler("backup", backup))
    application.add_handler(CommandHandler("eval", eval_command))
    application.add_handler(CommandHandler("server", server))
    application.add_handler(CommandHandler("ping", ping))
    
    # Utility commands
    application.add_handler(CommandHandler("dice", dice))
    application.add_handler(CommandHandler("flip", flip))
    application.add_handler(CommandHandler("password", password))
    application.add_handler(CommandHandler("qr", qr_code))
    application.add_handler(CommandHandler("countdown", countdown))
    application.add_handler(CommandHandler("timer", timer))
    application.add_handler(CommandHandler("rate", rate))
    application.add_handler(CommandHandler("decide", decide))
    application.add_handler(CommandHandler("color", color_preview))
    application.add_handler(CommandHandler("font", fancy_font))
    application.add_handler(CommandHandler("temp", temp_convert))
    application.add_handler(CommandHandler("currency", currency_convert))
    application.add_handler(CommandHandler("units", unit_convert))
    application.add_handler(CommandHandler("emoji", emoji_suggest))
    application.add_handler(CommandHandler("bmi", bmi_calc))
    application.add_handler(CommandHandler("id", get_id))
    
    # Button handler
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(CallbackQueryHandler(copy_id_button))
    
     # Message handler
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Error handler
    application.add_error_handler(error_handler)
    
    # Start the Bot
    logger.info("Bot is running...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

app = Flask(__name__)

@app.route("/")
def home():
    return "🤖 Bot is running!"

def run_flask():
    app.run(host="0.0.0.0", port=8000)
    
if __name__ == "__main__":
    # Start Flask server in a separate thread
    threading.Thread(target=run_flask).start()
    
    main()
    # Simple Flask server for health check

