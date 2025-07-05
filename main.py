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

if token is None:
    raise ValueError("DISCORD_TOKEN environment variable not set")
if venice_api_key is None:
    print("Warning: VENICE_API_KEY not set. AI features will be disabled.")

handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True  # Needed for voice state tracking

# Bot configuration - simplified for better voice stability
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

dogs_role_name = "Dogs"
cats_role_name = "Cats"
lizards_role_name = "Lizards"
pvp_role_name = "PVP"

# HTTP Server for Render.com health checks
async def health_check(request):
    """Health check endpoint for Render.com"""
    status = {
        "status": "healthy",
        "bot_ready": bot.is_ready() if bot else False,
        "timestamp": datetime.now().isoformat(),
        "service": "dogbot-music"
    }
    return web.json_response(status, status=200)

async def root_endpoint(request):
    """Root endpoint for Render.com port detection"""
    return web.Response(text="🤖 DogBot Music Service is running!\n🎵 Discord music bot ready for action.", status=200)

async def start_http_server():
    """Start HTTP server for Render.com port binding"""
    app = web.Application()
    app.router.add_get('/', root_endpoint)
    app.router.add_get('/health', health_check)
    app.router.add_get('/status', health_check)  # Additional endpoint for status
    app.router.add_get('/ping', root_endpoint)   # Additional endpoint for ping
    
    # Use PORT environment variable (default 10000 for Render.com)
    port = int(os.getenv('PORT', 10000))
    
    try:
        runner = web.AppRunner(app)
        await runner.setup()
        # Bind to 0.0.0.0 as required by Render.com - CRITICAL
        site = web.TCPSite(runner, '0.0.0.0', port)
        await site.start()
        print(f"🌐 HTTP server bound to 0.0.0.0:{port} for Render.com")
        print(f"🔗 Service should be accessible at your-service.onrender.com")
        return True
    except Exception as e:
        print(f"❌ CRITICAL: Failed to bind HTTP server to 0.0.0.0:{port} - {e}")
        print(f"💡 This will cause Render.com deployment to fail!")
        return False

class YouTubeAudioSource(discord.PCMVolumeTransformer):
    """Audio source for YouTube streaming using yt-dlp"""
    
    def __init__(self, source, *, data, volume=0.7):  # Increased volume for Bluetooth speakers
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=True):
        """Create audio source from YouTube URL using yt-dlp with improved network error handling"""
        loop = loop or asyncio.get_event_loop()
        
        ytdl_format_options = {
            # Optimized format selection for Render.com's FFmpeg
            'format': 'bestaudio[ext=webm]/bestaudio[ext=m4a]/bestaudio',
            'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
            'restrictfilenames': True,
            'noplaylist': True,
            'nocheckcertificate': True,
            'ignoreerrors': False,
            'logtostderr': False,
            'quiet': True,
            'no_warnings': True,
            'default_search': 'auto',
            'source_address': '0.0.0.0',
            'extract_flat': False,
            'cookiefile': 'cookies.txt',
            'prefer_ffmpeg': True,
            'keepvideo': False,
            # More conservative settings for cloud stability
            'user_agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'http_chunk_size': 512000,  # Smaller chunks for cloud stability
            'socket_timeout': 30,  # Shorter timeout to avoid hanging
            'retries': 15,  # More retries for cloud reliability
            'fragment_retries': 15,  # More fragment retries
            'retry_sleep': 2,  # Shorter sleep between retries
            'max_sleep_interval': 3,
            'sleep_interval_requests': 0.5,
            'sleep_interval_subtitles': 0.5,
            # Additional stability options for cloud deployment
            'geo_bypass': True,
            'geo_bypass_country': 'US',
        }

        # For cloud deployment (Render.com), use minimal FFmpeg options
        ytdl = yt_dlp.YoutubeDL(ytdl_format_options)

        def extract_info():
            return ytdl.extract_info(url, download=False)

        try:
            # Extract video info in a thread to avoid blocking
            data = await loop.run_in_executor(None, extract_info)
            
            if data is None:
                raise ValueError("No data extracted from URL")
                
            if 'entries' in data and data['entries']:
                # Take first item from a playlist
                data = data['entries'][0]

            if not data or 'url' not in data:
                raise ValueError("No playable URL found in extracted data")

            filename = data['url'] if stream else ytdl.prepare_filename(data)
            print(f"Creating audio source from: {filename}")
            print(f"Stream mode: {stream}")
            
            # Enhanced FFmpeg options optimized for Render.com's FFmpeg
            before_options = (
                '-reconnect 1 '
                '-reconnect_streamed 1 '
                '-reconnect_delay_max 5 '
                '-rw_timeout 15000000 '
                '-loglevel error '
                '-fflags +discardcorrupt+genpts '
                '-analyzeduration 1000000 '
                '-probesize 1000000 '
                '-multiple_requests 1 '
                '-http_persistent 0 '
            )
            
            # Simplified audio processing for cloud compatibility
            options = (
                '-vn '  # No video
                '-ac 2 '  # Force stereo
                '-ar 48000 '  # High sample rate
                '-ab 128k '  # Conservative bitrate for stability
                '-acodec pcm_s16le '  # Reliable PCM encoding
                '-f s16le '  # Standard format
                '-bufsize 64k '  # Smaller buffer for cloud
            )
            
            # Create the audio source with enhanced network stability
            source = discord.FFmpegPCMAudio(
                filename,
                before_options=before_options,
                options=options
            )
            print(f"FFmpegPCMAudio source created successfully with enhanced network options")
            
            return cls(source, data=data)
            
        except Exception as e:
            print(f"Error in YouTubeAudioSource.from_url: {e}")
            # Enhanced error detection and user-friendly messages
            error_str = str(e).lower()
            if 'ffmpeg' in error_str or 'executable' in error_str:
                raise ValueError(
                    "❌ FFmpeg not found! Please install FFmpeg to use music features.\n"
                    "💡 Install instructions:\n"
                    "• Windows: Download from https://ffmpeg.org/download.html\n"
                    "• Or use chocolatey: `choco install ffmpeg`\n"
                    "• Or use winget: `winget install ffmpeg`\n"
                    "• Make sure FFmpeg is in your system PATH"
                )
            elif 'cookies' in error_str or 'cookie' in error_str:
                raise ValueError(
                    "❌ Cookies file issue! Please check your cookies.txt file.\n"
                    "💡 Tips:\n"
                    "• Export cookies from your browser using a cookies.txt extension\n"
                    "• Make sure the file is in the same directory as the bot\n"
                    "• Try refreshing the cookies file if videos stop working"
                )
            elif 'tls' in error_str or 'ssl' in error_str or 'certificate' in error_str:
                # Handle TLS/SSL errors gracefully
                raise ValueError(
                    f"🔐 Network security error: {e}\n"
                    "💡 This is usually temporary. The bot will try another song."
                )
            elif 'connection' in error_str or 'timeout' in error_str or 'network' in error_str:
                # Handle network errors gracefully
                raise ValueError(
                    f"🌐 Network connection error: {e}\n"
                    "💡 This is usually temporary. The bot will try another song."
                )
            else:
                # Generic error with helpful context
                raise ValueError(f"❌ Audio source error: {e}")
            
            # If yt-dlp fails, try fallback method
            try:
                return await cls.from_url_fallback(url, loop=loop)
            except Exception as fallback_error:
                print(f"Fallback also failed: {fallback_error}")
                # Ultimate fallback - try with absolutely minimal FFmpeg options
                try:
                    return await cls.from_url_minimal(url, loop=loop)
                except Exception as minimal_error:
                    print(f"Minimal fallback also failed: {minimal_error}")
                    raise ValueError(f"Failed to extract audio from YouTube URL: {str(e)}")

    @classmethod
    async def from_url_fallback(cls, url, *, loop=None):
        """Fallback method when primary extraction fails"""
        if loop is None:
            loop = asyncio.get_event_loop()
            
        # Simple fallback with cloud-optimized settings
        try:
            ytdl_simple = yt_dlp.YoutubeDL({
                'format': 'bestaudio[ext=webm]/bestaudio',
                'quiet': True,
                'no_warnings': True,
                'cookiefile': 'cookies.txt',
                'prefer_ffmpeg': True,
                'socket_timeout': 20,  # Shorter timeout for cloud
                'retries': 8,  # Fewer retries for faster fallback
                'fragment_retries': 8,
                'retry_sleep': 1,  # Faster retry for cloud
                'geo_bypass': True,
            })
            
            def extract_simple():
                return ytdl_simple.extract_info(url, download=False)
            
            data = await loop.run_in_executor(None, extract_simple)
            
            if data is None:
                raise ValueError("No data from fallback extraction")
                
            if 'entries' in data and data['entries']:
                data = data['entries'][0]
            
            if not data or 'url' not in data:
                raise ValueError("No playable URL in fallback data")
                
            # Enhanced fallback FFmpeg options - optimized for Render.com
            source = discord.FFmpegPCMAudio(
                data['url'],
                before_options=(
                    '-reconnect 1 '
                    '-reconnect_delay_max 3 '
                    '-rw_timeout 10000000 '
                    '-loglevel error'
                ),
                options='-vn -ac 2 -ar 48000 -ab 96k'
            )
            return cls(source, data=data)
            
        except Exception as e:
            raise ValueError(f"All extraction methods failed: {str(e)}")

    @classmethod
    async def from_url_minimal(cls, url, *, loop=None):
        """Ultimate fallback: use absolutely minimal FFmpeg options for maximum compatibility"""
        if loop is None:
            loop = asyncio.get_event_loop()
        try:
            ytdl_minimal = yt_dlp.YoutubeDL({
                'format': 'bestaudio/best',
                'quiet': True,
                'no_warnings': True,
                'cookiefile': 'cookies.txt',
                'prefer_ffmpeg': True,
                'socket_timeout': 15,  # Very short for minimal fallback
                'retries': 5,  # Minimal retries
                'geo_bypass': True,
            })
            def extract_minimal():
                return ytdl_minimal.extract_info(url, download=False)
            data = await loop.run_in_executor(None, extract_minimal)
            if data is None:
                raise ValueError("No data from minimal extraction")
            if 'entries' in data and data['entries']:
                data = data['entries'][0]
            if not data or 'url' not in data:
                raise ValueError("No playable URL in minimal data")
            # Minimal FFmpeg options optimized for Render.com cloud deployment
            source = discord.FFmpegPCMAudio(
                data['url'],
                before_options=(
                    '-reconnect 1 '
                    '-rw_timeout 8000000 '
                    '-loglevel error'
                ),
                options='-vn -ac 2 -ar 44100'
            )
            return cls(source, data=data)
        except Exception as e:
            raise ValueError(f"Minimal extraction failed: {str(e)}")

