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

# User data storage
user_data = {}

# Main menu keyboard
def get_main_menu():
    keyboard = [
        [InlineKeyboardButton("🎵 অডিও মার্জ করুন", callback_data="merge")],
        [InlineKeyboardButton("🎬 ভিডিও বানান", callback_data="video")],
        [InlineKeyboardButton("❓ সাহায্য", callback_data="help")]
    ]
    return InlineKeyboardMarkup(keyboard)

# Cancel button
def get_cancel_button():
    keyboard = [[InlineKeyboardButton("❌ বাতিল করুন", callback_data="cancel")]]
    return InlineKeyboardMarkup(keyboard)

# Done button (for merge)
def get_done_button():
    keyboard = [
        [InlineKeyboardButton("✅ মার্জ সম্পন্ন করুন", callback_data="done")],
        [InlineKeyboardButton("❌ বাতিল করুন", callback_data="cancel")]
    ]
    return InlineKeyboardMarkup(keyboard)

# After merge options
def get_after_merge_options():
    keyboard = [
        [InlineKeyboardButton("➕ আরো অডিও যোগ করুন", callback_data="add_more")],
        [InlineKeyboardButton("🔄 নতুন মার্জ শুরু করুন", callback_data="merge")],
        [InlineKeyboardButton("🏠 মূল মেনু", callback_data="cancel")]
    ]
    return InlineKeyboardMarkup(keyboard)

# Start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    else:
        await update.callback_query.edit_message_text(
            welcome_text,
            reply_markup=get_main_menu(),
            parse_mode='Markdown'
        )

# Handle button clicks
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    action = query.data
    
    # Initialize user data if not exists
    if user_id not in user_data:
        user_data[user_id] = {}
    
    if action == "merge":
        await start_merge(update, context)
    elif action == "video":
        await start_video(update, context)
    elif action == "help":
        await show_help(update, context)
    elif action == "cancel":
        await cancel_action(update, context)
    elif action == "done":
        await merge_audios(update, context)
    elif action == "add_more":
        await add_more_audio(update, context)

