import os
import logging
import asyncio
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from telegram.error import BadRequest
from pydub import AudioSegment
import subprocess
from datetime import datetime, timedelta


# Logging setup
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)


# Bot token from environment variable - FIXED
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')


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
    keyboard = [[InlineKeyboardButton("❌ বাতিল করুন", callback_data="cancel")]]
    return InlineKeyboardMarkup(keyboard)


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
        [InlineKeyboardButton("🏠 মূল মেনু", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)


# --- Utility Functions ---

def get_progress_bar(percentage):
    filled = int(percentage / 10)
    empty = 10 - filled
    return "█" * filled + "░" * empty


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
        if "Message is not modified" in str(e):
            return True
        else:
            logger.warning(f"Could not edit message {message_id}: {e}")
        return False
    except Exception as e:
        logger.error(f"Error editing message {message_id}: {e}")
        return False


async def cleanup_user_files(user_id):
    if user_id not in user_data:
        return

    data = user_data[user_id]
    files_to_clean = []
    
    for key in ['audio_files', 'new_audio_files']:
        files_to_clean.extend(data.get(key, []))
    
    for key in ['merged_file', 'image', 'audio', 'output_video']:
        if data.get(key):
            files_to_clean.append(data[key])

    for file_path in files_to_clean:
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
                logger.info(f"Deleted file: {file_path}")
            except OSError as e:
                logger.error(f"Error removing file {file_path}: {e}")


async def reset_user(update: Update, context: ContextTypes.DEFAULT_TYPE, send_new_menu=True):
    user_id = update.effective_user.id
    
    await cleanup_user_files(user_id)

    if user_id in user_data and 'status_message_id' in user_data[user_id]:
        try:
            await context.bot.delete_message(chat_id=user_id, message_id=user_data[user_id]['status_message_id'])
        except Exception:
            pass

    if user_id in user_data:
        del user_data[user_id]
        
    if send_new_menu:
        welcome_text = "🎵 *অডিও ভিডিও বট এ স্বাগতম!*\n\nনিচের বাটন থেকে আপনার কাজ বেছে নিন:"
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


async def cleanup_inactive_users():
    while True:
        try:
            await asyncio.sleep(600)
            current_time = datetime.now()
            inactive_users = [
                uid for uid, data in user_data.items()
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


# --- Command and Action Handlers ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id in user_data:
        await cleanup_user_files(user_id)
        if 'status_message_id' in user_data[user_id]:
            try:
                await context.bot.delete_message(chat_id=user_id, message_id=user_data[user_id]['status_message_id'])
            except Exception:
                pass
        del user_data[user_id]

    welcome_text = "🎵 *অডিও ভিডিও বট এ স্বাগতম!*\n\nআমি যা করতে পারি:\n• একাধিক অডিও একসাথে জোড়া লাগানো\n• অডিও + ছবি দিয়ে ভিডিও বানানো\n\nনিচের বাটন থেকে আপনার কাজ বেছে নিন:"
    
    if update.message:
        try:
            await update.message.delete()
        except Exception:
            pass
    
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
    
    user_id = update.effective_user.id
    action = query.data
    
    update_user_activity(user_id)
    
    if user_id not in user_data:
        user_data[user_id] = {'last_activity': datetime.now()}
    
    actions = {
        "merge": start_merge,
        "video": start_video,
        "help": show_help,
        "cancel": cancel_action,
        "main_menu": cancel_action,
        "done": merge_audios,
        "add_more": add_more_audio,
    }
    
    if action in actions:
        await actions[action](update, context)


# --- Main Feature Functions ---

async def start_merge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    await cleanup_user_files(user_id)

    user_data[user_id].update({
        'mode': 'merge',
        'audio_files': [],
        'audio_names': [],
        'status_message_id': update.callback_query.message.message_id,
        'last_activity': datetime.now()
    })
    
    text = "🎵 *অডিও মার্জ মোড*\n\nএখন যতগুলো ইচ্ছে অডিও/ভয়েস পাঠান। শেষ হলে \"সম্পন্ন করুন\" বাটনে ক্লিক করুন।"
    await safe_edit_message(context, user_id, user_data[user_id]['status_message_id'], text, get_done_button())


async def add_more_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    
    text = "➕ *আরো অডিও যোগ করুন*\n\nনতুন অডিও/ভয়েস পাঠান। শেষ হলে \"সম্পন্ন করুন\" ক্লিক করুন۔"
    await safe_edit_message(context, user_id, user_data[user_id]['status_message_id'], text, get_done_button())


async def start_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    await cleanup_user_files(user_id)

    user_data[user_id].update({
        'mode': 'video',
        'image': None,
        'audio': None,
        'status_message_id': update.callback_query.message.message_id,
        'last_activity': datetime.now()
    })
    
    text = "🎬 *ভিডিও বানানোর মোড*\n\n📸 প্রথমে একটি ছবি পাঠান۔"
    await safe_edit_message(context, user_id, user_data[user_id]['status_message_id'], text, get_cancel_button())


async def show_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    help_text = "📖 *কীভাবে ব্যবহার করবেন:*\n\n*অডিও মার্জ করতে:*\n1. \"অডিও মার্জ করুন\" বাটনে ক্লিক করুন\n2. যতগুলো ইচ্ছে অডিও/ভয়েস পাঠান\n3. \"সম্পন্ন করুন\" বাটনে ক্লিক করুন\n\n*ভিডিও বানাতে:*\n1. \"ভিডিও বানান\" বাটনে ক্লিক করুন\n2. একটি ছবি পাঠান\n3. একটি অডিও/ভয়েস পাঠান"
    
    keyboard = [[InlineKeyboardButton("🔙 মূল মেনু", callback_data="main_menu")]]
    await safe_edit_message(
        context, user_id, update.callback_query.message.message_id,
        help_text, InlineKeyboardMarkup(keyboard)
    )


async def cancel_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await reset_user(update, context, send_new_menu=True)


# --- Media Handlers ---

async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_data or 'mode' not in user_data[user_id]:
        return

    update_user_activity(user_id)
    mode = user_data[user_id]['mode']
    
    try:
        await update.message.delete()
    except Exception:
        pass

    is_photo = bool(update.message.photo)
    is_audio_type = bool(update.message.audio or update.message.voice or 
                         (update.message.document and update.message.document.mime_type and 
                          update.message.document.mime_type.startswith('audio/')))

    if mode == 'video':
        if is_photo and not user_data[user_id].get('image'):
            await handle_photo(update, context)
        elif is_audio_type and user_data[user_id].get('image') and not user_data[user_id].get('audio'):
            await process_video_audio(update, context)
    elif mode in ['merge', 'add_more'] and is_audio_type:
        await process_incoming_audio(update, context)


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    status_id = user_data[user_id]['status_message_id']
    
    photo_file = await update.message.photo[-1].get_file()
    # FIXED: int() added to timestamp
    photo_path = f"image_{user_id}_{int(datetime.now().timestamp())}.jpg"
    
    try:
        await photo_file.download_to_drive(photo_path)
        user_data[user_id]['image'] = photo_path

        text = "🎬 *ভিডিও বানানোর মোড*\n\n✅ ছবি সংযুক্ত হয়েছে!\n\n🎵 এখন একটি অডিও বা ভয়েস পাঠান।"
        await safe_edit_message(context, user_id, status_id, text, get_cancel_button())
        
    except Exception as e:
        logger.error(f"Error downloading photo: {e}")
        text = "❌ ছবি আপলোডে সমস্যা হয়েছে। আবার চেষ্টা করুন।"
        await safe_edit_message(context, user_id, status_id, text, get_cancel_button())


async def process_incoming_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    mode = user_data[user_id]['mode']
    status_id = user_data[user_id]['status_message_id']
    is_add_more = (mode == 'add_more')

    file_list_key = 'new_audio_files' if is_add_more else 'audio_files'
    name_list_key = 'new_audio_names' if is_add_more else 'audio_names'

    file_obj = update.message.audio or update.message.voice or update.message.document

    # Check file size (MAX 100MB instead of 50MB)
    if hasattr(file_obj, 'file_size') and file_obj.file_size > 100 * 1024 * 1024:
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text="❌ ফাইল খুব বড়! সর্বোচ্চ 100MB এর ফাইল পাঠান।"
            )
        except Exception:
            pass
        return

    # Determine file extension
    if update.message.voice:
        file_extension = ".ogg"
    elif update.message.audio:
        file_extension = ".mp3"
    else:
        # For documents, try to detect format from mime type
        mime_type = getattr(update.message.document, 'mime_type', '')
        if 'ogg' in mime_type or 'opus' in mime_type:
            file_extension = ".ogg"
        elif 'wav' in mime_type:
            file_extension = ".wav"
        else:
            file_extension = ".mp3"  # default

    file_path = f"audio_{user_id}_{len(user_data[user_id].get(file_list_key, []))}_{int(datetime.now().timestamp())}{file_extension}"

    try:
        file_handle = await file_obj.get_file()
        await file_handle.download_to_drive(file_path)

        file_name = getattr(file_obj, 'file_name', f"Audio {len(user_data[user_id].get(file_list_key, [])) + 1}")

        if file_list_key not in user_data[user_id]:
            user_data[user_id][file_list_key] = []
        if name_list_key not in user_data[user_id]:
            user_data[user_id][name_list_key] = []
            
        user_data[user_id][file_list_key].append(file_path)
        user_data[user_id][name_list_key].append(file_name)

        audio_count = len(user_data[user_id][file_list_key])
        audio_list = "\n".join([f"  {i+1}. {name}" for i, name in enumerate(user_data[user_id][name_list_key][-5:])])
        
        if audio_count > 5:
            audio_list += f"\n  ... এবং আরও {audio_count - 5}টি"

        text = f"🎵 *অডিও মার্জ মোড*\n\n*যোগ করা অডিও: {audio_count}টি*\n{audio_list}\n\nআরো অডিও পাঠান অথবা \"সম্পন্ন করুন\" ক্লিক করুন।"
        await safe_edit_message(context, user_id, status_id, text, get_done_button())

    except Exception as e:
        logger.error(f"Error processing audio: {e}")
        error_type = type(e).__name__
        if "MemoryError" in error_type or "OSError" in error_type:
            error_msg = "❌ ফাইলটি খুব বড় বা মেমরি সমস্যা হচ্ছে। ছোট ফাইল পাঠান।"
        elif "DecodingError" in error_type:
            error_msg = "❌ অডিও ফাইলটি ক্ষতিগ্রস্ত বা সাপোর্টেড না। অন্য ফাইল পাঠান।"
        else:
            error_msg = f"❌ অডিও প্রসেস করতে সমস্যা হয়েছে ({error_type})। আবার চেষ্টা করুন।"
        
        await safe_edit_message(context, user_id, status_id, error_msg, get_done_button())


async def process_video_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    status_id = user_data[user_id]['status_message_id']
    
    file_obj = update.message.audio or update.message.voice or update.message.document
    
    # Check file size (MAX 100MB instead of 50MB)
    if hasattr(file_obj, 'file_size') and file_obj.file_size > 100 * 1024 * 1024:
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text="❌ ফাইল খুব বড়! সর্বোচ্চ 100MB এর ফাইল পাঠান।"
            )
        except Exception:
            pass
        return
    
    # Determine file extension
    if update.message.voice:
        file_extension = ".ogg"
    elif update.message.audio:
        file_extension = ".mp3"
    else:
        file_extension = ".mp3"
    
    # FIXED: int() added to timestamp
    audio_path = f"video_audio_{user_id}_{int(datetime.now().timestamp())}{file_extension}"
    
    try:
        file_handle = await file_obj.get_file()
        await file_handle.download_to_drive(audio_path)
        user_data[user_id]['audio'] = audio_path
        
        text = "🎬 *ভিডিও বানানোর মোড*\n\n✅ সব ফাইল পাওয়া গেছে!\n\n⏳ ভিডিও তৈরি করা হচ্ছে..."
        await safe_edit_message(context, user_id, status_id, text)
        await create_video(update, context)
        
    except Exception as e:
        logger.error(f"Error processing video audio: {e}")
        text = "❌ অডিও প্রসেস করতে সমস্যা হয়েছে। আবার চেষ্টা করুন।"
        await safe_edit_message(context, user_id, status_id, text, get_cancel_button())