class MusicBot:
    """Music bot functionality"""
    
    def __init__(self, bot):
        self.bot = bot
        self.voice_clients = {}  # guild_id -> voice_client
        self.current_songs = {}  # guild_id -> current_song_index
        self.is_playing = {}  # guild_id -> bool
        self.shuffle_playlists = {}  # guild_id -> shuffled_playlist
        self.shuffle_positions = {}  # guild_id -> current_position_in_shuffle
        self.manual_skip_in_progress = {}  # guild_id -> bool (prevents race conditions)
        self.queued_songs = {}  # guild_id -> list of queued song URLs
        self.playing_queued_song = {}  # guild_id -> bool (tracks if currently playing a queued song)
        self.network_error_count = {}  # guild_id -> count of recent network errors
        self.last_error_time = {}  # guild_id -> timestamp of last network error
        # Voice error tracking for recovery
        self.voice_error_tracker = {}
    
    async def handle_voice_error(self, guild_id, error_type, error_msg):
        """Handle voice connection errors with recovery logic"""
        current_time = datetime.now().timestamp()
        
        # Initialize error tracking for guild
        if guild_id not in self.voice_error_tracker:
            self.voice_error_tracker[guild_id] = {
                'error_count': 0,
                'last_error_time': 0,
                'recovery_attempts': 0
            }
        
        tracker = self.voice_error_tracker[guild_id]
        
        # Reset counter if enough time has passed (10 minutes)
        if current_time - tracker['last_error_time'] > 600:
            tracker['error_count'] = 0
            tracker['recovery_attempts'] = 0
        
        tracker['error_count'] += 1
        tracker['last_error_time'] = current_time
        
        print(f"[VOICE_ERROR] Guild {guild_id} - {error_type}: {error_msg}")
        print(f"[VOICE_ERROR] Error count: {tracker['error_count']}, Recovery attempts: {tracker['recovery_attempts']}")
        
        # If too many errors, stop trying to recover
        if tracker['error_count'] > 3:
            print(f"[VOICE_ERROR] Max errors reached for guild {guild_id}, stopping recovery attempts")
            return False
        
        # Return whether recovery should be attempted
        return tracker['recovery_attempts'] < 2

    def _generate_shuffle_playlist(self, guild_id):
        """Generate a shuffled playlist for infinite looping"""
        if not MUSIC_PLAYLISTS:
            return
        
        # Create a shuffled copy of the playlist
        shuffled = MUSIC_PLAYLISTS.copy()
        random.shuffle(shuffled)
        
        self.shuffle_playlists[guild_id] = shuffled
        self.shuffle_positions[guild_id] = 0
        print(f"[SHUFFLE] Generated new shuffle playlist for guild {guild_id} with {len(shuffled)} songs")
    
    def _get_current_song_url(self, guild_id):
        """Get the current song URL from the shuffled playlist"""
        if guild_id not in self.shuffle_playlists:
            self._generate_shuffle_playlist(guild_id)
        
        if not self.shuffle_playlists[guild_id]:
            return None
            
        current_pos = self.shuffle_positions.get(guild_id, 0)
        return self.shuffle_playlists[guild_id][current_pos]
        
    async def join_voice_channel(self, ctx, auto_start=False):
        """Join voice channel with enhanced error handling for cloud deployment"""
        guild_id = ctx.guild.id
        
        # Rate limiting for join attempts to prevent spam
        cooldown_key = f"join_cooldown_{guild_id}"
        current_time = asyncio.get_event_loop().time()
        last_join_attempt = getattr(self, cooldown_key, 0)
        
        # Enforce minimum 10 second cooldown between join attempts
        if current_time - last_join_attempt < 10:
            await ctx.send("⏳ Please wait before joining again.")
            return
        
        setattr(self, cooldown_key, current_time)
        
        if guild_id in self.voice_clients:
            voice_client = self.voice_clients[guild_id]
            if voice_client.is_connected():
                await ctx.send("🎵 Already connected to voice channel!")
                if auto_start:
                    await self.play_music(ctx, from_auto_start=True)
                return
        
        try:
            # Get user's voice channel
            if not ctx.author.voice or not ctx.author.voice.channel:
                await ctx.send("❌ You need to be in a voice channel first!")
                return
            
            channel = ctx.author.voice.channel
            
            # Enhanced connection with simplified settings
            voice_client = await channel.connect(
                timeout=30.0,
                reconnect=True
            )
            
            # Store voice client
            self.voice_clients[guild_id] = voice_client
            
            await ctx.send(f"🎵 Connected to **{channel.name}**!")
            
            # Auto-start music if requested
            if auto_start:
                await ctx.send("🔄 Starting infinite music loop...")
                await self.play_music(ctx, from_auto_start=True)
                
        except Exception as e:
            # Enhanced error handling with recovery suggestions
            error_str = str(e).lower()
            if 'timeout' in error_str:
                await ctx.send("⏰ Connection timed out. Please try again.")
            elif 'permission' in error_str or 'forbidden' in error_str:
                await ctx.send("❌ I don't have permission to join that voice channel!")
            elif 'channel' in error_str:
                await ctx.send("❌ Could not connect to voice channel. Please try again.")
            else:
                await ctx.send(f"❌ Failed to join voice channel: {str(e)[:100]}...")
            
            # Clean up failed connection attempt
            if guild_id in self.voice_clients:
                del self.voice_clients[guild_id]
            
            print(f"[VOICE_JOIN] Error joining voice channel: {e}")
    
    async def leave_voice_channel(self, ctx):
        """Leave the current voice channel"""
        guild_id = ctx.guild.id
        
        # First, try to sync voice clients to get accurate state
        self._sync_voice_clients(guild_id)
        
        # Check if we have a voice client record
        voice_client = None
        if guild_id in self.voice_clients:
            voice_client = self.voice_clients[guild_id]
        
        # Also check Discord's native voice clients
        discord_voice_client = None
        for vc in self.bot.voice_clients:
            try:
                vc_guild = getattr(vc, 'guild', None)
                if vc_guild and getattr(vc_guild, 'id', None) == guild_id:
                    discord_voice_client = vc
                    break
            except Exception:
                continue
        
        # If we found a Discord voice client but not in our records, update our records
        if discord_voice_client and not voice_client:
            self.voice_clients[guild_id] = discord_voice_client
            voice_client = discord_voice_client
        
        # If still no voice client found
        if not voice_client and not discord_voice_client:
            await ctx.send("❌ I'm not in a voice channel!")
            return
        
        # Use whichever voice client we have
        client_to_disconnect = voice_client or discord_voice_client
        
        if not client_to_disconnect:
            await ctx.send("❌ No voice connection found!")
            return
        
        try:
            # Disconnect from voice channel
            await client_to_disconnect.disconnect()
            await ctx.send("👋 Disconnected from voice channel!")
        except Exception as e:
            await ctx.send(f"⚠️ Error disconnecting: {str(e)[:100]}...")
            print(f"[VOICE_LEAVE] Error disconnecting: {e}")
        
        # Clean up all data for this guild regardless of disconnect success
        if guild_id in self.voice_clients:
            del self.voice_clients[guild_id]
        if guild_id in self.current_songs:
            del self.current_songs[guild_id]
        if guild_id in self.is_playing:
            del self.is_playing[guild_id]
        if guild_id in self.shuffle_playlists:
            del self.shuffle_playlists[guild_id]
        if guild_id in self.shuffle_positions:
            del self.shuffle_positions[guild_id]
        if guild_id in self.manual_skip_in_progress:
            del self.manual_skip_in_progress[guild_id]
        
        print(f"[VOICE_CLEANUP] Cleaned up all voice data for guild {guild_id}")
    
    async def play_music(self, ctx, from_auto_start=False):
        """Start playing music from the shuffled playlist"""
        # If called from auto-start, skip the sync check since we just connected
        if not from_auto_start:
            self._sync_voice_clients(ctx.guild.id)
        
        # Get voice client (should exist since we just joined or synced)
        if ctx.guild.id not in self.voice_clients:
            await ctx.send("❌ I'm not in a voice channel! Use `!join` first.")
            return
            
        voice_client = self.voice_clients[ctx.guild.id]
        
        # Double-check if voice client is actually connected
        if not voice_client or not voice_client.is_connected():
            await ctx.send("❌ Voice client is disconnected! Use `!join` to reconnect.")
            return
        
        if not MUSIC_PLAYLISTS:
            await ctx.send("❌ No music playlist configured!")
            return
            
        # Stop current music if playing
        if voice_client.is_playing():
            voice_client.stop()
            await asyncio.sleep(0.5)
            
        # Ensure we have a shuffle playlist
        if ctx.guild.id not in self.shuffle_playlists:
            self._generate_shuffle_playlist(ctx.guild.id)
        else:
            print(f"[PLAY_MUSIC] Using existing shuffle playlist for guild {ctx.guild.id}")
            
        self.is_playing[ctx.guild.id] = True
        print(f"[PLAY_MUSIC] Set is_playing=True for guild {ctx.guild.id}")
        
        # Get current song info for feedback
        current_pos = self.shuffle_positions.get(ctx.guild.id, 0)
        total_songs = len(MUSIC_PLAYLISTS)
        
        if from_auto_start:
            await ctx.send(f"🔄 Starting infinite music loop! ({total_songs} songs in shuffle)")
        else:
            await ctx.send(f"🎵 Resuming music! Position {current_pos + 1} in shuffle")
        print(f"[PLAY_MUSIC] Starting playback for guild {ctx.guild.id}, position {current_pos + 1}")
        
        # Start playing the playlist
        await self._play_current_song(ctx.guild.id)
    
    async def stop_music(self, ctx):
        """Stop playing music"""
        if ctx.guild.id not in self.voice_clients:
            await ctx.send("❌ I'm not in a voice channel!")
            return
            
        voice_client = self.voice_clients[ctx.guild.id]
        
        if voice_client.is_playing():
            voice_client.stop()
            await asyncio.sleep(0.5)
            
        self.is_playing[ctx.guild.id] = False
        await ctx.send("🎵 Music stopped!")
    
    async def next_song(self, ctx):
        """Skip to the next song in the shuffled playlist"""
        if ctx.guild.id not in self.voice_clients:
            await ctx.send("❌ I'm not in a voice channel!")
            return
            
        if not MUSIC_PLAYLISTS:
            await ctx.send("❌ No music playlist configured!")
            return
            
        voice_client = self.voice_clients[ctx.guild.id]
        
        # Ensure we have a shuffle playlist
        if ctx.guild.id not in self.shuffle_playlists:
            self._generate_shuffle_playlist(ctx.guild.id)
        
        # Move to next song in shuffle (safe position management)
        current_pos = self.shuffle_positions.get(ctx.guild.id, 0)
        next_pos = (current_pos + 1) % len(self.shuffle_playlists[ctx.guild.id])
        
        # Check if we've completed the shuffle and need to regenerate
        if next_pos == 0:
            self._generate_shuffle_playlist(ctx.guild.id)
            await ctx.send(f"🔀 Reshuffling playlist! ⏭️ Skipping to next song...")
        else:
            await ctx.send(f"⏭️ Skipping to next song...")
        
        self.shuffle_positions[ctx.guild.id] = next_pos
        
        # Set manual skip flag with longer duration to prevent race conditions
        self.manual_skip_in_progress[ctx.guild.id] = True
        
        # Instant cleanup for manual skip - no delays for instant transitions
        if voice_client.is_playing() or voice_client.is_paused():
            print(f"[NEXT] Instant stopping current audio for manual skip...")
            voice_client.stop()
            # Brief wait to ensure stop is processed
            await asyncio.sleep(0.3)
        
        if self.is_playing.get(ctx.guild.id, False):
            # Use skip_cleanup=True since we already did cleanup above
            await self._play_current_song(ctx.guild.id, skip_cleanup=True)
        else:
            await ctx.send(f"⏭️ Next song queued. Use `!start` to play.")
        
        # Clear manual skip flag after a longer delay to avoid race conditions
        async def clear_skip_flag():
            await asyncio.sleep(2.0)  # Increased from 1.0 to 2.0 seconds
            if ctx.guild.id in self.manual_skip_in_progress:
                del self.manual_skip_in_progress[ctx.guild.id]
        
        # Schedule flag clearing
        asyncio.create_task(clear_skip_flag())
    
    async def previous_song(self, ctx):
        """Go back to the previous song in the shuffled playlist"""
        if ctx.guild.id not in self.voice_clients:
            await ctx.send("❌ I'm not in a voice channel!")
            return
            
        if not MUSIC_PLAYLISTS:
            await ctx.send("❌ No music playlist configured!")
            return
            
        voice_client = self.voice_clients[ctx.guild.id]
        
        # Ensure we have a shuffle playlist
        if ctx.guild.id not in self.shuffle_playlists:
            self._generate_shuffle_playlist(ctx.guild.id)
        
        # Move to previous song in shuffle (safe position management)
        current_pos = self.shuffle_positions.get(ctx.guild.id, 0)
        previous_pos = current_pos - 1
        
        # Handle wrap-around for previous
        if previous_pos < 0:
            previous_pos = len(self.shuffle_playlists[ctx.guild.id]) - 1
        
        self.shuffle_positions[ctx.guild.id] = previous_pos
        
        # Set manual skip flag with longer duration to prevent race conditions
        self.manual_skip_in_progress[ctx.guild.id] = True
        
        # Instant cleanup for manual skip - no delays for instant transitions
        if voice_client.is_playing() or voice_client.is_paused():
            print(f"[PREVIOUS] Instant stopping current audio for manual skip...")
            voice_client.stop()
            # Brief wait to ensure stop is processed
            await asyncio.sleep(0.3)
        
        if self.is_playing.get(ctx.guild.id, False):
            await ctx.send(f"⏮️ Going back to previous song...")
            # Use skip_cleanup=True since we already did cleanup above
            await self._play_current_song(ctx.guild.id, skip_cleanup=True)
        else:
            await ctx.send(f"⏮️ Previous song queued. Use `!start` to play.")
        
        # Clear manual skip flag after a longer delay to avoid race conditions
        async def clear_skip_flag():
            await asyncio.sleep(2.0)  # Increased from 1.0 to 2.0 seconds
            if ctx.guild.id in self.manual_skip_in_progress:
                del self.manual_skip_in_progress[ctx.guild.id]
        
        # Schedule flag clearing
        asyncio.create_task(clear_skip_flag())
    
    async def get_current_song_info(self, ctx):
        """Get information about the current song"""
        if ctx.guild.id not in self.voice_clients:
            await ctx.send("❌ I'm not in a voice channel!")
            return
            
        if not MUSIC_PLAYLISTS:
            await ctx.send("❌ No music playlist configured!")
            return
        
        # Get current song from shuffle playlist
        current_url = self._get_current_song_url(ctx.guild.id)
        if not current_url:
            await ctx.send("❌ No current song available!")
            return
            
        current_pos = self.shuffle_positions.get(ctx.guild.id, 0)
        total_songs = len(MUSIC_PLAYLISTS)
        shuffle_total = len(self.shuffle_playlists.get(ctx.guild.id, []))
        
        # Try to extract title from URL
        try:
            # Fallback to extracting from URL
            if 'youtube.com/watch?v=' in current_url:
                title = current_url.split('v=')[1].split('&')[0]
            elif 'youtu.be/' in current_url:
                title = current_url.split('youtu.be/')[1].split('?')[0]
            else:
                title = 'Unknown Title'
        except:
            title = 'Unknown Title'
        
        embed = discord.Embed(
            title="🎵 Current Song Info (Shuffle Mode)",
            color=discord.Color.blue()
        )
        embed.add_field(name="Title", value=title, inline=False)
        embed.add_field(name="Shuffle Position", value=f"{current_pos + 1} of {shuffle_total}", inline=True)
        embed.add_field(name="Total Songs", value=f"{total_songs} available", inline=True)
        embed.add_field(name="Status", value="▶️ Playing" if self.is_playing.get(ctx.guild.id, False) else "⏸️ Stopped", inline=True)
        embed.set_footer(text="🔀 Shuffle is enabled - songs play in random order")
        
        await ctx.send(embed=embed)
        # Send the YouTube URL separately so Discord embeds the video
        await ctx.send(current_url)
    
    async def _play_current_song(self, guild_id, skip_cleanup=False):
        """Play the current song (helper method for next/previous)"""
        print(f"[PLAY_CURRENT] Starting _play_current_song for guild {guild_id}")
        print(f"[PLAY_CURRENT] voice_clients has guild: {guild_id in self.voice_clients}")
        print(f"[PLAY_CURRENT] is_playing for guild: {self.is_playing.get(guild_id, False)}")
        
        if guild_id not in self.voice_clients:
            print(f"[PLAY_CURRENT] ❌ No voice client for guild {guild_id}")
            return
            
        if not self.is_playing.get(guild_id, False):
            print(f"[PLAY_CURRENT] ❌ is_playing is False for guild {guild_id}")
            return
            
        voice_client = self.voice_clients[guild_id]
        print(f"[PLAY_CURRENT] Got voice client: {voice_client}")
        
        # Add stability check to prevent rapid restarts
        current_time = asyncio.get_event_loop().time()
        if not hasattr(self, 'last_play_attempt'):
            self.last_play_attempt = {}
        
        last_attempt = self.last_play_attempt.get(guild_id, 0)
        if current_time - last_attempt < 3.0:  # Prevent rapid successive calls within 3 seconds
            print(f"[STABILITY] Preventing rapid restart for guild {guild_id} (last attempt {current_time - last_attempt:.1f}s ago)")
            return
        
        self.last_play_attempt[guild_id] = current_time
        
        # Check if voice client is still connected - improved detection
        if not voice_client or not hasattr(voice_client, 'is_connected') or not voice_client.is_connected():
            print(f"[VOICE] Voice client disconnected or invalid for guild {guild_id}")
            
            # Try to sync and find the actual voice client first
            if self._sync_voice_clients(guild_id):
                voice_client = self.voice_clients[guild_id]
                print(f"[VOICE] Synced voice client successfully")
            else:
                print(f"[VOICE] Failed to sync voice client - stopping playback")
                self.is_playing[guild_id] = False
                return
        
        # Only clean up if not already done by manual skip commands
        if not skip_cleanup:
            # Ultra-minimal cleanup for instant transitions
            if voice_client.is_playing() or voice_client.is_paused():
                voice_client.stop()
                await asyncio.sleep(0.2)
        else:
            # Even with skip_cleanup=True, do instant safety check
            if voice_client.is_playing() or voice_client.is_paused():
                voice_client.stop()
                await asyncio.sleep(0.1)
        
        max_retries = 5  # More retries for better reliability on cloud platforms
        retries = 0
        last_error = None
        
        while retries < max_retries and self.is_playing.get(guild_id, False):
            try:
                # Get current song URL from shuffled playlist
                url = self._get_current_song_url(guild_id)
                if not url:
                    print(f"[PLAY_CURRENT] No current song URL for guild {guild_id}")
                    return
                    
                print(f"[RENDER_MUSIC] Attempting to play: {url}")
                
                # Create audio source with enhanced error handling
                try:
                    player = await YouTubeAudioSource.from_url(url, loop=self.bot.loop, stream=True)
                except Exception as source_error:
                    print(f"[AUDIO_SOURCE] Failed to create audio source: {source_error}")
                    raise source_error
                
                def after_playing(error):
                    if error:
                        print(f"[PLAYBACK] Error during playback: {error}")
                    else:
                        print(f"[PLAYBACK] Song finished playing normally")
                    
                    # Only auto-advance if we're still supposed to be playing and not manually skipping
                    if (self.is_playing.get(guild_id, False) and 
                        not self.manual_skip_in_progress.get(guild_id, False)):
                        
                        # Move to next song for infinite loop
                        current_pos = self.shuffle_positions.get(guild_id, 0)
                        next_pos = (current_pos + 1) % len(self.shuffle_playlists.get(guild_id, MUSIC_PLAYLISTS))
                        
                        if next_pos == 0:
                            # Regenerate shuffle when we reach the end
                            self._generate_shuffle_playlist(guild_id)
                            print(f"[AUTO_ADVANCE] Regenerated shuffle playlist for infinite loop")
                        
                        self.shuffle_positions[guild_id] = next_pos
                        print(f"[AUTO_ADVANCE] Auto-advancing to position {next_pos + 1}")
                        
                        # Continue playing next song
                        asyncio.run_coroutine_threadsafe(
                            self._play_current_song(guild_id), 
                            self.bot.loop
                        )
                    else:
                        print(f"[AUTO_ADVANCE] Not auto-advancing (playing={self.is_playing.get(guild_id, False)}, manual_skip={self.manual_skip_in_progress.get(guild_id, False)})")
                
                # Enhanced play method with better error detection and handling
                try:
                    # Final connection stability check before playing
                    if not voice_client.is_connected():
                        raise Exception("Voice client disconnected before playing")
                    
                    # Additional check - make sure Discord can receive audio
                    if hasattr(voice_client, 'channel') and voice_client.channel:
                        print(f"[VOICE_CHECK] Connected to {voice_client.channel.name}")
                    else:
                        raise Exception("Voice client has no channel")
                    
                    # Instant check before playing to avoid "already playing" errors
                    if voice_client.is_playing() or voice_client.is_paused():
                        voice_client.stop()
                        await asyncio.sleep(0.1)
                    
                    voice_client.play(player, after=after_playing)
                    print(f"[CLOUD_MUSIC] Successfully started playing: {player.title}")
                    print(f"[DEBUG] Voice client playing status: {voice_client.is_playing()}")
                    print(f"[DEBUG] Voice client connected: {voice_client.is_connected()}")
                    return  # Success! Exit the retry loop
                    
                except Exception as play_error:
                    error_str = str(play_error).lower()
                    last_error = play_error
                    
                    if "already playing" in error_str or "source is already playing audio" in error_str:
                        print(f"[PLAY_ERROR] Already playing error - stopping current audio and retrying")
                        voice_client.stop()
                        await asyncio.sleep(0.5)
                        retries += 1
                        continue
                    else:
                        print(f"[PLAY_ERROR] Play error: {play_error}")
                        raise play_error
                        
            except Exception as e:
                current_url = self._get_current_song_url(guild_id) or "unknown"
                error_str = str(e).lower()
                print(f"[ERROR] Playing music from {current_url}: {e}")
                last_error = e
                
                # Handle unavailable video errors - skip immediately
                if any(keyword in error_str for keyword in ['video is unavailable', 'private video', 'video has been removed', 'this video is not available']):
                    print(f"[VIDEO_UNAVAILABLE] Video unavailable, skipping to next song: {current_url}")
                    current_pos = self.shuffle_positions.get(guild_id, 0)
                    self.shuffle_positions[guild_id] = (current_pos + 1) % len(self.shuffle_playlists.get(guild_id, MUSIC_PLAYLISTS))
                    # Don't increment retries for unavailable videos
                    await asyncio.sleep(0.5)
                    continue
                
                retries += 1
                
                # Handle network errors by skipping more aggressively
                if any(keyword in error_str for keyword in ['tls', 'ssl', 'network', 'connection', 'timeout']):
                    print(f"[NETWORK_SKIP] Network error detected, skipping to next song")
                    current_pos = self.shuffle_positions.get(guild_id, 0)
                    self.shuffle_positions[guild_id] = (current_pos + 1) % len(self.shuffle_playlists.get(guild_id, MUSIC_PLAYLISTS))
                    await asyncio.sleep(3)  # Longer delay for network issues
                else:
                    # Skip to next song and try again (without regenerating shuffle every time)
                    current_shuffle_pos = self.shuffle_positions.get(guild_id, 0)
                    next_shuffle_pos = (current_shuffle_pos + 1) % len(self.shuffle_playlists.get(guild_id, MUSIC_PLAYLISTS))
                    self.shuffle_positions[guild_id] = next_shuffle_pos
                    
                    # Add a delay before retrying
                    await asyncio.sleep(2)
        
        # If we exhausted all retries, try to continue with next song instead of stopping
        if self.is_playing.get(guild_id, False):
            print(f"❌ Failed to play current song after {max_retries} attempts for guild {guild_id}")
            print(f"🔄 Attempting to continue with next song instead of stopping playback")
            
            # Move to next song and try once more
            current_pos = self.shuffle_positions.get(guild_id, 0)
            self.shuffle_positions[guild_id] = (current_pos + 1) % len(self.shuffle_playlists.get(guild_id, MUSIC_PLAYLISTS))
            
            # Try one more song before giving up
            try:
                await asyncio.sleep(2)  # Brief pause before trying next song
                await self._play_current_song(guild_id)
                return  # Success with next song
            except Exception as final_error:
                print(f"❌ Final recovery attempt also failed: {final_error}")
                print(f"❌ Stopping playback to prevent infinite loops for guild {guild_id}")
                self.is_playing[guild_id] = False
    
    async def add_song(self, ctx, url):
        """Add a song to the playlist"""
        if not url:
            await ctx.send("❌ Please provide a YouTube URL!")
            return
        
        # Validate URL format
        if not url.startswith(('http://', 'https://')):
            await ctx.send("❌ Please provide a valid HTTP/HTTPS URL!")
            return
        
        # Check if it's a YouTube URL (basic validation)
        if 'youtube.com' not in url and 'youtu.be' not in url:
            await ctx.send("❌ Please provide a YouTube URL! Other platforms may not work reliably.")
            return
        
        # Extract title from URL for display
        try:
            if 'youtube.com/watch?v=' in url:
                title = url.split('v=')[1].split('&')[0]
            elif 'youtu.be/' in url:
                title = url.split('youtu.be/')[1].split('?')[0]
            else:
                title = 'Unknown Title'
        except:
            title = 'Unknown Title'
        
        # Add to playlist
        MUSIC_PLAYLISTS.append(url)
        
        embed = discord.Embed(
            title="🎵 Song Added to Playlist",
            color=discord.Color.green()
        )
        embed.add_field(name="Title", value=title, inline=False)
        embed.add_field(name="URL", value=f"[Link]({url})", inline=False)
        embed.add_field(name="Position", value=f"{len(MUSIC_PLAYLISTS)} of {len(MUSIC_PLAYLISTS)}", inline=True)
        embed.set_footer(text=f"Added by {ctx.author.display_name}")
        
        await ctx.send(embed=embed)
    
    async def remove_song(self, ctx, url):
        """Remove a song from the playlist"""
        if not url:
            await ctx.send("❌ Please provide a YouTube URL to remove!")
            return
        
        # Find and remove the URL
        try:
            index = MUSIC_PLAYLISTS.index(url)
            removed_url = MUSIC_PLAYLISTS.pop(index)
            
            # Adjust current song index if needed
            for guild_id in self.current_songs:
                if self.current_songs[guild_id] > index:
                    self.current_songs[guild_id] -= 1
                elif self.current_songs[guild_id] == index:
                    # If we removed the currently playing song, reset to beginning
                    self.current_songs[guild_id] = 0
            
            embed = discord.Embed(
                title="🗑️ Song Removed from Playlist",
                color=discord.Color.red()
            )
            embed.add_field(name="Removed URL", value=f"[Link]({removed_url})", inline=False)
            embed.add_field(name="New Playlist Size", value=f"{len(MUSIC_PLAYLISTS)} songs", inline=True)
            embed.set_footer(text=f"Removed by {ctx.author.display_name}")
            
            await ctx.send(embed=embed)
            
        except ValueError:
            await ctx.send("❌ That URL is not in the playlist! Use `!playlist` to see current songs.")
    
    async def show_playlist(self, ctx):
        """Show the current playlist"""
        embed = discord.Embed(
            title="🎵 Current Playlist",
            description=f"Total songs: {len(MUSIC_PLAYLISTS)}",
            color=discord.Color.blue()
        )
        
        embed.add_field(
            name="View Full Playlist",
            value="[🔗 Click here to view the playlist on GitHub](https://github.com/Kameonx/Dogbot/blob/main/playlist.py)",
            inline=False
        )
        
        # Show current shuffle position if available
        if ctx.guild.id in self.shuffle_positions and ctx.guild.id in self.shuffle_playlists:
            current_pos = self.shuffle_positions[ctx.guild.id]
            shuffle_total = len(self.shuffle_playlists[ctx.guild.id])
            embed.add_field(
                name="Current Position",
                value=f"Song {current_pos + 1} of {shuffle_total} (shuffled)",
                inline=True
            )
        
        # Show playing status
        if ctx.guild.id in self.is_playing:
            status = "▶️ Playing" if self.is_playing[ctx.guild.id] else "⏸️ Stopped"
            embed.add_field(name="Status", value=status, inline=True)
        
        embed.set_footer(text="🔀 Music plays in shuffle mode • Use !add <url> to add songs")
        
        await ctx.send(embed=embed)
    
    async def play_specific_url(self, ctx, url):
        """Play a specific YouTube URL immediately"""
        if ctx.guild.id not in self.voice_clients:
            await ctx.send("❌ I'm not in a voice channel! Use `!join` first.")
            return
            
        voice_client = self.voice_clients[ctx.guild.id]
        
        # Check if voice client is still connected
        if not voice_client.is_connected():
            await ctx.send("❌ Voice client is disconnected! Use `!join` to reconnect.")
            return
        
        # Validate URL format
        if not url.startswith(('http://', 'https://')):
            await ctx.send("❌ Please provide a valid HTTP/HTTPS URL!")
            return
        
        # Check if it's a YouTube URL (basic validation)
        if 'youtube.com' not in url and 'youtu.be' not in url:
            await ctx.send("❌ Please provide a YouTube URL! Other platforms may not work reliably.")
            return
        
        # Remember if we were playing a playlist before
        was_playing_playlist = self.is_playing.get(ctx.guild.id, False)
        
        # Ensure we have a shuffle playlist ready for after the specific song
        if ctx.guild.id not in self.shuffle_playlists:
            self._generate_shuffle_playlist(ctx.guild.id)
        
        # If we weren't playing before, enable playing so the playlist will start after this song
        if not was_playing_playlist:
            self.is_playing[ctx.guild.id] = True
            await ctx.send("🎵 Will start shuffled playlist after this song finishes!")
        
        # Get song title for feedback
        try:
            if 'youtube.com/watch?v=' in url:
                title = url.split('v=')[1].split('&')[0]
            elif 'youtu.be/' in url:
                title = url.split('youtu.be/')[1].split('?')[0]
            else:
                title = 'Unknown Title'
        except:
            title = 'Unknown Title'
        
        await ctx.send(f"🎵 Now Playing: {title}")
        
        # Create audio source for specific URL
        try:
            player = await YouTubeAudioSource.from_url(url, loop=self.bot.loop, stream=True)
        except Exception as e:
            await ctx.send(f"❌ Failed to load URL: {str(e)[:100]}...")
            return

        # Clean stop of any existing audio for smooth transition
        if voice_client.is_playing() or voice_client.is_paused():
            print(f"[SPECIFIC_URL] Cleanly stopping current audio for smooth transition...")
            voice_client.stop()
            # Give time for clean audio stop to prevent choppy overlap
            await asyncio.sleep(1.0)
            print(f"[SPECIFIC_URL] Audio cleanly stopped, ready for new song")
        
        # Temporarily disable shuffled playlist auto-play but remember state
        original_playing_state = self.is_playing.get(ctx.guild.id, False)
        self.is_playing[ctx.guild.id] = False
        
        # Play the specific track with intelligent resume callback
        def after_specific(error):
            if error:
                print(f"[SPECIFIC_URL] Error playing specific URL: {error}")
            else:
                print(f"[SPECIFIC_URL] Specific URL finished playing successfully")
            
            # Always try to resume playlist if it was playing before OR if user had auto-start enabled
            should_resume = original_playing_state or was_playing_playlist
            
            if should_resume:
                print(f"[SPECIFIC_URL] Resuming shuffled playlist (was_playing={original_playing_state}, had_playlist={was_playing_playlist})...")
                
                async def resume_playlist():
                    try:
                        # Re-enable playlist mode
                        self.is_playing[ctx.guild.id] = True
                        
                        # Ensure we have a valid shuffle playlist
                        if ctx.guild.id not in self.shuffle_playlists:
                            self._generate_shuffle_playlist(ctx.guild.id)
                        
                        # Resume from current shuffle position - instant resume
                        await self._play_current_song(ctx.guild.id)
                        print(f"[SPECIFIC_URL] Successfully resumed shuffled playlist")
                        
                    except Exception as resume_error:
                        print(f"[SPECIFIC_URL] Failed to resume playlist: {resume_error}")
                        # If resume fails, ensure playing state is correct
                        self.is_playing[ctx.guild.id] = False
                
                # Schedule playlist resume
                asyncio.run_coroutine_threadsafe(resume_playlist(), self.bot.loop)
            else:
                print(f"[SPECIFIC_URL] Not resuming playlist (was not playing before)")
        
        voice_client.play(player, after=after_specific)
        print(f"[SPECIFIC_URL] Started playing specific URL: {title}")
        return
    
    async def get_playback_status(self, ctx):
        """Show current playback and auto-repeat status"""
        if ctx.guild.id not in self.voice_clients:
            await ctx.send("❌ I'm not in a voice channel!")
            return
        
        voice_client = self.voice_clients[ctx.guild.id]
        guild_id = ctx.guild.id
        
        embed = discord.Embed(
            title="🎵 Playback Status",
            color=discord.Color.blue()
        )
        
        # Voice status
        embed.add_field(
            name="Voice Channel", 
            value=voice_client.channel.name if voice_client.is_connected() else "Disconnected", 
            inline=True
        )
        
        # Playing status
        current_status = "▶️ Playing" if voice_client.is_playing() else "⏸️ Stopped"
        embed.add_field(name="Current Status", value=current_status, inline=True)
        
        # Auto-play status
        auto_play = "🔄 Enabled" if self.is_playing.get(guild_id, False) else "❌ Disabled"
        embed.add_field(name="Auto-Repeat", value=auto_play, inline=True)
        
        # Shuffle info
        if guild_id in self.shuffle_playlists:
            current_pos = self.shuffle_positions.get(guild_id, 0)
            shuffle_total = len(self.shuffle_playlists[guild_id])
            embed.add_field(
                name="Shuffle Position", 
                value=f"{current_pos + 1} of {shuffle_total}", 
                inline=True
            )
        
        # Total songs available
        embed.add_field(
            name="Total Songs", 
            value=f"{len(MUSIC_PLAYLISTS)} available", 
            inline=True
        )
        
        embed.set_footer(text="♾ Infinite loop enabled • Music plays forever • Auto-shuffle on playlist end")
        
        await ctx.send(embed=embed)
    
    def _sync_voice_clients(self, guild_id):
        """Sync voice client records with actual Discord voice clients - improved reliability"""
        try:
            # Check if bot is actually connected to a voice channel
            guild = self.bot.get_guild(guild_id)
            if not guild:
                print(f"[VOICE_SYNC] Guild {guild_id} not found")
                return False
                
            # Find actual voice client from Discord.py
            found_voice_client = None
            for vc in self.bot.voice_clients:
                try:
                    # Use getattr with default to safely check guild
                    vc_guild = getattr(vc, 'guild', None)
                    if vc_guild and getattr(vc_guild, 'id', None) == guild_id:
                        # More thorough connection checking
                        if (hasattr(vc, 'is_connected') and vc.is_connected() and
                            hasattr(vc, 'channel') and vc.channel):
                            print(f"[VOICE_SYNC] Found connected voice client for guild {guild_id} in {vc.channel.name}")
                            found_voice_client = vc
                            break
                except Exception:
                    # Skip any voice clients that cause errors
                    continue
            
            if found_voice_client:
                # Update our record with the actual voice client
                self.voice_clients[guild_id] = found_voice_client
                print(f"[VOICE_SYNC] Successfully synced voice client for guild {guild_id}")
                return True
            else:
                # Check if we have a stale record
                if guild_id in self.voice_clients:
                    stored_vc = self.voice_clients[guild_id]
                    # Only report disconnection if the stored client is truly disconnected
                    if stored_vc and hasattr(stored_vc, 'is_connected'):
                        if stored_vc.is_connected():
                            print(f"[VOICE_SYNC] Stored voice client is still connected for guild {guild_id}")
                            return True
                        else:
                            print(f"[VOICE_SYNC] Stored voice client is disconnected for guild {guild_id}")
                    else:
                        print(f"[VOICE_SYNC] Invalid stored voice client for guild {guild_id}")
                print(f"[VOICE_SYNC] No active voice connection found for guild {guild_id}")
                return False
                
        except Exception as e:
            print(f"[VOICE_SYNC] Error syncing voice clients: {e}")
            return False

    async def voice_health_check(self):
        """Very conservative health check to avoid interference with voice connections"""
        reconnection_attempts = {}  # guild_id -> attempt_count
        last_reconnection_time = {}  # guild_id -> timestamp
        
        while True:
            try:
                current_time = asyncio.get_event_loop().time()
                
                for guild_id in list(self.voice_clients.keys()):
                    try:
                        voice_client = self.voice_clients[guild_id]
                        
                        # Only check if voice client exists and is truly disconnected
                        if not voice_client or not hasattr(voice_client, 'is_connected'):
                            print(f"[HEALTH_CHECK] Invalid voice client for guild {guild_id}")
                            continue
                            
                        if not voice_client.is_connected():
                            print(f"[HEALTH_CHECK] Voice client disconnected for guild {guild_id}")
                            
                            # Only attempt reconnection if we were playing and haven't tried recently
                            should_reconnect = self.is_playing.get(guild_id, False)
                            attempts = reconnection_attempts.get(guild_id, 0)
                            last_attempt = last_reconnection_time.get(guild_id, 0)
                            
                            # Very conservative reconnection: max 1 attempt, wait 5 minutes between attempts
                            if (should_reconnect and attempts < 1 and 
                                current_time - last_attempt > 300):
                                
                                print(f"[HEALTH_CHECK] Attempting single auto-reconnection for guild {guild_id}")
                                reconnection_attempts[guild_id] = attempts + 1
                                last_reconnection_time[guild_id] = current_time
                                
                                # Clean up current state
                                del self.voice_clients[guild_id]
                                self.is_playing[guild_id] = False
                                
                            else:
                                # Clean up disconnected voice client
                                del self.voice_clients[guild_id]
                                if guild_id in self.is_playing:
                                    self.is_playing[guild_id] = False
                            
                            continue
                        
                        # Reset reconnection attempts if connection is stable
                        if guild_id in reconnection_attempts:
                            reconnection_attempts[guild_id] = 0
                        
                        # NO automatic playback restart - let manual commands handle it
                        # This prevents interference with voice connections
                        
                    except Exception as guild_error:
                        print(f"[HEALTH_CHECK] Error checking guild {guild_id}: {guild_error}")
                        continue
                
                # Much longer sleep - 300 seconds (5 minutes) to minimize interference
                await asyncio.sleep(300)
                
            except Exception as e:
                print(f"[HEALTH_CHECK] Error in health check loop: {e}")
                await asyncio.sleep(180)  # 3 minute sleep on error

