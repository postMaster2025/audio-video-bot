import os
import logging
import asyncio
import re
import gc
import tempfile
import shutil
from typing import Dict, List, Optional, Any
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from telegram.error import BadRequest, TimedOut, NetworkError
from telegram.constants import FileSizeLimit
from pydub import AudioSegment
from pydub.utils import make_chunks
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
import aiofiles
import traceback

# ==================== কনফিগারেশন ====================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')  # set this in env

# Constants
MAX_FILE_SIZE = 200 * 1024 * 1024   # 200 MB
CHUNK_SIZE = 50 * 1024 * 1024       # 50 MB chunk (if needed)
USER_TIMEOUT = timedelta(hours=2)
TEMP_DIR = tempfile.mkdtemp(prefix="telegram_bot_")
MAX_AUDIO_FILES = 50
PROGRESS_UPDATE_INTERVAL = 2  # seconds

# In-memory user data
user_data: Dict[int, Dict[str, Any]] = {}

# ==================== Utilities ====================

class FileManager:
    """File management utilities."""
    @staticmethod
    def get_user_temp_dir(user_id: int) -> Path:
        user_dir = Path(TEMP_DIR) / str(user_id)
        user_dir.mkdir(parents=True, exist_ok=True)
        return user_dir

    @staticmethod
    async def cleanup_user_files(user_id: int) -> None:
        try:
            user_dir = Path(TEMP_DIR) / str(user_id)
            if user_dir.exists():
                shutil.rmtree(user_dir, ignore_errors=True)
                logger.info(f"Cleaned up files for user {user_id}")
            # Also remove any single files referenced in user_data
            if user_id in user_data:
                for key in ['merged_file', 'output_video', 'image', 'audio']:
                    path = user_data[user_id].get(key)
                    if path and os.path.exists(path):
                        try:
                            os.remove(path)
                        except Exception as e:
                            logger.debug(f"Could not remove {path}: {e}")
        except Exception as e:
            logger.error(f"Error cleaning up user files: {e}")

    @staticmethod
    def get_file_size_mb(file_path: str) -> float:
        try:
            return os.path.getsize(file_path) / (1024 * 1024)
        except:
            return 0

def get_progress_bar(percentage: int) -> str:
    filled = int(percentage / 5)  # 20 blocks
    empty = 20 - filled
    return "█" * filled + "░" * empty

def format_file_size(size_bytes: int) -> str:
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} TB"

async def safe_edit_message(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    message_id: int,
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None
) -> bool:
    try:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        return True
    except BadRequest as e:
        if "Message is not modified" not in str(e):
            logger.warning(f"Could not edit message {message_id}: {e}")
    except (TimedOut, NetworkError) as e:
        logger.error(f"Network error editing message: {e}")
    except Exception as e:
        logger.error(f"Unexpected error editing message: {e}")
    return False

def update_user_activity(user_id: int) -> None:
    if user_id in user_data:
        user_data[user_id]['last_activity'] = datetime.now()

async def reset_user(update: Update, context: ContextTypes.DEFAULT_TYPE, send_new_menu: bool = True) -> None:
    user_id = update.effective_user.id
    await FileManager.cleanup_user_files(user_id)
    if user_id in user_data and 'status_message_id' in user_data[user_id]:
        try:
            await context.bot.delete_message(chat_id=user_id, message_id=user_data[user_id]['status_message_id'])
        except:
            pass
    if user_id in user_data:
        del user_data[user_id]
    if send_new_menu:
        welcome_text = (
            "🎵 *অডিও ভিডিও বট এ স্বাগতম!*\n\n"
            "আমি আপনাকে সাহায্য করতে পারি:\n"
            "• 🎵 একাধিক অডিও একসাথে জোড়া লাগাতে\n"
            "• 🎬 অডিও + ছবি দিয়ে ভিডিও বানাতে\n"
            "• 📊 বড় ফাইল প্রসেস করতে (200MB পর্যন্ত)\n\n"
            "নিচের বাটন থেকে আপনার কাজ বেছে নিন:"
        )
        msg = await context.bot.send_message(
            chat_id=user_id,
            text=welcome_text,
            reply_markup=Keyboards.main_menu(),
            parse_mode='Markdown'
        )
        user_data[user_id] = {
            'status_message_id': msg.message_id,
            'last_activity': datetime.now()
        }

