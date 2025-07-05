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
import yt_dlp
import subprocess
from playlist import MUSIC_PLAYLISTS  # moved playlist definitions to playlist.py
from music import MusicBot, YouTubeAudioSource  # import music functionality from music.py

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

dogs_role_name = "Dogs"
cats_role_name = "Cats"
lizards_role_name = "Lizards"
pvp_role_name = "PVP"

# Initialize global variables for music functionality
music_bot = None

# YouTube Data API v3 Configuration
YOUTUBE_API_BASE_URL = "https://www.googleapis.com/youtube/v3"

# Venice AI Configuration
VENICE_API_URL = "https://api.venice.ai/api/v1/chat/completions"
VENICE_MODEL = "venice-uncensored"

# YouTube Data API v3 Configuration
YOUTUBE_API_BASE_URL = "https://www.googleapis.com/youtube/v3"

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
        result = subprocess.run(['ffmpeg', '-version'], capture_output=True, text=True, timeout=5)
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
    
    # Voice health check disabled for stability
    # asyncio.create_task(music_bot.voice_health_check())
    # print("Voice health check started")

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
    try:
        if music_bot:
            # Reset any problematic states
            for guild_id in list(music_bot.voice_clients.keys()):
                try:
                    voice_client = music_bot.voice_clients[guild_id]
                    if not voice_client.is_connected():
                        print(f"[BOT_ERROR] Cleaning up disconnected voice client for guild {guild_id}")
                        del music_bot.voice_clients[guild_id]
                        music_bot.is_playing[guild_id] = False
                except Exception as cleanup_error:
                    print(f"[BOT_ERROR] Error during cleanup: {cleanup_error}")
    except Exception as e:
        print(f"[BOT_ERROR] Error in error handler: {e}")

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

# Commented out to prevent unwanted disconnections/reconnect loops
# @bot.event
# async def on_voice_state_update(member, before, after):
#     """Track voice state changes to detect when the bot is disconnected"""
#     if member == bot.user:
#         return  # No action, rely on built-in reconnect
#     # ...voice state update logic disabled for stability...

# Helper function to check for admin/moderator permissions
def has_admin_or_moderator_role(ctx):
    """Check if user has Admin or Moderator role"""
    user_roles = [role.name.lower() for role in ctx.author.roles]
    return any(role in ['admin', 'moderator', 'administrator'] for role in user_roles)

@bot.command()
async def help(ctx):
    """Show all available commands"""
    embed = discord.Embed(
        title="🐕 Dogbot Commands",
        description="Here are all the commands you can use:",
        color=discord.Color.blue()
    )
    
    # Music Commands
    embed.add_field(
        name="🎵 **Music Commands**",
        value=(
            "`!join` - Join your voice channel and start music\n"
            "`!leave` - Leave voice channel\n"
            "`!play [url]` - Play music or specific YouTube URL\n"
            "`!stop` - Stop playing music\n"
            "`!next` / `!skip` - Skip to next song\n"
            "`!previous` - Go to previous song\n"
            "`!playlist` / `!queue` - Show current playlist\n"
            "`!add <url>` - Add song to queue\n"
            "`!remove <url>` - Remove song from queue\n"
            "`!nowplaying` / `!np` - Show current song\n"
            "`!volume [0-100]` - Check or set volume\n"
            "`!reshuffle` - Generate new shuffle order\n"
            "`!loop` - Show infinite loop status"
        ),
        inline=False
    )
    
    # AI & Chat Commands
    embed.add_field(
        name="🤖 **AI & Chat Commands**",
        value=(
            "`!chat <message>` - Chat with AI (with memory)\n"
            "`!ask <question>` - Ask AI a question (no memory)\n"
            "`!clear_history` - Clear your chat history\n"
            "`!history` - View your recent chat history"
        ),
        inline=False
    )
    
    # Utility Commands
    embed.add_field(
        name="🔧 **Utility Commands**",
        value=(
            "`!hello` - Say hello to Dogbot\n"
            "`!test` - Test bot functionality\n"
            "`!status` - Debug voice channel status\n"
            "`!audiotest` - Test audio playback\n"
            "`!bluetooth` - Optimize for Bluetooth speakers\n"
            "`!help` - Show this help message"
        ),
        inline=False
    )
    
    embed.set_footer(text="🐕 Woof! Use these commands to interact with me!")
    await ctx.send(embed=embed)