# Initialize music bot
music_bot = MusicBot(bot)

# Event handlers
@bot.event
async def on_ready():
    """Bot startup event"""
    print(f'🤖 Logged in as {bot.user} (ID: {bot.user.id if bot.user else "Unknown"})')
    print(f'🎵 Bot is ready! Connected to {len(bot.guilds)} servers.')
    print(f'🔊 Voice support: {discord.opus.is_loaded()}')
    print(f'🎶 Music playlists available: {len(MUSIC_PLAYLISTS)} songs')
    print('------')
    
    # Start HTTP server for Render.com health checks
    server_started = await start_http_server()
    if server_started:
        print("✅ HTTP server started successfully")
    else:
        print("❌ HTTP server failed to start - deployment may fail")
    
    # Start the voice health check loop in the background
    asyncio.create_task(music_bot.voice_health_check())
    print("🔄 Voice health check loop started")

@bot.event
async def on_voice_state_update(member, before, after):
    """Handle voice state changes"""
    # Only care about our own voice state changes
    if member != bot.user:
        return
    
    # If we were kicked or moved from a voice channel
    if before.channel and not after.channel:
        guild_id = before.channel.guild.id
        print(f"[VOICE_STATE] Bot was disconnected from voice channel in guild {guild_id}")
        
        # Clean up voice client records
        if guild_id in music_bot.voice_clients:
            del music_bot.voice_clients[guild_id]
        if guild_id in music_bot.is_playing:
            music_bot.is_playing[guild_id] = False
        
        print(f"[VOICE_STATE] Cleaned up voice data for guild {guild_id}")

