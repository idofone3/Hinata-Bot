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
        self.bot_name = self.config.get('BOT_NAME', 'ᴄʜᴀᴛ ᴄᴏᴍᴘᴀɴɪᴏɴ')
        self.owner_name = self.config.get('OWNER_NAME', 'ʙᴏᴛ ᴏᴡɴᴇʀ')
        self.language = self.config.get('LANGUAGE', 'ʜɪɴɢʟɪꜱʜ')
        self.support_group = self.config.get('SUPPORT_GROUP', 'https://t.me/yourgroup')
        self.bot_username = self.config.get('BOT_USERNAME', '@YourBotUsername')
        self.owner_id = 7996509135  # Your user ID
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
            "gemini-1.5-pro-lite",
            "gemini-2.0-flash"
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
                    if self.get_current_model() != "gemini-1.5-pro-lite":
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
        await message.edit_text(f"⏳ Co
