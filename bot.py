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

✅ যোগ করা অডিও: 0টি

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
3. "মার্জ সম্পন্ন করুন" বাটনে ক্লিক করুন

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
        if 'image' in user_data[user_id] and user_data[user_id]['image']:
            if os.path.exists(user_data[user_id]['image']):
                os.remove(user_data[user_id]['image'])
        if 'audio' in user_data[user_id] and user_data[user_id]['audio']:
            if os.path.exists(user_data[user_id]['audio']):
                os.remove(user_data[user_id]['audio'])
    
    # Return to main menu
    await start(update, context)

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
                caption=f"✅ {len(user_data[user_id]['audio_files'])} টি অডিও একসাথে জোড়া লাগানো হয়েছে!"
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
        for audio_path in user_data[user_id]['audio_files']:
            if os.path.exists(audio_path):
                os.remove(audio_path)
        if os.path.exists(output_path):
            os.remove(output_path)
        
        # Reset user data with new main message
        user_data[user_id] = {'main_message_id': menu_msg.message_id}
        
    except Exception as e:
        logger.error(f"Error merging audio: {e}")
        await context.bot.send_message(
            chat_id=user_id,
            text="❌ অডিও মার্জ করতে সমস্যা হয়েছে। আবার চেষ্টা করুন।"
        )

# Create video
async def create_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    main_msg_id = user_data[user_id]['main_message_id']
    
    try:
        # Step 1: Starting (0-20%)
        await context.bot.edit_message_text(
            chat_id=user_id,
            message_id=main_msg_id,
            text=f"⏳ *ভিডিও বানানো হচ্ছে...*\n\n{get_progress_bar(10)} 10%\n\n📂 ফাইল প্রস্তুত করা হচ্ছে...",
            parse_mode='Markdown'
        )
        
        image_path = user_data[user_id]['image']
        audio_path = user_data[user_id]['audio']
        output_video = f"video_{user_id}.mp4"
        
        # Step 2: Getting audio duration (20-40%)
        await context.bot.edit_message_text(
            chat_id=user_id,
            message_id=main_msg_id,
            text=f"⏳ *ভিডিও বানানো হচ্ছে...*\n\n{get_progress_bar(30)} 30%\n\n🎵 অডিও প্রসেস করা হচ্ছে...",
            parse_mode='Markdown'
        )
        
        # Get audio duration
        audio = AudioSegment.from_file(audio_path)
        duration = len(audio) / 1000  # Convert to seconds
        
        # Step 3: Creating video (40-80%)
        await context.bot.edit_message_text(
            chat_id=user_id,
            message_id=main_msg_id,
            text=f"⏳ *ভিডিও বানানো হচ্ছে...*\n\n{get_progress_bar(60)} 60%\n\n🎬 ভিডিও রেন্ডার করা হচ্ছে...",
            parse_mode='Markdown'
        )
        
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
        
        # Step 4: Finalizing (80-100%)
        await context.bot.edit_message_text(
            chat_id=user_id,
            message_id=main_msg_id,
            text=f"⏳ *ভিডিও বানানো হচ্ছে...*\n\n{get_progress_bar(90)} 90%\n\n💾 ভিডিও সংরক্ষণ করা হচ্ছে...",
            parse_mode='Markdown'
        )
        
        # Brief pause to show 100%
        await context.bot.edit_message_text(
            chat_id=user_id,
            message_id=main_msg_id,
            text=f"⏳ *ভিডিও বানানো হচ্ছে...*\n\n{get_progress_bar(100)} 100%\n\n✅ সম্পন্ন হয়েছে!",
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
    application.add_handler(MessageHandler(filters.AUDIO, handle_audio))
    application.add_handler(MessageHandler(filters.VOICE, handle_voice))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    
    # Start bot
    logger.info("Bot is starting...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