@bot.event
async def on_command_error(ctx, error):
    """Handle command errors"""
    if isinstance(error, commands.CommandNotFound):
        await ctx.send("❌ Command not found! Use `!help` to see available commands.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Missing required argument: {error.param.name}")
    elif isinstance(error, commands.BadArgument):
        await ctx.send(f"❌ Invalid argument provided!")
    else:
        await ctx.send(f"❌ An error occurred: {str(error)[:100]}...")
        print(f"Command error: {error}")

# Music Commands
@bot.command(name='join', aliases=['connect'])
async def join_command(ctx):
    """Join the user's voice channel"""
    await music_bot.join_voice_channel(ctx)

@bot.command(name='leave', aliases=['disconnect'])
async def leave_command(ctx):
    """Leave the current voice channel"""
    await music_bot.leave_voice_channel(ctx)

@bot.command(name='start', aliases=['play'])
async def start_command(ctx):
    """Start playing music from the shuffled playlist"""
    await music_bot.play_music(ctx)

@bot.command(name='stop')
async def stop_command(ctx):
    """Stop playing music"""
    await music_bot.stop_music(ctx)

@bot.command(name='next', aliases=['skip'])
async def next_command(ctx):
    """Skip to the next song"""
    await music_bot.next_song(ctx)

@bot.command(name='previous', aliases=['prev', 'back'])
async def previous_command(ctx):
    """Go back to the previous song"""
    await music_bot.previous_song(ctx)

