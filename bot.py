import os
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from pydub import AudioSegment
import subprocess

# Logging setup
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Bot token from environment variable
TOKEN = os.getenv('BOT_TOKEN')

# User data storage
user_audio_files = {}
user_images = {}

# Start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = """
🎵 অডিও ভিডিও বট এ স্বাগতম! 🎬

আমি যা করতে পারি:
1️⃣ একাধিক অডিও একসাথে জোড়া লাগাতে পারি
2️⃣ অডিও + ছবি দিয়ে ভিডিও বানাতে পারি

📌 কমান্ড সমূহ:
/merge - অডিও মার্জ করুন
/video - ভিডিও বানান
/cancel - বাতিল করুন
/help - সাহায্য

ব্যবহার শুরু করতে /merge বা /video লিখুন!
"""
    await update.message.reply_text(welcome_text)

# Help command
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
📖 কীভাবে ব্যবহার করবেন:

🎵 অডিও মার্জ করতে:
1. /merge কমান্ড দিন
2. যতগুলো ইচ্ছে অডিও পাঠান
3. শেষ হলে /done লিখুন

🎬 ভিডিও বানাতে:
1. /video কমান্ড দিন
2. একটা ছবি পাঠান
3. একটা অডিও পাঠান
4. আমি ভিডিও বানিয়ে দিবো!

❌ বাতিল করতে: /cancel
"""
    await update.message.reply_text(help_text)

# Merge command - start audio merging
async def merge_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_audio_files[user_id] = []
    await update.message.reply_text(
        "🎵 অডিও মার্জ মোড চালু হয়েছে!\n\n"
        "এখন যতগুলো ইচ্ছে অডিও ফাইল পাঠান।\n"
        "শেষ হলে /done লিখুন।\n"
        "বাতিল করতে /cancel লিখুন।"
    )

# Video command - start video creation
async def video_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_images[user_id] = {'mode': 'video', 'image': None, 'audio': None}
    await update.message.reply_text(
        "🎬 ভিডিও বানানোর মোড চালু হয়েছে!\n\n"
        "প্রথমে একটা ছবি পাঠান।\n"
        "বাতিল করতে /cancel লিখুন।"
    )

# Cancel command
async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in user_audio_files:
        del user_audio_files[user_id]
    if user_id in user_images:
        del user_images[user_id]
    await update.message.reply_text("❌ বাতিল করা হয়েছে। নতুন করে শুরু করতে /merge বা /video দিন।")

# Done command - merge all audios
async def done_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id not in user_audio_files or len(user_audio_files[user_id]) == 0:
        await update.message.reply_text("❌ কোনো অডিও পাওয়া যায়নি! প্রথমে /merge দিয়ে অডিও পাঠান।")
        return
    
    if len(user_audio_files[user_id]) < 2:
        await update.message.reply_text("❌ কমপক্ষে ২টা অডিও পাঠান!")
        return
    
    await update.message.reply_text("⏳ অডিও মার্জ করা হচ্ছে... অপেক্ষা করুন...")
    
    try:
        # Merge all audio files
        combined = AudioSegment.empty()
        for audio_path in user_audio_files[user_id]:
            audio = AudioSegment.from_file(audio_path)
            combined += audio
        
        # Export merged audio
        output_path = f"merged_{user_id}.mp3"
        combined.export(output_path, format="mp3")
        
        # Send merged audio
        with open(output_path, 'rb') as audio_file:
            await update.message.reply_audio(
                audio=audio_file,
                title="Merged Audio",
                caption=f"✅ {len(user_audio_files[user_id])} টি অডিও একসাথে জোড়া লাগানো হয়েছে!"
            )
        
        # Cleanup
        for audio_path in user_audio_files[user_id]:
            if os.path.exists(audio_path):
                os.remove(audio_path)
        if os.path.exists(output_path):
            os.remove(output_path)
        
        del user_audio_files[user_id]
        
    except Exception as e:
        logger.error(f"Error merging audio: {e}")
        await update.message.reply_text(f"❌ অডিও মার্জ করতে সমস্যা হয়েছে। আবার চেষ্টা করুন।")