# --- Core Logic: Merge and Create ---

async def merge_audios(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        # Step 1: Preparation
        text = f"⏳ *অডিও মার্জ হচ্ছে...*\n\n{get_progress_bar(0)} 0%\n\nপ্রস্তুতি চলছে..."
        await safe_edit_message(context, user_id, status_id, text)
        
        combined = AudioSegment.empty()
        total_duration = 0
        current_duration = 0
        
        # Step 2: Analyze files and calculate total duration
        text = f"⏳ *অডিও মার্জ হচ্ছে...*\n\n{get_progress_bar(5)} 5%\n\nফাইল এনালাইজ করা হচ্ছে..."
        await safe_edit_message(context, user_id, status_id, text)
        
        file_durations = []
        for idx, audio_path in enumerate(all_files):
            try:
                # OPTIMIZED: Use proper format detection to reduce memory usage
                file_extension = audio_path.split('.')[-1].lower()
                if file_extension in ['mp3', 'wav', 'ogg', 'm4a', 'flac']:
                    audio = AudioSegment.from_file(audio_path, format=file_extension)
                else:
                    audio = AudioSegment.from_file(audio_path)
                
                duration = len(audio)
                file_durations.append(duration)
                total_duration += duration
                
                # Clear audio variable to free memory
                del audio
                
                progress = 5 + int((idx + 1) / len(all_files) * 15)
                text = f"⏳ *অডিও মার্জ হচ্ছে...*\n\n{get_progress_bar(progress)} {progress}%\n\nফাইল এনালাইজ করা হচ্ছে... ({idx + 1}/{len(all_files)})"
                await safe_edit_message(context, user_id, status_id, text)
                
            except Exception as e:
                logger.error(f"Error analyzing file {audio_path}: {e}")
                file_durations.append(0)
        
        # Step 3: Merge audio files with precise progress and memory optimization
        for idx, (audio_path, file_duration) in enumerate(zip(all_files, file_durations)):
            progress = 20 + int((current_duration / total_duration) * 70) if total_duration > 0 else 20
            text = f"⏳ *অডিও মার্জ হচ্ছে...*\n\n{get_progress_bar(progress)} {progress}%\n\nঅডিও মার্জ করা হচ্ছে... ({idx + 1}/{total_files})"
            await safe_edit_message(context, user_id, status_id, text)
            
            try:
                # OPTIMIZED: Use proper format detection to reduce memory usage
                file_extension = audio_path.split('.')[-1].lower()
                if file_extension in ['mp3', 'wav', 'ogg', 'm4a', 'flac']:
                    audio = AudioSegment.from_file(audio_path, format=file_extension)
                else:
                    audio = AudioSegment.from_file(audio_path)
                
                combined += audio
                current_duration += file_duration
                
                # Clear audio variable to free memory
                del audio
                
                # Update progress for every 5% change
                new_progress = 20 + int((current_duration / total_duration) * 70) if total_duration > 0 else 20
                if new_progress != progress:
                    text = f"⏳ *অডিও মার্জ হচ্ছে...*\n\n{get_progress_bar(new_progress)} {new_progress}%\n\nঅডিও মার্জ করা হচ্ছে... ({idx + 1}/{total_files})"
                    await safe_edit_message(context, user_id, status_id, text)
                    
            except Exception as e:
                logger.error(f"Error processing file {audio_path}: {e}")
                # Continue with other files even if one fails
                continue
        
        # Step 4: Export the merged file
        progress = 90
        text = f"⏳ *অডিও মার্জ হচ্ছে...*\n\n{get_progress_bar(progress)} {progress}%\n\nফাইল সংরক্ষণ করা হচ্ছে..."
        await safe_edit_message(context, user_id, status_id, text)
        
        # FIXED: int() added to timestamp
        output_path = f"merged_{user_id}_{int(datetime.now().timestamp())}.mp3"
        combined.export(output_path, format="mp3", bitrate="128k", parameters=["-ac", "1"])
        
        # Step 5: Complete
        progress = 100
        text = f"✅ *মার্জ সম্পন্ন!*\n\n{get_progress_bar(progress)} {progress}%\n\nআপনার অডিও ফাইল প্রস্তুত!"
        await safe_edit_message(context, user_id, status_id, text)
        
        # Send the file directly
        await send_merged_audio(context, user_id, output_path, status_id)
        
    except Exception as e:
        logger.error(f"Error merging audio: {e}")
        text = "❌ অডিও মার্জ করতে সমস্যা হয়েছে। আবার চেষ্টা করুন।"
        await safe_edit_message(context, user_id, status_id, text, get_main_menu())


async def send_merged_audio(context: ContextTypes.DEFAULT_TYPE, user_id: int, output_path: str, status_id: int):
    try:
        with open(output_path, 'rb') as audio_file:
            await context.bot.send_audio(
                chat_id=user_id, 
                audio=audio_file, 
                title="Merged Audio",
                caption="✅ আপনার মার্জড অডিও ফাইল প্রস্তুত!"
            )
        
        # Clean up old merged file
        old_merged = user_data.get(user_id, {}).get('merged_file')
        if old_merged and os.path.exists(old_merged):
            try:
                os.remove(old_merged)
            except Exception as e:
                logger.error(f"Error removing old merged file: {e}")
        
        # Update user data
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
        await safe_edit_message(context, user_id, status_id, text, get_after_merge_options())
        
    except Exception as e:
        logger.error(f"Error sending audio: {e}")
        text = "❌ ফাইল পাঠাতে সমস্যা হয়েছে। আবার চেষ্টা করুন।"
        await safe_edit_message(context, user_id, status_id, text, get_after_merge_options())


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


async def create_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    status_id = user_data[user_id]['status_message_id']
    
    try:
        image_path = user_data[user_id]['image']
        audio_path = user_data[user_id]['audio']
        # FIXED: int() added to timestamp
        output_video = f"video_{user_id}_{int(datetime.now().timestamp())}.mp4"
        
        # Get audio duration for progress calculation
        try:
            # OPTIMIZED: Use proper format detection
            file_extension = audio_path.split('.')[-1].lower()
            if file_extension in ['mp3', 'wav', 'ogg', 'm4a', 'flac']:
                audio = AudioSegment.from_file(audio_path, format=file_extension)
            else:
                audio = AudioSegment.from_file(audio_path)
            audio_duration = len(audio) / 1000.0
            logger.info(f"Audio duration: {audio_duration}s")
        except Exception as e:
            logger.error(f"Cannot read audio duration: {e}")
            audio_duration = 0
        
        # FFmpeg command
        cmd = [
            'ffmpeg', '-loop', '1', '-i', image_path, '-i', audio_path,
            '-c:v', 'libx264', '-preset', 'fast', '-crf', '28',
            '-c:a', 'aac', '-b:a', '128k',
            '-pix_fmt', 'yuv420p', '-shortest', '-movflags', '+faststart',
            '-y', output_video, '-progress', 'pipe:1', '-loglevel', 'error'
        ]
        
        process = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        
        last_reported_progress = -1
        
        while True:
            line_bytes = await process.stdout.readline()
            if not line_bytes:
                break
            
            line = line_bytes.decode('utf-8', errors='ignore').strip()
            
            # Parse progress from FFmpeg output
            if line.startswith('out_time_ms='):
                try:
                    time_us = int(line.split('=')[1])
                    current_time_sec = time_us / 1000000.0
                    
                    if audio_duration > 0:
                        progress = min(99, int((current_time_sec / audio_duration) * 100))
                        
                        # Update for every percentage change
                        if progress != last_reported_progress:
                            last_reported_progress = progress
                            text = f"⏳ *ভিডিও তৈরি হচ্ছে...*\n\n{get_progress_bar(progress)} {progress}%\n\nদয়া করে অপেক্ষা করুন..."
                            await safe_edit_message(context, user_id, status_id, text)
                except (ValueError, IndexError) as e:
                    logger.debug(f"Could not parse progress: {e}")

        await process.wait()
        
        if process.returncode == 0:
            user_data[user_id]['output_video'] = output_video
            
            progress = 100
            text = f"✅ *ভিডিও তৈরি সম্পন্ন!*\n\n{get_progress_bar(progress)} {progress}%\n\nআপনার ভিডিও প্রস্তুত!"
            await safe_edit_message(context, user_id, status_id, text)
            
            # Send the video directly
            await send_created_video(context, user_id, output_video, status_id)
        else:
            stderr_output = (await process.stderr.read()).decode()
            logger.error(f"FFmpeg error (code {process.returncode}): {stderr_output}")
            raise Exception(f"FFmpeg failed with code {process.returncode}")

    except Exception as e:
        logger.error(f"Error creating video: {e}")
        await cleanup_user_files(user_id)
        text = "❌ ভিডিও বানাতে সমস্যা হয়েছে।\n\n💡 Tips:\n• ছবির সাইজ 10MB এর কম কিনা চেক করুন\n• অডিও ফাইল সঠিক আছে কিনা দেখুন\n• আবার চেষ্টা করুন"
        await safe_edit_message(context, user_id, status_id, text, get_main_menu())


async def send_created_video(context: ContextTypes.DEFAULT_TYPE, user_id: int, output_video: str, status_id: int):
    try:
        with open(output_video, 'rb') as video_file:
            await context.bot.send_video(
                chat_id=user_id,
                video=video_file,
                caption="✅ আপনার ভিডিও প্রস্তুত!"
            )
        
        welcome_text = "আপনার ভিডিও সফলভাবে তৈরি হয়েছে!\n\nনিচের বাটন থেকে আপনার কাজ বেছে নিন:"
        await safe_edit_message(context, user_id, status_id, welcome_text, get_main_menu())
        
        await cleanup_user_files(user_id)
        user_data[user_id] = {
            'status_message_id': status_id,
            'last_activity': datetime.now()
        }
        
    except Exception as e:
        logger.error(f"Error sending video: {e}")
        text = "❌ ভিডিও পাঠাতে সমস্যা হয়েছে। আবার চেষ্টা করুন।"
        await safe_edit_message(context, user_id, status_id, text, get_main_menu())


# --- Main Bot Execution ---

async def post_init(application: Application):
    asyncio.create_task(cleanup_inactive_users())


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