@bot.command()
async def chat(ctx, *, message):
    """Chat with AI with conversation memory"""
    if not message:
        await ctx.send("❌ Please provide a message to chat about!")
        return
    
    try:
        # Show typing indicator
        async with ctx.typing():
            user_id = str(ctx.author.id)
            response = await get_ai_response_with_history(user_id, message, use_history=True)
            
            # Save this exchange to chat history
            await save_chat_message(user_id, message, response)
        
        # Split long responses if needed
        if len(response) > 2000:
            chunks = [response[i:i+2000] for i in range(0, len(response), 2000)]
            for chunk in chunks:
                await ctx.send(chunk)
        else:
            await ctx.send(response)
            
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
    """View your recent chat history"""
    try:
        user_id = str(ctx.author.id)
        history = await get_chat_history(user_id, limit=5)
        
        if not history:
            await ctx.send("📭 Your chat history is empty!")
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

@bot.command()
async def test(ctx):
    """Test bot functionality"""
    embed = discord.Embed(
        title="🔧 Bot Test Results",
        color=discord.Color.green()
    )
    
    # Test music bot
    if music_bot:
        embed.add_field(name="Music Bot", value="✅ Initialized", inline=True)
    else:
        embed.add_field(name="Music Bot", value="❌ Not initialized", inline=True)
    
    # Test playlist
    if MUSIC_PLAYLISTS:
        embed.add_field(name="Playlist", value=f"✅ {len(MUSIC_PLAYLISTS)} songs", inline=True)
    else:
        embed.add_field(name="Playlist", value="❌ Empty", inline=True)
    
    # Test voice connection
    if music_bot and ctx.guild.id in music_bot.voice_clients:
        voice_client = music_bot.voice_clients[ctx.guild.id]
        if voice_client.is_connected():
            embed.add_field(name="Voice", value="✅ Connected", inline=True)
        else:
            embed.add_field(name="Voice", value="❌ Disconnected", inline=True)
    else:
        embed.add_field(name="Voice", value="❌ Not connected", inline=True)
    
    embed.set_footer(text="Use !join to start music")
    await ctx.send(embed=embed)

# Music Bot Commands
@bot.command()
async def join(ctx):
    """Join voice channel and auto-start music"""
    if not music_bot:
        await ctx.send("❌ Music bot is not initialized!")
        return
    await music_bot.join_voice_channel(ctx, auto_start=True)

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
    await music_bot.stop_music(ctx)

@bot.command()
async def next(ctx):
    """Skip to next song"""
    if not music_bot:
        await ctx.send("❌ Music bot is not initialized!")
        return
    await music_bot.next_song(ctx)

@bot.command()
async def skip(ctx):
    """Skip to next song (alias for !next)"""
    if not music_bot:
        await ctx.send("❌ Music bot is not initialized!")
        return
    await music_bot.next_song(ctx)

@bot.command()
async def previous(ctx):
    """Go to previous song"""
    if not music_bot:
        await ctx.send("❌ Music bot is not initialized!")
        return
    await music_bot.previous_song(ctx)

@bot.command()
async def play(ctx, *, url=None):
    """Play music or specific URL"""
    if not music_bot:
        await ctx.send("❌ Music bot is not initialized!")
        return
    
    if url:
        await music_bot.play_specific_url(ctx, url)
    else:
        await music_bot.play_music(ctx)

@bot.command()
async def playlist(ctx):
    """Show current playlist"""
    if not music_bot:
        await ctx.send("❌ Music bot is not initialized!")
        return
    await music_bot.show_playlist(ctx)

@bot.command()
async def queue(ctx):
    """Show current playlist (alias for !playlist)"""
    if not music_bot:
        await ctx.send("❌ Music bot is not initialized!")
        return
    await music_bot.show_playlist(ctx)

@bot.command()
async def add(ctx, *, url):
    """Add song to playlist"""
    if not music_bot:
        await ctx.send("❌ Music bot is not initialized!")
        return
    await music_bot.add_song(ctx, url)

