import discord
from discord.ext import commands
import logging
from dotenv import load_dotenv
import os
import asyncio
from aiohttp import web
import httpx
import json
import aiosqlite
from datetime import datetime
import random
from typing import Optional
import re
import subprocess
from music import MusicBot, YouTubeAudioSource  # restore music functionality imports
import base64
import io
import traceback
import time

# Ensure opus is loaded for voice support
if not discord.opus.is_loaded():
    # Try to load opus
    try:
        discord.opus.load_opus('opus')
    except:
        try:
            discord.opus.load_opus('libopus.so.0')
        except:
            try:
                discord.opus.load_opus('libopus-0.dll')
            except:
                print("⚠️  Warning: Could not load opus library. Voice features may not work properly.")

print(f"Opus loaded: {discord.opus.is_loaded()}")

load_dotenv()
token = os.getenv('DISCORD_TOKEN')
venice_api_key = os.getenv('VENICE_API_KEY')
youtube_api_key = os.getenv('YOUTUBE_API_KEY')

if token is None:
    raise ValueError("DISCORD_TOKEN environment variable not set")
if venice_api_key is None:
    print("Warning: VENICE_API_KEY not set. AI features will be disabled.")
if youtube_api_key is None:
    print("Warning: YOUTUBE_API_KEY not set. YouTube API features will be disabled.")

handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True  # Needed for voice state tracking

bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

# If True, always use a conservative safe emoji set for polls (regional indicators / keycaps)
FORCE_SAFE_EMOJI = True
# If True, when the user requests clock mapping, force the bot to overwrite
# AI-provided emojis and use authoritative clock glyphs for both display and reactions
FORCE_AUTHORITATIVE_CLOCKS = True

dogs_role_name = "Dogs"
cats_role_name = "Cats"
lizards_role_name = "Lizards"
pvp_role_name = "PVP"
elves_role_name = "Elves"

# Initialize global variables for music functionality
music_bot = None

# YouTube Data API v3 Configuration
YOUTUBE_API_BASE_URL = "https://www.googleapis.com/youtube/v3"

# Venice AI Configuration
VENICE_API_URL = "https://api.venice.ai/api/v1/chat/completions"
VENICE_MODEL = "venice-uncensored"
IMAGE_API_URL = "https://api.venice.ai/api/v1/image/generate"