@bot.command(name='current', aliases=['now', 'playing'])
async def current_command(ctx):
    """Show information about the current song"""
    await music_bot.get_current_song_info(ctx)

@bot.command(name='status')
async def status_command(ctx):
    """Show playback status"""
    await music_bot.get_playback_status(ctx)

@bot.command(name='playlist', aliases=['queue'])
async def playlist_command(ctx):
    """Show the current playlist"""
    await music_bot.show_playlist(ctx)

@bot.command(name='add')
async def add_command(ctx, *, url):
    """Add a song to the playlist"""
    await music_bot.add_song(ctx, url)

@bot.command(name='remove')
async def remove_command(ctx, *, url):
    """Remove a song from the playlist"""
    await music_bot.remove_song(ctx, url)

@bot.command(name='playurl', aliases=['url'])
async def playurl_command(ctx, *, url):
    """Play a specific YouTube URL immediately"""
    await music_bot.play_specific_url(ctx, url)

@bot.command(name='autostart')
async def autostart_command(ctx):
    """Auto-join voice channel and start music"""
    await music_bot.join_voice_channel(ctx, auto_start=True)

# Role Commands
@bot.command(name='dog', aliases=['dogs'])
async def dog_role(ctx):
    """Get the Dogs role"""
    role = discord.utils.get(ctx.guild.roles, name=dogs_role_name)
    if role:
        if role in ctx.author.roles:
            await ctx.author.remove_roles(role)
            await ctx.send(f"🐕 Removed **{dogs_role_name}** role from {ctx.author.mention}!")
        else:
            await ctx.author.add_roles(role)
            await ctx.send(f"🐕 Added **{dogs_role_name}** role to {ctx.author.mention}!")
    else:
        await ctx.send(f"❌ **{dogs_role_name}** role not found!")