@bot.command()
async def remove(ctx, *, url):
    """Remove song from playlist"""
    if not music_bot:
        await ctx.send("❌ Music bot is not initialized!")
        return
    await music_bot.remove_song(ctx, url)

@bot.command()
async def nowplaying(ctx):
    """Show current song info"""
    if not music_bot:
        await ctx.send("❌ Music bot is not initialized!")
        return
    await music_bot.get_current_song_info(ctx)

@bot.command()
async def np(ctx):
    """Show current song info (alias for !nowplaying)"""
    if not music_bot:
        await ctx.send("❌ Music bot is not initialized!")
        return
    await music_bot.get_current_song_info(ctx)
    
@bot.command()
async def status(ctx):
    """Debug voice channel status"""
    if not music_bot:
        await ctx.send("❌ Music bot is not initialized!")
        return
    
    embed = discord.Embed(
        title="🔧 Voice Channel Debug Status",
        color=discord.Color.orange()
    )
    
    guild_id = ctx.guild.id
    
    # Check bot's voice state
    bot_voice_state = ctx.guild.me.voice
    discord_voice_channel = bot_voice_state.channel.name if bot_voice_state and bot_voice_state.channel else "None"
    
    # Check our voice client record
    has_voice_client = guild_id in music_bot.voice_clients
    voice_client_connected = False
    if has_voice_client:
        try:
            voice_client_connected = music_bot.voice_clients[guild_id].is_connected()
        except:
            voice_client_connected = False
    
    # Check Discord's native voice clients
    discord_voice_clients = []
    for vc in bot.voice_clients:
        try:
            # Use getattr with default to safely check guild
            vc_guild = getattr(vc, 'guild', None)
            if vc_guild and getattr(vc_guild, 'id', None) == guild_id:
                discord_voice_clients.append(vc)
        except Exception:
            # Skip any voice clients that cause errors
            continue
    
    embed.add_field(name="Bot Voice Channel", value=discord_voice_channel or "None", inline=True)
    embed.add_field(name="Has Voice Client Record", value="✅ Yes" if has_voice_client else "❌ No", inline=True)
    embed.add_field(name="Voice Client Connected", value="✅ Yes" if voice_client_connected else "❌ No", inline=True)
    embed.add_field(name="Total Voice Clients", value=str(len(discord_voice_clients)), inline=True)
    embed.add_field(name="Playing Status", value="▶️ Playing" if music_bot.is_playing.get(guild_id, False) else "⏸️ Stopped", inline=True)
    embed.add_field(name="Manual Skip Active", value="🔄 Yes" if music_bot.manual_skip_in_progress.get(guild_id, False) else "❌ No", inline=True)
    
    await ctx.send(embed=embed)

@bot.command()
async def loop(ctx):
    """Show infinite loop status and statistics"""
    if not music_bot:
        await ctx.send("❌ Music bot is not initialized!")
        return
    
    guild_id = ctx.guild.id
    
    embed = discord.Embed(
        title="🔄 Infinite Loop Status",
        color=discord.Color.green()
    )
    
    # Playing status
    is_playing = music_bot.is_playing.get(guild_id, False)
    embed.add_field(
        name="🎵 Current Status", 
        value="🔄 **INFINITE LOOP ACTIVE**" if is_playing else "⏹️ Stopped", 
        inline=False
    )
    
    # Playlist info
    total_songs = len(MUSIC_PLAYLISTS)
    embed.add_field(name="📚 Total Songs", value=f"{total_songs} songs available", inline=True)
    
    if guild_id in music_bot.shuffle_playlists:
        current_pos = music_bot.shuffle_positions.get(guild_id, 0)
        shuffle_total = len(music_bot.shuffle_playlists[guild_id])
        embed.add_field(
            name="🔀 Current Shuffle",
            value=f"Position {current_pos + 1} of {shuffle_total}",
            inline=True
        )
        
        # Calculate how many times the playlist has looped
        if guild_id in music_bot.current_songs:
            # This is a rough estimate based on position
            loops_completed = current_pos // total_songs if total_songs > 0 else 0
            embed.add_field(
                name="♾️ Loops Completed",
                value=f"~{loops_completed} full loops",
                inline=True
            )
    
    # Voice status
    if guild_id in music_bot.voice_clients:
        voice_client = music_bot.voice_clients[guild_id]
        if voice_client.is_connected():
            embed.add_field(
                name="🔊 Voice Status",
                value=f"Connected to {voice_client.channel.name}",
                inline=False
            )
        else:
            embed.add_field(name="🔊 Voice Status", value="❌ Disconnected", inline=False)
    else:
        embed.add_field(name="🔊 Voice Status", value="❌ Not in voice channel", inline=False)
    
    embed.set_footer(text="🔄 Music will automatically loop forever when playing • Use !stop to disable")
    
    await ctx.send(embed=embed)

