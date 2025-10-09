import os
import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from telegram.error import BadRequest
from pydub import AudioSegment
import subprocess
from datetime import datetime, timedelta


# Logging setup
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)


# Bot token from environment variable
TOKEN = os.getenv('BOT_TOKEN')


# User data storage (In-memory) with timeout
user_data = {}
USER_TIMEOUT = timedelta(hours=1)


# --- Keyboard Layouts ---

def get_main_menu():
    keyboard = [
        [InlineKeyboardButton("🎵 অডিও মার্জ করুন", callback_data="merge")],
        [InlineKeyboardButton("🎬 ভিডিও বানান", callback_data="video")],
        [InlineKeyboardButton("❓ সাহায্য", callback_data="help")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_cancel_button():
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ বাতিল করুন", callback_data="cancel")]])

def get_done_button():
    keyboard = [
        [InlineKeyboardButton("✅ সম্পন্ন করুন", callback_data="done")],
        [InlineKeyboardButton("❌ বাতিল করুন", callback_data="cancel")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_after_merge_options():
    keyboard = [
        [InlineKeyboardButton("➕ আরো অডিও যোগ করুন", callback_data="add_more")],
        [InlineKeyboardButton("🔄 নতুন মার্জ শুরু করুন", callback_data="merge")],
        [InlineKeyboardButton("🏠 মূল মেনু", callback_data="cancel")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_download_button(file_type):
    return InlineKeyboardMarkup([[InlineKeyboardButton(f"⬇️ {file_type} ডাউনলোড করুন", callback_data=f"download_{file_type}")]])


# --- Utility Functions ---

def get_progress_bar(percentage):
    filled = int(percentage / 10)
    return "█" * filled + "░" * (10 - filled)

async def safe_edit_message(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int, text: str, reply_markup=None):
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
        return False
    except Exception as e:
        logger.error(f"Error editing message {message_id}: {e}")
        return False

async def cleanup_user_files(user_id):
    if user_id not in user_data:
        return
    
    data = user_data[user_id]
    files_to_clean = (
        data.get('audio_files', []) + 
        data.get('new_audio_files', []) +
        [data.get(key) for key in ['merged_file', 'image', 'audio', 'output_video'] if data.get(key)]
    )
    
    for file_path in files_to_clean:
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
                logger.info(f"Deleted file: {file_path}")
            except OSError as e:
                logger.error(f"Error removing file {file_path}: {e}")

async def reset_user_on_error(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await cleanup_user_files(user_id)
    
    # Don't delete the status message, just edit it
    if user_id in user_data and 'status_message_id' in user_data[user_id]:
        error_text = "❌ একটি সমস্যা হয়েছে। সেশনটি রিসেট করা হয়েছে।\n\nআবার শুরু করতে নিচের বাটন থেকে আপনার কাজ বেছে নিন:"
        await safe_edit_message(
            context, 
            user_id, 
            user_data[user_id]['status_message_id'], 
            error_text, 
            get_main_menu()
        )
        user_data[user_id] = {
            'status_message_id': user_data[user_id]['status_message_id'], 
            'last_activity': datetime.now()
        }
    else:
        # If no status message exists, send a new one
        error_text = "❌ একটি সমস্যা হয়েছে। সেশনটি রিসেট করা হয়েছে।\n\nআবার শুরু করতে নিচের বাটন থেকে আপনার কাজ বেছে নিন:"
        msg = await context.bot.send_message(
            chat_id=user_id, 
            text=error_text, 
            reply_markup=get_main_menu(), 
            parse_mode='Markdown'
        )
        user_data[user_id] = {
            'status_message_id': msg.message_id, 
            'last_activity': datetime.now()
        }

async def cleanup_inactive_users():
    while True:
        try:
            await asyncio.sleep(600)  # Check every 10 minutes
            current_time = datetime.now()
            inactive_users = [
                uid for uid, data in list(user_data.items())
                if current_time - data.get('last_activity', current_time) > USER_TIMEOUT
            ]
            
            for uid in inactive_users:
                await cleanup_user_files(uid)
                if uid in user_data:
                    del user_data[uid]
                logger.info(f"Cleaned up inactive user: {uid}")
        except Exception as e:
            logger.error(f"Error in cleanup task: {e}")

def update_user_activity(user_id):
    if user_id in user_data:
        user_data[user_id]['last_activity'] = datetime.now()


# --- Command Handlers ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await cleanup_user_files(user_id)
    
    # Delete user's /start message
    if update.message:
        try:
            await update.message.delete()
        except Exception:
            pass
    
    # Check if status message exists
    if user_id in user_data and 'status_message_id' in user_data[user_id]:
        # Edit existing message
        welcome_text = "🎵 *অডিও ভিডিও বট এ স্বাগতম!* 🎬\n\nআমি যা করতে পারি:\n━━━━━━━━━━━━━━━\n🎵 একাধিক অডিও একসাথে জোড়া লাগাতে পারি\n🎬 অডিও + ছবি দিয়ে ভিডিও বানাতে পারি\n\nনিচের বাটন থেকে আপনার কাজ বেছে নিন:"
        await safe_edit_message(
            context, 
            user_id, 
            user_data[user_id]['status_message_id'], 
            welcome_text, 
            get_main_menu()
        )
        user_data[user_id] = {
            'status_message_id': user_data[user_id]['status_message_id'], 
            'last_activity': datetime.now()
        }
    else:
        # Send new message
        welcome_text = "🎵 *অডিও ভিডিও বট এ স্বাগতম!* 🎬\n\nআমি যা করতে পারি:\n━━━━━━━━━━━━━━━\n🎵 একাধিক অডিও একসাথে জোড়া লাগাতে পারি\n🎬 অডিও + ছবি দিয়ে ভিডিও বানাতে পারি\n\nনিচের বাটন থেকে আপনার কাজ বেছে নিন:"
        msg = await context.bot.send_message(
            chat_id=user_id, 
            text=welcome_text, 
            reply_markup=get_main_menu(), 
            parse_mode='Markdown'
        )
        user_data[user_id] = {
            'status_message_id': msg.message_id, 
            'last_activity': datetime.now()
        }


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    action = query.data
    
    update_user_activity(user_id)
    
    if user_id not in user_data:
        user_data[user_id] = {}
    
    user_data[user_id]['status_message_id'] = query.message.message_id
    
    actions = {
        "merge": start_merge,
        "video": start_video,
        "help": show_help,
        "cancel": cancel_action,
        "done": merge_audios,
        "add_more": add_more_audio,
        "download_audio": download_audio,
        "download_video": download_video,
    }
    
    if action in actions:
        await actions[action](update, context)


# --- Feature Start Functions ---

async def start_merge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Clean up previous files
    await cleanup_user_files(user_id)
    
    user_data[user_id].update({
        'mode': 'merge',
        'audio_files': [],
        'audio_names': [],
        'last_activity': datetime.now()
    })
    
    text = "🎵 *অডিও মার্জ মোড*\n\nএখন যতগুলো ইচ্ছে অডিও/ভয়েস পাঠান। শেষ হলে \"সম্পন্ন করুন\" বাটনে ক্লিক করুন।"
    await safe_edit_message(
        context, 
        user_id, 
        user_data[user_id]['status_message_id'], 
        text, 
        get_done_button()
    )

async def add_more_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if 'merged_file' not in user_data.get(user_id, {}):
        return await update.callback_query.answer("❌ প্রথমে একটি অডিও মার্জ করুন!", show_alert=True)
    
    user_data[user_id].update({
        'mode': 'add_more',
        'new_audio_files': [],
        'new_audio_names': [],
        'last_activity': datetime.now()
    })
    
    text = "➕ *আরো অডিও যোগ করুন*\n\nনতুন অডিও/ভয়েস পাঠান। শেষ হলে \"সম্পন্ন করুন\" ক্লিক করুন।"
    await safe_edit_message(
        context, 
        user_id, 
        user_data[user_id]['status_message_id'], 
        text, 
        get_done_button()
    )

async def start_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Clean up previous files
    await cleanup_user_files(user_id)
    
    user_data[user_id].update({
        'mode': 'video',
        'image': None,
        'audio': None,
        'last_activity': datetime.now()
    })
    
    text = "🎬 *ভিডিও বানানোর মোড*\n\n📸 প্রথমে একটি ছবি পাঠান।\n\n✅ ছবি: ❌\n✅ অডিও: ❌"
    await safe_edit_message(
        context, 
        user_id, 
        user_data[user_id]['status_message_id'], 
        text, 
        get_cancel_button()
    )

async def show_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = "📖 *কীভাবে ব্যবহার করবেন:*\n\n*অডিও মার্জ করতে:*\n1. \"অডিও মার্জ করুন\" বাটনে ক্লিক করুন।\n2. যতগুলো ইচ্ছে অডিও/ভয়েস পাঠান।\n3. \"সম্পন্ন করুন\" বাটনে ক্লিক করুন।\n\n*ভিডিও বানাতে:*\n1. \"ভিডিও বানান\" বাটনে ক্লিক করুন।\n2. একটি ছবি পাঠান।\n3. একটি অডিও/ভয়েস পাঠান।\n\n*বৈশিষ্ট্য:*\n• আপনার পাঠানো ফাইল সাথে সাথে ডিলিট হবে\n• ফাইল ছোট এবং অপ্টিমাইজড (720p ভিডিও)\n• মার্জ করা ফাইলে আরো অডিও যোগ করা যায়"
    
    await safe_edit_message(
        context, 
        update.effective_user.id, 
        update.callback_query.message.message_id, 
        help_text, 
        InlineKeyboardMarkup([[InlineKeyboardButton("🔙 মূল মেনু", callback_data="cancel")]])
    )

async def cancel_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    
    await cleanup_user_files(user_id)
    
    welcome_text = "আপনার আগের সেশন বাতিল করা হয়েছে।\n\nনিচের বাটন থেকে আপনার কাজ বেছে নিন:"
    await safe_edit_message(
        context, 
        user_id, 
        query.message.message_id, 
        welcome_text, 
        get_main_menu()
    )
    
    user_data[user_id] = {
        'status_message_id': query.message.message_id, 
        'last_activity': datetime.now()
    }


# --- Media Handlers with Progress ---

async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Delete user's message immediately
    try:
        await update.message.delete()
    except Exception:
        pass
    
    user_id = update.effective_user.id
    
    if user_id not in user_data or 'mode' not in user_data.get(user_id, {}):
        return
    
    update_user_activity(user_id)
    
    mode = user_data[user_id]['mode']
    is_photo = bool(update.message.photo)
    is_audio = bool(
        update.message.audio or 
        update.message.voice or 
        (update.message.document and 
         update.message.document.mime_type and 
         update.message.document.mime_type.startswith('audio'))
    )
    
    if mode == 'video':
        if is_photo and not user_data[user_id].get('image'):
            await handle_photo(update, context)
        elif is_audio and user_data[user_id].get('image') and not user_data[user_id].get('audio'):
            await process_video_audio(update, context)
    elif mode in ['merge', 'add_more'] and is_audio:
        await process_incoming_audio(update, context)

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    status_id = user_data[user_id]['status_message_id']
    
    await safe_edit_message(
        context, 
        user_id, 
        status_id, 
        f"📥 *ছবি ডাউনলোড হচ্ছে...*\n\n{get_progress_bar(50)} 50%"
    )
    
    photo_file = await update.message.photo[-1].get_file()
    photo_path = f"image_{user_id}_{datetime.now().timestamp()}.jpg"
    
    try:
        await photo_file.download_to_drive(photo_path)
        user_data[user_id]['image'] = photo_path
        
        text = "🎬 *ভিডিও বানানোর মোড*\n\n🎵 এখন একটি অডিও বা ভয়েস পাঠান।\n\n✅ ছবি: ✔️ (সংযুক্ত)\n✅ অডিও: ❌"
        await safe_edit_message(
            context, 
            user_id, 
            status_id, 
            text, 
            get_cancel_button()
        )
    except Exception as e:
        logger.error(f"Error downloading photo: {e}")
        await safe_edit_message(
            context, 
            user_id, 
            status_id, 
            "❌ ছবি আপলোডে সমস্যা হয়েছে।", 
            get_cancel_button()
        )

async def process_incoming_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    status_id = user_data[user_id]['status_message_id']
    
    await safe_edit_message(
        context, 
        user_id, 
        status_id, 
        f"📥 *অডিও ডাউনলোড হচ্ছে...*\n\n{get_progress_bar(50)} 50%"
    )
    
    mode = user_data[user_id]['mode']
    file_list_key = 'new_audio_files' if mode == 'add_more' else 'audio_files'
    name_list_key = 'new_audio_names' if mode == 'add_more' else 'audio_names'
    
    file_obj = update.message.audio or update.message.voice or update.message.document
    file_handle = await file_obj.get_file()
    file_path = f"audio_{user_id}_{len(user_data[user_id].get(file_list_key, []))}_{datetime.now().timestamp()}"
    
    try:
        await file_handle.download_to_drive(file_path)
        
        file_name = getattr(file_obj, 'file_name', f"Audio {len(user_data[user_id].get(file_list_key, [])) + 1}")
        
        user_data[user_id].setdefault(file_list_key, []).append(file_path)
        user_data[user_id].setdefault(name_list_key, []).append(file_name)
        
        audio_count = len(user_data[user_id][name_list_key])
        audio_list_str = "\n".join([f"  `{i+1}. {name}`" for i, name in enumerate(user_data[user_id][name_list_key])])
        
        text = f"🎵 *অডিও মার্জ মোড*\n\n*যোগ করা অডিও: {audio_count}টি*\n{audio_list_str}\n\nআরো অডিও পাঠান অথবা \"সম্পন্ন করুন\" ক্লিক করুন।"
        await safe_edit_message(
            context, 
            user_id, 
            status_id, 
            text, 
            get_done_button()
        )
    except Exception as e:
        logger.error(f"Error processing audio: {e}")
        await safe_edit_message(
            context, 
            user_id, 
            status_id, 
            "❌ অডিও প্রসেস করতে সমস্যা হয়েছে।", 
            get_done_button()
        )

async def process_video_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    status_id = user_data[user_id]['status_message_id']
    
    await safe_edit_message(
        context, 
        user_id, 
        status_id, 
        f"📥 *অডিও ডাউনলোড হচ্ছে...*\n\n{get_progress_bar(50)} 50%"
    )
    
    file_obj = update.message.audio or update.message.voice or update.message.document
    file_handle = await file_obj.get_file()
    audio_path = f"video_audio_{user_id}_{datetime.now().timestamp()}"
    
    try:
        await file_handle.download_to_drive(audio_path)
        user_data[user_id]['audio'] = audio_path
        
        text = "🎬 *ভিডিও বানানোর মোড*\n\nসব ফাইল পাওয়া গেছে! ভিডিও তৈরি করা হচ্ছে...\n\n✅ ছবি: ✔️\n✅ অডিও: ✔️"
        await safe_edit_message(context, user_id, status_id, text)
        
        await create_video(update, context)
    except Exception as e:
        logger.error(f"Error processing video audio: {e}")
        await safe_edit_message(
            context, 
            user_id, 
            status_id, 
            "❌ অডিও প্রসেস করতে সমস্যা হয়েছে।", 
            get_cancel_button()
        )


# --- Core Logic ---

async def merge_audios(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    mode = user_data[user_id].get('mode')
    is_add_more = (mode == 'add_more')
    
    base_files = [user_data[user_id]['merged_file']] if is_add_more and 'merged_file' in user_data[user_id] else []
    new_files = user_data[user_id].get('new_audio_files' if is_add_more else 'audio_files', [])
    
    if not new_files or (not is_add_more and len(new_files) < 2):
        return await update.callback_query.answer(
            "❌ কমপক্ষে " + ("১টি নতুন" if is_add_more else "২টি") + " অডিও পাঠান!", 
            show_alert=True
        )
    
    await update.callback_query.answer()
    
    status_id = user_data[user_id]['status_message_id']
    all_files = base_files + new_files
    
    try:
        combined = AudioSegment.empty()
        
        for idx, audio_path in enumerate(all_files):
            progress = int(((idx + 1) / len(all_files)) * 80)
            await safe_edit_message(
                context, 
                user_id, 
                status_id, 
                f"⏳ *অডিও মার্জ হচ্ছে...*\n\n{get_progress_bar(progress)} {progress}%\n\n*ধাপ ১/২:* ফাইল লোড হচ্ছে ({idx + 1}/{len(all_files)})..."
            )
            combined += AudioSegment.from_file(audio_path)
        
        await safe_edit_message(
            context, 
            user_id, 
            status_id, 
            f"⏳ *অডিও মার্জ হচ্ছে...*\n\n{get_progress_bar(90)} 90%\n\n*ধাপ ২/২:* ফাইল সংরক্ষণ করা হচ্ছে..."
        )
        
        output_path = f"merged_{user_id}_{datetime.now().timestamp()}.mp3"
        combined.export(output_path, format="mp3", bitrate="128k")
        
        await safe_edit_message(
            context, 
            user_id, 
            status_id, 
            f"✅ *মার্জ সম্পন্ন!*\n\n{get_progress_bar(100)} 100%\n\nফাইল প্রস্তুত!", 
            get_download_button("audio")
        )
        
        # Clean up old merged file
        if 'merged_file' in user_data[user_id] and os.path.exists(user_data[user_id]['merged_file']):
            os.remove(user_data[user_id]['merged_file'])
        
        # Clean up temporary audio files
        for f in new_files:
            if os.path.exists(f):
                os.remove(f)
        
        user_data[user_id].update({
            'merged_file': output_path,
            'file_ready': True,
            'last_activity': datetime.now(),
            'new_audio_files': [],
            'new_audio_names': []
        })
        
    except Exception as e:
        logger.error(f"Error merging audio: {e}")
        await reset_user_on_error(update, context)

async def download_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    status_id = user_data[user_id]['status_message_id']
    output_path = user_data[user_id].get('merged_file')
    
    if not output_path or not os.path.exists(output_path):
        return await update.callback_query.answer("❌ ফাইল পাওয়া যায়নি!", show_alert=True)
    
    await update.callback_query.answer()
    
    await safe_edit_message(context, user_id, status_id, f"📤 *ফাইল আপলোড হচ্ছে...*")
    
    try:
        with open(output_path, 'rb') as audio_file:
            await context.bot.send_audio(
                chat_id=user_id, 
                audio=audio_file, 
                title="Merged Audio", 
                caption="✅ আপনার অডিও ফাইল প্রস্তুত!"
            )
        
        await safe_edit_message(
            context, 
            user_id, 
            status_id, 
            "এখন কি করবেন?", 
            get_after_merge_options()
        )
    except Exception as e:
        logger.error(f"Error sending audio: {e}")
        await safe_edit_message(
            context, 
            user_id, 
            status_id, 
            "❌ ফাইল পাঠাতে সমস্যা হয়েছে।", 
            get_after_merge_options()
        )

async def download_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    status_id = user_data[user_id]['status_message_id']
    output_video = user_data[user_id].get('output_video')
    
    if not output_video or not os.path.exists(output_video):
        return await update.callback_query.answer("❌ ফাইল পাওয়া যায়নি!", show_alert=True)
    
    await update.callback_query.answer()
    
    await safe_edit_message(context, user_id, status_id, f"📤 *ফাইল আপলোড হচ্ছে...*")
    
    try:
        with open(output_video, 'rb') as video_file:
            await context.bot.send_video(
                chat_id=user_id, 
                video=video_file, 
                caption="✅ আপনার ভিডিও প্রস্তুত!"
            )
        
        welcome_text = "আপনার ভিডিও সফলভাবে তৈরি হয়েছে!\n\nনিচের বাটন থেকে আপনার কাজ বেছে নিন:"
        await safe_edit_message(
            context, 
            user_id, 
            status_id, 
            welcome_text, 
            get_main_menu()
        )
        
        await cleanup_user_files(user_id)
        user_data[user_id] = {
            'status_message_id': status_id, 
            'last_activity': datetime.now()
        }
    except Exception as e:
        logger.error(f"Error sending video: {e}")
        await safe_edit_message(
            context, 
            user_id, 
            status_id, 
            "❌ ভিডিও পাঠাতে সমস্যা হয়েছে।", 
            get_main_menu()
        )

async def create_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    status_id = user_data[user_id]['status_message_id']
    
    try:
        image_path = user_data[user_id]['image']
        audio_path = user_data[user_id]['audio']
        output_video = f"video_{user_id}_{datetime.now().timestamp()}.mp4"
        user_data[user_id]['output_video'] = output_video
        
        # Get audio duration
        try:
            audio_duration = len(AudioSegment.from_file(audio_path)) / 1000.0
        except Exception:
            audio_duration = 0
        
        # FFmpeg command for video creation
        cmd = [
            'ffmpeg',
            '-loop', '1',
            '-i', image_path,
            '-i', audio_path,
            '-c:v', 'libx264',
            '-preset', 'medium',
            '-crf', '30',
            '-c:a', 'aac',
            '-b:a', '128k',
            '-pix_fmt', 'yuv420p',
            '-vf', "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,setsar=1",
            '-shortest',
            '-movflags', '+faststart',
            '-y',
            output_video,
            '-progress', 'pipe:1',
            '-loglevel', 'error'
        ]
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        last_reported_progress = -1
        
        while True:
            line = await process.stdout.readline()
            if not line:
                break
            
            line_str = line.decode('utf-8', errors='ignore').strip()
            
            if line_str.startswith('out_time_ms='):
                try:
                    current_sec = int(line_str.split('=')[1]) / 1000000.0
                    
                    if audio_duration > 0:
                        progress = min(99, int((current_sec / audio_duration) * 100))
                        
                        if progress > last_reported_progress and progress % 5 == 0:
                            last_reported_progress = progress
                            await safe_edit_message(
                                context, 
                                user_id, 
                                status_id, 
                                f"⏳ *ভিডিও তৈরি হচ্ছে...*\n\n{get_progress_bar(progress)} {progress}%\n\nদয়া করে অপেক্ষা করুন।"
                            )
                except (ValueError, IndexError):
                    pass
        
        await process.wait()
        
        if process.returncode == 0:
            await safe_edit_message(
                context, 
                user_id, 
                status_id, 
                f"✅ *ভিডিও তৈরি সম্পন্ন!*\n\n{get_progress_bar(100)} 100%\n\nফাইল প্রস্তুত!", 
                get_download_button("video")
            )
            user_data[user_id]['file_ready'] = True
        else:
            stderr = (await process.stderr.read()).decode()
            logger.error(f"FFmpeg error: {stderr}")
            raise Exception("FFmpeg failed")
            
    except Exception as e:
        logger.error(f"Error creating video: {e}")
        await reset_user_on_error(update, context)


# --- Main Bot Execution ---

async def post_init(application: Application):
    """Initialize background tasks after bot starts"""
    asyncio.create_task(cleanup_inactive_users())
    logger.info("Background cleanup task started")

def main():
    if not TOKEN:
        logger.error("BOT_TOKEN not found! Please set it as an environment variable.")
        return
    
    # Build application
    application = Application.builder().token(TOKEN).post_init(post_init).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # Media handler for audio, voice, photo, and documents
    media_filters = filters.AUDIO | filters.VOICE | filters.PHOTO | filters.Document.ALL
    application.add_handler(MessageHandler(media_filters, handle_media))
    
    logger.info("Bot is starting...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