class YouTubeAPI:
    """YouTube Data API v3 integration for reliable cloud deployment"""
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or youtube_api_key
        self.session = None
    
    async def search_videos(self, query: str, max_results: int = 10):
        """Search for YouTube videos using the API"""
        if not self.api_key:
            raise ValueError("YouTube API key not configured")
        
        params = {
            'part': 'snippet',
            'q': query,
            'type': 'video',
            'maxResults': max_results,
            'key': self.api_key,
            'videoCategoryId': '10',  # Music category
            'videoEmbeddable': 'true',  # Only embeddable videos
            'videoSyndicated': 'true',  # Only syndicated videos
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{YOUTUBE_API_BASE_URL}/search", params=params)
            response.raise_for_status()
            return response.json()
    
    async def get_video_details(self, video_id: str):
        """Get detailed information about a YouTube video"""
        if not self.api_key:
            raise ValueError("YouTube API key not configured")
        
        params = {
            'part': 'snippet,contentDetails,status',
            'id': video_id,
            'key': self.api_key
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{YOUTUBE_API_BASE_URL}/videos", params=params)
            response.raise_for_status()
            data = response.json()
            
            if not data.get('items'):
                return None
                
            return data['items'][0]
    
    def extract_video_id(self, url: str) -> Optional[str]:
        """Extract video ID from various YouTube URL formats"""
        
        patterns = [
            r'(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/embed\/)([^&\n?#]+)',
            r'youtube\.com\/watch\?.*v=([^&\n?#]+)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        
        return None
    
    def get_youtube_url(self, video_id: str) -> str:
        """Generate a clean YouTube URL from video ID"""
        return f"https://www.youtube.com/watch?v={video_id}"

# Initialize YouTube API
youtube_api = YouTubeAPI() if youtube_api_key else None

# Database setup
async def init_database():
    """Initialize the chat history database"""
    async with aiosqlite.connect("chat_history.db") as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                user_name TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                message TEXT NOT NULL,
                response TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create undo stack table for universal undo/redo
        await db.execute("""
            CREATE TABLE IF NOT EXISTS undo_stack (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                action_type TEXT NOT NULL,  -- 'chat'
                action_id INTEGER NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Migration: Add user_id and action_type columns to existing undo_stack if they don't exist
        try:
            await db.execute("ALTER TABLE undo_stack ADD COLUMN user_id TEXT")
        except:
            pass  # Column already exists
        
        try:
            await db.execute("ALTER TABLE undo_stack ADD COLUMN action_type TEXT DEFAULT 'chat'")
        except:
            pass  # Column already exists
            
        await db.commit()

async def save_chat_history(user_id: str, user_name: str, channel_id: str, message: str, response: str) -> int:
    """Save chat interaction to database, returns the action ID"""
    async with aiosqlite.connect("chat_history.db") as db:
        cursor = await db.execute(
            "INSERT INTO chat_history (user_id, user_name, channel_id, message, response) VALUES (?, ?, ?, ?, ?)",
            (user_id, user_name, channel_id, message, response)
        )
        await db.commit()
        return cursor.lastrowid or 0

async def save_chat_message(user_id: str, message: str, response: str) -> int:
    """Simple wrapper for save_chat_history with default values"""
    return await save_chat_history(user_id, "User", "0", message, response)

async def clear_user_chat_history(user_id: str) -> bool:
    """Clear all chat history for a specific user"""
    try:
        async with aiosqlite.connect("chat_history.db") as db:
            await db.execute("DELETE FROM chat_history WHERE user_id = ?", (user_id,))
            await db.commit()
            return True
    except Exception:
        return False

async def get_chat_history(user_id: str, limit: int = 5):
    """Get recent chat history for a user (for context)"""
    async with aiosqlite.connect("chat_history.db") as db:
        cursor = await db.execute(
            "SELECT message, response FROM chat_history WHERE user_id = ? ORDER BY timestamp ASC LIMIT ?",
            (user_id, limit)
        )
        rows = await cursor.fetchall()
        return [(str(row[0]), str(row[1])) for row in rows]

async def undo_last_action(channel_id: str, user_id: str) -> tuple[bool, str]:
    """Undo the last chat action by the user in the channel. Returns (success, message)"""
    async with aiosqlite.connect("chat_history.db") as db:
        # Try chat action
        cursor = await db.execute(
            "SELECT id, user_name, message FROM chat_history WHERE channel_id = ? AND user_id = ? ORDER BY timestamp DESC LIMIT 1",
            (channel_id, user_id)
        )
        chat_row = await cursor.fetchone()
        
        if not chat_row:
            return False, "No actions to undo!"
        
        action_id, user_name, message = chat_row
        
        # Delete chat action
        await db.execute(
            "DELETE FROM chat_history WHERE id = ?",
            (action_id,)
        )
        
        # Add to undo stack
        await db.execute(
            "INSERT INTO undo_stack (channel_id, user_id, action_type, action_id) VALUES (?, ?, ?, ?)",
            (channel_id, user_id, 'chat', action_id)
        )
        
        await db.commit()
        return True, f"Undone chat message by {user_name}: {message[:100]}..."

async def redo_last_undo(channel_id: str, user_id: str) -> tuple[bool, str]:
    """Redo the last undone action by the user. Returns (success, message)"""
    async with aiosqlite.connect("chat_history.db") as db:
        return False, "Chat actions cannot be redone once undone!"

async def get_ai_response_with_history(user_id: str, prompt: str, max_tokens: int = 500, use_history: bool = True) -> str:
    """Get response from Venice AI with chat history context"""
    if not venice_api_key:
        return "AI features are disabled. Please set VENICE_API_KEY environment variable."
    
    messages = []
    
    # Add system message for emoji usage
    messages.append({"role": "system", "content": "You are Dogbot, a helpful AI assistant with a friendly dog personality! 🐕 Use emojis frequently and Discord formatting to make your responses engaging and fun! Use **bold** for emphasis, *italics* for subtle emphasis, `code blocks` for technical terms, and > quotes for highlighting important information. Keep responses conversational and helpful! 😊✨"})
    
    # Add chat history for context if enabled
    if use_history:
        history = await get_chat_history(user_id, limit=3)  # Last 3 exchanges
        for user_msg, ai_response in history:
            messages.append({"role": "user", "content": user_msg})
            messages.append({"role": "assistant", "content": ai_response})
    
    # Add current message
    messages.append({"role": "user", "content": prompt})
    
    headers = {
        "Authorization": f"Bearer {venice_api_key}",
        "Content-Type": "application/json"
    }
    
    data = {
        "model": VENICE_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.7
    }
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(VENICE_API_URL, headers=headers, json=data)
            response.raise_for_status()
            
            result = response.json()
            return result["choices"][0]["message"]["content"].strip()
    except httpx.TimeoutException:
        return "⏰ AI response timed out. Please try again."
    except httpx.HTTPStatusError as e:
        return f"❌ AI service error: {e.response.status_code}"
    except Exception as e:
        return f"❌ Error: {str(e)}"

# Keep the old function for compatibility
async def get_ai_response(user_id: str, prompt: str, max_tokens: int = 500) -> str:
    """Get response from Venice AI, without chat history context"""
    if not venice_api_key:
        return "AI features are disabled. Please set VENICE_API_KEY environment variable."
    
    headers = {
        "Authorization": f"Bearer {venice_api_key}",
        "Content-Type": "application/json"
    }
    
    data = {
        "model": VENICE_MODEL,
        "messages": [
            {"role": "system", "content": "You are Dogbot, a helpful AI assistant with a friendly dog personality! 🐕 Use emojis frequently and Discord formatting to make your responses engaging and fun! Use **bold** for emphasis, *italics* for subtle emphasis, `code blocks` for technical terms, and > quotes for highlighting important information. Keep responses conversational and helpful! 😊✨"},
            {"role": "user", "content": prompt}
        ],
        "max_tokens": max_tokens,
        "temperature": 0.7
    }
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(VENICE_API_URL, headers=headers, json=data)
            response.raise_for_status()
            
            result = response.json()
            return result["choices"][0]["message"]["content"].strip()
    except httpx.TimeoutException:
        return "⏰ AI response timed out. Please try again."
    except httpx.HTTPStatusError as e:
        return f"❌ AI service error: {e.response.status_code}"
    except Exception as e:
        return f"❌ Error: {str(e)}"

@bot.event
async def on_ready():
    global music_bot
    if bot.user is not None:
        print(f"We are ready to go in, {bot.user.name}")
    else:
        print("We are ready to go in, but bot.user is None")
    
    # Cloud environment diagnostics for Render.com
    print("="*50)
    print("[RENDER.COM] Environment Diagnostics:")
    
    # Check if we're running on Render.com
    render_service = os.getenv('RENDER_SERVICE_NAME')
    if render_service:
        print(f"[RENDER.COM] Service Name: {render_service}")
    else:
        print("[RENDER.COM] Not detected (running locally?)")
    
    # Check FFmpeg availability
    try:
        # Prefer an explicit ffmpeg executable if available (FFMPEG_PATH or C:\\ffmpeg)
        try:
            from music import find_ffmpeg_executable
            ffmpeg_exec = find_ffmpeg_executable() or 'ffmpeg'
        except Exception:
            ffmpeg_exec = 'ffmpeg'

        result = subprocess.run([ffmpeg_exec, '-version'], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            # Extract version info
            version_lines = result.stdout.split('\n')
            version_line = version_lines[0] if version_lines else "Unknown version"
            
            print(f"[RENDER.COM] FFmpeg: {version_line}")
        else:
            print("[RENDER.COM] FFmpeg: Available but returned error")
    except FileNotFoundError:
               print("[RENDER.COM] FFmpeg: NOT FOUND")
    except Exception as e:
        print(f"[RENDER.COM] FFmpeg: Error checking - {e}")
    
    # Check Discord voice support
    try:
        if discord.opus.is_loaded():
            print("[RENDER.COM] Discord Opus: Loaded")
        else:
            print("[RENDER.COM] Discord Opus: Available but not loaded")
    except Exception as e:
        print(f"[RENDER.COM] Discord Opus: Error - {e}")
    
    print("="*50)
    
    # Initialize database
    await init_database()
    print("Chat history database initialized")
    
    # Initialize music bot
    music_bot = MusicBot(bot)
    print("Music bot initialized")

@bot.event
async def on_disconnect():
    """Called when the bot disconnects from Discord"""
    print("[DISCONNECT] ⚠️ Bot disconnected from Discord!")
    print(f"[DISCONNECT] Time: {datetime.now()}")
    
@bot.event
async def on_resumed():
    """Called when the bot resumes connection after a disconnect"""
    print("[RESUMED] ✅ Bot resumed connection to Discord!")
    print(f"[RESUMED] Time: {datetime.now()}")

@bot.event
async def on_error(event, *args, **kwargs):
    """Global error handler to catch unhandled exceptions"""
    import traceback
    print(f"[BOT_ERROR] ❌ Unhandled error in event {event}:")
    print(f"[BOT_ERROR] Time: {datetime.now()}")
    traceback.print_exc()
    
    # Try to continue running rather than crash
    print("[BOT_ERROR] Attempting to continue operation...")

@bot.event
async def on_member_join(member):
    # Get the system channel (default channel) or the first text channel
    channel = member.guild.system_channel

    if channel is None:
        # If no system channel, find the first text channel
        for ch in member.guild.text_channels:
            if ch.permissions_for(member.guild.me).send_messages:
                channel = ch
                break
    
    if channel:
        await channel.send(f"🐶 Woof woof! Welcome to the server, {member.mention}! ")

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
    
    # Just process commands, don't handle them manually here
    await bot.process_commands(message)

@bot.event
async def on_command_error(ctx, error):
    """Surface command errors so they don't look like silent failures."""
    # Ignore unknown commands to reduce noise
    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Missing argument: {error.param.name}")
        return
    try:
        await ctx.send(f"❌ Error: {error}")
    except Exception:
        pass
    # Always log traceback for debugging
    print("[COMMAND_ERROR]", type(error).__name__, "-", error)

@bot.before_invoke
async def log_command_invocation(ctx):
    try:
        user = f"{ctx.author} ({ctx.author.id})"
        cmd = ctx.command.qualified_name if ctx.command else 'unknown'
        chan = f"#{ctx.channel}"
        guild = f"{ctx.guild.name} ({ctx.guild.id})" if ctx.guild else 'DM'
        print(f"[COMMAND] {user} invoked !{cmd} in {chan} @ {guild}")
    except Exception as e:
        print(f"[COMMAND] Invocation log error: {e}")

@bot.event
async def on_voice_state_update(member, before, after):
    """Handle voice state updates - simplified to avoid reconnection loops"""
    # Only act on bot's own voice state
    if bot.user is None or member.id != bot.user.id:
        return
    
    # Just log disconnections without auto-rejoin to prevent loops
    if before.channel and after.channel is None:
        print(f"[MUSIC] Bot disconnected from voice channel {before.channel.name}")
    elif after.channel and before.channel is None:
        print(f"[MUSIC] Bot connected to voice channel {after.channel.name}")

# Helper function to check for admin/moderator permissions
def has_admin_or_moderator_role(ctx):
    """Check if user has Admin or Moderator role"""
    try:
        perms = getattr(ctx.author, 'guild_permissions', None)
        if perms and (perms.administrator or perms.manage_guild or perms.manage_roles):
            return True
        for role in getattr(ctx.author, 'roles', []):
            name = getattr(role, 'name', '').lower()
            if 'admin' in name or 'moderator' in name or name == 'mod':
                return True
        return False
    except Exception:
        return False

@bot.command()
async def chat(ctx, *, message: str):
    """Chat with the AI and optionally create polls with emoji reactions.

    This command wraps the AI call, splits long responses, and then
    (best-effort) parses any poll options from the AI's response and adds
    matching reactions. Poll parsing is heuristic and best-effort.
    """
    if not message:
        await ctx.send("❌ Please provide a message to chat with the AI.")
        return

    try:
        async with ctx.typing():
            user_id = str(ctx.author.id)
            # Use history-aware response when available
            response = await get_ai_response_with_history(user_id, message)

        sent_messages = []
        # Split long responses into 2000-char chunks and send them sequentially
        if len(response) > 2000:
            chunks = [response[i:i+2000] for i in range(0, len(response), 2000)]
            for chunk in chunks:
                m = await ctx.send(chunk)
                sent_messages.append((m, chunk))
                await asyncio.sleep(0.05)
        else:
            m = await ctx.send(response)
            sent_messages.append((m, response))

        # If the user asked to create a poll, try to parse options and add reactions
        try:
            poll_lc = message.lower()
            is_poll_request = ('poll' in poll_lc and 'create' in poll_lc) or re.search(r"\bcreate\b.*\bpoll\b", poll_lc)
            if not is_poll_request:
                return

            logging.info(f"[POLL] Detected poll request: {poll_lc[:160]}")

            # Lightweight option extractor (tries bullets, numbered lines, or comma lists)
            def extract_poll_options(text: str) -> list:
                opts = []
                # lines beginning with a bullet or digit
                for line in text.splitlines():
                    s = line.strip()
                    if not s:
                        continue
                    if re.match(r'^[\d]+[\.)]\s+', s) or s.startswith(('-', '*', '•')):
                        # strip leading marker
                        s2 = re.sub(r'^[\d]+[\.)]\s+|^[\-\*•]\s+', '', s).strip()
                        if s2:
                            opts.append(s2)
                    elif ',' in s and len(s.split(',')) <= 12:
                        parts = [p.strip() for p in s.split(',') if p.strip()]
                        if len(parts) > 1:
                            opts.extend(parts)
                # Fallback: if we found nothing, try newline tokens
                if not opts:
                    lines = [l.strip() for l in text.splitlines() if l.strip()]
                    if len(lines) > 1:
                        return lines
                return opts

            # helper to parse inline user-provided options
            def parse_inline_from_user(msg_text: str) -> list:
                parts = [p.strip() for p in re.split(r'[;,\n]', msg_text) if p.strip()]
                if len(parts) > 1:
                    return parts
                # try splitting on double spaces
                parts = [p.strip() for p in re.split(r'\s{2,}', msg_text) if p.strip()]
                return parts

            number_emojis = ['1️⃣','2️⃣','3️⃣','4️⃣','5️⃣','6️⃣','7️⃣','8️⃣','9️⃣','🔟']

            for sent_msg, chunk_text in sent_messages:
                options = extract_poll_options(chunk_text)
                if not options:
                    options = parse_inline_from_user(message)

                # sanitize & dedupe
                opts_clean = []
                seen = set()
                for o in options:
                    o_clean = re.sub(r"^(?:\d+[\.)]|[\-•\*]\s+|\d+\.)\s*", '', o).strip()
                    if o_clean and o_clean.lower() not in seen:
                        opts_clean.append(o_clean)
                        seen.add(o_clean.lower())
                    if len(opts_clean) >= 26:
                        break

                # If many tokens were pulled from the full user sentence (common when splitting
                # the prompt on commas), prefer tokens that look like times (e.g. '5pm') or
                # short option fragments. This prevents the long instruction sentence from
                # being interpreted as an option (it often contains '1-2 hours' which would
                # incorrectly map to a '1' clock).
                if opts_clean:
                    # normalize common 'other' phrasing
                    opts_clean = [o if 'other' not in o.lower() else 'Other' for o in opts_clean]

                    # collect items that look like times (contain 'am'/'pm' or standalone hour)
                    time_like = []
                    time_re = re.compile(r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm)?\b", flags=re.IGNORECASE)
                    for o in opts_clean:
                        # treat as time-like if contains pm/am or is a short digit token
                        low = o.lower()
                        if re.search(r"\b(am|pm)\b", low) or re.match(r"^\d{1,2}(?::\d{2})?$", o.strip()):
                            time_like.append(o)

                    # If we detected multiple time-like tokens among the parsed options,
                    # prefer them and drop long sentence-like entries.
                    if len(time_like) >= 2 and len(time_like) >= (len(opts_clean) // 2):
                        opts_clean = time_like

                if not opts_clean:
                    # nothing to do
                    continue

                # Emoji banks
                alpha_emojis = [chr(0x1F1E6 + i) for i in range(26)]

                # Try to detect and extract any leading emoji in each option (the AI
                # may include its own emoji labels). If present, prefer using the
                # same emoji as the reaction so labels and reactions match.
                def extract_leading_emoji(s: str):
                    """Return (emoji, rest_of_string).

                    This will detect custom discord emoji like <a:name:id>,
                    keycap sequences (e.g. 1️⃣), and common unicode emoji
                    sequences anywhere near the start. If no emoji is found,
                    returns (None, original_string).
                    
                    NOTE: Regional indicator symbols (flag letters like 🇦 🇧) are
                    intentionally excluded as they're typically list markers, not
                    meaningful poll reaction emojis.
                    """
                    if not s:
                        return None, s
                    # custom emoji like <a:name:id> at start
                    m = re.match(r'^(<a?:\w+:\d+>)\s*(.*)', s)
                    if m:
                        return m.group(1), m.group(2).strip()

                    # Try to find a keycap (e.g. 1️⃣) or digit+combining marks at start
                    m = re.match(r'^([0-9]\ufe0f?\u20e3)\s*(.*)', s)
                    if m:
                        return m.group(1), m.group(2).strip()

                    # Generic emoji regex for several common emoji blocks.
                    # Explicitly EXCLUDES regional indicator symbols (U+1F1E6-U+1F1FF)
                    # which are used for flag letters and often appear as list markers.
                    emoji_pattern = re.compile(
                        r'(^|\s)('
                        r'<a?:\w+:\d+>|'  # custom emoji
                        r'[\u2600-\u26FF]\ufe0f?|'  # Misc symbols
                        r'[\u2700-\u27BF]\ufe0f?|'  # Dingbats
                        r'[\U0001F300-\U0001F5FF]+|'  # symbols & pictographs
                        r'[\U0001F600-\U0001F64F]+|'  # emoticons
                        r'[\U0001F680-\U0001F6FF]+|'  # transport & map
                        r'[0-9]\ufe0f?\u20e3'  # keycap
                        r')', flags=re.UNICODE)

                    m2 = emoji_pattern.search(s)
                    if m2:
                        # Use the matched emoji token (strip leading space)
                        token = m2.group(2)
                        # remove the first occurrence of the token from the string
                        rest = s.replace(token, '', 1).strip()
                        return token, rest

                    # Fallback: if first character looks non-ascii and is likely emoji
                    # BUT exclude regional indicators (0x1F1E6-0x1F1FF)
                    first = s[0]
                    first_ord = ord(first)
                    if first_ord > 127 and not first.isalnum():
                        # Exclude regional indicator range
                        if not (0x1F1E6 <= first_ord <= 0x1F1FF):
                            rest = s[1:].strip()
                            return first, rest

                    return None, s

                leading = []
                stripped_labels = []
                for o in opts_clean:
                    em, rest = extract_leading_emoji(o)
                    leading.append(em)
                    stripped_labels.append(rest if rest else o)

                # Only use emojis that the AI explicitly included in the response
                reaction_emojis = []
                
                # Extract emojis the AI included, filtering out regional indicators
                for i, opt in enumerate(opts_clean):
                    lead = leading[i] if i < len(leading) else None
                    # Double-check: exclude any regional indicator symbols
                    if lead and len(lead) == 1 and 0x1F1E6 <= ord(lead) <= 0x1F1FF:
                        lead = None  # Ignore regional indicators
                    
                    if lead:
                        reaction_emojis.append(lead)

                # Add reactions using only the emojis found in AI response
                poll_debug = os.getenv('POLL_DEBUG', '0') == '1'
                
                # Filter out plain ASCII digits, None values, and regional indicators
                filtered = []
                for e in reaction_emojis:
                    if not e:
                        continue
                    # Skip plain ASCII digits
                    if len(e) == 1 and e.isdigit():
                        continue
                    # Skip regional indicators
                    if len(e) == 1 and 0x1F1E6 <= ord(e) <= 0x1F1FF:
                        continue
                    filtered.append(e)
                
                if poll_debug:
                    try:
                        await ctx.send(f"[POLL DEBUG] will add {len(filtered)} reactions: {', '.join(filtered)}")
                    except Exception:
                        pass

                for em in filtered:
                    try:
                        await sent_msg.add_reaction(em)
                        await asyncio.sleep(0.25)
                    except discord.Forbidden:
                        await ctx.send('❌ I do not have permission to add reactions. Please give me Add Reactions permission.')
                        break
                    except Exception as ex:
                        logging.exception(f"[POLL] Failed to add reaction {em}: {ex}")
                        continue
        except Exception:
            # ignore poll reaction errors
            pass

    except Exception as e:
        await ctx.send(f"❌ Error processing chat: {str(e)}")                        
@bot.command()
async def ask(ctx, *, question):
    """Ask AI a question without conversation memory"""
    if not question:
        await ctx.send("❌ Please provide a question to ask!")
        return
    
    try:
        # Show typing indicator
        async with ctx.typing():
            user_id = str(ctx.author.id)
            response = await get_ai_response(user_id, question)
        
        # Split long responses if needed
        if len(response) > 2000:
            chunks = [response[i:i+2000] for i in range(0, len(response), 2000)]
            for chunk in chunks:
                await ctx.send(chunk)
        else:
            await ctx.send(response)
            
    except Exception as e:
        await ctx.send(f"❌ Error processing question: {str(e)}")

@bot.command()
async def clear_history(ctx):
    """Clear your chat history with the AI"""
    try:
        user_id = str(ctx.author.id)
        success = await clear_user_chat_history(user_id)
        
        if success:
            await ctx.send("🗑️ Your chat history has been cleared!")
        else:
            await ctx.send("❌ Failed to clear chat history.")
            
    except Exception as e:
        await ctx.send(f"❌ Error clearing history: {str(e)}")

@bot.command()
async def history(ctx):
    """Show recent chat history"""
    try:
        user_id = str(ctx.author.id)
        history = await get_chat_history(user_id, limit=5)

        if not history:
            await ctx.send("ℹ️ No chat history found.")
            return

        embed = discord.Embed(
            title="💬 Your Recent Chat History",
            color=discord.Color.green()
        )

        for i, (user_msg, ai_response) in enumerate(history, 1):
            # Truncate long messages for display
            display_user_msg = user_msg[:100] + "..." if len(user_msg) > 100 else user_msg
            display_ai_response = ai_response[:200] + "..." if len(ai_response) > 200 else ai_response

            embed.add_field(
                name=f"💬 Exchange {i}",
                value=f"**You:** {display_user_msg}\n**Dogbot:** {display_ai_response}",
                inline=False
            )

        embed.set_footer(text="Use !clear_history to clear this history")
        await ctx.send(embed=embed)

    except Exception as e:
        await ctx.send(f"❌ Error retrieving history: {str(e)}")

@bot.command()
async def hello(ctx):
    await ctx.send(f'🐕 Woof woof! Hello {ctx.author.name}!')



# Music Bot Commands
@bot.command()
async def join(ctx):
    """Join voice channel and auto-start music"""
    if not music_bot:
        await ctx.send("❌ Music bot is not initialized!")
        return

    success = await music_bot.join_voice_channel(ctx)
    if not success:
        return
    # Auto-start music after join
    await music_bot.play_music(ctx)

@bot.command()
async def leave(ctx):
    """Leave voice channel"""
    if not music_bot:
        await ctx.send("❌ Music bot is not initialized!")
        return
    await music_bot.leave_voice_channel(ctx)

@bot.command()
async def start(ctx):
    """Start playing music"""
    if not music_bot:
        await ctx.send("❌ Music bot is not initialized!")
        return
    await music_bot.play_music(ctx)

@bot.command()
async def stop(ctx):
    """Stop playing music"""
    if not music_bot:
        await ctx.send("❌ Music bot is not initialized!")
        return
    
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.stop()
        music_bot._cleanup_guild_state(ctx.guild.id)
        await ctx.send("🛑 Music stopped!")
    else:
        await ctx.send("❌ Nothing is playing!")

@bot.command()
async def next(ctx):
    """Skip to next song"""
    if not music_bot:
        await ctx.send("❌ Music bot is not initialized!")
        return
    await music_bot.skip_song(ctx)

@bot.command()
async def skip(ctx):
    """Skip to next song (alias for !next)"""
    if not music_bot:
        await ctx.send("❌ Music bot is not initialized!")
        return
    await music_bot.skip_song(ctx)

@bot.command()
async def previous(ctx):
    """Go to previous song"""
    if not music_bot:
        await ctx.send("❌ Music bot is not initialized!")
        return
    await ctx.send("❌ Previous song not available in simplified mode!")

@bot.command()
async def play(ctx, *, url: str):
    """Play a single YouTube URL, then resume the main playlist."""
    if not music_bot:
        await ctx.send("❌ Music bot is not initialized!")
        return
    await music_bot.play_url(ctx, url)

@bot.command()
async def playlist(ctx):
    """Show current playlist"""
    if not music_bot:
        await ctx.send("❌ Music bot is not initialized!")
        return
    
    from playlist import MUSIC_PLAYLISTS
    embed = discord.Embed(
        title="🎵 Music Playlist",
        description=f"Total songs: {len(MUSIC_PLAYLISTS)}",
        color=discord.Color.blue()
    )
    embed.add_field(
        name="View Full Playlist",
        value="[🔗 Click here to view on GitHub](https://github.com/Kameonx/Dogbot/blob/main/playlist.py)",
        inline=False
    )
    await ctx.send(embed=embed)

@bot.command()
async def queue(ctx):
    """Show current playlist (alias for !playlist)"""
    if not music_bot:
        await ctx.send("❌ Music bot is not initialized!")
        return
    
    from playlist import MUSIC_PLAYLISTS
    embed = discord.Embed(
        title="🎵 Music Queue",
        description=f"Total songs: {len(MUSIC_PLAYLISTS)}",
        color=discord.Color.blue()
    )
    embed.add_field(
        name="View Full Playlist",
        value="[🔗 Click here to view on GitHub](https://github.com/Kameonx/Dogbot/blob/main/playlist.py)",
        inline=False
    )
    await ctx.send(embed=embed)

@bot.command()
async def add(ctx, *, url):
    """Add song to playlist"""
    await ctx.send("❌ Adding songs is disabled in simplified mode for stability!")

@bot.command()
async def remove(ctx, *, url):
    """Remove song from playlist"""
    await ctx.send("❌ Removing songs is disabled in simplified mode for stability!")

@bot.command()
async def nowplaying(ctx):
    """Show current song info"""
    if not music_bot:
        await ctx.send("❌ Music bot is not initialized!")
        return
    await music_bot.now_playing(ctx)

@bot.command()
async def np(ctx):
    """Show current song info (alias for !nowplaying)"""
    if not music_bot:
        await ctx.send("❌ Music bot is not initialized!")
        return
    await music_bot.now_playing(ctx)
    
@bot.command()
async def status(ctx):
    """Debug voice channel status"""
    if not music_bot:
        await ctx.send("❌ Music bot is not initialized!")
        return
    
    embed = discord.Embed(
        title="🔧 Voice Channel Status",
        color=discord.Color.orange()
    )
    
    guild_id = ctx.guild.id
    
    # Check bot's voice state
    bot_voice_state = ctx.guild.me.voice
    discord_voice_channel = bot_voice_state.channel.name if bot_voice_state and bot_voice_state.channel else "None"
    
    # Check if we have a voice client
    has_voice_client = ctx.voice_client is not None
    voice_client_connected = ctx.voice_client.is_connected() if ctx.voice_client else False
    
    # Check if music is playing
    is_playing = ctx.voice_client.is_playing() if ctx.voice_client else False
    is_paused = ctx.voice_client.is_paused() if ctx.voice_client else False
    
    # Check guild state
    guild_state = music_bot._get_guild_state(guild_id)
    current_index = guild_state.get('current_index', 0)
    playlist_length = len(guild_state.get('current_playlist', []))
    
    embed.add_field(name="Bot Voice Channel", value=discord_voice_channel or "None", inline=True)
    embed.add_field(name="Connected", value="✅ Yes" if voice_client_connected else "❌ No", inline=True)
    embed.add_field(name="Playing", value="▶️ Yes" if is_playing else "⏸️ Paused" if is_paused else "⏹️ No", inline=True)
    embed.add_field(name="Playlist Progress", value=f"{current_index + 1}/{playlist_length}" if playlist_length > 0 else "No playlist", inline=True)
    
    await ctx.send(embed=embed)











# Role Management Commands
@bot.command()
async def dogsrole(ctx):
    """Add the Dogs role to yourself"""
    role = discord.utils.get(ctx.guild.roles, name=dogs_role_name)
    if role is None:
        await ctx.send(f"❌ The '{dogs_role_name}' role doesn't exist on this server!")
        return
    
    if role in ctx.author.roles:
        await ctx.send(f"🐕 You already have the {dogs_role_name} role!")
        return
    
    try:
        await ctx.author.add_roles(role)
        await ctx.send(f"🐕 Successfully added the {dogs_role_name} role! Woof woof!")
    except discord.Forbidden:
        await ctx.send("❌ I don't have permission to assign roles!")
    except Exception as e:
        await ctx.send(f"❌ Error adding role: {e}")

@bot.command()
async def catsrole(ctx):
    """Add the Cats role to yourself"""
    role = discord.utils.get(ctx.guild.roles, name=cats_role_name)
    if role is None:
        await ctx.send(f"❌ The '{cats_role_name}' role doesn't exist on this server!")
        return
    
    if role in ctx.author.roles:
        await ctx.send(f"🐱 You already have the {cats_role_name} role!")
        return
    
    try:
        await ctx.author.add_roles(role)
        await ctx.send(f"🐱 Successfully added the {cats_role_name} role! Meow!")
    except discord.Forbidden:
        await ctx.send("❌ I don't have permission to assign roles!")
    except Exception as e:
        await ctx.send(f"❌ Error adding role: {e}")

@bot.command()
async def lizardsrole(ctx):
    """Add the Lizards role to yourself"""
    role = discord.utils.get(ctx.guild.roles, name=lizards_role_name)
    if role is None:
        await ctx.send(f"❌ The '{lizards_role_name}' role doesn't exist on this server!")
        return
    
    if role in ctx.author.roles:
        await ctx.send(f"🦎 You already have the {lizards_role_name} role!")
        return
    
    try:
        await ctx.author.add_roles(role)
        await ctx.send(f"🦎 Successfully added the {lizards_role_name} role! Hiss!")
    except discord.Forbidden:
        await ctx.send("❌ I don't have permission to assign roles!")
    except Exception as e:
        await ctx.send(f"❌ Error adding role: {e}")

@bot.command()
async def pvprole(ctx):
    """Add the PVP role to yourself"""
    role = discord.utils.get(ctx.guild.roles, name=pvp_role_name)
    if role is None:
        await ctx.send(f"❌ The '{pvp_role_name}' role doesn't exist on this server!")
        return
    
    if role in ctx.author.roles:
        await ctx.send(f"⚔️ You already have the {pvp_role_name} role!")
        return
    
    try:
        await ctx.author.add_roles(role)
        await ctx.send(f"⚔️ Successfully added the {pvp_role_name} role! Ready for battle!")
    except discord.Forbidden:
        await ctx.send("❌ I don't have permission to assign roles!")
    except Exception as e:
        await ctx.send(f"❌ Error adding role: {e}")

@bot.command()
async def elvesrole(ctx):
    """Add the Elves role to yourself"""
    role = discord.utils.get(ctx.guild.roles, name=elves_role_name)
    if role is None:
        await ctx.send(f"❌ The '{elves_role_name}' role doesn't exist on this server!")
        return
    
    if role in ctx.author.roles:
        await ctx.send(f"🧝 You already have the {elves_role_name} role!")
        return
    
    try:
        await ctx.author.add_roles(role)
        await ctx.send(f"🧝 Successfully added the {elves_role_name} role!")
    except discord.Forbidden:
        await ctx.send("❌ I don't have permission to assign roles!")
    except Exception as e:
        await ctx.send(f"❌ Error adding role: {e}")

@bot.command()
async def removedogsrole(ctx, member: Optional[discord.Member] = None):
    """Remove the Dogs role from yourself, or from @user if you're a moderator"""
    role = discord.utils.get(ctx.guild.roles, name=dogs_role_name)
    if role is None:
        await ctx.send(f"❌ The '{dogs_role_name}' role doesn't exist on this server!")
        return
    
    target = member or ctx.author
    if member is not None and not has_admin_or_moderator_role(ctx):
        await ctx.send("❌ You need Admin or Moderator role to remove roles from others!")
        return
    
    if role not in target.roles:
        await ctx.send(f"❌ {target.mention if member else 'You'} don't have the {dogs_role_name} role!")
        return
    
    try:
        await target.remove_roles(role)
        if member:
            await ctx.send(f"🐕 Successfully removed the {dogs_role_name} role from {target.mention}!")
        else:
            await ctx.send(f"🐕 Successfully removed your {dogs_role_name} role!")
    except discord.Forbidden:
        await ctx.send("❌ I don't have permission to remove roles!")
    except Exception as e:
        await ctx.send(f"❌ Error removing role: {e}")

@bot.command()
async def removecatsrole(ctx, member: Optional[discord.Member] = None):
    """Remove the Cats role from yourself, or from @user if you're a moderator"""
    role = discord.utils.get(ctx.guild.roles, name=cats_role_name)
    if role is None:
        await ctx.send(f"❌ The '{cats_role_name}' role doesn't exist on this server!")
        return
    
    target = member or ctx.author
    if member is not None and not has_admin_or_moderator_role(ctx):
        await ctx.send("❌ You need Admin or Moderator role to remove roles from others!")
        return
    
    if role not in target.roles:
        await ctx.send(f"❌ {target.mention if member else 'You'} don't have the {cats_role_name} role!")
        return
    
    try:
        await target.remove_roles(role)
        if member:
            await ctx.send(f"🐱 Successfully removed the {cats_role_name} role from {target.mention}!")
        else:
            await ctx.send(f"🐱 Successfully removed your {cats_role_name} role!")
    except discord.Forbidden:
        await ctx.send("❌ I don't have permission to remove roles!")
    except Exception as e:
        await ctx.send(f"❌ Error removing role: {e}")

@bot.command()
async def removelizardsrole(ctx, member: Optional[discord.Member] = None):
    """Remove the Lizards role from yourself, or from @user if you're a moderator"""
    role = discord.utils.get(ctx.guild.roles, name=lizards_role_name)
    if role is None:
        await ctx.send(f"❌ The '{lizards_role_name}' role doesn't exist on this server!")
        return
    
    target = member or ctx.author
    if member is not None and not has_admin_or_moderator_role(ctx):
        await ctx.send("❌ You need Admin or Moderator role to remove roles from others!")
        return
    
    if role not in target.roles:
        await ctx.send(f"❌ {target.mention if member else 'You'} don't have the {lizards_role_name} role!")
        return
    
    try:
        await target.remove_roles(role)
        if member:
            await ctx.send(f"🦎 Successfully removed the {lizards_role_name} role from {target.mention}!")
        else:
            await ctx.send(f"🦎 Successfully removed your {lizards_role_name} role!")
    except discord.Forbidden:
        await ctx.send("❌ I don't have permission to remove roles!")
    except Exception as e:
        await ctx.send(f"❌ Error removing role: {e}")

@bot.command()
async def removeelvesrole(ctx, member: Optional[discord.Member] = None):
    """Remove the Elves role from yourself, or from @user if you're a moderator"""
    role = discord.utils.get(ctx.guild.roles, name=elves_role_name)
    if role is None:
        await ctx.send(f"❌ The '{elves_role_name}' role doesn't exist on this server!")
        return
    
    target = member or ctx.author
    if member is not None and not has_admin_or_moderator_role(ctx):
        await ctx.send("❌ You need Admin or Moderator role to remove roles from others!")
        return
    
    if role not in target.roles:
        await ctx.send(f"❌ {target.mention if member else 'You'} don't have the {elves_role_name} role!")
        return
    
    try:
        await target.remove_roles(role)
        if member:
            await ctx.send(f"🧝 Successfully removed the {elves_role_name} role from {target.mention}!")
        else:
            await ctx.send(f"🧝 Successfully removed your {elves_role_name} role!")
    except discord.Forbidden:
        await ctx.send("❌ I don't have permission to remove roles!")
    except Exception as e:
        await ctx.send(f"❌ Error removing role: {e}")

@bot.command()
async def removepvprole(ctx, member: Optional[discord.Member] = None):
    """Remove the PVP role from yourself or another user (moderator only)"""
    # If no target, remove from self
    if member is None:
        role = discord.utils.get(ctx.guild.roles, name=pvp_role_name)
        if role is None:
            await ctx.send(f"❌ The '{pvp_role_name}' role doesn't exist on this server!")
            return
        
        if role not in ctx.author.roles:
            await ctx.send(f"❌ You don't have the {pvp_role_name} role!")
            return
        
        try:
            await ctx.author.remove_roles(role)
            await ctx.send(f"⚔️ Successfully removed your {pvp_role_name} role!")
        except discord.Forbidden:
            await ctx.send("❌ I don't have permission to remove roles!")
        except Exception as e:
            await ctx.send(f"❌ Error removing role: {e}")
    else:
        # Moderator removal
        if not has_admin_or_moderator_role(ctx):
            await ctx.send("❌ You need Admin or Moderator role to use this command!")
            return
        role = discord.utils.get(ctx.guild.roles, name=pvp_role_name)
        if role is None:
            await ctx.send(f"❌ The '{pvp_role_name}' role doesn't exist on this server!")
            return
        
        if role not in member.roles:
            await ctx.send(f"❌ {member.mention} doesn't have the {pvp_role_name} role!")
            return
        
        try:
            await member.remove_roles(role)
            await ctx.send(f"⚔️ Successfully removed the {pvp_role_name} role from {member.mention}!")
        except discord.Forbidden:
            await ctx.send("❌ I don't have permission to remove roles!")
        except Exception as e:
            await ctx.send(f"❌ Error removing role: {e}")

@bot.command()
async def modhelp(ctx):
    """Show moderator and utility commands"""
    embed = discord.Embed(
        title="🛠️ Moderator & Utility Commands",
        description="Advanced commands for moderators and debugging:",
        color=discord.Color.orange()
    )
    
    # Role Assignment Commands
    embed.add_field(
        name="🎭 **Role Commands (Available to All Users)**",
        value=(
            "**Add Roles:**\n"
            "`!dogsrole` - Add Dogs role 🐕\n"
            "`!catsrole` - Add Cats role 🐱\n"
            "`!lizardsrole` - Add Lizards role 🦎\n"
            "`!pvprole` - Add PVP role ⚔️\n"
            "**Remove Roles:**\n"
            "`!removedogsrole` - Remove Dogs role\n"
            "`!removecatsrole` - Remove Cats role\n"
            "`!removelizardsrole` - Remove Lizards role\n"
            "`!removepvprole` - Remove PVP role"
        ),
        inline=False
    )
    
    # Moderator Role Assignment Commands
    embed.add_field(
        name="👑 **Moderator Role Assignment**",
        value=(
            "`!assigndogsrole @username` - Assign Dogs role to user\n"
            "`!removedogsrolefrom @username` - Remove Dogs role from user\n"
            "`!assigncatsrole @username` - Assign Cats role to user\n"
            "`!removecatsrolefrom @username` - Remove Cats role from user\n"
            "`!assignlizardsrole @username` - Assign Lizards role to user\n"
            "`!removelizardsrolefrom @username` - Remove Lizards role from user\n"
            "`!assignelvesrole @username` - Assign Elves role to user\n"
            "`!removeelvesrolefrom @username` - Remove Elves role from user\n"
            "`!assignpvprole @username` - Assign PVP role to user\n"
            "`!removepvprolefrom @username` - Remove PVP role from user"
        ),
        inline=False
    )
    
    # Test & Debug Commands
    embed.add_field(
        name="🔧 **Test & Debug**",
        value=(
            "`!status` - Check voice channel status\n"
            "`!audiotest` - Test audio system components\n"
            "`!voicediag` - Detailed voice connection diagnostics"
        ),
        inline=False
    )
    
    # Chat Management
    embed.add_field(
        name="💬 **Chat Management**",
        value=(
            "`!clear_history` - Clear your chat history\n"
            "`!history` - View your recent chat history"
        ),
        inline=False
    )
    
    embed.set_footer(text="🔧 These commands help with troubleshooting and management!")
    await ctx.send(embed=embed)

## Download command removed: the bot now streams audio only.

@bot.command()
async def voicediag(ctx):
    """Diagnostic command for voice connection issues"""
    if not music_bot:
        await ctx.send("❌ Music bot is not initialized!")
        return
    
    # Check user voice state
    user_voice = ctx.author.voice
    if not user_voice:
        await ctx.send("❌ **User Status:** Not in any voice channel")
        return
    
    user_channel = user_voice.channel
    
    # Check bot voice state
    bot_voice = ctx.voice_client
    guild_voice = ctx.guild.voice_client
    
    # Check permissions
    permissions = user_channel.permissions_for(ctx.guild.me)
    
    embed = discord.Embed(title="🔧 Voice Connection Diagnostics", color=0x00ff00)
    
    # User info
    embed.add_field(
        name="👤 User Status",
        value=f"Channel: **{user_channel.name}** (ID: {user_channel.id})\nUser Count: {len(user_channel.members)}",
        inline=False
    )
    
    # Bot voice status
    bot_status = []
    if bot_voice:
        bot_status.append(f"Connected: {bot_voice.is_connected()}")
        bot_status.append(f"Channel: {bot_voice.channel.name if bot_voice.channel else 'None'}")
        bot_status.append(f"Playing: {bot_voice.is_playing()}")
        bot_status.append(f"Paused: {bot_voice.is_paused()}")
    else:
        bot_status.append("No voice client found")
    
    embed.add_field(
        name="🤖 Bot Voice Status (ctx.voice_client)",
        value="\n".join(bot_status),
        inline=True
    )
    
    # Guild voice status
    guild_status = []
    if guild_voice:
        guild_status.append(f"Connected: {guild_voice.is_connected()}")
        guild_status.append(f"Channel: {guild_voice.channel.name if guild_voice.channel else 'None'}")
        guild_status.append(f"Same client: {bot_voice is guild_voice}")
    else:
        guild_status.append("No guild voice client found")
    
    embed.add_field(
        name="🏰 Guild Voice Status",
        value="\n".join(guild_status),
        inline=True
    )
    
    # Permissions
    perm_status = []
    perm_status.append(f"Connect: {'✅' if permissions.connect else '❌'}")
    perm_status.append(f"Speak: {'✅' if permissions.speak else '❌'}")
    perm_status.append(f"Use Voice Activity: {'✅' if permissions.use_voice_activation else '❌'}")
    
    embed.add_field(
        name="🔐 Bot Permissions",
        value="\n".join(perm_status),
        inline=True
    )
    
    # Opus status
    embed.add_field(
        name="🎵 Audio System",
        value=f"Opus loaded: {'✅' if discord.opus.is_loaded() else '❌'}",
        inline=True
    )
    
    await ctx.send(embed=embed)

@bot.command()
async def audiotest(ctx):
    """Test if audio system is working (doesn't require voice connection)"""
    if not music_bot:
        await ctx.send("❌ Music bot is not initialized!")
        return
    
    try:
        # Test basic system components
        embed = discord.Embed(title="🔧 Audio System Test", color=0x00ff00)
        
        # Test Opus
        opus_status = "✅ Loaded" if discord.opus.is_loaded() else "❌ Not loaded"
        embed.add_field(name="Opus Library", value=opus_status, inline=True)
        
        # Test yt-dlp availability
        try:
            import yt_dlp
            ytdl_status = "✅ Available"
        except ImportError:
            ytdl_status = "❌ Not available"
        embed.add_field(name="yt-dlp", value=ytdl_status, inline=True)
        
    # pytube no longer used
        
        # Test FFmpeg (try to create a basic instance)
        try:
            # This tests if FFmpeg is available without actually connecting
            test_source = discord.FFmpegPCMAudio("test", before_options="-f lavfi -i anullsrc=duration=0.1", options="-vn")
            ffmpeg_status = "✅ Available"
        except Exception as e:
            ffmpeg_status = f"❌ Error: {str(e)[:50]}"
        embed.add_field(name="FFmpeg", value=ffmpeg_status, inline=True)
        
        # Test basic playlist access
        try:
            from playlist import MUSIC_PLAYLISTS
            playlist_status = f"✅ {len(MUSIC_PLAYLISTS)} songs loaded"
        except Exception as e:
            playlist_status = f"❌ Error: {str(e)[:50]}"
        embed.add_field(name="Playlist", value=playlist_status, inline=True)
        
        # Check bot's voice-related permissions (if user is in voice)
        if ctx.author.voice and ctx.author.voice.channel:
            channel = ctx.author.voice.channel
            permissions = channel.permissions_for(ctx.guild.me)
            perm_status = []
            perm_status.append(f"Connect: {'✅' if permissions.connect else '❌'}")
            perm_status.append(f"Speak: {'✅' if permissions.speak else '❌'}")
            embed.add_field(name="Voice Permissions", value="\n".join(perm_status), inline=True)
        
        await ctx.send(embed=embed)
        
    except Exception as e:
        await ctx.send(f"❌ Audio test failed: {str(e)[:100]}")

@bot.command()
async def pause(ctx):
    """Pause current song"""
    if not music_bot:
        await ctx.send("❌ Music bot is not initialized!")
        return
    await music_bot.pause_music(ctx)

@bot.command()
async def resume(ctx):
    """Resume paused song"""
    if not music_bot:
        await ctx.send("❌ Music bot is not initialized!")
        return
    await music_bot.resume_music(ctx)

@bot.command()
async def volume(ctx, volume: Optional[int] = None):
    """Check or set volume (0-100)"""
    if not music_bot:
        await ctx.send("❌ Music bot is not initialized!")
        return
    
    if volume is None:
        # Check current volume
        if not ctx.voice_client or not ctx.voice_client.source:
            await ctx.send("❌ Nothing is playing!")
            return
        
        if isinstance(ctx.voice_client.source, discord.PCMVolumeTransformer):
            current_volume = int(ctx.voice_client.source.volume * 100)
            await ctx.send(f"🔊 Current volume: {current_volume}%")
        else:
            await ctx.send("❌ Volume control not available for this audio source!")
    else:
        # Set volume
        await music_bot.set_volume(ctx, volume)

# Moderator Role Assignment Commands (for admins/moderators to assign roles to others)
@bot.command()
async def assigndogsrole(ctx, member: Optional[discord.Member] = None):
    """Assign Dogs role to a user (moderator only)"""
    if not has_admin_or_moderator_role(ctx):
        await ctx.send("❌ You need Admin or Moderator role to use this command!")
        return
    
    if member is None:
        await ctx.send("❌ Please mention a user to assign the role to! Usage: `!assigndogsrole @username`")
        return
    
    role = discord.utils.get(ctx.guild.roles, name=dogs_role_name)
    if role is None:
        await ctx.send(f"❌ The '{dogs_role_name}' role doesn't exist on this server!")
        return
    
    if role in member.roles:
        await ctx.send(f"🐕 {member.mention} already has the {dogs_role_name} role!")
        return
    
    try:
        await member.add_roles(role)
        await ctx.send(f"🐕 Successfully assigned the {dogs_role_name} role to {member.mention}! Woof woof!")
    except discord.Forbidden:
        await ctx.send("❌ I don't have permission to assign roles!")
    except Exception as e:
        await ctx.send(f"❌ Error assigning role: {e}")

@bot.command()
async def removedogsrolefrom(ctx, member: Optional[discord.Member] = None):
    """Remove Dogs role from a user (moderator only)"""
    if not has_admin_or_moderator_role(ctx):
        await ctx.send("❌ You need Admin or Moderator role to use this command!")
        return
    
    if member is None:
        await ctx.send("❌ Please mention a user to remove the role from! Usage: `!removedogsrolefrom @username`")
        return
    
    role = discord.utils.get(ctx.guild.roles, name=dogs_role_name)
    if role is None:
        await ctx.send(f"❌ The '{dogs_role_name}' role doesn't exist on this server!")
        return
    
    if role not in member.roles:
        await ctx.send(f"❌ {member.mention} doesn't have the {dogs_role_name} role!")
        return
    
    try:
        await member.remove_roles(role)
        await ctx.send(f"🐕 Successfully removed the {dogs_role_name} role from {member.mention}!")
    except discord.Forbidden:
        await ctx.send("❌ I don't have permission to remove roles!")
    except Exception as e:
        await ctx.send(f"❌ Error removing role: {e}")

@bot.command()
async def assigncatsrole(ctx, member: Optional[discord.Member] = None):
    """Assign Cats role to a user (moderator only)"""
    if not has_admin_or_moderator_role(ctx):
        await ctx.send("❌ You need Admin or Moderator role to use this command!")
        return
    
    if member is None:
        await ctx.send("❌ Please mention a user to assign the role to! Usage: `!assigncatsrole @username`")
        return
    
    role = discord.utils.get(ctx.guild.roles, name=cats_role_name)
    if role is None:
        await ctx.send(f"❌ The '{cats_role_name}' role doesn't exist on this server!")
        return
    
    if role in member.roles:
        await ctx.send(f"🐱 {member.mention} already has the {cats_role_name} role!")
        return
    
    try:
        await member.add_roles(role)
        await ctx.send(f"🐱 Successfully assigned the {cats_role_name} role to {member.mention}! Meow!")
    except discord.Forbidden:
        await ctx.send("❌ I don't have permission to assign roles!")
    except Exception as e:
        await ctx.send(f"❌ Error assigning role: {e}")

@bot.command()
async def removecatsrolefrom(ctx, member: Optional[discord.Member] = None):
    """Remove Cats role from a user (moderator only)"""
    if not has_admin_or_moderator_role(ctx):
        await ctx.send("❌ You need Admin or Moderator role to use this command!")
        return
    
    if member is None:
        await ctx.send("❌ Please mention a user to remove the role from! Usage: `!removecatsrolefrom @username`")
        return
    
    role = discord.utils.get(ctx.guild.roles, name=cats_role_name)
    if role is None:
        await ctx.send(f"❌ The '{cats_role_name}' role doesn't exist on this server!")
        return
    
    if role not in member.roles:
        await ctx.send(f"❌ {member.mention} doesn't have the {cats_role_name} role!")
        return
    
    try:
        await member.remove_roles(role)
        await ctx.send(f"🐱 Successfully removed the {cats_role_name} role from {member.mention}!")
    except discord.Forbidden:
        await ctx.send("❌ I don't have permission to remove roles!")
    except Exception as e:
        await ctx.send(f"❌ Error removing role: {e}")

@bot.command()
async def assignlizardsrole(ctx, member: Optional[discord.Member] = None):
    """Assign Lizards role to a user (moderator only)"""
    if not has_admin_or_moderator_role(ctx):
        await ctx.send("❌ You need Admin or Moderator role to use this command!")
        return
    
    if member is None:
        await ctx.send("❌ Please mention a user to assign the role to! Usage: `!assignlizardsrole @username`")
        return
    
    role = discord.utils.get(ctx.guild.roles, name=lizards_role_name)
    if role is None:
        await ctx.send(f"❌ The '{lizards_role_name}' role doesn't exist on this server!")
        return
    
    if role in member.roles:
        await ctx.send(f"🦎 {member.mention} already has the {lizards_role_name} role!")
        return
    
    try:
        await member.add_roles(role)
        await ctx.send(f"🦎 Successfully assigned the {lizards_role_name} role to {member.mention}! Hiss!")
    except discord.Forbidden:
        await ctx.send("❌ I don't have permission to assign roles!")
    except Exception as e:
        await ctx.send(f"❌ Error assigning role: {e}")

@bot.command()
async def removelizardsrolefrom(ctx, member: Optional[discord.Member] = None):
    """Remove Lizards role from a user (moderator only)"""
    if not has_admin_or_moderator_role(ctx):
        await ctx.send("❌ You need Admin or Moderator role to use this command!")
        return
    if member is None:
        await ctx.send("❌ Please mention a user to remove the role from! Usage: `!removelizardsrolefrom @username`")
        return
    role = discord.utils.get(ctx.guild.roles, name=lizards_role_name)
    if role is None:
        await ctx.send(f"❌ The '{lizards_role_name}' role doesn't exist on this server!")
        return
    if role not in member.roles:
        await ctx.send(f"❌ {member.mention} doesn't have the {lizards_role_name} role!")
        return
    try:
        await member.remove_roles(role)
        await ctx.send(f"🦎 Successfully removed the {lizards_role_name} role from {member.mention}!")
    except discord.Forbidden:
        await ctx.send("❌ I don't have permission to remove roles!")
    except Exception as e:
        await ctx.send(f"❌ Error removing role: {e}")

@bot.command()
async def assignpvprole(ctx, member: Optional[discord.Member] = None):
    """Assign PVP role to a user (moderator only)"""
    if not has_admin_or_moderator_role(ctx):
        await ctx.send("❌ You need Admin or Moderator role to use this command!")
        return
    if member is None:
        await ctx.send("❌ Please mention a user to assign the role to! Usage: `!assignpvprole @username`")
        return
    role = discord.utils.get(ctx.guild.roles, name=pvp_role_name)
    if role is None:
        await ctx.send(f"❌ The '{pvp_role_name}' role doesn't exist on this server!")
        return
    if role in member.roles:
        await ctx.send(f"⚔️ {member.mention} already has the {pvp_role_name} role!")
        return
    try:
        await member.add_roles(role)
        await ctx.send(f"⚔️ Successfully assigned the {pvp_role_name} role to {member.mention}!")
    except discord.Forbidden:
        await ctx.send("❌ I don't have permission to assign roles!")
    except Exception as e:
        await ctx.send(f"❌ Error assigning role: {e}")

@bot.command()
async def removepvprolefrom(ctx, member: Optional[discord.Member] = None):
    """Remove PVP role from a user (moderator only)"""
    if not has_admin_or_moderator_role(ctx):
        await ctx.send("❌ You need Admin or Moderator role to use this command!")
        return
    if member is None:
        await ctx.send("❌ Please mention a user to remove the role from! Usage: `!removepvprolefrom @username`")
        return
    role = discord.utils.get(ctx.guild.roles, name=pvp_role_name)
    if role is None:
        await ctx.send(f"❌ The '{pvp_role_name}' role doesn't exist on this server!")
        return
    if role not in member.roles:
        await ctx.send(f"❌ {member.mention} doesn't have the {pvp_role_name} role!")
        return
    try:
        await member.remove_roles(role)
        await ctx.send(f"⚔️ Successfully removed the {pvp_role_name} role from {member.mention}!")
    except discord.Forbidden:
        await ctx.send("❌ I don't have permission to remove roles!")
    except Exception as e:
        await ctx.send(f"❌ Error removing role: {e}")

@bot.command(aliases=["assighelvesrole"])  # keep old misspelling as alias
async def assignelvesrole(ctx, member: Optional[discord.Member] = None):
    """Assign Elves role to a user (moderator only)"""
    if not has_admin_or_moderator_role(ctx):
        await ctx.send("❌ You need Admin or Moderator role to use this command!")
        return
    if member is None:
        await ctx.send("❌ Please mention a user to assign the role to! Usage: `!assignelvesrole @username`")
        return
    role = discord.utils.get(ctx.guild.roles, name=elves_role_name)
    if role is None:
        await ctx.send(f"❌ The '{elves_role_name}' role doesn't exist on this server!")
        return
    if role in member.roles:
        await ctx.send(f"🧝 {member.mention} already has the {elves_role_name} role!")
        return
    try:
        await member.add_roles(role)
        await ctx.send(f"🧝 Successfully assigned the {elves_role_name} role to {member.mention}!")
    except discord.Forbidden:
        await ctx.send("❌ I don't have permission to assign roles!")
    except Exception as e:
        await ctx.send(f"❌ Error assigning role: {e}")

@bot.command()
async def removeelvesrolefrom(ctx, member: Optional[discord.Member] = None):
    """Remove Elves role from a user (moderator only)"""
    if not has_admin_or_moderator_role(ctx):
        await ctx.send("❌ You need Admin or Moderator role to use this command!")
        return
    if member is None:
        await ctx.send("❌ Please mention a user to remove the role from! Usage: `!removeelvesrolefrom @username`")
        return
    role = discord.utils.get(ctx.guild.roles, name=elves_role_name)
    if role is None:
        await ctx.send(f"❌ The '{elves_role_name}' role doesn't exist on this server!")
        return
    if role not in member.roles:
        await ctx.send(f"❌ {member.mention} doesn't have the {elves_role_name} role!")
        return
    try:
        await member.remove_roles(role)
        await ctx.send(f"🧝 Successfully removed the {elves_role_name} role from {member.mention}!")
    except discord.Forbidden:
        await ctx.send("❌ I don't have permission to remove roles!")
    except Exception as e:
        await ctx.send(f"❌ Error removing role: {e}")

@bot.command(name='generate')
async def generate(ctx, *, prompt: Optional[str] = None):
    """Generate an AI image using HiDream model"""
    if not prompt:
        await ctx.send("❌ Please provide a prompt for image generation!")
        return
    if not venice_api_key:
        await ctx.send("❌ AI image generation is disabled. Please set VENICE_API_KEY.")
        return
    payload = {
        "prompt": prompt,
        "model": "hidream",
        "format": "webp",
        "width": 1024,
        "height": 1024,
        "steps": 20,
        "safe_mode": True,
        "hide_watermark": True,
        "embed_exif_metadata": False,
        "return_binary": True,  # request base64 image data
        "seed": 0
    }
    headers = {"Authorization": f"Bearer {venice_api_key}", "Content-Type": "application/json"}
    try:
        async with ctx.typing():
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(IMAGE_API_URL, json=payload, headers=headers)
                resp.raise_for_status()
                # Determine if response is JSON or image data
                content_type = resp.headers.get("Content-Type", "")
                if content_type.startswith("image"):
                    img_bytes = resp.content
                    buffer = io.BytesIO(img_bytes)
                    buffer.seek(0)
                    file = discord.File(buffer, filename="image.png")
                    embed = discord.Embed(
                        title="🖼️ AI Image Generation", description=f"Prompt: {prompt}", color=discord.Color.purple()
                    )
                    embed.set_image(url="attachment://image.png")
                    await ctx.send(embed=embed, file=file)
                    return
                # Otherwise parse JSON for image URLs or base64
                data = resp.json()
                items = data.get("data", [])
                
                if not items:
                    await ctx.send("❌ No image returned from AI.")
                    return
                # Handle base64 encoded image
                b64_data = items[0].get("b64_json") or items[0].get("image") or items[0].get("base64")
                if b64_data:
                    img_bytes = base64.b64decode(b64_data)
                    buffer = io.BytesIO(img_bytes)
                    buffer.seek(0)
                    file = discord.File(buffer, filename="image.png")
                    embed = discord.Embed(
                        title="🖼️ AI Image Generation", description=f"Prompt: {prompt}", color=discord.Color.purple()
                    )
                    embed.set_image(url="attachment://image.png")
                    await ctx.send(embed=embed, file=file)
                    return
                # Fallback to URL if binary not provided
                img_url = items[0].get("url") or items[0].get("image_url")
                if img_url:
                    embed = discord.Embed(
                        title="🖼️ AI Image Generation", description=f"Prompt: {prompt}", color=discord.Color.purple()
                    )
                    embed.set_image(url=img_url)
                    await ctx.send(embed=embed)
                    return
                await ctx.send("❌ Failed to retrieve image data.")
    except httpx.HTTPStatusError as e:
        await ctx.send(f"❌ Image generation failed: {e.response.status_code}")
    except Exception as e:
        await ctx.send(f"❌ Error generating image: {e}")

# Web server setup for Render.com port binding
async def health_check(request):
    """Health check endpoint for Render.com"""
    return web.Response(text="Bot is running!")

async def init_web_server():
    """Initialize web server for Render.com"""
    app = web.Application()
    app.router.add_get('/', health_check)
    app.router.add_get('/health', health_check)
    port = int(os.getenv('PORT', 10000))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f"[RENDER] Web server started on port {port}")
    return runner

async def main():
    """Start web server and Discord bot"""
    web_runner = await init_web_server()
    print("[RENDER] Web server initialized")
    print("[DISCORD] Starting Discord bot...")
    assert token is not None, "DISCORD_TOKEN must be set"
    await bot.start(token)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("[SHUTDOWN] Bot stopped by user")
    except Exception as e:
        print(f"[SHUTDOWN] Bot stopped due to error: {e}")