@bot.command()
async def reshuffle(ctx):
    """Generate new shuffle order"""
    if not music_bot:
        await ctx.send("❌ Music bot is not initialized!")
        return
    
    if ctx.guild.id in music_bot.shuffle_playlists:
        music_bot._generate_shuffle_playlist(ctx.guild.id)
        await ctx.send("🔀 Generated new shuffle order! Use `!next` to skip to a new song.")
    else:
        await ctx.send("❌ No active shuffle playlist found!")

@bot.command()
async def volume(ctx, vol: Optional[int] = None):
    """Check or set the music volume (0-100)"""
    if not music_bot:
        await ctx.send("❌ Music bot is not initialized!")
        return
    
    if ctx.guild.id not in music_bot.voice_clients:
        await ctx.send("❌ I'm not in a voice channel!")
        return
    
    voice_client = music_bot.voice_clients[ctx.guild.id]
    
    if vol is None:
        # Just check current volume
        if voice_client.source:
            current_vol = int(voice_client.source.volume * 100)
            await ctx.send(f"🔊 Current volume: {current_vol}%")
        else:
            await ctx.send("🔊 No audio source active")
        return
    
    # Set volume
    if vol < 0 or vol > 100:
        await ctx.send("❌ Volume must be between 0 and 100!")
        return
    
    if voice_client.source:
        voice_client.source.volume = vol / 100.0
        await ctx.send(f"🔊 Volume set to {vol}%")
    else:
        await ctx.send("❌ No audio source active to adjust volume")

@bot.command()
async def audiotest(ctx):
    """Test audio playback with debug info"""
    if not music_bot:
        await ctx.send("❌ Music bot is not initialized!")
        return
    
    if ctx.guild.id not in music_bot.voice_clients:
        await ctx.send("❌ I'm not in a voice channel!")
        return
    
    voice_client = music_bot.voice_clients[ctx.guild.id]
    
    embed = discord.Embed(
        title="🔊 Audio Debug Test",
        color=discord.Color.blue()
    )
    
    # Voice client status
    embed.add_field(name="Connected", value="✅ Yes" if voice_client.is_connected() else "❌ No", inline=True)
    embed.add_field(name="Playing", value="▶️ Yes" if voice_client.is_playing() else "⏸️ No", inline=True)
    embed.add_field(name="Paused", value="⏸️ Yes" if voice_client.is_paused() else "▶️ No", inline=True)
    
    # Channel info
    if voice_client.is_connected():
        embed.add_field(name="Channel", value=voice_client.channel.name, inline=True)
        embed.add_field(name="Channel Members", value=len(voice_client.channel.members), inline=True)
    
    # Volume info
    if voice_client.source:
        volume = int(voice_client.source.volume * 100)
        embed.add_field(name="Volume", value=f"{volume}%", inline=True)
    else:
        embed.add_field(name="Volume", value="No audio source", inline=True)
    
    # Bot's audio state
    is_playing = music_bot.is_playing.get(ctx.guild.id, False)
    embed.add_field(name="Bot State", value="🔄 Playing" if is_playing else "⏹️ Stopped", inline=True)
    
    embed.set_footer(text="Use this to debug why you might not hear audio")
    await ctx.send(embed=embed)

@bot.command()
async def bluetooth(ctx):
    """Optimize audio settings for Bluetooth speakers"""
    if not music_bot:
        await ctx.send("❌ Music bot is not initialized!")
        return
    
    if ctx.guild.id not in music_bot.voice_clients:
        await ctx.send("❌ I'm not in a voice channel!")
        return

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