# ==================== Progress tracker (simple) ====================
class ProgressTracker:
    def __init__(self):
        self.last_update_time = datetime.now()
        self.last_progress = -1
    def should_update(self, current_progress: int) -> bool:
        now = datetime.now()
        time_diff = (now - self.last_update_time).total_seconds()
        if current_progress != self.last_progress and (time_diff >= PROGRESS_UPDATE_INTERVAL or current_progress == 100 or abs(current_progress - self.last_progress) >= 5):
            self.last_update_time = now
            self.last_progress = current_progress
            return True
        return False

# ==================== Keyboards ====================
class Keyboards:
    @staticmethod
    def main_menu() -> InlineKeyboardMarkup:
        keyboard = [
            [InlineKeyboardButton("🎵 অডিও মার্জ করুন", callback_data="merge")],
            [InlineKeyboardButton("🎬 ভিডিও বানান", callback_data="video")],
            [InlineKeyboardButton("📊 স্ট্যাটাস", callback_data="status")],
            [InlineKeyboardButton("❓ সাহায্য", callback_data="help")]
        ]
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def cancel_button() -> InlineKeyboardMarkup:
        keyboard = [[InlineKeyboardButton("❌ বাতিল করুন", callback_data="cancel")]]
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def done_button() -> InlineKeyboardMarkup:
        keyboard = [
            [InlineKeyboardButton("✅ সম্পন্ন করুন", callback_data="done")],
            [InlineKeyboardButton("❌ বাতিল করুন", callback_data="cancel")]
        ]
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def after_merge_options() -> InlineKeyboardMarkup:
        keyboard = [
            [InlineKeyboardButton("➕ আরো অডিও যোগ করুন", callback_data="add_more")],
            [InlineKeyboardButton("🔄 নতুন মার্জ শুরু করুন", callback_data="merge")],
            [InlineKeyboardButton("🏠 মূল মেনু", callback_data="main_menu")]
        ]
        return InlineKeyboardMarkup(keyboard)

# ==================== Cleanup tasks ====================
async def cleanup_inactive_users() -> None:
    while True:
        try:
            await asyncio.sleep(600)
            current_time = datetime.now()
            inactive_users = [
                uid for uid, data in list(user_data.items())
                if current_time - data.get('last_activity', current_time) > USER_TIMEOUT
            ]
            for uid in inactive_users:
                await FileManager.cleanup_user_files(uid)
                if uid in user_data:
                    del user_data[uid]
                logger.info(f"Cleaned up inactive user: {uid}")
        except Exception as e:
            logger.error(f"Error in cleanup task: {e}")

async def cleanup_temp_directory() -> None:
    while True:
        try:
            await asyncio.sleep(3600)
            temp_path = Path(TEMP_DIR)
            if temp_path.exists():
                for user_dir in temp_path.iterdir():
                    if user_dir.is_dir():
                        dir_age = datetime.now() - datetime.fromtimestamp(user_dir.stat().st_mtime)
                        if dir_age > timedelta(hours=2):
                            shutil.rmtree(user_dir, ignore_errors=True)
                            logger.info(f"Cleaned old directory: {user_dir}")
        except Exception as e:
            logger.error(f"Error in temp cleanup: {e}")

