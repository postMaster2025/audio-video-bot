import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
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
        [InlineKeyboardButton("✅ মার্জ সম্পন্ন করুন", callback_data="done")],
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

# --- Command and Action Handlers ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /start command and returns user to the main menu."""
    user_id = update.effective_user.id
    
    # Reset user data
    if user_id in user_data:
        del user_data[user_id]
    
    welcome_text = """
🎵 *অডিও ভিডিও বট এ স্বাগতম!* 🎬

আমি যা করতে পারি:
━━━━━━━━━━━━━━━
🎵 একাধিক অডিও একসাথে জোড়া লাগাতে পারি
🎬 অডিও + ছবি দিয়ে ভিডিও বানাতে পারি

নিচের বাটন থেকে আপনার কাজ বেছে নিন:
"""
    
    if update.message:
        message = await update.message.reply_text(
            welcome_text,
            reply_markup=get_main_menu(),
            parse_mode='Markdown'
        )
        # Store message ID for later updates
        user_data[user_id] = {'main_message_id': message.message_id}
    elif update.callback_query:
        await update.callback_query.edit_message_text(
            welcome_text,
            reply_markup=get_main_menu(),
            parse_mode='Markdown'
        )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles all button clicks and routes them to the correct function."""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    action = query.data
    
    # Initialize user data if it doesn't exist
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
    
    user_data[user_id] = {
        'mode': 'merge',
        'audio_files': [],
        'audio_names': [],
        'main_message_id': update.callback_query.message.message_id,
        'user_messages': []
    }
    
    text = """
🎵 *অডিও মার্জ মোড চালু হয়েছে!*

━━━━━━━━━━━━━━━
📝 এখন যতগুলো ইচ্ছে অডিও/ভয়েস পাঠান
(Music অথবা File - দুইভাবেই পাঠাতে পারবেন)

✅ যোগ করা অডিও: 0টি

শেষ হলে "✅ মার্জ সম্পন্ন করুন" বাটন ক্লিক করুন
"""
    
    await update.callback_query.edit_message_text(
        text,
        reply_markup=get_done_button(),
        parse_mode='Markdown'
    )

async def add_more_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Allows adding more audio to a previously merged file."""
    user_id = update.effective_user.id
    
    if 'merged_file' not in user_data.get(user_id, {}):
         await update.callback_query.answer("❌ প্রথমে একটি অডিও মার্জ করুন!", show_alert=True)
         return

    user_data[user_id].update({
        'mode': 'add_more',
        'new_audio_files': [],
        'new_audio_names': [],
        'main_message_id': update.callback_query.message.message_id,
        'user_messages': []
    })
    
    text = """
➕ *আরো অডিও যোগ করুন!*

━━━━━━━━━━━━━━━
📝 নতুন অডিও/ভয়েস পাঠান
(পূর্বের মার্জ করা অডিওর সাথে যুক্ত হবে)

✅ নতুন অডিও: 0টি

শেষ হলে "✅ মার্জ সম্পন্ন করুন" বাটন ক্লিক করুন
"""
    
    await update.callback_query.edit_message_text(
        text,
        reply_markup=get_done_button(),
        parse_mode='Markdown'
    )

async def start_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Starts the video creation process."""
    user_id = update.effective_user.id
    
    user_data[user_id] = {
        'mode': 'video',
        'image': None,
        'image_name': None,
        'audio': None,
        'audio_name': None,
        'main_message_id': update.callback_query.message.message_id,
        'user_messages': []
    }
    
    text = """
🎬 *ভিডিও বানানোর মোড চালু হয়েছে!*

━━━━━━━━━━━━━━━
📸 প্রথমে একটা ছবি পাঠান