@bot.command(name='cat', aliases=['cats'])
async def cat_role(ctx):
    """Get the Cats role"""
    role = discord.utils.get(ctx.guild.roles, name=cats_role_name)
    if role:
        if role in ctx.author.roles:
            await ctx.author.remove_roles(role)
            await ctx.send(f"🐱 Removed **{cats_role_name}** role from {ctx.author.mention}!")
        else:
            await ctx.author.add_roles(role)
            await ctx.send(f"🐱 Added **{cats_role_name}** role to {ctx.author.mention}!")
    else:
        await ctx.send(f"❌ **{cats_role_name}** role not found!")

@bot.command(name='lizard', aliases=['lizards'])
async def lizard_role(ctx):
    """Get the Lizards role"""
    role = discord.utils.get(ctx.guild.roles, name=lizards_role_name)
    if role:
        if role in ctx.author.roles:
            await ctx.author.remove_roles(role)
            await ctx.send(f"🦎 Removed **{lizards_role_name}** role from {ctx.author.mention}!")
        else:
            await ctx.author.add_roles(role)
            await ctx.send(f"🦎 Added **{lizards_role_name}** role to {ctx.author.mention}!")
    else:
        await ctx.send(f"❌ **{lizards_role_name}** role not found!")

@bot.command(name='pvp')
async def pvp_role(ctx):
    """Get the PVP role"""
    role = discord.utils.get(ctx.guild.roles, name=pvp_role_name)
    if role:
        if role in ctx.author.roles:
            await ctx.author.remove_roles(role)
            await ctx.send(f"⚔️ Removed **{pvp_role_name}** role from {ctx.author.mention}!")
        else:
            await ctx.author.add_roles(role)
            await ctx.send(f"⚔️ Added **{pvp_role_name}** role to {ctx.author.mention}!")
    else:
        await ctx.send(f"❌ **{pvp_role_name}** role not found!")

