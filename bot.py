import os
import asyncio
import logging
from typing import Dict, List, Set, Tuple, Optional
from datetime import datetime
import tempfile
import shutil
import psutil

from telegram import (
    Update, 
    InlineKeyboardButton, 
    InlineKeyboardMarkup,
    InputFile,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)
from telegram.constants import ParseMode

import subprocess
import json

# ===== CONFIGURATION =====
API_ID = 22768311
API_HASH = "702d8884f48b42e865425391432b3794"
BOT_TOKEN = ""  

OWNER_ID = 6040503076
ADMIN_IDS = {OWNER_ID}  # Add more admin IDs as needed

# Bot settings - OPTIMIZED FOR PRIVATE USE
BOT_MODE = "private"  # Private mode only
MAX_FILE_SIZE = 950 * 1024 * 1024  # 950MB limit
MAX_CONCURRENT_PROCESSES = 6  # Increased to 6 for private use
PROCESS_TIMEOUT = 300  # 5 minutes timeout

# ===== LOGGING SETUP =====
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ===== GLOBAL VARIABLES =====
user_sessions = {}
active_processes = {}
admins = ADMIN_IDS.copy()
current_processes = 0
process_lock = asyncio.Lock()

# Emojis for better UI
EMOJI_SELECTED = "✅ "
EMOJI_UNSELECTED = "🔘 "
EMOJI_AUDIO = "🎵 "
EMOJI_SUBTITLE = "📝 "
EMOJI_BACK = "⬅️ "
EMOJI_NEXT = "➡️ "
EMOJI_DONE = "🚀 Process Now"
EMOJI_CANCEL = "❌ Cancel"
EMOJI_HOME = "🏠 Home"
EMOJI_LOADING = "⏳"
EMOJI_SUCCESS = "✅"
EMOJI_ERROR = "❌"

# ===== RESOURCE MANAGEMENT =====
async def can_process_video() -> bool:
    """Check if system can handle another video processing task"""
    async with process_lock:
        if current_processes >= MAX_CONCURRENT_PROCESSES:
            return False
        
        # Check system resources
        cpu_percent = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        
        if cpu_percent > 85 or memory.percent > 85:
            return False
            
        return True

async def increment_process_count():
    """Increment active process count"""
    global current_processes
    async with process_lock:
        current_processes += 1

async def decrement_process_count():
    """Decrement active process count"""
    global current_processes
    async with process_lock:
        current_processes -= 1

def get_system_status() -> str:
    """Get current system status"""
    cpu_percent = psutil.cpu_percent()
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    
    return (
        f"🖥️ CPU: {cpu_percent:.1f}% | "
        f"💾 RAM: {memory.percent:.1f}% | "
        f"💿 Disk: {disk.percent:.1f}% | "
        f"⚡ Processes: {current_processes}/{MAX_CONCURRENT_PROCESSES}"
    )

# ===== UTILITY FUNCTIONS =====
def is_admin(user_id: int) -> bool:
    """Check if user is admin"""
    return user_id in admins

def is_authorized(user_id: int) -> bool:
    """Check if user is authorized based on bot mode"""
    return is_admin(user_id)  # Always private mode

