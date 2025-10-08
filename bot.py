import os
import logging
import asyncio
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from telegram.error import BadRequest
from pydub import AudioSegment
import subprocess

# Logging setup
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Bot token from environment variable
TOKEN = os.getenv('BOT_TOKEN')

# User data storage (In-memory)
user_data = {}

# --- Keyboard Layouts ---

def get_main_menu():
    """Returns the main menu keyboard."""
    keyboard = [
        [InlineKeyboardButton("🎵 অডিও মার্জ করুন", callback_data="merge")],
        [InlineKeyboardButton("🎬 ভিডিও বানান", callback_data="video")],
        [InlineKeyboardButton("❓ সাহায্য", callback_data="help")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_cancel_button():
    """Returns a single cancel button."""
    keyboard = [[InlineKeyboardButton("❌ বাতিল করুন", callback_data="cancel")]]
    return InlineKeyboardMarkup(keyboard)

def get_done_button():
    """Returns 'Done' and 'Cancel' buttons for merging."""
    keyboard = [
        [InlineKeyboardButton("✅ সম্পন্ন করুন", callback_data="done")],
        [InlineKeyboardButton("❌ বাতিল করুন", callback_data="cancel")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_after_merge_options():
    """Returns options after a merge is complete."""
    keyboard = [
        [InlineKeyboardButton("➕ আরো অডিও যোগ করুন", callback_data="add_more")],
        [InlineKeyboardButton("🔄 নতুন মার্জ শুরু করুন", callback_data="merge")],
        [InlineKeyboardButton("🏠 মূল মেনু", callback_data="cancel")]
    ]
    return InlineKeyboardMarkup(keyboard)

# --- Utility Functions ---

def get_progress_bar(percentage):
    """Generates a simple text-based progress bar."""
    filled = int(percentage / 10)
    empty = 10 - filled
    return "█" * filled + "░" * empty

async def safe_edit_message(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int, text: str, reply_markup=None):
    """Safely edits a message, catching common errors."""
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
            pass
        else:
            logger.warning(f"Could not edit message {message_id}: {e}")
        return False
    except Exception as e:
        logger.error(f"Error editing message {message_id}: {e}")
        return False

async def cleanup_user_files(user_id):
    """Cleans up all temporary files for a given user."""
    if user_id not in user_data:
        return

    data = user_data[user_id]
    files_to_clean = (
        data.get('audio_files', []) +
        data.get('new_audio_files', []) +
        [data.get(key) for key in ['merged_file', 'image', 'audio', 'output_video']]
    )

    for file_path in files_to_clean:
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
                logger.info(f"Deleted file: {file_path}")
            except OSError as e:
                logger.error(f"Error removing file {file_path}: {e}")

async def cleanup_user_messages(context: ContextTypes.DEFAULT_TYPE, user_id):
    """Cleans up all temporary messages for a given user."""
    if user_id not in user_data:
        return
    
    data = user_data[user_id]
    messages_to_delete = data.get('user_messages', [])
    if 'status_message_id' in data:
        messages_to_delete.append(data['status_message_id'])

    for msg_id in messages_to_delete:
        try:
            await context.bot.delete_message(chat_id=user_id, message_id=msg_id)
        except Exception:
            pass

async def reset_user(update: Update, context: ContextTypes.DEFAULT_TYPE, send_new_menu=True):
    """Cleans up user data and shows the main menu."""
    user_id = update.effective_user.id
    
    await cleanup_user_files(user_id)
    await cleanup_user_messages(context, user_id)

    if user_id in user_data:
        del user_data[user_id]
        
    if send_new_menu:
        welcome_text = "আপনার আগের সেশন বাতিল করা হয়েছে।\n\nনিচের বাটন থেকে আপনার কাজ বেছে নিন:"
        await context.bot.send_message(
            chat_id=user_id,
            text=welcome_text,
            reply_markup=get_main_menu(),
            parse_mode='Markdown'
        )

# --- Command and Action Handlers ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /start command."""
    user_id = update.effective_user.id
    await cleanup_user_files(user_id)
    
    if user_id in user_data:
        await cleanup_user_messages(context, user_id)
        if user_id in user_data:
            del user_data[user_id]

    welcome_text = "🎵 *অডিও ভিডিও বট এ স্বাগতম!* 🎬\n\nআমি যা করতে পারি:\n━━━━━━━━━━━━━━━\n🎵 একাধিক অডিও একসাথে জোড়া লাগাতে পারি\n🎬 অডিও + ছবি দিয়ে ভিডিও বানাতে পারি\n\nনিচের বাটন থেকে আপনার কাজ বেছে নিন:"
    
    if update.message:
        await update.message.reply_text(
            welcome_text,
            reply_markup=get_main_menu(),
            parse_mode='Markdown'
        )
    elif update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(
            welcome_text,
            reply_markup=get_main_menu(),
            parse_mode='Markdown'
        )
        try:
            await update.callback_query.message.delete()
        except Exception:
            pass

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles all button clicks."""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    action = query.data
    
    if user_id not in user_data:
        user_data[user_id] = {}
    
    actions = {
        "merge": start_merge,
        "video": start_video,
        "help": show_help,
        "cancel": cancel_action,
        "done": merge_audios,
        "add_more": add_more_audio,
    }
    
    if action in actions:
        await actions[action](update, context)

# --- Main Feature Functions ---

async def start_merge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Starts the audio merging process."""
    user_id = update.effective_user.id
    
    try:
        await update.callback_query.message.delete()
    except Exception:
        pass

    user_data[user_id] = {
        'mode': 'merge',
        'audio_files': [],
        'audio_names': [],
        'user_messages': []
    }
    
    text = "🎵 *অডিও মার্জ মোড*\n\nএখন যতগুলো ইচ্ছে অডিও/ভয়েস পাঠান। শেষ হলে \"সম্পন্ন করুন\" বাটনে ক্লিক করুন।"
    status_message = await context.bot.send_message(user_id, text, reply_markup=get_done_button(), parse_mode='Markdown')
    user_data[user_id]['status_message_id'] = status_message.message_id

async def add_more_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Adds more audio to an existing merged file."""
    user_id = update.effective_user.id
    if 'merged_file' not in user_data.get(user_id, {}):
        await update.callback_query.answer("❌ প্রথমে একটি অডিও মার্জ করুন!", show_alert=True)
        return
    
    try:
        await update.callback_query.message.delete()
    except Exception:
        pass

    user_data[user_id].update({
        'mode': 'add_more',
        'new_audio_files': [],
        'new_audio_names': [],
        'user_messages': []
    })
    
    text = "➕ *আরো অডিও যোগ করুন*\n\nনতুন অডিও/ভয়েস পাঠান। শেষ হলে \"সম্পন্ন করুন\" ক্লিক করুন।"
    status_message = await context.bot.send_message(user_id, text, reply_markup=get_done_button(), parse_mode='Markdown')
    user_data[user_id]['status_message_id'] = status_message.message_id

async def start_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Starts the video creation process."""
    user_id = update.effective_user.id
    try:
        await update.callback_query.message.delete()
    except Exception:
        pass

    user_data[user_id] = {
        'mode': 'video',
        'image': None,
        'audio': None,
        'user_messages': []
    }
    
    text = "🎬 *ভিডিও বানানোর মোড*\n\n📸 প্রথমে একটি ছবি পাঠান।\n\n✅ ছবি: ❌\n✅ অডিও: ❌"
    status_message = await context.bot.send_message(user_id, text, reply_markup=get_cancel_button(), parse_mode='Markdown')
    user_data[user_id]['status_message_id'] = status_message.message_id

async def show_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows help information."""
    try:
        await update.callback_query.message.delete()
    except Exception:
        pass

    help_text = "📖 *কীভাবে ব্যবহার করবেন:*\n\n*অডিও মার্জ করতে:*\n1. \"অডিও মার্জ করুন\" বাটনে ক্লিক করুন।\n2. যতগুলো ইচ্ছে অডিও/ভয়েস পাঠান।\n3. \"সম্পন্ন করুন\" বাটনে ক্লিক করুন।\n\n*ভিডিও বানাতে:*\n1. \"ভিডিও বানান\" বাটনে ক্লিক করুন।\n2. একটি ছবি পাঠান।\n3. একটি অডিও/ভয়েস পাঠান।"
    
    keyboard = [[InlineKeyboardButton("🔙 মূল মেনু", callback_data="cancel")]]
    await context.bot.send_message(
        chat_id=update.effective_user.id,
        text=help_text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def cancel_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancels the current operation."""
    await reset_user(update, context, send_new_menu=True)

# --- Media Handlers ---

async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Routes media to appropriate handlers based on mode."""
    user_id = update.effective_user.id
    if user_id not in user_data or 'mode' not in user_data.get(user_id, {}):
        return

    mode = user_data[user_id]['mode']
    user_data[user_id]['user_messages'].append(update.message.message_id)

    is_photo = bool(update.message.photo)
    is_audio_type = bool(update.message.audio or update.message.voice or (update.message.document and update.message.document.mime_type and update.message.document.mime_type.startswith('audio')))

    if mode == 'video':
        if is_photo and not user_data[user_id].get('image'):
            await handle_photo(update, context)
        elif is_audio_type and user_data[user_id].get('image'):
            await process_video_audio(update, context)
    elif mode in ['merge', 'add_more'] and is_audio_type:
        await process_incoming_audio(update, context)


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles photo upload for video creation."""
    user_id = update.effective_user.id
    photo_file = await update.message.photo[-1].get_file()
    photo_path = f"image_{user_id}.jpg"
    await photo_file.download_to_drive(photo_path)
    user_data[user_id]['image'] = photo_path

    text = "🎬 *ভিডিও বানানোর মোড*\n\n🎵 এখন একটি অডিও বা ভয়েস পাঠান।\n\n✅ ছবি: ✔️ (সংযুক্ত)\n✅ অডিও: ❌"
    await safe_edit_message(context, user_id, user_data[user_id]['status_message_id'], text, get_cancel_button())


async def process_incoming_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processes incoming audio files for merging."""
    user_id = update.effective_user.id
    mode = user_data[user_id]['mode']
    is_add_more = (mode == 'add_more')
    
    file_list_key = 'new_audio_files' if is_add_more else 'audio_files'
    name_list_key = 'new_audio_names' if is_add_more else 'audio_names'
    
    file_obj = update.message.audio or update.message.voice or update.message.document
    file_handle = await file_obj.get_file()
    file_path = f"audio_{user_id}_{len(user_data[user_id][file_list_key])}"
    await file_handle.download_to_drive(file_path)

    file_name = getattr(file_obj, 'file_name', f"Audio {len(user_data[user_id][file_list_key]) + 1}")
        
    user_data[user_id][file_list_key].append(file_path)
    user_data[user_id][name_list_key].append(file_name)
    
    audio_count = len(user_data[user_id][file_list_key])
    audio_list = "\n".join([f"  `{i+1}. {name}`" for i, name in enumerate(user_data[user_id][name_list_key])])
    
    text = f"🎵 *অডিও মার্জ মোড*\n\n*যোগ করা অডিও: {audio_count}টি*\n{audio_list}\n\nআরো অডিও পাঠান অথবা \"সম্পন্ন করুন\" ক্লিক করুন।"
    await safe_edit_message(context, user_id, user_data[user_id]['status_message_id'], text, get_done_button())


async def process_video_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processes audio for video creation."""
    user_id = update.effective_user.id
    file_obj = update.message.audio or update.message.voice or update.message.document
    file_handle = await file_obj.get_file()
    audio_path = f"video_audio_{user_id}"
    await file_handle.download_to_drive(audio_path)
    user_data[user_id]['audio'] = audio_path
    
    text = "🎬 *ভিডিও বানানোর মোড*\n\nসব ফাইল পাওয়া গেছে! ভিডিও তৈরি করা হচ্ছে...\n\n✅ ছবি: ✔️\n✅ অডিও: ✔️"
    await safe_edit_message(context, user_id, user_data[user_id]['status_message_id'], text)
    await create_video(update, context)

# --- Core Logic: Merge and Create ---

async def merge_audios(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Merges multiple audio files into one."""
    user_id = update.effective_user.id
    mode = user_data[user_id].get('mode')
    
    is_add_more = (mode == 'add_more')
    base_files = [user_data[user_id]['merged_file']] if is_add_more else []
    new_files = user_data[user_id].get('new_audio_files' if is_add_more else 'audio_files', [])

    if not new_files or (not is_add_more and len(new_files) < 2):
        await update.callback_query.answer("❌ কমপক্ষে " + ("১টি নতুন" if is_add_more else "২টি") + " অডিও পাঠান!", show_alert=True)
        return

    await update.callback_query.answer()
    status_id = user_data[user_id]['status_message_id']
    all_files = base_files + new_files
    total_files = len(all_files)

    try:
        combined = AudioSegment.empty()
        # 1. Loading Phase (0% -> 80%)
        for idx, audio_path in enumerate(all_files):
            progress = int(((idx + 1) / total_files) * 80)
            text = f"⏳ *অডিও মার্জ হচ্ছে...*\n\n{get_progress_bar(progress)} {progress}%\n\n*ধাপ ১/২:* অডিও ফাইল লোড করা হচ্ছে ({idx + 1}/{total_files})..."
            await safe_edit_message(context, user_id, status_id, text)
            audio = AudioSegment.from_file(audio_path)
            combined += audio
        
        # 2. Exporting Phase (80% -> 100%)
        progress = 90
        text = f"⏳ *অডিও মার্জ হচ্ছে...*\n\n{get_progress_bar(progress)} {progress}%\n\n*ধাপ ২/২:* সব অডিও একত্রিত করে সংরক্ষণ করা হচ্ছে..."
        await safe_edit_message(context, user_id, status_id, text)
        
        output_path = f"merged_{user_id}.mp3"
        combined.export(output_path, format="mp3")
        
        progress = 100
        text = f"✅ *মার্জ সম্পন্ন!*\n\n{get_progress_bar(progress)} {progress}%\n\nএখন আপনাকে ফাইলটি পাঠানো হচ্ছে..."
        await safe_edit_message(context, user_id, status_id, text)
        
        await asyncio.sleep(0.5)
        
        with open(output_path, 'rb') as audio_file:
            await context.bot.send_audio(
                chat_id=user_id, audio=audio_file, title="Merged Audio",
                caption=f"✅ {len(new_files)} টি অডিও সফলভাবে মার্জ হয়েছে!"
            )
        
        await cleanup_user_messages(context, user_id)
        
        merged_file = user_data[user_id].get('merged_file')
        if merged_file and os.path.exists(merged_file):
            os.remove(merged_file)
        
        user_data[user_id] = {'merged_file': output_path}
        options_msg = await context.bot.send_message(
            chat_id=user_id, text="এখন কি করবেন?", reply_markup=get_after_merge_options()
        )
        user_data[user_id]['status_message_id'] = options_msg.message_id
        
    except Exception as e:
        logger.error(f"Error merging audio: {e}")
        await reset_user(update, context, send_new_menu=False)
        await context.bot.send_message(chat_id=user_id, text="❌ অডিও মার্জ করতে সমস্যা হয়েছে। আবার চেষ্টা করুন।", reply_markup=get_main_menu())


def parse_ffmpeg_time(time_str: str) -> float:
    """Converts FFmpeg time format HH:MM:SS.ss to seconds."""
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
    """Creates a video from an image and audio with real-time progress."""
    user_id = update.effective_user.id
    status_id = user_data[user_id]['status_message_id']
    
    try:
        image_path = user_data[user_id]['image']
        audio_path = user_data[user_id]['audio']
        output_video = f"video_{user_id}.mp4"
        user_data[user_id]['output_video'] = output_video
        
        try:
            audio_duration = len(AudioSegment.from_file(audio_path)) / 1000.0
            logger.info(f"Audio duration: {audio_duration}s")
        except Exception as e:
            logger.error(f"Cannot read audio duration: {e}")
            audio_duration = 0
        
        cmd = [
            'ffmpeg', '-loop', '1', '-i', image_path, '-i', audio_path,
            '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23', 
            '-c:a', 'aac', '-b:a', '192k', '-pix_fmt', 'yuv420p', 
            '-shortest', '-y', output_video, '-progress', 'pipe:1', '-loglevel', 'error'
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
            
            if line.startswith('out_time_ms='):
                try:
                    time_us = int(line.split('=')[1])
                    current_time_sec = time_us / 1000000.0
                    
                    if audio_duration > 0:
                        progress = min(99, int((current_time_sec / audio_duration) * 100))
                        
                        if progress > last_reported_progress and progress % 10 == 0:
                            last_reported_progress = progress
                            text = f"⏳ *ভিডিও তৈরি হচ্ছে...*\n\n{get_progress_bar(progress)} {progress}%\n\nদয়া করে অপেক্ষা করুন।"
                            await safe_edit_message(context, user_id, status_id, text)
                            await asyncio.sleep(0.3)
                except (ValueError, IndexError) as e:
                    logger.debug(f"Could not parse progress: {e}")
            
            elif 'time=' in line:
                time_match = re.search(r"time=(\d{2}:\d{2}:\d{2}\.\d{2})", line)
                if time_match:
                    current_time_str = time_match.group(1)
                    current_time_sec = parse_ffmpeg_time(current_time_str)
                    
                    if audio_duration > 0 and current_time_sec > 0:
                        progress = min(99, int((current_time_sec / audio_duration) * 100))
                        
                        if progress > last_reported_progress and progress % 10 == 0:
                            last_reported_progress = progress
                            text = f"⏳ *ভিডিও তৈরি হচ্ছে...*\n\n{get_progress_bar(progress)} {progress}%\n\nদয়া করে অপেক্ষা করুন।"
                            await safe_edit_message(context, user_id, status_id, text)
                            await asyncio.sleep(0.3)

        await process.wait()
        
        if process.returncode == 0:
            text = f"✅ *ভিডিও তৈরি সম্পন্ন!*\n\n{get_progress_bar(100)} 100%\n\nএখন আপনাকে ভিডিওটি পাঠানো হচ্ছে..."
            await safe_edit_message(context, user_id, status_id, text)
            
            with open(output_video, 'rb') as video_file:
                await context.bot.send_video(
                    chat_id=user_id,
                    video=video_file,
                    caption="✅ আপনার ভিডিও তৈরি সম্পন্ন হয়েছে!"
                )
            await reset_user(update, context, send_new_menu=True)
        else:
            stderr_output = (await process.stderr.read()).decode()
            logger.error(f"FFmpeg error (code {process.returncode}): {stderr_output}")
            raise Exception(f"FFmpeg failed with code {process.returncode}")

    except Exception as e:
        logger.error(f"Error creating video: {e}")
        await reset_user(update, context, send_new_menu=False)
        await context.bot.send_message(chat_id=user_id, text="❌ ভিডিও বানাতে একটি সমস্যা হয়েছে। আবার চেষ্টা করুন।", reply_markup=get_main_menu())


# --- Main Bot Execution ---

def main():
    """Main entry point for the bot."""
    if not TOKEN:
        logger.error("BOT_TOKEN not found! Please set the BOT_TOKEN environment variable.")
        return
    
    application = Application.builder().token(TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))
    
    media_filters = filters.AUDIO | filters.VOICE | filters.PHOTO | filters.Document.ALL
    application.add_handler(MessageHandler(media_filters, handle_media))
    
    logger.info("Bot is starting...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