# AI Chat Command
@bot.command(name='ai', aliases=['chat'])
async def ai_chat(ctx, *, message):
    """Chat with Venice AI"""
    if not venice_api_key:
        await ctx.send("❌ AI features are disabled. VENICE_API_KEY not configured.")
        return
    
    async with ctx.typing():
        try:
            # Venice AI API call
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://api.venice.ai/api/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {venice_api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": "venice",
                        "messages": [
                            {
                                "role": "system",
                                "content": "You are DogBot, a friendly Discord bot assistant. Keep responses concise and helpful."
                            },
                            {
                                "role": "user", 
                                "content": message
                            }
                        ],
                        "max_tokens": 200,
                        "temperature": 0.7
                    },
                    timeout=30.0
                )
            
            if response.status_code == 200:
                data = response.json()
                ai_response = data['choices'][0]['message']['content']
                
                # Split long responses if needed
                if len(ai_response) > 2000:
                    chunks = [ai_response[i:i+2000] for i in range(0, len(ai_response), 2000)]
                    for chunk in chunks:
                        await ctx.send(chunk)
                else:
                    await ctx.send(ai_response)
            else:
                await ctx.send("❌ AI service temporarily unavailable. Please try again later.")
                
        except Exception as e:
            await ctx.send("❌ Failed to get AI response. Please try again later.")
            print(f"AI chat error: {e}")