def get_video_info(file_path: str) -> Dict:
    """Get video information using ffprobe - OPTIMIZED"""
    try:
        cmd = [
            'ffprobe', '-v', 'quiet', '-print_format', 'json',
            '-show_streams', '-show_format', file_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return json.loads(result.stdout)
    except Exception as e:
        logger.error(f"Error getting video info: {e}")
        return {}

def get_audio_tracks(video_info: Dict) -> List[Dict]:
    """Extract audio tracks information"""
    audio_tracks = []
    if 'streams' not in video_info:
        return audio_tracks
    
    for stream in video_info['streams']:
        if stream.get('codec_type') == 'audio':
            language = stream.get('tags', {}).get('language', 'unknown')
            title = stream.get('tags', {}).get('title', '')
            
            # Create better display name
            if language == 'unknown' and title:
                display_lang = title
            elif language != 'unknown' and title:
                display_lang = f"{language.upper()} - {title}"
            else:
                display_lang = language.upper()
            
            track_info = {
                'index': stream['index'],
                'codec': stream.get('codec_name', 'unknown').upper(),
                'language': language,
                'channels': stream.get('channels', 1),
                'title': title,
                'display_name': display_lang
            }
            audio_tracks.append(track_info)
    
    return audio_tracks

def get_subtitle_tracks(video_info: Dict) -> List[Dict]:
    """Extract subtitle tracks information"""
    subtitle_tracks = []
    if 'streams' not in video_info:
        return subtitle_tracks
    
    for stream in video_info['streams']:
        if stream.get('codec_type') == 'subtitle':
            language = stream.get('tags', {}).get('language', 'unknown')
            title = stream.get('tags', {}).get('title', '')
            
            # Create better display name
            if language == 'unknown' and title:
                display_lang = title
            elif language != 'unknown' and title:
                display_lang = f"{language.upper()} - {title}"
            else:
                display_lang = language.upper()
            
            track_info = {
                'index': stream['index'],
                'codec': stream.get('codec_name', 'unknown').upper(),
                'language': language,
                'title': title,
                'display_name': display_lang
            }
            subtitle_tracks.append(track_info)
    
    return subtitle_tracks

def remove_tracks(input_path: str, output_path: str, audio_tracks_to_remove: Set[int], subtitle_tracks_to_remove: Set[int]) -> bool:
    """Remove specified audio and subtitle tracks using ffmpeg - OPTIMIZED FOR SPEED"""
    try:
        # Build optimized ffmpeg command for speed
        cmd = [
            'ffmpeg', 
            '-i', input_path, 
            '-c', 'copy',  # Stream copy for maximum speed
            '-y'  # Overwrite output file
        ]
        
        # Map all streams by default
        cmd.extend(['-map', '0'])
        
        # Remove specified audio tracks
        for audio_index in audio_tracks_to_remove:
            cmd.extend(['-map', f'-0:a:{audio_index}'])
        
        # Remove specified subtitle tracks
        for sub_index in subtitle_tracks_to_remove:
            cmd.extend(['-map', f'-0:s:{sub_index}'])
        
        cmd.append(output_path)
        
        # Run ffmpeg with timeout
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=PROCESS_TIMEOUT)
        
        if result.returncode == 0:
            return True
        else:
            logger.error(f"FFmpeg error: {result.stderr}")
            return False
            
    except subprocess.TimeoutExpired:
        logger.error("FFmpeg process timed out")
        return False
    except Exception as e:
        logger.error(f"Error in remove_tracks: {e}")
        return False

def cleanup_files(*file_paths):
    """Clean up temporary files - ENHANCED"""
    for file_path in file_paths:
        try:
            if file_path and os.path.exists(file_path):
                os.remove(file_path)
                logger.info(f"Cleaned up: {file_path}")
        except Exception as e:
            logger.error(f"Error cleaning up file {file_path}: {e}")

# ===== KEYBOARD GENERATORS =====
def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    """Get main menu keyboard"""
    keyboard = [
        [InlineKeyboardButton("🎵 Remove Audio Tracks", callback_data="remaudio")],
        [InlineKeyboardButton("📝 Remove Subtitle Tracks", callback_data="remsubtitles")],
        [InlineKeyboardButton("🗑️ Remove All Audio", callback_data="remallaudio")],
        [InlineKeyboardButton("🗑️ Remove All Subtitles", callback_data="remallsubtitles")],
        [InlineKeyboardButton("🔥 Remove All Tracks", callback_data="remall")],
        [InlineKeyboardButton("📊 System Status", callback_data="status")],
        [InlineKeyboardButton("ℹ️ Help", callback_data="help")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_track_selection_keyboard(tracks: List[Dict], selected_tracks: Set[int], page: int, tracks_per_page: int = 8) -> InlineKeyboardMarkup:
    """Generate track selection keyboard with pagination"""
    keyboard = []
    
    # Calculate pagination
    start_idx = page * tracks_per_page
    end_idx = start_idx + tracks_per_page
    page_tracks = tracks[start_idx:end_idx]
    
    # Add track buttons
    for track in page_tracks:
        track_index = track['index']
        display_name = track.get('display_name', f"Track {track_index}")
        codec = track.get('codec', '')
        
        display_text = f"{display_name}"
        if codec:
            display_text += f" ({codec})"
        
        # Add selection indicator
        prefix = EMOJI_SELECTED if track_index in selected_tracks else EMOJI_UNSELECTED
        button_text = f"{prefix}{display_text}"
        
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"track_{track_index}")])
    
    # Add navigation buttons
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(EMOJI_BACK + " Previous", callback_data=f"page_{page-1}"))
    
    if end_idx < len(tracks):
        nav_buttons.append(InlineKeyboardButton(EMOJI_NEXT + " Next", callback_data=f"page_{page+1}"))
    
    if nav_buttons:
        keyboard.append(nav_buttons)
    
    # Add action buttons
    selected_count = len(selected_tracks)
    action_buttons = [
        InlineKeyboardButton(f"🚀 Process ({selected_count} selected)", callback_data="done_selection"),
        InlineKeyboardButton(EMOJI_CANCEL, callback_data="cancel_selection")
    ]
    keyboard.append(action_buttons)
    
    return InlineKeyboardMarkup(keyboard)