✅ ছবি: ❌
✅ অডিও: ❌
"""
    
    await update.callback_query.edit_message_text(
        text,
        reply_markup=get_cancel_button(),
        parse_mode='Markdown'
    )

async def show_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays the help message."""
    help_text = """
📖 *কীভাবে ব্যবহার করবেন:*

━━━━━━━━━━━━━━━
🎵 *অডিও মার্জ করতে:*
1. "অডিও মার্জ করুন" বাটনে ক্লিক করুন
2. যতগুলো ইচ্ছে অডিও/ভয়েস পাঠান
   (Music বা File - যেকোনোভাবে)
3. "মার্জ সম্পন্ন করুন" বাটনে ক্লিক করুন
4. মার্জের পর আরো অডিও যোগ করতে পারবেন!

🎬 *ভিডিও বানাতে:*
1. "ভিডিও বানান" বাটনে ক্লিক করুন
2. একটা ছবি পাঠান
3. একটা অডিও/ভয়েস পাঠান
4. আমি ভিডিও বানিয়ে দিবো!

━━━━━━━━━━━━━━━
💡 সব মেসেজ অটোমেটিক ডিলিট হয়ে যাবে
💡 শুধু ফাইনাল আউটপুট থাকবে
"""
    
    keyboard = [[InlineKeyboardButton("🔙 মূল মেনু", callback_data="cancel")]]
    
    await update.callback_query.edit_message_text(
        help_text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def cancel_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancels the current operation and cleans up files."""
    user_id = update.effective_user.id
    
    # Delete user's messages
    if user_id in user_data and 'user_messages' in user_data[user_id]:
        for msg_id in user_data[user_id]['user_messages']:
            try:
                await context.bot.delete_message(chat_id=user_id, message_id=msg_id)
            except Exception:
                pass
    
    # Clean up all temporary files associated with the user
    if user_id in user_data:
        files_to_clean = [
            user_data[user_id].get('audio_files', []),
            user_data[user_id].get('new_audio_files', []),
            [user_data[user_id].get('merged_file')],
            [user_data[user_id].get('image')],
            [user_data[user_id].get('audio')]
        ]
        for file_list in files_to_clean:
            for file_path in file_list:
                if file_path and os.path.exists(file_path):
                    os.remove(file_path)
    
    await start(update, context)

# --- Media Handlers ---

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles files sent as documents."""
    user_id = update.effective_user.id
    
    if user_id not in user_data: user_data[user_id] = {}
    if 'user_messages' not in user_data[user_id]: user_data[user_id]['user_messages'] = []
    user_data[user_id]['user_messages'].append(update.message.message_id)
    
    document = update.message.document
    mime_type = document.mime_type or ""
    file_name = document.file_name or ""
    
    audio_extensions = ['.mp3', '.wav', '.ogg', '.m4a', '.aac', '.flac', '.wma']
    audio_mimes = ['audio/', 'application/ogg']
    
    is_audio = any(file_name.lower().endswith(ext) for ext in audio_extensions) or \
               any(mime in mime_type for mime in audio_mimes)
    
    if not is_audio:
        msg = await update.message.reply_text("❌ শুধুমাত্র অডিও ফাইল পাঠান!")
        user_data[user_id]['user_messages'].append(msg.message_id)
        return

    mode = user_data.get(user_id, {}).get('mode')
    if not mode:
        msg = await update.message.reply_text("প্রথমে মূল মেনু থেকে একটা অপশন বেছে নিন। /start চাপুন।")
        user_data[user_id]['user_messages'].append(msg.message_id)
        return
    
    if mode == 'merge': await handle_merge_document(update, context)
    elif mode == 'add_more': await handle_add_more_document(update, context)
    elif mode == 'video': await handle_video_document(update, context)

async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles audio files."""
    user_id = update.effective_user.id

    if user_id not in user_data: user_data[user_id] = {}
    if 'user_messages' not in user_data[user_id]: user_data[user_id]['user_messages'] = []
    user_data[user_id]['user_messages'].append(update.message.message_id)
    
    mode = user_data.get(user_id, {}).get('mode')
    if not mode:
        msg = await update.message.reply_text("প্রথমে মূল মেনু থেকে একটা অপশন বেছে নিন। /start চাপুন।")
        user_data[user_id]['user_messages'].append(msg.message_id)
        return
        
    if mode == 'merge': await handle_merge_audio(update, context)
    elif mode == 'add_more': await handle_add_more_audio(update, context)
    elif mode == 'video': await handle_video_audio(update, context)

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles voice messages."""
    user_id = update.effective_user.id
    
    if user_id not in user_data: user_data[user_id] = {}
    if 'user_messages' not in user_data[user_id]: user_data[user_id]['user_messages'] = []
    user_data[user_id]['user_messages'].append(update.message.message_id)
    
    mode = user_data.get(user_id, {}).get('mode')
    if not mode:
        msg = await update.message.reply_text("প্রথমে মূল মেনু থেকে একটা অপশন বেছে নিন। /start চাপুন।")
        user_data[user_id]['user_messages'].append(msg.message_id)
        return
    
    if mode == 'merge': await handle_merge_voice(update, context)
    elif mode == 'add_more': await handle_add_more_voice(update, context)
    elif mode == 'video': await handle_video_voice(update, context)

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles photos, specifically for video creation."""
    user_id = update.effective_user.id
    
    if user_id not in user_data: user_data[user_id] = {}
    if 'user_messages' not in user_data[user_id]: user_data[user_id]['user_messages'] = []
    user_data[user_id]['user_messages'].append(update.message.message_id)
    
    if user_data.get(user_id, {}).get('mode') != 'video':
        msg = await update.message.reply_text("প্রথমে 'ভিডিও বানান' বাটনে ক্লিক করুন। /start চাপুন।")
        user_data[user_id]['user_messages'].append(msg.message_id)
        return
    
    try:
        photo_file = await update.message.photo[-1].get_file()
        photo_path = f"image_{user_id}.jpg"
        await photo_file.download_to_drive(photo_path)
        
        user_data[user_id]['image'] = photo_path
        user_data[user_id]['image_name'] = "ছবি.jpg"
        
        text = f"""
🎬 *ভিডিও বানানোর মোড চালু হয়েছে!*

━━━━━━━━━━━━━━━
✅ ছবি: {user_data[user_id]['image_name']}
❌ অডিও: এখনো পাঠাননি

এখন একটা অডিও বা ভয়েস পাঠান
"""
        await context.bot.edit_message_text(
            chat_id=user_id,
            message_id=user_data[user_id]['main_message_id'],
            text=text,
            reply_markup=get_cancel_button(),
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Error handling photo: {e}")

# --- File Processing Logic ---

async def process_incoming_audio(update, context, audio_type):
    """Generic function to process and save audio/voice/document files."""
    user_id = update.effective_user.id
    mode = user_data[user_id]['mode']
    is_add_more = (mode == 'add_more')
    
    file_list_key = 'new_audio_files' if is_add_more else 'audio_files'
    name_list_key = 'new_audio_names' if is_add_more else 'audio_names'
    
    file_prefix = "add_" if is_add_more else ""
    
    try:
        if audio_type == 'audio':
            file_obj = update.message.audio
            file_ext = ".mp3"
            default_name = f"অডিও_{len(user_data[user_id][file_list_key]) + 1}{file_ext}"
            file_name = file_obj.file_name or default_name
        elif audio_type == 'voice':
            file_obj = update.message.voice
            file_ext = ".ogg"
            file_name = f"ভয়েস_{len(user_data[user_id][file_list_key]) + 1}{file_ext}"
        elif audio_type == 'document':
            file_obj = update.message.document
            file_ext = ""
            default_name = f"audio_{len(user_data[user_id][file_list_key]) + 1}"
            file_name = file_obj.file_name or default_name
        
        file_handle = await file_obj.get_file()
        file_path = f"{file_prefix}{audio_type}_{user_id}_{len(user_data[user_id][file_list_key])}{file_ext}"
        await file_handle.download_to_drive(file_path)
        
        user_data[user_id][file_list_key].append(file_path)
        user_data[user_id][name_list_key].append(file_name)
        
        audio_count = len(user_data[user_id][file_list_key])
        audio_list = "\n".join([f"  {i+1}. {name}" for i, name in enumerate(user_data[user_id][name_list_key])])
        
        if is_add_more:
            text = f"""
➕ *আরো অডিও যোগ করুন!*
━━━━━━━━━━━━━━━
✅ নতুন অডিও: {audio_count}টি
{audio_list}
আরো পাঠান অথবা "✅ মার্জ সম্পন্ন করুন" বাটন ক্লিক করুন
"""
        else:
            text = f"""
🎵 *অডিও মার্জ মোড চালু হয়েছে!*
━━━━━━━━━━━━━━━
✅ যোগ করা অডিও: {audio_count}টি
{audio_list}
আরো অডিও পাঠান অথবা "✅ মার্জ সম্পন্ন করুন" বাটন ক্লিক করুন
"""
        await context.bot.edit_message_text(
            chat_id=user_id,
            message_id=user_data[user_id]['main_message_id'],
            text=text,
            reply_markup=get_done_button(),
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Error processing incoming {audio_type}: {e}")

# Simplified handlers calling the generic processor
async def handle_merge_audio(update, context): await process_incoming_audio(update, context, 'audio')
async def handle_merge_document(update, context): await process_incoming_audio(update, context, 'document')
async def handle_merge_voice(update, context): await process_incoming_audio(update, context, 'voice')
async def handle_add_more_audio(update, context): await process_incoming_audio(update, context, 'audio')
async def handle_add_more_document(update, context): await process_incoming_audio(update, context, 'document')
async def handle_add_more_voice(update, context): await process_incoming_audio(update, context, 'voice')

async def process_video_audio(update: Update, context: ContextTypes.DEFAULT_TYPE, audio_type: str):
    """Generic function to handle audio for video creation."""
    user_id = update.effective_user.id
    if user_data.get(user_id, {}).get('image') is None:
        return

    try:
        if audio_type == 'audio':
            file_obj = update.message.audio
            file_ext = ".mp3"
            default_name = "অডিও.mp3"
            file_name = file_obj.file_name or default_name
        elif audio_type == 'voice':
            file_obj = update.message.voice
            file_ext = ".ogg"
            file_name = "ভয়েস.ogg"
        elif audio_type == 'document':
            file_obj = update.message.document
            file_ext = ""
            file_name = file_obj.file_name or "audio.mp3"

        file_handle = await file_obj.get_file()
        audio_path = f"video_{audio_type}_{user_id}{file_ext}"
        await file_handle.download_to_drive(audio_path)
        
        user_data[user_id]['audio'] = audio_path
        user_data[user_id]['audio_name'] = file_name
        
        await create_video(update, context)
    except Exception as e:
        logger.error(f"Error handling video {audio_type}: {e}")

# Simplified handlers for video audio
async def handle_video_audio(update, context): await process_video_audio(update, context, 'audio')
async def handle_video_document(update, context): await process_video_audio(update, context, 'document')
async def handle_video_voice(update, context): await process_video_audio(update, context, 'voice')

# --- Core Logic: Merge and Create ---

def get_progress_bar(percentage):
    """Generates a simple text-based progress bar."""
    filled = int(percentage / 10)
    empty = 10 - filled
    return "▓" * filled + "░" * empty

async def merge_audios(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Main function to merge audio files."""
    user_id = update.effective_user.id
    mode = user_data[user_id]['mode']
    
    if mode == 'add_more':
        if len(user_data[user_id].get('new_audio_files', [])) < 1:
            await update.callback_query.answer("❌ কমপক্ষে ১টা নতুন অডিও পাঠান!", show_alert=True)
            return
        await merge_with_previous(update, context)
        return
    
    if len(user_data[user_id].get('audio_files', [])) < 2:
        await update.callback_query.answer("❌ কমপক্ষে ২টা অডিও পাঠান!", show_alert=True)
        return
    
    await update.callback_query.answer()
    main_msg_id = user_data[user_id]['main_message_id']
    
    try:
        await context.bot.edit_message_text(
            chat_id=user_id, message_id=main_msg_id,
            text=f"⏳ *অডিও মার্জ করা হচ্ছে...*\n\n{get_progress_bar(10)} 10%\n\n📂 অডিও ফাইল লোড করা হচ্ছে...",
            parse_mode='Markdown'
        )
        
        combined = AudioSegment.empty()
        audio_files = user_data[user_id]['audio_files']
        total_files = len(audio_files)
        
        for idx, audio_path in enumerate(audio_files):
            audio = AudioSegment.from_file(audio_path)
            combined += audio
            progress = 30 + int((idx + 1) / total_files * 40)
            await context.bot.edit_message_text(
                chat_id=user_id, message_id=main_msg_id,
                text=f"⏳ *অডিও মার্জ করা হচ্ছে...*\n\n{get_progress_bar(progress)} {progress}%\n\n🔗 অডিও একত্রিত করা হচ্ছে... ({idx + 1}/{total_files})",
                parse_mode='Markdown'
            )
        
        await context.bot.edit_message_text(
            chat_id=user_id, message_id=main_msg_id,
            text=f"⏳ *অডিও মার্জ করা হচ্ছে...*\n\n{get_progress_bar(80)} 80%\n\n💾 ফাইল সংরক্ষণ করা হচ্ছে...",
            parse_mode='Markdown'
        )
        
        output_path = f"merged_{user_id}.mp3"
        combined.export(output_path, format="mp3")
        
        await context.bot.edit_message_text(
            chat_id=user_id, message_id=main_msg_id,
            text=f"⏳ *অডিও মার্জ করা হচ্ছে...*\n\n{get_progress_bar(100)} 100%\n\n✅ সম্পন্ন হয়েছে!",
            parse_mode='Markdown'
        )
        
        # Cleanup messages
        for msg_id in user_data[user_id]['user_messages']:
            try: await context.bot.delete_message(chat_id=user_id, message_id=msg_id)
            except Exception: pass
        try: await context.bot.delete_message(chat_id=user_id, message_id=main_msg_id)
        except Exception: pass
        
        # Send result
        with open(output_path, 'rb') as audio_file:
            await context.bot.send_audio(
                chat_id=user_id, audio=audio_file, title="Merged Audio",
                caption=f"✅ {total_files} টি অডিও একসাথে জোড়া লাগানো হয়েছে!\n\nআরো অডিও যোগ করতে চান?"
            )
        
        options_msg = await context.bot.send_message(
            chat_id=user_id, text="এখন কি করবেন?", reply_markup=get_after_merge_options()
        )
        
        # Cleanup files and update user data for next step
        for audio_path in audio_files:
            if os.path.exists(audio_path): os.remove(audio_path)
        
        user_data[user_id] = {
            'main_message_id': options_msg.message_id,
            'merged_file': output_path
        }
        
    except Exception as e:
        logger.error(f"Error merging audio: {e}")
        await context.bot.send_message(chat_id=user_id, text="❌ অডিও মার্জ করতে সমস্যা হয়েছে। আবার চেষ্টা করুন।")

async def merge_with_previous(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Merges new audio files with a previously merged one."""
    user_id = update.effective_user.id
    await update.callback_query.answer()
    main_msg_id = user_data[user_id]['main_message_id']
    
    try:
        await context.bot.edit_message_text(
            chat_id=user_id, message_id=main_msg_id,
            text=f"⏳ *অডিও মার্জ করা হচ্ছে...*\n\n{get_progress_bar(10)} 10%\n\n📂 পূর্বের ফাইল লোড করা হচ্ছে...",
            parse_mode='Markdown'
        )
        
        combined = AudioSegment.from_file(user_data[user_id]['merged_file'])
        new_audio_files = user_data[user_id]['new_audio_files']
        total_files = len(new_audio_files)

        for idx, audio_path in enumerate(new_audio_files):
            audio = AudioSegment.from_file(audio_path)
            combined += audio
            progress = 30 + int((idx + 1) / total_files * 40)
            await context.bot.edit_message_text(
                chat_id=user_id, message_id=main_msg_id,
                text=f"⏳ *অডিও মার্জ করা হচ্ছে...*\n\n{get_progress_bar(progress)} {progress}%\n\n🔗 নতুন অডিও যোগ করা হচ্ছে... ({idx + 1}/{total_files})",
                parse_mode='Markdown'
            )
        
        await context.bot.edit_message_text(
            chat_id=user_id, message_id=main_msg_id,
            text=f"⏳ *অডিও মার্জ করা হচ্ছে...*\n\n{get_progress_bar(80)} 80%\n\n💾 ফাইল সংরক্ষণ করা হচ্ছে...",
            parse_mode='Markdown'
        )
        
        output_path = f"merged_{user_id}_new.mp3"
        combined.export(output_path, format="mp3")
        
        await context.bot.edit_message_text(
            chat_id=user_id, message_id=main_msg_id,
            text=f"⏳ *অডিও মার্জ করা হচ্ছে...*\n\n{get_progress_bar(100)} 100%\n\n✅ সম্পন্ন হয়েছে!",
            parse_mode='Markdown'
        )
        
        # Cleanup messages
        for msg_id in user_data[user_id].get('user_messages', []):
            try: await context.bot.delete_message(chat_id=user_id, message_id=msg_id)
            except Exception: pass
        try: await context.bot.delete_message(chat_id=user_id, message_id=main_msg_id)
        except Exception: pass
        
        # Send result
        with open(output_path, 'rb') as audio_file:
            await context.bot.send_audio(
                chat_id=user_id, audio=audio_file, title="Updated Merged Audio",
                caption=f"✅ আপডেট সম্পন্ন! {total_files} টি নতুন অডিও যোগ হয়েছে!"
            )
        
        options_msg = await context.bot.send_message(
            chat_id=user_id, text="এখন কি করবেন?", reply_markup=get_after_merge_options()
        )
        
        # Cleanup old files
        for audio_path in new_audio_files:
            if os.path.exists(audio_path): os.remove(audio_path)
        if os.path.exists(user_data[user_id]['merged_file']):
            os.remove(user_data[user_id]['merged_file'])
        
        # Update user data for next step
        user_data[user_id] = {
            'main_message_id': options_msg.message_id,
            'merged_file': output_path
        }
        
    except Exception as e:
        logger.error(f"Error merging with previous: {e}")
        await context.bot.send_message(chat_id=user_id, text="❌ অডিও মার্জ করতে সমস্যা হয়েছে। আবার চেষ্টা করুন।")

async def create_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Creates a video from an image and an audio file using FFmpeg."""
    user_id = update.effective_user.id
    main_msg_id = user_data[user_id]['main_message_id']
    
    await context.bot.edit_message_text(
        chat_id=user_id, message_id=main_msg_id,
        text="⏳ ভিডিও বানানো হচ্ছে... অপেক্ষা করুন...",
        parse_mode='Markdown'
    )
    
    try:
        image_path = user_data[user_id]['image']
        audio_path = user_data[user_id]['audio']
        output_video = f"video_{user_id}.mp4"
        
        audio_segment = AudioSegment.from_file(audio_path)
        duration = len(audio_segment) / 1000.0
        
        cmd = [
            'ffmpeg', '-loop', '1', '-i', image_path, '-i', audio_path,
            '-c:v', 'libx264', '-tune', 'stillimage', '-c:a', 'aac',
            '-b:a', '192k', '-pix_fmt', 'yuv420p', '-shortest', '-t', str(duration),
            '-y', output_video
        ]
        
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        
        # Cleanup messages
        for msg_id in user_data[user_id]['user_messages']:
            try:
                await context.bot.delete_message(chat_id=user_id, message_id=msg_id)
            except Exception:
                pass
        try:
            await context.bot.delete_message(chat_id=user_id, message_id=main_msg_id)
        except Exception:
            pass
        
        # Send video
        with open(output_video, 'rb') as video_file:
            await context.bot.send_video(
                chat_id=user_id,
                video=video_file,
                caption="✅ ভিডিও তৈরি সম্পন্ন হয়েছে!"
            )
        
        # Cleanup temporary files
        if os.path.exists(image_path): os.remove(image_path)
        if os.path.exists(audio_path): os.remove(audio_path)
        if os.path.exists(output_video): os.remove(output_video)
        
        # Reset to main menu
        welcome_text = "আপনার কাজ সম্পন্ন হয়েছে! নতুন করে শুরু করতে পারেন।"
        menu_msg = await context.bot.send_message(
            chat_id=user_id, text=welcome_text,
            reply_markup=get_main_menu(), parse_mode='Markdown'
        )
        user_data[user_id] = {'main_message_id': menu_msg.message_id}
        
    except subprocess.CalledProcessError as e:
        logger.error(f"Error creating video with FFmpeg: {e.stderr}")
        await context.bot.send_message(chat_id=user_id, text="❌ ভিডিও বানাতে সমস্যা হয়েছে। অডিও বা ছবির ফরম্যাট চেক করুন।")
    except Exception as e:
        logger.error(f"Error creating video: {e}")
        await context.bot.send_message(chat_id=user_id, text="❌ ভিডিও বানাতে একটি অপ্রত্যাশিত সমস্যা হয়েছে। আবার চেষ্টা করুন।")


# --- Main Bot Execution ---

def main():
    """Starts the bot."""
    if not TOKEN:
        logger.error("BOT_TOKEN not found in environment variables!")
        return
    
    application = Application.builder().token(TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.AUDIO, handle_audio))
    application.add_handler(MessageHandler(filters.VOICE, handle_voice))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    
    logger.info("Bot is starting...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()