# Utility Commands
@bot.command(name='ping')
async def ping_command(ctx):
    """Check bot latency"""
    latency = round(bot.latency * 1000)
    await ctx.send(f"🏓 Pong! **{latency}ms**")

@bot.command(name='help')
async def help_command(ctx):
    """Show available commands"""
    embed = discord.Embed(
        title="🤖 DogBot Commands",
        description="Here are all the available commands:",
        color=discord.Color.blue()
    )
    
    # Music Commands
    embed.add_field(
        name="🎵 Music Commands",
        value=(
            "`!join` - Join your voice channel\n"
            "`!leave` - Leave voice channel\n"
            "`!start` - Start playing music\n"
            "`!stop` - Stop playing music\n"
            "`!next` - Skip to next song\n"
            "`!previous` - Go to previous song\n"
            "`!current` - Show current song\n"
            "`!status` - Show playback status\n"
            "`!playlist` - Show song list\n"
            "`!add <url>` - Add song to playlist\n"
            "`!remove <url>` - Remove song\n"
            "`!playurl <url>` - Play specific URL\n"
            "`!autostart` - Auto-join and start"
        ),
        inline=False
    )
    
    # Role Commands
    embed.add_field(
        name="🎭 Role Commands",
        value=(
            "`!dog` - Toggle Dogs role\n"
            "`!cat` - Toggle Cats role\n"
            "`!lizard` - Toggle Lizards role\n"
            "`!pvp` - Toggle PVP role"
        ),
        inline=True
    )
    
    # Other Commands
    embed.add_field(
        name="🔧 Other Commands",
        value=(
            "`!ai <message>` - Chat with AI\n"
            "`!ping` - Check bot latency\n"
            "`!help` - Show this help"
        ),
        inline=True
    )
    
    embed.set_footer(text="🎶 Music plays in infinite shuffle mode • Made with ❤️")
    
    await ctx.send(embed=embed)

# Main execution
if __name__ == "__main__":
    try:
        print("🚀 Starting DogBot...")
        print(f"🐍 Python version: {__import__('sys').version}")
        print(f"📦 Discord.py version: {discord.__version__}")
        print(f"🎵 Total songs in playlist: {len(MUSIC_PLAYLISTS)}")
        print(f"🔊 Opus loaded: {discord.opus.is_loaded()}")
        
        # Check for required environment variables
        if not token:
            print("❌ DISCORD_TOKEN environment variable not set!")
            exit(1)
        
        print("🤖 Starting bot...")
        bot.run(token, log_handler=handler, log_level=logging.WARNING)
        
    except Exception as e:
        print(f"❌ Failed to start bot: {e}")
        exit(1)