# ===== MESSAGE HANDLERS =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    user_id = update.effective_user.id
    
    if not is_authorized(user_id):
        await update.message.reply_text(
            "❌ *Access Denied*\n\n"
            "This bot is private. Only authorized users can use it.",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    welcome_text = (
        "🎬 *Welcome to Track Killer Bot!* 🎬\n\n"
        "*PRIVATE MODE* - Optimized for performance\n\n"
        "⚡ *Features:*\n"
        "• Remove specific audio/subtitle tracks\n"
        "• Fast processing with stream copy\n"
        "• Support up to 950MB files\n"
        "• Concurrent processing: 6 tasks\n"
        "• Automatic file cleanup\n\n"
        "Send a video or use the menu below!"
    )
    
    await update.message.reply_text(
        welcome_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_main_menu_keyboard()
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command"""
    help_text = (
        "📖 *Track Killer Bot - Help*\n\n"
        "*Commands:*\n"
        "• /start - Start bot\n"
        "• /help - This message\n"
        "• /trackkiller - Main track removal\n"
        "• /remaudio - Remove audio tracks\n"
        "• /remsubtitles - Remove subtitle tracks\n"
        "• /remallaudio - Remove all audio\n"
        "• /remallsubtitles - Remove all subtitles\n"
        "• /remall - Remove all tracks\n"
        "• /cancel - Cancel current task\n"
        "• /status - System status\n\n"
        "*Limits:*\n"
        "• Max file size: 950MB\n"
        "• Max concurrent tasks: 6\n"
        "• Automatic file cleanup\n"
    )
    
    await update.message.reply_text(
        help_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_main_menu_keyboard()
    )

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /status command"""
    user_id = update.effective_user.id
    
    if not is_authorized(user_id):
        await update.message.reply_text("❌ Access denied.")
        return
    
    status_text = (
        "📊 *System Status*\n\n"
        f"{get_system_status()}\n\n"
        f"*Active Sessions:* {len(user_sessions)}\n"
        f"*Bot Mode:* {BOT_MODE.upper()}\n"
        f"*Max File Size:* {MAX_FILE_SIZE // (1024*1024)}MB\n"
        f"*Max Processes:* {MAX_CONCURRENT_PROCESSES}"
    )
    
    await update.message.reply_text(
        status_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_main_menu_keyboard()
    )

async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming video files"""
    user_id = update.effective_user.id
    
    if not is_authorized(user_id):
        await update.message.reply_text("❌ Access denied. Private bot.")
        return
    
    video = update.message.video or update.message.document
    
    if not video:
        return
    
    # Check file size
    if video.file_size > MAX_FILE_SIZE:
        await update.message.reply_text(
            f"❌ File too large! Maximum size is {MAX_FILE_SIZE // (1024*1024)}MB"
        )
        return
    
    # Store video info in user session
    user_sessions[user_id] = {
        'video_file_id': video.file_id,
        'video_message_id': update.message.message_id,
        'selected_audio_tracks': set(),
        'selected_subtitle_tracks': set(),
        'processing': False,
        'downloaded_files': []  # Track files for cleanup
    }
    
    await update.message.reply_text(
        "🎬 Video received! Choose an option:",
        reply_markup=get_main_menu_keyboard()
    )

# ===== COMMAND HANDLERS =====
async def track_killer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /trackkiller command"""
    user_id = update.effective_user.id
    
    if not is_authorized(user_id):
        await update.message.reply_text("❌ Access denied.")
        return
    
    if not update.message.reply_to_message:
        await update.message.reply_text("❌ Reply to a video with this command.")
        return
    
    replied_message = update.message.reply_to_message
    video = replied_message.video or replied_message.document
    
    if not video:
        await update.message.reply_text("❌ Reply to a video file.")
        return
    
    # Store video info
    user_sessions[user_id] = {
        'video_file_id': video.file_id,
        'video_message_id': replied_message.message_id,
        'selected_audio_tracks': set(),
        'selected_subtitle_tracks': set(),
        'processing': False,
        'downloaded_files': []
    }
    
    await show_track_selection(update, context, user_id)

async def rem_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /remaudio command"""
    await handle_track_removal_command(update, context, 'audio')

async def rem_subtitles(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /remsubtitles command"""
    await handle_track_removal_command(update, context, 'subtitles')

async def handle_track_removal_command(update: Update, context: ContextTypes.DEFAULT_TYPE, track_type: str):
    """Handle track removal commands"""
    user_id = update.effective_user.id
    
    if not is_authorized(user_id):
        await update.message.reply_text("❌ Access denied.")
        return
    
    if user_id not in user_sessions:
        await update.message.reply_text("❌ Send a video file first.")
        return
    
    user_session = user_sessions[user_id]
    
    if track_type == 'audio':
        user_session['selected_subtitle_tracks'] = set()
    else:
        user_session['selected_audio_tracks'] = set()
    
    await show_track_selection(update, context, user_id, track_type)

async def rem_all_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /remallaudio command"""
    await process_remove_all(update, context, remove_audio=True, remove_subtitles=False)

async def rem_all_subtitles(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /remallsubtitles command"""
    await process_remove_all(update, context, remove_audio=False, remove_subtitles=True)

async def rem_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /remall command"""
    await process_remove_all(update, context, remove_audio=True, remove_subtitles=True)

async def process_remove_all(update: Update, context: ContextTypes.DEFAULT_TYPE, remove_audio: bool, remove_subtitles: bool):
    """Process remove all tracks commands"""
    user_id = update.effective_user.id
    
    if not is_authorized(user_id):
        await update.message.reply_text("❌ Access denied.")
        return
    
    if user_id not in user_sessions:
        await update.message.reply_text("❌ Send a video file first.")
        return
    
    # Check system capacity
    if not await can_process_video():
        await update.message.reply_text(
            f"❌ System busy. Please wait...\n{get_system_status()}"
        )
        return
    
    user_session = user_sessions[user_id]
    user_session['processing'] = True
    
    processing_msg = await update.message.reply_text(
        f"{EMOJI_LOADING} Processing your video...\n{get_system_status()}"
    )
    
    input_path = None
    output_path = None
    
    try:
        await increment_process_count()
        
        # Download video
        video_file = await context.bot.get_file(user_session['video_file_id'])
        
        with tempfile.NamedTemporaryFile(delete=False, suffix='.mp4') as input_file:
            await video_file.download_to_drive(input_file.name)
            input_path = input_file.name
            user_session['downloaded_files'].append(input_path)
        
        output_path = input_path.replace('.mp4', '_processed.mp4')
        
        # Get video info
        video_info = get_video_info(input_path)
        audio_tracks = get_audio_tracks(video_info)
        subtitle_tracks = get_subtitle_tracks(video_info)
        
        audio_tracks_to_remove = set()
        subtitle_tracks_to_remove = set()
        
        if remove_audio:
            audio_tracks_to_remove = {track['index'] for track in audio_tracks}
        
        if remove_subtitles:
            subtitle_tracks_to_remove = {track['index'] for track in subtitle_tracks}
        
        # Update processing message
        await processing_msg.edit_text(
            f"{EMOJI_LOADING} Removing tracks...\n"
            f"Audio: {len(audio_tracks_to_remove)} tracks\n"
            f"Subtitles: {len(subtitle_tracks_to_remove)} tracks\n"
            f"{get_system_status()}"
        )
        
        # Process video
        success = remove_tracks(input_path, output_path, audio_tracks_to_remove, subtitle_tracks_to_remove)
        
        if success and os.path.exists(output_path):
            # Send processed video
            file_size = os.path.getsize(output_path) / (1024 * 1024)
            with open(output_path, 'rb') as video_file:
                await update.message.reply_document(
                    document=InputFile(
                        video_file, 
                        filename=f"trackkiller_{datetime.now().strftime('%H%M%S')}.mp4"
                    ),
                    caption=(
                        f"{EMOJI_SUCCESS} Processing completed!\n"
                        f"📁 Output: {file_size:.1f}MB\n"
                        f"🎵 Audio removed: {len(audio_tracks_to_remove)}\n"
                        f"📝 Subtitles removed: {len(subtitle_tracks_to_remove)}"
                    )
                )
            await processing_msg.delete()
        else:
            await processing_msg.edit_text(f"{EMOJI_ERROR} Error processing video.")
        
    except Exception as e:
        logger.error(f"Error in process_remove_all: {e}")
        await processing_msg.edit_text(f"{EMOJI_ERROR} Processing failed: {str(e)}")
    
    finally:
        # CLEANUP ALL FILES
        cleanup_files(input_path, output_path)
        if user_id in user_sessions:
            for file_path in user_session.get('downloaded_files', []):
                cleanup_files(file_path)
            user_session['downloaded_files'] = []
            user_session['processing'] = False
        
        await decrement_process_count()

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /cancel command"""
    user_id = update.effective_user.id
    
    if user_id in user_sessions:
        # Cleanup files
        user_session = user_sessions[user_id]
        for file_path in user_session.get('downloaded_files', []):
            cleanup_files(file_path)
        user_session['downloaded_files'] = []
        user_session['processing'] = False
        
        await update.message.reply_text("✅ Operation cancelled and files cleaned up.")
    else:
        await update.message.reply_text("❌ No active operation.")

# ===== TRACK SELECTION FLOW =====
async def show_track_selection(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, track_type: str = 'audio'):
    """Show track selection interface"""
    user_session = user_sessions[user_id]
    
    processing_msg = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"{EMOJI_LOADING} Analyzing video..."
    )
    
    input_path = None
    
    try:
        video_file = await context.bot.get_file(user_session['video_file_id'])
        
        with tempfile.NamedTemporaryFile(delete=False, suffix='.mp4') as temp_file:
            await video_file.download_to_drive(temp_file.name)
            input_path = temp_file.name
            user_session['downloaded_files'].append(input_path)
        
        video_info = get_video_info(input_path)
        
        if track_type == 'audio':
            tracks = get_audio_tracks(video_info)
            title = "🎵 Select Audio Tracks to Remove"
        else:
            tracks = get_subtitle_tracks(video_info)
            title = "📝 Select Subtitle Tracks to Remove"
        
        if not tracks:
            await processing_msg.edit_text(f"❌ No {track_type} tracks found.")
            return
        
        user_session['current_tracks'] = tracks
        user_session['current_track_type'] = track_type
        user_session['current_page'] = 0
        
        keyboard = get_track_selection_keyboard(
            tracks, 
            user_session[f'selected_{track_type}_tracks'],
            0
        )
        
        message_text = (
            f"{title}\n\n"
            f"📊 Found {len(tracks)} track(s)\n"
            f"✅ Click to select/deselect\n"
            f"🚀 Process when ready!"
        )
        
        await processing_msg.edit_text(message_text, reply_markup=keyboard)
        
    except Exception as e:
        logger.error(f"Error in show_track_selection: {e}")
        await processing_msg.edit_text(f"{EMOJI_ERROR} Analysis failed.")
    
    finally:
        # Input file is kept for processing, will be cleaned up later

# ===== CALLBACK QUERY HANDLERS =====
async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all callback queries"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    data = query.data
    
    if not is_authorized(user_id):
        await query.edit_message_text("❌ Access denied.")
        return
    
    if user_id not in user_sessions:
        await query.edit_message_text("❌ Session expired. Send a video again.")
        return
    
    user_session = user_sessions[user_id]
    
    if data == "help":
        await help_command(update, context)
        return
    elif data == "status":
        await status_command(update, context)
        return
    elif data in ["remaudio", "remsubtitles"]:
        track_type = "audio" if data == "remaudio" else "subtitles"
        if data == "remaudio":
            user_session['selected_subtitle_tracks'] = set()
        else:
            user_session['selected_audio_tracks'] = set()
        await show_track_selection(update, context, user_id, track_type)
    elif data in ["remallaudio", "remallsubtitles", "remall"]:
        remove_audio = data in ["remallaudio", "remall"]
        remove_subtitles = data in ["remallsubtitles", "remall"]
        await process_remove_all_callback(query, context, user_id, remove_audio, remove_subtitles)
    elif data.startswith("track_"):
        await handle_track_selection(query, user_session, data)
    elif data.startswith("page_"):
        await handle_page_navigation(query, user_session, data)
    elif data == "done_selection":
        await handle_done_selection(query, context, user_id)
    elif data == "cancel_selection":
        await handle_cancel_selection(query, user_id)

async def handle_track_selection(query, user_session, data):
    """Handle individual track selection"""
    track_index = int(data.split('_')[1])
    track_type = user_session['current_track_type']
    selected_tracks = user_session[f'selected_{track_type}_tracks']
    
    if track_index in selected_tracks:
        selected_tracks.remove(track_index)
    else:
        selected_tracks.add(track_index)
    
    keyboard = get_track_selection_keyboard(
        user_session['current_tracks'],
        selected_tracks,
        user_session['current_page']
    )
    
    await query.edit_message_reply_markup(reply_markup=keyboard)

async def handle_page_navigation(query, user_session, data):
    """Handle pagination"""
    page = int(data.split('_')[1])
    user_session['current_page'] = page
    
    track_type = user_session['current_track_type']
    keyboard = get_track_selection_keyboard(
        user_session['current_tracks'],
        user_session[f'selected_{track_type}_tracks'],
        page
    )
    
    await query.edit_message_reply_markup(reply_markup=keyboard)

async def handle_done_selection(query, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    """Handle done selection and process video"""
    user_session = user_sessions[user_id]
    
    # Check system capacity
    if not await can_process_video():
        await query.edit_message_text(
            f"❌ System busy. Please wait...\n{get_system_status()}"
        )
        return
    
    track_type = user_session['current_track_type']
    selected_count = len(user_session[f'selected_{track_type}_tracks'])
    
    if selected_count == 0:
        await query.edit_message_text(
            "❌ No tracks selected. Please select at least one track.",
            reply_markup=get_main_menu_keyboard()
        )
        return
    
    processing_msg = await query.edit_message_text(
        f"{EMOJI_LOADING} Starting processing...\n"
        f"Selected: {selected_count} {track_type} track(s)\n"
        f"{get_system_status()}"
    )
    
    await process_selected_tracks(processing_msg, context, user_id)

async def handle_cancel_selection(query, user_id: int):
    """Handle cancel selection with cleanup"""
    if user_id in user_sessions:
        user_session = user_sessions[user_id]
        for file_path in user_session.get('downloaded_files', []):
            cleanup_files(file_path)
        user_session['downloaded_files'] = []
    
    await query.edit_message_text(
        "❌ Operation cancelled.",
        reply_markup=get_main_menu_keyboard()
    )

async def process_selected_tracks(processing_msg, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    """Process video with selected tracks"""
    user_session = user_sessions[user_id]
    user_session['processing'] = True
    
    input_path = None
    output_path = None
    
    try:
        await increment_process_count()
        
        # Download video if not already downloaded
        if not user_session.get('downloaded_files'):
            video_file = await context.bot.get_file(user_session['video_file_id'])
            with tempfile.NamedTemporaryFile(delete=False, suffix='.mp4') as input_file:
                await video_file.download_to_drive(input_file.name)
                input_path = input_file.name
                user_session['downloaded_files'].append(input_path)
        else:
            input_path = user_session['downloaded_files'][0]
        
        output_path = input_path.replace('.mp4', '_processed.mp4')
        
        # Update processing message
        audio_count = len(user_session['selected_audio_tracks'])
        sub_count = len(user_session['selected_subtitle_tracks'])
        
        await processing_msg.edit_text(
            f"{EMOJI_LOADING} Removing tracks...\n"
            f"🎵 Audio: {audio_count} tracks\n"
            f"📝 Subtitles: {sub_count} tracks\n"
            f"{get_system_status()}"
        )
        
        # Process video
        success = remove_tracks(
            input_path, 
            output_path, 
            user_session['selected_audio_tracks'],
            user_session['selected_subtitle_tracks']
        )
        
        if success and os.path.exists(output_path):
            # Send processed video
            file_size = os.path.getsize(output_path) / (1024 * 1024)
            with open(output_path, 'rb') as video_file:
                await context.bot.send_document(
                    chat_id=processing_msg.chat_id,
                    document=InputFile(
                        video_file, 
                        filename=f"trackkiller_{datetime.now().strftime('%H%M%S')}.mp4"
                    ),
                    caption=(
                        f"{EMOJI_SUCCESS} Processing completed!\n"
                        f"📁 Output: {file_size:.1f}MB\n"
                        f"🎵 Audio removed: {audio_count}\n"
                        f"📝 Subtitles removed: {sub_count}"
                    )
                )
            await processing_msg.delete()
        else:
            await processing_msg.edit_text(f"{EMOJI_ERROR} Processing failed.")
        
    except Exception as e:
        logger.error(f"Error in process_selected_tracks: {e}")
        await processing_msg.edit_text(f"{EMOJI_ERROR} Error: {str(e)}")
    
    finally:
        # CLEANUP ALL FILES
        cleanup_files(input_path, output_path)
        if user_id in user_sessions:
            for file_path in user_session.get('downloaded_files', []):
                cleanup_files(file_path)
            user_session['downloaded_files'] = []
            user_session['processing'] = False
        
        await decrement_process_count()

async def process_remove_all_callback(query, context: ContextTypes.DEFAULT_TYPE, user_id: int, remove_audio: bool, remove_subtitles: bool):
    """Process remove all tracks from callback"""
    user_session = user_sessions[user_id]
    user_session['processing'] = True
    
    processing_msg = await query.edit_message_text(
        f"{EMOJI_LOADING} Starting processing...\n{get_system_status()}"
    )
    
    input_path = None
    output_path = None
    
    try:
        await increment_process_count()
        
        # Download video
        video_file = await context.bot.get_file(user_session['video_file_id'])
        
        with tempfile.NamedTemporaryFile(delete=False, suffix='.mp4') as input_file:
            await video_file.download_to_drive(input_file.name)
            input_path = input_file.name
            user_session['downloaded_files'].append(input_path)
        
        output_path = input_path.replace('.mp4', '_processed.mp4')
        
        # Get video info
        video_info = get_video_info(input_path)
        audio_tracks = get_audio_tracks(video_info)
        subtitle_tracks = get_subtitle_tracks(video_info)
        
        audio_tracks_to_remove = set()
        subtitle_tracks_to_remove = set()
        
        if remove_audio:
            audio_tracks_to_remove = {track['index'] for track in audio_tracks}
        
        if remove_subtitles:
            subtitle_tracks_to_remove = {track['index'] for track in subtitle_tracks}
        
        await processing_msg.edit_text(
            f"{EMOJI_LOADING} Removing tracks...\n"
            f"Audio: {len(audio_tracks_to_remove)} tracks\n"
            f"Subtitles: {len(subtitle_tracks_to_remove)} tracks\n"
            f"{get_system_status()}"
        )
        
        success = remove_tracks(input_path, output_path, audio_tracks_to_remove, subtitle_tracks_to_remove)
        
        if success and os.path.exists(output_path):
            file_size = os.path.getsize(output_path) / (1024 * 1024)
            with open(output_path, 'rb') as video_file:
                await context.bot.send_document(
                    chat_id=query.message.chat_id,
                    document=InputFile(
                        video_file, 
                        filename=f"trackkiller_{datetime.now().strftime('%H%M%S')}.mp4"
                    ),
                    caption=(
                        f"{EMOJI_SUCCESS} Processing completed!\n"
                        f"📁 Output: {file_size:.1f}MB\n"
                        f"🎵 Audio removed: {len(audio_tracks_to_remove)}\n"
                        f"📝 Subtitles removed: {len(subtitle_tracks_to_remove)}"
                    )
                )
            await processing_msg.delete()
        else:
            await processing_msg.edit_text(f"{EMOJI_ERROR} Processing failed.")
        
    except Exception as e:
        logger.error(f"Error in process_remove_all_callback: {e}")
        await processing_msg.edit_text(f"{EMOJI_ERROR} Error: {str(e)}")
    
    finally:
        cleanup_files(input_path, output_path)
        if user_id in user_sessions:
            for file_path in user_session.get('downloaded_files', []):
                cleanup_files(file_path)
            user_session['downloaded_files'] = []
            user_session['processing'] = False
        
        await decrement_process_count()

# ===== ADMIN MANAGEMENT =====
async def add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add admin (Owner only)"""
    user_id = update.effective_user.id
    
    if user_id != OWNER_ID:
        await update.message.reply_text("❌ Owner access required.")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: /addadmin <user_id>")
        return
    
    try:
        new_admin_id = int(context.args[0])
        admins.add(new_admin_id)
        await update.message.reply_text(f"✅ User {new_admin_id} added as admin.")
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID.")

async def remove_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove admin (Owner only)"""
    user_id = update.effective_user.id
    
    if user_id != OWNER_ID:
        await update.message.reply_text("❌ Owner access required.")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: /removeadmin <user_id>")
        return
    
    try:
        admin_id = int(context.args[0])
        if admin_id == OWNER_ID:
            await update.message.reply_text("❌ Cannot remove owner.")
            return
        
        if admin_id in admins:
            admins.remove(admin_id)
            await update.message.reply_text(f"✅ User {admin_id} removed from admins.")
        else:
            await update.message.reply_text("❌ User is not an admin.")
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID.")

async def list_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all admins (Owner only)"""
    user_id = update.effective_user.id
    
    if user_id != OWNER_ID:
        await update.message.reply_text("❌ Owner access required.")
        return
    
    admin_list = "\n".join([f"• {admin_id}" for admin_id in admins])
    await update.message.reply_text(f"👑 Admins:\n{admin_list}")

# ===== ERROR HANDLER =====
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors"""
    logger.error(f"Exception while handling an update: {context.error}")
    
    try:
        if update and update.effective_message:
            await update.effective_message.reply_text(
                "❌ An error occurred. Please try again later."
            )
    except Exception as e:
        logger.error(f"Error in error handler: {e}")

# ===== MAIN FUNCTION =====
def main():
    """Start the bot"""
    # Check if ffmpeg is available
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
        print("✅ FFmpeg is available")
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("❌ FFmpeg is not installed. Please install FFmpeg.")
        return
    
    # Create application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("trackkiller", track_killer))
    application.add_handler(CommandHandler("remaudio", rem_audio))
    application.add_handler(CommandHandler("remsubtitles", rem_subtitles))
    application.add_handler(CommandHandler("remallaudio", rem_all_audio))
    application.add_handler(CommandHandler("remallsubtitles", rem_all_subtitles))
    application.add_handler(CommandHandler("remall", rem_all))
    application.add_handler(CommandHandler("cancel", cancel))
    application.add_handler(CommandHandler("addadmin", add_admin))
    application.add_handler(CommandHandler("removeadmin", remove_admin))
    application.add_handler(CommandHandler("listadmins", list_admins))
    
    # Message handlers
    application.add_handler(MessageHandler(filters.VIDEO, handle_video))
    application.add_handler(MessageHandler(filters.Document.VIDEO, handle_video))
    
    # Callback query handler
    application.add_handler(CallbackQueryHandler(handle_callback_query))
    
    # Error handler
    application.add_error_handler(error_handler)
    
    # Start the bot
    print("🤖 Track Killer Bot is running...")
    print(f"📊 Max concurrent processes: {MAX_CONCURRENT_PROCESSES}")
    print(f"💾 Max file size: {MAX_FILE_SIZE // (1024*1024)}MB")
    print(f"🔒 Private mode: Only {len(admins)} authorized users")
    application.run_polling()

if __name__ == "__main__":
    main()