# Start merge process
async def start_merge(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

# Add more audio to existing merge
async def add_more_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Keep the merged file reference if exists
    if 'merged_file' not in user_data[user_id]:
        user_data[user_id]['merged_file'] = None
    
    user_data[user_id]['mode'] = 'add_more'
    user_data[user_id]['new_audio_files'] = []
    user_data[user_id]['new_audio_names'] = []
    user_data[user_id]['main_message_id'] = update.callback_query.message.message_id
    
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

# Start video process
async def start_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

# Show help
async def show_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

# Cancel action
async def cancel_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Delete user's messages
    if user_id in user_data and 'user_messages' in user_data[user_id]:
        for msg_id in user_data[user_id]['user_messages']:
            try:
                await context.bot.delete_message(chat_id=user_id, message_id=msg_id)
            except:
                pass
    
    # Clean up files
    if user_id in user_data:
        if 'audio_files' in user_data[user_id]:
            for file_path in user_data[user_id]['audio_files']:
                if os.path.exists(file_path):
                    os.remove(file_path)
        if 'new_audio_files' in user_data[user_id]:
            for file_path in user_data[user_id]['new_audio_files']:
                if os.path.exists(file_path):
                    os.remove(file_path)
        if 'merged_file' in user_data[user_id] and user_data[user_id]['merged_file']:
            if os.path.exists(user_data[user_id]['merged_file']):
                os.remove(user_data[user_id]['merged_file'])
        if 'image' in user_data[user_id] and user_data[user_id]['image']:
            if os.path.exists(user_data[user_id]['image']):
                os.remove(user_data[user_id]['image'])
        if 'audio' in user_data[user_id] and user_data[user_id]['audio']:
            if os.path.exists(user_data[user_id]['audio']):
                os.remove(user_data[user_id]['audio'])
    
    # Return to main menu
    await start(update, context)

# Handle document files (audio sent as file)
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Store user message ID for later deletion
    if user_id not in user_data:
        user_data[user_id] = {'user_messages': []}
    
    if 'user_messages' not in user_data[user_id]:
        user_data[user_id]['user_messages'] = []
    
    user_data[user_id]['user_messages'].append(update.message.message_id)
    
    # Check if it's an audio file
    document = update.message.document
    mime_type = document.mime_type if document.mime_type else ""
    file_name = document.file_name if document.file_name else ""
    
    # Check if it's audio format
    audio_extensions = ['.mp3', '.wav', '.ogg', '.m4a', '.aac', '.flac', '.wma']
    audio_mimes = ['audio/', 'application/ogg']
    
    is_audio = any(file_name.lower().endswith(ext) for ext in audio_extensions) or \
               any(mime in mime_type for mime in audio_mimes)
    
    if not is_audio:
        msg = await update.message.reply_text("❌ শুধুমাত্র অডিও ফাইল পাঠান!")
        user_data[user_id]['user_messages'].append(msg.message_id)
        return
    
    # Check mode
    if user_id not in user_data or 'mode' not in user_data[user_id]:
        msg = await update.message.reply_text("প্রথমে মূল মেনু থেকে একটা অপশন বেছে নিন। /start চাপুন।")
        user_data[user_id]['user_messages'].append(msg.message_id)
        return
    
    mode = user_data[user_id]['mode']
    
    if mode == 'merge':
        await handle_merge_document(update, context)
    elif mode == 'add_more':
        await handle_add_more_document(update, context)
    elif mode == 'video':
        await handle_video_document(update, context)

# Handle audio files
async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Store user message ID for later deletion
    if user_id not in user_data:
        user_data[user_id] = {'user_messages': []}
    
    if 'user_messages' not in user_data[user_id]:
        user_data[user_id]['user_messages'] = []
    
    user_data[user_id]['user_messages'].append(update.message.message_id)
    
    # Check mode
    if user_id not in user_data or 'mode' not in user_data[user_id]:
        msg = await update.message.reply_text("প্রথমে মূল মেনু থেকে একটা অপশন বেছে নিন। /start চাপুন।")
        user_data[user_id]['user_messages'].append(msg.message_id)
        return
    
    mode = user_data[user_id]['mode']
    
    if mode == 'merge':
        await handle_merge_audio(update, context)
    elif mode == 'add_more':
        await handle_add_more_audio(update, context)
    elif mode == 'video':
        await handle_video_audio(update, context)

# Handle voice messages
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Store user message ID
    if user_id not in user_data:
        user_data[user_id] = {'user_messages': []}
    
    if 'user_messages' not in user_data[user_id]:
        user_data[user_id]['user_messages'] = []
    
    user_data[user_id]['user_messages'].append(update.message.message_id)
    
    # Check mode
    if user_id not in user_data or 'mode' not in user_data[user_id]:
        msg = await update.message.reply_text("প্রথমে মূল মেনু থেকে একটা অপশন বেছে নিন। /start চাপুন।")
        user_data[user_id]['user_messages'].append(msg.message_id)
        return
    
    mode = user_data[user_id]['mode']
    
    if mode == 'merge':
        await handle_merge_voice(update, context)
    elif mode == 'add_more':
        await handle_add_more_voice(update, context)
    elif mode == 'video':
        await handle_video_voice(update, context)

# Handle photo
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Store user message ID
    if user_id not in user_data:
        user_data[user_id] = {'user_messages': []}
    
    if 'user_messages' not in user_data[user_id]:
        user_data[user_id]['user_messages'] = []
    
    user_data[user_id]['user_messages'].append(update.message.message_id)
    
    # Check mode
    if user_id not in user_data or 'mode' not in user_data[user_id] or user_data[user_id]['mode'] != 'video':
        msg = await update.message.reply_text("প্রথমে 'ভিডিও বানান' বাটনে ক্লিক করুন। /start চাপুন।")
        user_data[user_id]['user_messages'].append(msg.message_id)
        return
    
    try:
        # Download photo
        photo_file = await update.message.photo[-1].get_file()
        photo_path = f"image_{user_id}.jpg"
        await photo_file.download_to_drive(photo_path)
        
        user_data[user_id]['image'] = photo_path
        user_data[user_id]['image_name'] = "ছবি.jpg"
        
        # Update main message
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
        # Handle merge audio
async def handle_merge_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    try:
        # Download audio
        audio_file = await update.message.audio.get_file()
        audio_path = f"audio_{user_id}_{len(user_data[user_id]['audio_files'])}.mp3"
        await audio_file.download_to_drive(audio_path)
        
        # Get audio name
        audio_name = update.message.audio.file_name or f"অডিও_{len(user_data[user_id]['audio_files']) + 1}.mp3"
        
        user_data[user_id]['audio_files'].append(audio_path)
        user_data[user_id]['audio_names'].append(audio_name)
        
        # Update main message
        audio_list = "\n".join([f"  {i+1}. {name}" for i, name in enumerate(user_data[user_id]['audio_names'])])
        
        text = f"""
🎵 *অডিও মার্জ মোড চালু হয়েছে!*

━━━━━━━━━━━━━━━
✅ যোগ করা অডিও: {len(user_data[user_id]['audio_files'])}টি

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
        logger.error(f"Error handling audio: {e}")

# Handle merge document (file)
async def handle_merge_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    try:
        # Download document
        doc_file = await update.message.document.get_file()
        file_name = update.message.document.file_name or f"audio_{len(user_data[user_id]['audio_files'])}.mp3"
        audio_path = f"doc_{user_id}_{len(user_data[user_id]['audio_files'])}_{file_name}"
        await doc_file.download_to_drive(audio_path)
        
        user_data[user_id]['audio_files'].append(audio_path)
        user_data[user_id]['audio_names'].append(file_name)
        
        # Update main message
        audio_list = "\n".join([f"  {i+1}. {name}" for i, name in enumerate(user_data[user_id]['audio_names'])])
        
        text = f"""
🎵 *অডিও মার্জ মোড চালু হয়েছে!*

━━━━━━━━━━━━━━━
✅ যোগ করা অডিও: {len(user_data[user_id]['audio_files'])}টি

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
        logger.error(f"Error handling document: {e}")

# Handle merge voice
async def handle_merge_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    try:
        # Download voice
        voice_file = await update.message.voice.get_file()
        voice_path = f"voice_{user_id}_{len(user_data[user_id]['audio_files'])}.ogg"
        await voice_file.download_to_drive(voice_path)
        
        voice_name = f"ভয়েস_{len(user_data[user_id]['audio_files']) + 1}.ogg"
        
        user_data[user_id]['audio_files'].append(voice_path)
        user_data[user_id]['audio_names'].append(voice_name)
        
        # Update main message
        audio_list = "\n".join([f"  {i+1}. {name}" for i, name in enumerate(user_data[user_id]['audio_names'])])
        
        text = f"""
🎵 *অডিও মার্জ মোড চালু হয়েছে!*

━━━━━━━━━━━━━━━
✅ যোগ করা অডিও: {len(user_data[user_id]['audio_files'])}টি

{audio_list}

আরো অডিও/ভয়েস পাঠান অথবা "✅ মার্জ সম্পন্ন করুন" বাটন ক্লিক করুন
"""
        
        await context.bot.edit_message_text(
            chat_id=user_id,
            message_id=user_data[user_id]['main_message_id'],
            text=text,
            reply_markup=get_done_button(),
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"Error handling voice: {e}")

# Handle add more audio
async def handle_add_more_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    try:
        # Download audio
        audio_file = await update.message.audio.get_file()
        audio_path = f"add_audio_{user_id}_{len(user_data[user_id]['new_audio_files'])}.mp3"
        await audio_file.download_to_drive(audio_path)
        
        audio_name = update.message.audio.file_name or f"অডিও_{len(user_data[user_id]['new_audio_files']) + 1}.mp3"
        
        user_data[user_id]['new_audio_files'].append(audio_path)
        user_data[user_id]['new_audio_names'].append(audio_name)
        
        # Update main message
        audio_list = "\n".join([f"  {i+1}. {name}" for i, name in enumerate(user_data[user_id]['new_audio_names'])])
        
        text = f"""
➕ *আরো অডিও যোগ করুন!*

━━━━━━━━━━━━━━━
✅ নতুন অডিও: {len(user_data[user_id]['new_audio_files'])}টি

{audio_list}

আরো পাঠান অথবা "✅ মার্জ সম্পন্ন করুন" বাটন ক্লিক করুন
"""
        
        await context.bot.edit_message_text(
            chat_id=user_id,
            message_id=user_data[user_id]['main_message_id'],
            text=text,
            reply_markup=get_done_button(),
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"Error handling add more audio: {e}")

# Handle add more document
async def handle_add_more_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    try:
        # Download document
        doc_file = await update.message.document.get_file()
        file_name = update.message.document.file_name or f"audio_{len(user_data[user_id]['new_audio_files'])}.mp3"
        audio_path = f"add_doc_{user_id}_{len(user_data[user_id]['new_audio_files'])}_{file_name}"
        await doc_file.download_to_drive(audio_path)
        
        user_data[user_id]['new_audio_files'].append(audio_path)
        user_data[user_id]['new_audio_names'].append(file_name)
        
        # Update main message
        audio_list = "\n".join([f"  {i+1}. {name}" for i, name in enumerate(user_data[user_id]['new_audio_names'])])
        
        text = f"""
➕ *আরো অডিও যোগ করুন!*

━━━━━━━━━━━━━━━
✅ নতুন অডিও: {len(user_data[user_id]['new_audio_files'])}টি

{audio_list}

আরো পাঠান অথবা "✅ মার্জ সম্পন্ন করুন" বাটন ক্লিক করুন
"""
        
        await context.bot.edit_message_text(
            chat_id=user_id,
            message_id=user_data[user_id]['main_message_id'],
            text=text,
            reply_markup=get_done_button(),
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"Error handling add more document: {e}")

# Handle add more voice
async def handle_add_more_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    try:
        # Download voice
        voice_file = await update.message.voice.get_file()
        voice_path = f"add_voice_{user_id}_{len(user_data[user_id]['new_audio_files'])}.ogg"
        await voice_file.download_to_drive(voice_path)
        
        voice_name = f"ভয়েস_{len(user_data[user_id]['new_audio_files']) + 1}.ogg"
        
        user_data[user_id]['new_audio_files'].append(voice_path)
        user_data[user_id]['new_audio_names'].append(voice_name)
        
        # Update main message
        audio_list = "\n".join([f"  {i+1}. {name}" for i, name in enumerate(user_data[user_id]['new_audio_names'])])
        
        text = f"""
➕ *আরো অডিও যোগ করুন!*

━━━━━━━━━━━━━━━
✅ নতুন অডিও: {len(user_data[user_id]['new_audio_files'])}টি

{audio_list}

আরো পাঠান অথবা "✅ মার্জ সম্পন্ন করুন" বাটন ক্লিক করুন
"""
        
        await context.bot.edit_message_text(
            chat_id=user_id,
            message_id=user_data[user_id]['main_message_id'],
            text=text,
            reply_markup=get_done_button(),
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"Error handling add more voice: {e}")

# Handle video audio
async def handle_video_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_data[user_id]['image'] is None:
        return
    
    try:
        # Download audio
        audio_file = await update.message.audio.get_file()
        audio_path = f"video_audio_{user_id}.mp3"
        await audio_file.download_to_drive(audio_path)
        
        audio_name = update.message.audio.file_name or "অডিও.mp3"
        
        user_data[user_id]['audio'] = audio_path
        user_data[user_id]['audio_name'] = audio_name
        
        # Create video
        await create_video(update, context)
        
    except Exception as e:
        logger.error(f"Error handling video audio: {e}")

# Handle video document
async def handle_video_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_data[user_id]['image'] is None:
        return
    
    try:
        # Download document
        doc_file = await update.message.document.get_file()
        file_name = update.message.document.file_name or "audio.mp3"
        audio_path = f"video_doc_{user_id}_{file_name}"
        await doc_file.download_to_drive(audio_path)
        
        user_data[user_id]['audio'] = audio_path
        user_data[user_id]['audio_name'] = file_name
        
        # Create video
        await create_video(update, context)
        
    except Exception as e:
        logger.error(f"Error handling video document: {e}")

# Handle video voice
async def handle_video_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_data[user_id]['image'] is None:
        return
    
    try:
        # Download voice
        voice_file = await update.message.voice.get_file()
        voice_path = f"video_voice_{user_id}.ogg"
        await voice_file.download_to_drive(voice_path)
        
        user_data[user_id]['audio'] = voice_path
        user_data[user_id]['audio_name'] = "ভয়েস.ogg"
        
        # Create video
        await create_video(update, context)
        
    except Exception as e:
        logger.error(f"Error handling video voice: {e}")

# Progress bar generator
def get_progress_bar(percentage):
    filled = int(percentage / 10)
    empty = 10 - filled
    return "▓" * filled + "░" * empty

# Merge audios
async def merge_audios(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    mode = user_data[user_id]['mode']
    
    # Check for add_more mode
    if mode == 'add_more':
        if len(user_data[user_id]['new_audio_files']) < 1:
            await update.callback_query.answer("❌ কমপক্ষে ১টা নতুন অডিও পাঠান!", show_alert=True)
            return
        
        # Merge with previous file
        await merge_with_previous(update, context)
        return
    
    # Regular merge mode
    if len(user_data[user_id]['audio_files']) < 2:
        await update.callback_query.answer("❌ কমপক্ষে ২টা অডিও পাঠান!", show_alert=True)
        return
    
    await update.callback_query.answer()
    
    main_msg_id = user_data[user_id]['main_message_id']
    
    try:
        # Step 1: Loading audio files (0-30%)
        await context.bot.edit_message_text(
            chat_id=user_id,
            message_id=main_msg_id,
            text=f"⏳ *অডিও মার্জ করা হচ্ছে...*\n\n{get_progress_bar(10)} 10%\n\n📂 অডিও ফাইল লোড করা হচ্ছে...",
            parse_mode='Markdown'
        )
        
        # Merge all audio files with progress
        combined = AudioSegment.empty()
        total_files = len(user_data[user_id]['audio_files'])
        
        for idx, audio_path in enumerate(user_data[user_id]['audio_files']):
            audio = AudioSegment.from_file(audio_path)
            combined += audio
            
            # Update progress (30% to 70%)
            progress = 30 + int((idx + 1) / total_files * 40)
            await context.bot.edit_message_text(
                chat_id=user_id,
                message_id=main_msg_id,
                text=f"⏳ *অডিও মার্জ করা হচ্ছে...*\n\n{get_progress_bar(progress)} {progress}%\n\n🔗 অডিও একত্রিত করা হচ্ছে... ({idx + 1}/{total_files})",
                parse_mode='Markdown'
            )
        
        # Step 2: Exporting (70-90%)
        await context.bot.edit_message_text(
            chat_id=user_id,
            message_id=main_msg_id,
            text=f"⏳ *অডিও মার্জ করা হচ্ছে...*\n\n{get_progress_bar(80)} 80%\n\n💾 ফাইল সংরক্ষণ করা হচ্ছে...",
            parse_mode='Markdown'
        )
        
        # Export merged audio
        output_path = f"merged_{user_id}.mp3"
        combined.export(output_path, format="mp3")
        
        # Step 3: Finalizing (90-100%)
        await context.bot.edit_message_text(
            chat_id=user_id,
            message_id=main_msg_id,
            text=f"⏳ *অডিও মার্জ করা হচ্ছে...*\n\n{get_progress_bar(100)} 100%\n\n✅ সম্পন্ন হয়েছে!",
            parse_mode='Markdown'
        )
        
        # Delete all user messages
        for msg_id in user_data[user_id]['user_messages']:
            try:
                await context.bot.delete_message(chat_id=user_id, message_id=msg_id)
            except:
                pass
        
        # Delete main message
        try:
            await context.bot.delete_message(chat_id=user_id, message_id=user_data[user_id]['main_message_id'])
        except:
            pass
        
        # Send merged audio
        with open(output_path, 'rb') as audio_file:
            sent_msg = await context.bot.send_audio(
                chat_id=user_id,
                audio=audio_file,
                title="Merged Audio",
                caption=f"✅ {len(user_data[user_id]['audio_files'])} টি অডিও একসাথে জোড়া লাগানো হয়েছে!\n\nআরো অডিও যোগ করতে চান?"
            )
        
        # Send options menu
        options_text = "এখন কি করবেন?"
        
        options_msg = await context.bot.send_message(
            chat_id=user_id,
            text=options_text,
            reply_markup=get_after_merge_options()
        )
        
        # Cleanup old files
        for audio_path in user_data[user_id]['audio_files']:
            if os.path.exists(audio_path):
                os.remove(audio_path)
        
        # Keep merged file for later use
        user_data[user_id] = {
            'main_message_id': options_msg.message_id,
            'merged_file': output_path
        }
        
    except Exception as e:
        logger.error(f"Error merging audio: {e}")
        await context.bot.send_message(
            chat_id=user_id,
            text="❌ অডিও মার্জ করতে সমস্যা হয়েছে। আবার চেষ্টা করুন।"
        )

# Merge with previous file
async def merge_with_previous(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    await update.callback_query.answer()
    
    main_msg_id = user_data[user_id]['main_message_id']
    
    try:
        # Load previous merged file
        await context.bot.edit_message_text(
            chat_id=user_id,
            message_id=main_msg_id,
            text=f"⏳ *অডিও মার্জ করা হচ্ছে...*\n\n{get_progress_bar(10)} 10%\n\n📂 পূর্বের ফাইল লোড করা হচ্ছে...",
            parse_mode='Markdown'
        )
        
        combined = AudioSegment.from_file(user_data[user_id]['merged_file'])
        
        # Add new audio files
        total_files = len(user_data[user_id]['new_audio_files'])
        
        for idx, audio_path in enumerate(user_data[user_id]['new_audio_files']):
            audio = AudioSegment.from_file(audio_path)
            combined += audio
            
            progress = 30 + int((idx + 1) / total_files * 40)
            await context.bot.edit_message_text(
                chat_id=user_id,
                message_id=main_msg_id,
                text=f"⏳ *অডিও মার্জ করা হচ্ছে...*\n\n{get_progress_bar(progress)} {progress}%\n\n🔗 নতুন অডিও যোগ করা হচ্ছে... ({idx + 1}/{total_files})",
                parse_mode='Markdown'
            )
        
        await context.bot.edit_message_text(
            chat_id=user_id,
            message_id=main_msg_id,
            text=f"⏳ *অডিও মার্জ করা হচ্ছে...*\n\n{get_progress_bar(80)} 80%\n\n💾 ফাইল সংরক্ষণ করা হচ্ছে...",
            parse_mode='Markdown'
        )
        
        # Export new merged audio
        output_path = f"merged_{user_id}.mp3"
        combined.export(output_path, format="mp3")
        
        await context.bot.edit_message_text(
            chat_id=user_id,
            message_id=main_msg_id,
            text=f"⏳ *অডিও মার্জ করা হচ্ছে...*\n\n{get_progress_bar(100)} 100%\n\n✅ সম্পন্ন হয়েছে!",
            parse_mode='Markdown'
        )
        
        # Delete user messages
        for msg_id in user_data[user_id]['user_messages']:
            try:
                await context.bot.delete_message(chat_id=user_id, message_id=msg_id)
            except:
                pass
        
        # Delete main message
        try:
            await context.bot.delete_message(chat_id=user_id, message_id=user_data[user_id]['main_message_id'])
        except:
            pass
        
        # Send merged audio
        with open(output_path, 'rb') as audio_file:
            await context.bot.send_audio(
                chat_id=user_id,
                audio=audio_file,
                title="Merged Audio",
                caption=f"✅ আপডেট সম্পন্ন! {len(user_data[user_id]['new_audio_files'])} টি নতুন অডিও যোগ হয়েছে!"
            )
        
        # Send options menu
        options_msg = await context.bot.send_message(
            chat_id=user_id,
            text="এখন কি করবেন?",
            reply_markup=get_after_merge_options()
        )
        
        # Cleanup
        for audio_path in user_data[user_id]['new_audio_files']:
            if os.path.exists(audio_path):
                os.remove(audio_path)
        
        # Delete old merged file
        if os.path.exists(user_data[user_id]['merged_file']):
            os.remove(user_data[user_id]['merged_file'])
        
        # Update user data
        user_data[user_id] = {
            'main_message_id': options_msg.message_id,
            'merged_file': output_path
        }
        
    except Exception as e:
        logger.error(f"Error merging with previous: {e}")
        await context.bot.send_message(
            chat_id=user_id,
            text="❌ অডিও মার্জ করতে সমস্যা হয়েছে। আবার চেষ্টা করুন।"
        )

# Create video
async def create_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Update message - processing
    await context.bot.edit_message_text(
        chat_id=user_id,
        message_id=user_data[user_id]['main_message_id'],
        text="⏳ ভিডিও বানানো হচ্ছে... অপেক্ষা করুন...",
        parse_mode='Markdown'
    )
    
    try:
        image_path = user_data[user_id]['image']
        audio_path = user_data[user_id]['audio']
        output_video = f"video_{user_id}.mp4"
        
        # Get audio duration
        audio = AudioSegment.from_file(audio_path)
        duration = len(audio) / 1000  # Convert to seconds
        
        # FFmpeg command to create video
        cmd = [
            'ffmpeg', '-loop', '1', '-i', image_path,
            '-i', audio_path,
            '-c:v', 'libx264', '-tune', 'stillimage',
            '-c:a', 'aac', '-b:a', '192k',
            '-pix_fmt', 'yuv420p',
            '-shortest', '-t', str(duration),
            '-y', output_video
        ]
        
        subprocess.run(cmd, check=True, capture_output=True)
        
        # Delete all user messages
        for msg_id in user_data[user_id]['user_messages']:
            try:
                await context.bot.delete_message(chat_id=user_id, message_id=msg_id)
except:
                pass
        
        # Delete main message
        try:
            await context.bot.delete_message(chat_id=user_id, message_id=user_data[user_id]['main_message_id'])
        except:
            pass
        
        # Send video
        with open(output_video, 'rb') as video_file:
            await context.bot.send_video(
                chat_id=user_id,
                video=video_file,
                caption="✅ ভিডিও তৈরি সম্পন্ন হয়েছে!"
            )  
        # Send main menu again
        welcome_text = """
🎵 *অডিও ভিডিও বট এ স্বাগতম!* 🎬

আমি যা করতে পারি:
━━━━━━━━━━━━━━━
🎵 একাধিক অডিও একসাথে জোড়া লাগাতে পারি
🎬 অডিও + ছবি দিয়ে ভিডিও বানাতে পারি

নিচের বাটন থেকে আপনার কাজ বেছে নিন:
"""
        
        menu_msg = await context.bot.send_message(
            chat_id=user_id,
            text=welcome_text,
            reply_markup=get_main_menu(),
            parse_mode='Markdown'
        )
        
        # Cleanup
        if os.path.exists(image_path):
            os.remove(image_path)
        if os.path.exists(audio_path):
            os.remove(audio_path)
        if os.path.exists(output_video):
            os.remove(output_video)
        
        # Reset user data
        user_data[user_id] = {'main_message_id': menu_msg.message_id}
        
    except Exception as e:
        logger.error(f"Error creating video: {e}")
        await context.bot.send_message(
            chat_id=user_id,
            text="❌ ভিডিও বানাতে সমস্যা হয়েছে। আবার চেষ্টা করুন।"
        )

# Main function
def main():
    if not TOKEN:
        logger.error("BOT_TOKEN not found in environment variables!")
        return
    
    # Create application
    application = Application.builder().token(TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    application.add_handler(MessageHandler(filters.AUDIO, handle_audio))
    application.add_handler(MessageHandler(filters.VOICE, handle_voice))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    
    # Start bot
    logger.info("Bot is starting...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()      