# ==================== Handlers ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name
    if user_id in user_data:
        await FileManager.cleanup_user_files(user_id)
        if 'status_message_id' in user_data[user_id]:
            try:
                await context.bot.delete_message(chat_id=user_id, message_id=user_data[user_id]['status_message_id'])
            except:
                pass
        del user_data[user_id]

    welcome_text = (
        f"স্বাগতম *{user_name}*! 👋\n\n"
        "🎵 *অডিও ভিডিও বট এ আপনাকে স্বাগতম!*\n\n"
        "আমি আপনাকে সাহায্য করতে পারি:\n"
        "• 🎵 একাধিক অডিও একসাথে জোড়া লাগাতে\n"
        "• 🎬 অডিও + ছবি দিয়ে ভিডিও বানাতে\n"
        "• 📊 বড় ফাইল প্রসেস করতে (200MB পর্যন্ত)\n\n"
        "*বৈশিষ্ট্য:*\n"
        "✅ বড় ফাইল সাপোর্ট\n"
        "✅ দ্রুত প্রসেসিং\n"
        "✅ উচ্চ মানের আউটপুট\n"
        "✅ প্রগ্রেস ট্র্যাকিং\n\n"
        "নিচের বাটন থেকে আপনার কাজ বেছে নিন:"
    )

    if update.message:
        try:
            await update.message.delete()
        except:
            pass

    msg = await context.bot.send_message(
        chat_id=user_id,
        text=welcome_text,
        reply_markup=Keyboards.main_menu(),
        parse_mode='Markdown'
    )

    user_data[user_id] = {
        'status_message_id': msg.message_id,
        'last_activity': datetime.now(),
        'user_temp_dir': str(FileManager.get_user_temp_dir(user_id))
    }

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if user_id not in user_data:
        text = "📊 *স্ট্যাটাস*\n\nকোনো সক্রিয় কাজ নেই।"
    else:
        data = user_data[user_id]
        mode = data.get('mode', 'idle')
        status_info = []
        status_info.append(f"*মোড:* {mode}")
        if mode in ['merge', 'add_more']:
            audio_count = len(data.get('audio_files', [])) + len(data.get('new_audio_files', []))
            status_info.append(f"*অডিও ফাইল:* {audio_count}টি")
            total_size = 0
            for file in data.get('audio_files', []) + data.get('new_audio_files', []):
                if os.path.exists(file):
                    total_size += os.path.getsize(file)
            status_info.append(f"*মোট সাইজ:* {format_file_size(total_size)}")
        elif mode == 'video':
            if data.get('image'):
                status_info.append("*ছবি:* ✅ আপলোড হয়েছে")
            if data.get('audio'):
                status_info.append("*অডিও:* ✅ আপলোড হয়েছে")
        text = "📊 *স্ট্যাটাস*\n\n" + "\n".join(status_info)

    keyboard = [[InlineKeyboardButton("🔙 ফিরে যান", callback_data="main_menu")]]
    # update.callback_query may be None if invoked via command; handle both
    if update.callback_query:
        await safe_edit_message(context, user_id, update.callback_query.message.message_id, text, InlineKeyboardMarkup(keyboard))
    else:
        await context.bot.send_message(chat_id=user_id, text=text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    action = query.data
    update_user_activity(user_id)
    if user_id not in user_data:
        user_data[user_id] = {'last_activity': datetime.now(), 'user_temp_dir': str(FileManager.get_user_temp_dir(user_id))}
    actions = {
        "merge": start_merge,
        "video": start_video,
        "help": show_help,
        "status": status_command,
        "cancel": cancel_action,
        "main_menu": cancel_action,
        "done": merge_audios,
        "add_more": add_more_audio,
    }
    if action in actions:
        await actions[action](update, context)

# ==================== Feature functions ====================

async def start_merge(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    await FileManager.cleanup_user_files(user_id)
    user_data[user_id].update({
        'mode': 'merge',
        'audio_files': [],
        'audio_names': [],
        'audio_info': [],
        'status_message_id': update.callback_query.message.message_id,
        'last_activity': datetime.now()
    })
    text = (
        "🎵 *অডিও মার্জ মোড*\n\n"
        "📌 নির্দেশনা:\n"
        "• যতগুলো ইচ্ছে অডিও/ভয়েস পাঠান\n"
        "• সর্বোচ্চ ফাইল সাইজ: 200MB\n"
        "• সমর্থিত ফরম্যাট: MP3, OGG, WAV, M4A\n\n"
        "অডিও পাঠান এবং শেষ হলে ✅ \"সম্পন্ন করুন\" চাপুন"
    )
    await safe_edit_message(context, user_id, user_data[user_id]['status_message_id'], text, Keyboards.done_button())

async def add_more_audio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if 'merged_file' not in user_data.get(user_id, {}):
        await update.callback_query.answer("❌ প্রথমে একটি অডিও মার্জ করুন!", show_alert=True)
        return
    user_data[user_id].update({
        'mode': 'add_more',
        'new_audio_files': [],
        'new_audio_names': [],
        'status_message_id': update.callback_query.message.message_id,
        'last_activity': datetime.now()
    })
    text = (
        "➕ *আরো অডিও যোগ করুন*\n\n"
        "নতুন অডিও/ভয়েস পাঠান।\n"
        "শেষ হলে \"সম্পন্ন করুন\" ক্লিক করুন।"
    )
    await safe_edit_message(context, user_id, user_data[user_id]['status_message_id'], text, Keyboards.done_button())

async def start_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    await FileManager.cleanup_user_files(user_id)
    user_data[user_id].update({
        'mode': 'video',
        'image': None,
        'audio': None,
        'status_message_id': update.callback_query.message.message_id,
        'last_activity': datetime.now()
    })
    text = (
        "🎬 *ভিডিও বানানোর মোড*\n\n"
        "📸 প্রথমে একটি ছবি পাঠান\n\n"
        "📌 নির্দেশনা:\n"
        "• ছবি ফরম্যাট: JPG, PNG\n"
        "• সর্বোচ্চ সাইজ: 20MB\n"
    )
    await safe_edit_message(context, user_id, user_data[user_id]['status_message_id'], text, Keyboards.cancel_button())

async def show_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    help_text = (
        "📖 *কীভাবে ব্যবহার করবেন:*\n\n"
        "*🎵 অডিও মার্জ করতে:*\n"
        "1. \"অডিও মার্জ করুন\" বাটনে ক্লিক করুন\n"
        "2. যতগুলো ইচ্ছে অডিও/ভয়েস পাঠান\n"
        "3. \"সম্পন্ন করুন\" বাটনে ক্লিক করুন\n\n"
        "*🎬 ভিডিও বানাতে:*\n"
        "1. \"ভিডিও বানান\" বাটনে ক্লিক করুন\n"
        "2. একটি ছবি পাঠান\n"
        "3. একটি অডিও/ভয়েস পাঠান\n\n"
        "*✨ বৈশিষ্ট্য:*\n"
        "• বড় ফাইল সাপোর্ট (200MB)\n"
        "• একাধিক ফরম্যাট সাপোর্ট\n"
        "• দ্রুত প্রসেসিং\n"
        "• প্রগ্রেস ট্র্যাকিং\n\n"
        "*⚠️ সীমাবদ্ধতা:*\n"
        "• সর্বোচ্চ ফাইল সাইজ: 200MB\n"
        "• সর্বোচ্চ অডিও সংখ্যা: 50টি\n\n"
        "*🆘 সমস্যা?*\n"
        "সাপোর্টের জন্য বট অ্যাডমিনকে জানাও।"
    )
    keyboard = [[InlineKeyboardButton("🔙 মূল মেনু", callback_data="main_menu")]]
    await safe_edit_message(context, user_id, update.callback_query.message.message_id, help_text, InlineKeyboardMarkup(keyboard))

async def cancel_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await reset_user(update, context, send_new_menu=True)

# ==================== Media handling ====================

async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if user_id not in user_data or 'mode' not in user_data[user_id]:
        return
    update_user_activity(user_id)
    mode = user_data[user_id]['mode']
    try:
        if update.message:
            await update.message.delete()
    except:
        pass

    is_photo = bool(update.message.photo)
    is_audio_type = bool(
        update.message.audio or
        update.message.voice or
        (update.message.document and update.message.document.mime_type and update.message.document.mime_type.startswith('audio/'))
    )

    if mode == 'video':
        if is_photo and not user_data[user_id].get('image'):
            await handle_photo(update, context)
        elif is_audio_type and user_data[user_id].get('image') and not user_data[user_id].get('audio'):
            await process_video_audio(update, context)
    elif mode in ['merge', 'add_more'] and is_audio_type:
        await process_incoming_audio(update, context)

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    status_id = user_data[user_id]['status_message_id']
    user_dir = FileManager.get_user_temp_dir(user_id)

    try:
        photo_file = await update.message.photo[-1].get_file()
        # file size check using telegram metadata if available
        if getattr(photo_file, 'file_size', None) and photo_file.file_size > 20 * 1024 * 1024:
            text = "❌ ছবি খুব বড়! সর্বোচ্চ 20MB এর ছবি পাঠান।"
            await safe_edit_message(context, user_id, status_id, text, Keyboards.cancel_button())
            return

        photo_path = str(user_dir / f"image_{user_id}_{int(datetime.now().timestamp())}.jpg")
        await photo_file.download_to_drive(photo_path)
        user_data[user_id]['image'] = photo_path

        text = (
            "🎬 *ভিডিও বানানোর মোড*\n\n"
            "✅ ছবি সংযুক্ত হয়েছে!\n"
            f"📊 সাইজ: {format_file_size(os.path.getsize(photo_path))}\n\n"
            "🎵 এখন একটি অডিও বা ভয়েস পাঠান"
        )
        await safe_edit_message(context, user_id, status_id, text, Keyboards.cancel_button())

    except Exception as e:
        logger.error(f"Error handling photo: {e}\n{traceback.format_exc()}")
        text = "❌ ছবি আপলোডে সমস্যা হয়েছে। আবার চেষ্টা করুন।"
        await safe_edit_message(context, user_id, status_id, text, Keyboards.cancel_button())

async def process_incoming_audio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    mode = user_data[user_id]['mode']
    status_id = user_data[user_id]['status_message_id']
    is_add_more = (mode == 'add_more')

    file_list_key = 'new_audio_files' if is_add_more else 'audio_files'
    name_list_key = 'new_audio_names' if is_add_more else 'audio_names'

    file_obj = update.message.audio or update.message.voice or update.message.document

    # Check file size (MAX_FILE_SIZE)
    if hasattr(file_obj, 'file_size') and file_obj.file_size > MAX_FILE_SIZE:
        try:
            await context.bot.send_message(chat_id=user_id, text=f"❌ ফাইল খুব বড়! সর্বোচ্চ {int(MAX_FILE_SIZE/(1024*1024))}MB এর ফাইল পাঠান।")
        except Exception:
            pass
        return

    # extension detection
    if update.message.audio:
        file_extension = ".mp3"
    elif update.message.voice:
        file_extension = ".ogg"
    else:
        # try to get extension from document filename
        filename = getattr(file_obj, 'file_name', None)
        if filename and '.' in filename:
            file_extension = "." + filename.split('.')[-1]
        else:
            file_extension = ".mp3"

    user_dir = FileManager.get_user_temp_dir(user_id)
    index = len(user_data[user_id].get(file_list_key, []))
    file_path = str(user_dir / f"audio_{user_id}_{index+1}_{int(datetime.now().timestamp())}{file_extension}")

    try:
        file_handle = await file_obj.get_file()
        await file_handle.download_to_drive(file_path)

        file_name = getattr(file_obj, 'file_name', f"Audio {index+1}")

        user_data[user_id].setdefault(file_list_key, []).append(file_path)
        user_data[user_id].setdefault(name_list_key, []).append(file_name)

        # enforce max audio files
        total_count = len(user_data[user_id].get('audio_files', [])) + len(user_data[user_id].get('new_audio_files', []))
        if total_count > MAX_AUDIO_FILES:
            await context.bot.send_message(chat_id=user_id, text=f"❌ বেশি ফাইল! সর্বোচ্চ {MAX_AUDIO_FILES}টি অডিও অনুমোদিত।")
            # remove last added
            user_data[user_id][file_list_key].pop()
            user_data[user_id][name_list_key].pop()
            return

        audio_count = len(user_data[user_id][file_list_key])
        # show last few files for context
        recent_names = user_data[user_id][name_list_key][-5:]
        audio_list = "\n".join([f"  {i+1}. {name}" for i, name in enumerate(recent_names)])
        if audio_count > 5:
            audio_list += f"\n  ... এবং আরও {audio_count - 5}টি"

        text = f"🎵 *অডিও মার্জ মোড*\n\n*যোগ করা অডিও: {audio_count}টি*\n{audio_list}\n\nআরো অডিও পাঠান অথবা \"সম্পন্ন করুন\" ক্লিক করুন।"
        await safe_edit_message(context, user_id, status_id, text, Keyboards.done_button())
    except Exception as e:
        logger.error(f"Error processing audio: {e}\n{traceback.format_exc()}")
        text = "❌ অডিও প্রসেস করতে সমস্যা হয়েছে। আবার চেষ্টা করুন।"
        await safe_edit_message(context, user_id, status_id, text, Keyboards.done_button())

async def process_video_audio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    status_id = user_data[user_id]['status_message_id']

    file_obj = update.message.audio or update.message.voice or update.message.document

    if hasattr(file_obj, 'file_size') and file_obj.file_size > MAX_FILE_SIZE:
        try:
            await context.bot.send_message(chat_id=user_id, text=f"❌ ফাইল খুব বড়! সর্বোচ্চ {int(MAX_FILE_SIZE/(1024*1024))}MB এর ফাইল পাঠান।")
        except Exception:
            pass
        return

    if update.message.audio:
        file_extension = ".mp3"
    elif update.message.voice:
        file_extension = ".ogg"
    else:
        filename = getattr(file_obj, 'file_name', None)
        if filename and '.' in filename:
            file_extension = "." + filename.split('.')[-1]
        else:
            file_extension = ".mp3"

    user_dir = FileManager.get_user_temp_dir(user_id)
    audio_path = str(user_dir / f"video_audio_{user_id}_{int(datetime.now().timestamp())}{file_extension}")

    try:
        file_handle = await file_obj.get_file()
        await file_handle.download_to_drive(audio_path)
        user_data[user_id]['audio'] = audio_path

        text = "🎬 *ভিডিও বানানোর মোড*\n\n✅ সব ফাইল পাওয়া গেছে!\n\n⏳ ভিডিও তৈরি করা হচ্ছে..."
        await safe_edit_message(context, user_id, status_id, text)
        await create_video(update, context)
    except Exception as e:
        logger.error(f"Error processing video audio: {e}\n{traceback.format_exc()}")
        text = "❌ অডিও প্রসেস করতে সমস্যা হয়েছে। আবার চেষ্টা করুন।"
        await safe_edit_message(context, user_id, status_id, text, Keyboards.cancel_button())

# ==================== Merge & Create ====================

async def merge_audios(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    mode = user_data[user_id].get('mode')

    is_add_more = (mode == 'add_more')
    base_files = [user_data[user_id]['merged_file']] if is_add_more and user_data[user_id].get('merged_file') else []
    new_files = user_data[user_id].get('new_audio_files' if is_add_more else 'audio_files', [])

    if not new_files or (not is_add_more and len(new_files) < 2):
        await update.callback_query.answer("❌ কমপক্ষে " + ("১টি নতুন" if is_add_more else "২টি") + " অডিও পাঠান!", show_alert=True)
        return

    await update.callback_query.answer()
    status_id = user_data[user_id]['status_message_id']
    all_files = base_files + new_files
    total_files = len(all_files)

    try:
        text = f"⏳ *অডিও মার্জ হচ্ছে...*\n\n{get_progress_bar(0)} 0%\n\nপ্রস্তুতি চলছে..."
        await safe_edit_message(context, user_id, status_id, text)

        combined = AudioSegment.empty()
        total_duration = 0
        file_durations = []

        # Analyze durations
        for idx, audio_path in enumerate(all_files):
            try:
                audio = AudioSegment.from_file(audio_path)
                duration = len(audio)
                file_durations.append(duration)
                total_duration += duration
                progress = 5 + int((idx + 1) / len(all_files) * 15)
                text = f"⏳ *অডিও মার্জ হচ্ছে...*\n\n{get_progress_bar(progress)} {progress}%\n\nফাইল এনালাইজ করা হচ্ছে... ({idx + 1}/{len(all_files)})"
                await safe_edit_message(context, user_id, status_id, text)
            except Exception as e:
                logger.error(f"Error analyzing file {audio_path}: {e}")
                file_durations.append(0)

        current_duration = 0
        # Merge with progress based on durations
        for idx, (audio_path, file_duration) in enumerate(zip(all_files, file_durations)):
            progress = 20 + int((current_duration / total_duration) * 70) if total_duration > 0 else 20
            text = f"⏳ *অডিও মার্জ হচ্ছে...*\n\n{get_progress_bar(progress)} {progress}%\n\nঅডিও মার্জ করা হচ্ছে... ({idx + 1}/{total_files})"
            await safe_edit_message(context, user_id, status_id, text)
            try:
                audio = AudioSegment.from_file(audio_path)
                combined += audio
                current_duration += file_duration
                new_progress = 20 + int((current_duration / total_duration) * 70) if total_duration > 0 else progress
                if new_progress != progress:
                    text = f"⏳ *অডিও মার্জ হচ্ছে...*\n\n{get_progress_bar(new_progress)} {new_progress}%\n\nঅডিও মার্জ করা হচ্ছে... ({idx + 1}/{total_files})"
                    await safe_edit_message(context, user_id, status_id, text)
            except Exception as e:
                logger.error(f"Error processing file {audio_path}: {e}")
                continue

        progress = 90
        text = f"⏳ *অডিও মার্জ হচ্ছে...*\n\n{get_progress_bar(progress)} {progress}%\n\nফাইল সংরক্ষণ করা হচ্ছে..."
        await safe_edit_message(context, user_id, status_id, text)

        output_path = str(FileManager.get_user_temp_dir(user_id) / f"merged_{user_id}_{int(datetime.now().timestamp())}.mp3")
        combined.export(output_path, format="mp3", bitrate="128k", parameters=["-ac", "1"])

        progress = 100
        text = f"✅ *মার্জ সম্পন্ন!*\n\n{get_progress_bar(progress)} {progress}%\n\nআপনার অডিও ফাইল প্রস্তুত!"
        await safe_edit_message(context, user_id, status_id, text)

        await send_merged_audio(context, user_id, output_path, status_id)

    except Exception as e:
        logger.error(f"Error merging audio: {e}\n{traceback.format_exc()}")
        text = "❌ অডিও মার্জ করতে সমস্যা হয়েছে। আবার চেষ্টা করুন।"
        await safe_edit_message(context, user_id, status_id, text, Keyboards.main_menu())

async def send_merged_audio(context: ContextTypes.DEFAULT_TYPE, user_id: int, output_path: str, status_id: int):
    try:
        with open(output_path, 'rb') as audio_file:
            await context.bot.send_audio(
                chat_id=user_id,
                audio=audio_file,
                title="Merged Audio",
                caption="✅ আপনার মার্জড অডিও ফাইল প্রস্তুত!"
            )

        old_merged = user_data.get(user_id, {}).get('merged_file')
        if old_merged and os.path.exists(old_merged):
            try:
                os.remove(old_merged)
            except Exception as e:
                logger.error(f"Error removing old merged file: {e}")

        user_data[user_id].update({
            'merged_file': output_path,
            'audio_files': [],
            'audio_names': [],
            'new_audio_files': [],
            'new_audio_names': [],
            'status_message_id': status_id,
            'last_activity': datetime.now()
        })

        text = "এখন কি করবেন?"
        await safe_edit_message(context, user_id, status_id, text, Keyboards.after_merge_options())

    except Exception as e:
        logger.error(f"Error sending audio: {e}\n{traceback.format_exc()}")
        text = "❌ ফাইল পাঠাতে সমস্যা হয়েছে। আবার চেষ্টা করুন।"
        await safe_edit_message(context, user_id, status_id, text, Keyboards.after_merge_options())

# FFmpeg time parse helper
def parse_ffmpeg_time(time_str: str) -> float:
    try:
        parts = time_str.split(':')
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds = float(parts[2])
        return hours * 3600 + minutes * 60 + seconds
    except Exception as e:
        logger.error(f"Error parsing time {time_str}: {e}")
        return 0.0

async def create_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    status_id = user_data[user_id]['status_message_id']

    try:
        image_path = user_data[user_id]['image']
        audio_path = user_data[user_id]['audio']
        output_video = str(FileManager.get_user_temp_dir(user_id) / f"video_{user_id}_{int(datetime.now().timestamp())}.mp4")

        # get audio duration
        try:
            audio = AudioSegment.from_file(audio_path)
            audio_duration = len(audio) / 1000.0
        except Exception as e:
            logger.error(f"Cannot read audio duration: {e}")
            audio_duration = 0

        cmd = [
            'ffmpeg', '-loop', '1', '-i', image_path, '-i', audio_path,
            '-c:v', 'libx264', '-preset', 'fast', '-crf', '28',
            '-c:a', 'aac', '-b:a', '128k',
            '-pix_fmt', 'yuv420p', '-shortest', '-movflags', '+faststart',
            '-y', output_video, '-progress', 'pipe:1', '-loglevel', 'error'
        ]

        process = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        last_reported_progress = -1

        while True:
            line_bytes = await process.stdout.readline()
            if not line_bytes:
                break
            line = line_bytes.decode('utf-8', errors='ignore').strip()
            if line.startswith('out_time_ms='):
                try:
                    time_us = int(line.split('=')[1])
                    current_time_sec = time_us / 1000000.0
                    if audio_duration > 0:
                        progress = min(99, int((current_time_sec / audio_duration) * 100))
                        if progress != last_reported_progress:
                            last_reported_progress = progress
                            text = f"⏳ *ভিডিও তৈরি হচ্ছে...*\n\n{get_progress_bar(progress)} {progress}%\n\nদয়া করে অপেক্ষা করুন..."
                            await safe_edit_message(context, user_id, status_id, text)
                except Exception as e:
                    logger.debug(f"Could not parse progress: {e}")

        await process.wait()
        if process.returncode == 0:
            user_data[user_id]['output_video'] = output_video
            progress = 100
            text = f"✅ *ভিডিও তৈরি সম্পন্ন!*\n\n{get_progress_bar(progress)} {progress}%\n\nআপনার ভিডিও প্রস্তুত!"
            await safe_edit_message(context, user_id, status_id, text)
            await send_created_video(context, user_id, output_video, status_id)
        else:
            stderr_output = (await process.stderr.read()).decode()
            logger.error(f"FFmpeg error (code {process.returncode}): {stderr_output}")
            raise Exception("FFmpeg failed")

    except Exception as e:
        logger.error(f"Error creating video: {e}\n{traceback.format_exc()}")
        await FileManager.cleanup_user_files(user_id)
        text = "❌ ভিডিও বানাতে সমস্যা হয়েছে।\n\n💡 Tips:\n• ছবির সাইজ 20MB এর কম রাখুন\n• অডিও ফাইল সঠিক আছে কিনা দেখুন\n• আবার চেষ্টা করুন"
        await safe_edit_message(context, user_id, status_id, text, Keyboards.main_menu())

async def send_created_video(context: ContextTypes.DEFAULT_TYPE, user_id: int, output_video: str, status_id: int) -> None:
    try:
        with open(output_video, 'rb') as video_file:
            await context.bot.send_video(chat_id=user_id, video=video_file, caption="✅ আপনার ভিডিও প্রস্তুত!")
        welcome_text = "আপনার ভিডিও সফলভাবে তৈরি হয়েছে!\n\nনিচের বাটন থেকে আপনার কাজ বেছে নিন:"
        await safe_edit_message(context, user_id, status_id, welcome_text, Keyboards.main_menu())
        await FileManager.cleanup_user_files(user_id)
        user_data[user_id] = {'status_message_id': status_id, 'last_activity': datetime.now()}
    except Exception as e:
        logger.error(f"Error sending video: {e}\n{traceback.format_exc()}")
        text = "❌ ভিডিও পাঠাতে সমস্যা হয়েছে। আবার চেষ্টা করুন।"
        await safe_edit_message(context, user_id, status_id, text, Keyboards.main_menu())

# ==================== Main ====================

async def post_init(application: Application):
    asyncio.create_task(cleanup_inactive_users())
    asyncio.create_task(cleanup_temp_directory())

def main():
    if not TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not found! Please set the TELEGRAM_BOT_TOKEN environment variable.")
        return

    application = Application.builder().token(TOKEN).post_init(post_init).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))
    media_filters = filters.AUDIO | filters.VOICE | filters.PHOTO | filters.Document.AUDIO
    application.add_handler(MessageHandler(media_filters, handle_media))
    logger.info("Bot is starting...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