# Handle audio files
async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Check if user is in merge mode
    if user_id in user_audio_files:
        try:
            # Download audio
            audio_file = await update.message.audio.get_file()
            audio_path = f"audio_{user_id}_{len(user_audio_files[user_id])}.mp3"
            await audio_file.download_to_drive(audio_path)
            
            user_audio_files[user_id].append(audio_path)
            
            await update.message.reply_text(
                f"✅ অডিও #{len(user_audio_files[user_id])} যোগ করা হয়েছে!\n\n"
                f"আরো অডিও পাঠান অথবা /done লিখুন।"
            )
        except Exception as e:
            logger.error(f"Error downloading audio: {e}")
            await update.message.reply_text("❌ অডিও ডাউনলোড করতে সমস্যা হয়েছে।")
    
    # Check if user is in video mode
    elif user_id in user_images and user_images[user_id]['image'] is not None:
        try:
            # Download audio
            audio_file = await update.message.audio.get_file()
            audio_path = f"video_audio_{user_id}.mp3"
            await audio_file.download_to_drive(audio_path)
            
            user_images[user_id]['audio'] = audio_path
            
            await update.message.reply_text("⏳ ভিডিও বানানো হচ্ছে... অপেক্ষা করুন...")
            
            # Create video
            image_path = user_images[user_id]['image']
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
            
            # Send video
            with open(output_video, 'rb') as video_file:
                await update.message.reply_video(
                    video=video_file,
                    caption="✅ ভিডিও তৈরি সম্পন্ন হয়েছে!"
                )
            
            # Cleanup
            if os.path.exists(image_path):
                os.remove(image_path)
            if os.path.exists(audio_path):
                os.remove(audio_path)
            if os.path.exists(output_video):
                os.remove(output_video)
            
            del user_images[user_id]
            
        except Exception as e:
            logger.error(f"Error creating video: {e}")
            await update.message.reply_text("❌ ভিডিও বানাতে সমস্যা হয়েছে। আবার চেষ্টা করুন।")
    
    else:
        await update.message.reply_text(
            "প্রথমে /merge বা /video কমান্ড দিন!"
        )

# Handle voice messages
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id in user_audio_files:
        try:
            # Download voice
            voice_file = await update.message.voice.get_file()
            voice_path = f"voice_{user_id}_{len(user_audio_files[user_id])}.ogg"
            await voice_file.download_to_drive(voice_path)
            
            user_audio_files[user_id].append(voice_path)
            
            await update.message.reply_text(
                f"✅ ভয়েস #{len(user_audio_files[user_id])} যোগ করা হয়েছে!\n\n"
                f"আরো অডিও/ভয়েস পাঠান অথবা /done লিখুন।"
            )
        except Exception as e:
            logger.error(f"Error downloading voice: {e}")
            await update.message.reply_text("❌ ভয়েস ডাউনলোড করতে সমস্যা হয়েছে।")
    
    elif user_id in user_images and user_images[user_id]['image'] is not None:
        try:
            # Download voice for video
            voice_file = await update.message.voice.get_file()
            voice_path = f"video_voice_{user_id}.ogg"
            await voice_file.download_to_drive(voice_path)
            
            user_images[user_id]['audio'] = voice_path
            
            await update.message.reply_text("⏳ ভিডিও বানানো হচ্ছে... অপেক্ষা করুন...")
            
            # Create video
            image_path = user_images[user_id]['image']
            output_video = f"video_{user_id}.mp4"
            
            # Get audio duration
            audio = AudioSegment.from_file(voice_path)
            duration = len(audio) / 1000
            
            cmd = [
                'ffmpeg', '-loop', '1', '-i', image_path,
                '-i', voice_path,
                '-c:v', 'libx264', '-tune', 'stillimage',
                '-c:a', 'aac', '-b:a', '192k',
                '-pix_fmt', 'yuv420p',
                '-shortest', '-t', str(duration),
                '-y', output_video
            ]
            
            subprocess.run(cmd, check=True, capture_output=True)
            
            with open(output_video, 'rb') as video_file:
                await update.message.reply_video(
                    video=video_file,
                    caption="✅ ভিডিও তৈরি সম্পন্ন হয়েছে!"
                )
            
            # Cleanup
            if os.path.exists(image_path):
                os.remove(image_path)
            if os.path.exists(voice_path):
                os.remove(voice_path)
            if os.path.exists(output_video):
                os.remove(output_video)
            
            del user_images[user_id]
            
        except Exception as e:
            logger.error(f"Error creating video: {e}")
            await update.message.reply_text("❌ ভিডিও বানাতে সমস্যা হয়েছে।")
    
    else:
        await update.message.reply_text("প্রথমে /merge বা /video কমান্ড দিন!")

# Handle photos
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id in user_images and user_images[user_id]['mode'] == 'video':
        try:
            # Download photo
            photo_file = await update.message.photo[-1].get_file()
            photo_path = f"image_{user_id}.jpg"
            await photo_file.download_to_drive(photo_path)
            
            user_images[user_id]['image'] = photo_path
            
            await update.message.reply_text(
                "✅ ছবি পাওয়া গেছে!\n\n"
                "এখন একটা অডিও বা ভয়েস পাঠান।"
            )
        except Exception as e:
            logger.error(f"Error downloading photo: {e}")
            await update.message.reply_text("❌ ছবি ডাউনলোড করতে সমস্যা হয়েছে।")
    else:
        await update.message.reply_text(
            "প্রথমে /video কমান্ড দিন!"
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
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("merge", merge_command))
    application.add_handler(CommandHandler("video", video_command))
    application.add_handler(CommandHandler("cancel", cancel_command))
    application.add_handler(CommandHandler("done", done_command))
    application.add_handler(MessageHandler(filters.AUDIO, handle_audio))
    application.add_handler(MessageHandler(filters.VOICE, handle_voice))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    
    # Start bot
    logger.info("Bot is starting...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
