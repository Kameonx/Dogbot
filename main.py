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

# YouTube Data API v3 Configuration
YOUTUBE_API_BASE_URL = "https://www.googleapis.com/youtube/v3"

# HTTP Server for Render.com health checks
async def health_check(request):
    """Health check endpoint for Render.com"""
    return web.Response(text="Bot is running!", status=200)

async def start_http_server():
    """Start HTTP server for Render.com port binding"""
    app = web.Application()
    app.router.add_get('/', health_check)
    app.router.add_get('/health', health_check)
    
    # Use PORT environment variable or default to 8080
    port = int(os.getenv('PORT', 8080))
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f"🌐 HTTP server started on port {port} for Render.com")

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
                    # Final fallback - get metadata from YouTube API if available
                    if youtube_api:
                        try:
                            video_id = youtube_api.extract_video_id(url)
                            if video_id:
                                video_details = await youtube_api.get_video_details(video_id)
                                title = video_details['snippet']['title'] if video_details else 'Unknown Title'
                                raise ValueError(f"Failed to extract audio from: {title}")
                        except:
                            pass
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
    
    def _generate_shuffle_playlist(self, guild_id):
        """Generate a new shuffled playlist for the guild"""
        if not MUSIC_PLAYLISTS:
            print(f"⚠️ No songs in MUSIC_PLAYLISTS for guild {guild_id}")
            return
        
        # Filter out any empty or invalid URLs
        valid_urls = [url for url in MUSIC_PLAYLISTS if url and url.strip() and ('youtube.com' in url or 'youtu.be' in url)]
        
        if not valid_urls:
            print(f"⚠️ No valid YouTube URLs found in playlist for guild {guild_id}")
            return
            
        # Create a shuffled copy of the playlist
        shuffled = valid_urls.copy()
        random.shuffle(shuffled)
        
        self.shuffle_playlists[guild_id] = shuffled
        self.shuffle_positions[guild_id] = 0
        print(f"🔀 Generated new shuffle playlist for guild {guild_id} with {len(shuffled)} songs")
        
        # Ensure continuous playback - if we're currently playing, this is a regeneration
        if self.is_playing.get(guild_id, False):
            print(f"🔄 Playlist regenerated during playback - continuous music ensured")
    
    def _get_current_song_url(self, guild_id):
        """Get the current song URL - prioritizes queued songs, then shuffled playlist"""
        # Check if there are queued songs first
        if guild_id in self.queued_songs and self.queued_songs[guild_id]:
            queued_url = self.queued_songs[guild_id].pop(0)  # Get first queued song
            self.playing_queued_song[guild_id] = True
            print(f"🎵 Playing queued song: {queued_url}")
            return queued_url
        
        # Reset queued song flag if no more queued songs
        self.playing_queued_song[guild_id] = False
        
        # Continue with normal shuffled playlist
        if guild_id not in self.shuffle_playlists or not self.shuffle_playlists[guild_id]:
            self._generate_shuffle_playlist(guild_id)
        
        if guild_id not in self.shuffle_playlists or not self.shuffle_playlists[guild_id]:
            print(f"⚠️ No songs available for guild {guild_id} - playlist may be empty")
            return None
            
        position = self.shuffle_positions.get(guild_id, 0)
        playlist = self.shuffle_playlists[guild_id]
        
        if position >= len(playlist):
            # Regenerate shuffle when we reach the end (infinite loop)
            print(f"🔄 Reached end of playlist, regenerating for infinite loop (guild {guild_id})")
            self._generate_shuffle_playlist(guild_id)
            position = 0
            # Update the position after regeneration
            self.shuffle_positions[guild_id] = position
            playlist = self.shuffle_playlists[guild_id]
        
        # Ensure position is valid after all checks
        if position < len(playlist):
            return playlist[position]
        else:
            print(f"⚠️ Position {position} out of bounds for playlist length {len(playlist)} in guild {guild_id}")
            return None
        
    async def join_voice_channel(self, ctx, auto_start=False):
        """Join the voice channel of the user who called the command"""
        if not ctx.author.voice:
            await ctx.send("❌ You need to be in a voice channel to use this command!")
            return None
            
        channel = ctx.author.voice.channel
        guild_id = ctx.guild.id
        
        # Add connection cooldown to prevent rapid reconnection attempts
        cooldown_key = f"join_cooldown_{guild_id}"
        current_time = asyncio.get_event_loop().time()
        last_join_attempt = getattr(self, cooldown_key, 0)
        
        # Enforce minimum 10 second cooldown between join attempts
        if current_time - last_join_attempt < 10:
            remaining = 10 - (current_time - last_join_attempt)
            await ctx.send(f"⏳ Please wait {remaining:.1f} seconds before attempting to join again.")
            return None
        
        setattr(self, cooldown_key, current_time)
        
        if guild_id in self.voice_clients:
            voice_client = self.voice_clients[guild_id]
            # Check if voice client is still connected
            if voice_client.is_connected():
                if voice_client.channel == channel:
                    if auto_start:
                        await ctx.send("🎵 I'm already in your voice channel! Starting music...")
                        if not self.is_playing.get(guild_id, False):
                            await self.play_music(ctx, from_auto_start=True)
                    else:
                        await ctx.send("🎵 I'm already in your voice channel!")
                    return voice_client
                else:
                    try:
                        await voice_client.move_to(channel)
                        if auto_start:
                            await ctx.send(f"🎵 Moved to {channel.name} and starting music!")
                            if not self.is_playing.get(guild_id, False):
                                await self.play_music(ctx, from_auto_start=True)
                        else:
                            await ctx.send(f"🎵 Moved to {channel.name}!")
                        return voice_client
                    except Exception as e:
                        print(f"[VOICE] Failed to move to channel {channel.name}: {e}")
                        # Clean up and try fresh connection
                        del self.voice_clients[guild_id]
            else:
                # Clean up disconnected voice client
                print(f"[VOICE] Cleaning up disconnected voice client for guild {guild_id}")
                del self.voice_clients[guild_id]
        
        try:
            print(f"[VOICE] Attempting to connect to {channel.name} in guild {guild_id}")
            print(f"[VOICE] Bot has permissions: {channel.permissions_for(ctx.guild.me)}")
            voice_client = await channel.connect()
            print(f"[VOICE] Successfully connected to {channel.name}")
            print(f"[VOICE] Voice client connected status: {voice_client.is_connected()}")
            
            # Add delay to ensure connection is stable
            await asyncio.sleep(2)
            
            # Verify connection is still active
            if not voice_client.is_connected():
                print(f"[VOICE] Connection failed immediately after connect for guild {guild_id}")
                await ctx.send("❌ Failed to establish stable voice connection. Please try again.")
                return None
            
            # Store voice client after verification
            self.voice_clients[guild_id] = voice_client
            
            # Generate initial shuffle playlist and start at random position
            self._generate_shuffle_playlist(guild_id)
            # Start at a random position in the shuffled playlist
            if self.shuffle_playlists.get(guild_id):
                self.shuffle_positions[guild_id] = random.randint(0, len(self.shuffle_playlists[guild_id]) - 1)
            
            self.current_songs[guild_id] = 0
            self.is_playing[guild_id] = False
            self.manual_skip_in_progress[guild_id] = False  # Initialize flag
            # Initialize queue properties
            if guild_id not in self.queued_songs:
                self.queued_songs[guild_id] = []
            if guild_id not in self.playing_queued_song:
                self.playing_queued_song[guild_id] = False
            
            # Reset network error tracking for fresh start
            self.network_error_count[guild_id] = 0
            self.last_error_time[guild_id] = 0
            
            if auto_start:
                await ctx.send(f"🎵 Joined {channel.name} and starting music in shuffle mode!")
                # Give more time for voice client to fully stabilize
                await asyncio.sleep(3)
                await self.play_music(ctx, from_auto_start=True)
            else:
                await ctx.send(f"🎵 Joined {channel.name}! Ready to play music in shuffle mode!")
            return voice_client
        except Exception as e:
            print(f"[VOICE] Connection failed with error: {e}")
            await ctx.send(f"❌ Failed to join voice channel: {e}")
            return None
    
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
                # Use getattr with default to safely check guild
                vc_guild = getattr(vc, 'guild', None)
                if vc_guild and getattr(vc_guild, 'id', None) == guild_id:
                    discord_voice_client = vc
                    break
            except Exception:
                # Skip any voice clients that cause errors
                continue
        
        # If we found a Discord voice client but not in our records, update our records
        if discord_voice_client and not voice_client:
            self.voice_clients[guild_id] = discord_voice_client
            voice_client = discord_voice_client
            print(f"[VOICE_FIX] Found and restored voice client for guild {guild_id}")
        
        # If still no voice client found
        if not voice_client and not discord_voice_client:
            await ctx.send("❌ I'm not in a voice channel!")
            return
        
        # Use whichever voice client we have
        client_to_disconnect = voice_client or discord_voice_client
        
        if not client_to_disconnect:
            await ctx.send("❌ I'm not in a voice channel!")
            return
        
        try:
            await client_to_disconnect.disconnect()
            await ctx.send("🎵 Left the voice channel!")
        except Exception as e:
            print(f"[VOICE_ERROR] Error disconnecting: {e}")
            await ctx.send("🎵 Disconnected from voice channel (forced)!")
        
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
            # First try to sync voice clients in case of connection issues
            if not self._sync_voice_clients(ctx.guild.id):
                await ctx.send("❌ I'm not in a voice channel! Use `!join` first.")
                return
        
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
            print(f"[PLAY_MUSIC] No songs in MUSIC_PLAYLISTS!")
            return
            
        # Stop current music if playing
        if voice_client.is_playing():
            voice_client.stop()
            
        # Ensure we have a shuffle playlist
        if ctx.guild.id not in self.shuffle_playlists:
            print(f"[PLAY_MUSIC] Generating shuffle playlist for guild {ctx.guild.id}")
            self._generate_shuffle_playlist(ctx.guild.id)
        else:
            print(f"[PLAY_MUSIC] Using existing shuffle playlist for guild {ctx.guild.id}")
            
        self.is_playing[ctx.guild.id] = True
        print(f"[PLAY_MUSIC] Set is_playing=True for guild {ctx.guild.id}")
        
        # Get current song info for feedback
        current_pos = self.shuffle_positions.get(ctx.guild.id, 0)
        total_songs = len(MUSIC_PLAYLISTS)
        
        if from_auto_start:
            await ctx.send(f"🎵 **AUTO-STARTING MUSIC!** 🔀 Shuffled playlist ready with {total_songs} songs!")
        else:
            await ctx.send(f"🎵 Starting shuffled music stream... Playing song {current_pos + 1} of shuffle")
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
        
        # Set manual skip flag to prevent race conditions with auto-advance
        self.manual_skip_in_progress[ctx.guild.id] = True
        
        # Instant cleanup for manual skip - no delays for instant transitions
        if voice_client.is_playing() or voice_client.is_paused():
            print(f"[NEXT] Instant stopping current audio for manual skip...")
            voice_client.stop()
            # Brief wait to ensure stop is processed
            await asyncio.sleep(0.2)
        
        if self.is_playing.get(ctx.guild.id, False):
            # Use skip_cleanup=True since we already did cleanup above
            await self._play_current_song(ctx.guild.id, skip_cleanup=True)
        else:
            await ctx.send(f"⏭️ Next song queued. Use `!start` to play.")
        
        # Clear manual skip flag after a longer delay to avoid race conditions
        await asyncio.sleep(1.0)  # Give time for the old song's callback to finish
        self.manual_skip_in_progress[ctx.guild.id] = False
    
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
        
        # Set manual skip flag to prevent race conditions with auto-advance
        self.manual_skip_in_progress[ctx.guild.id] = True
        
        # Instant cleanup for manual skip - no delays for instant transitions
        if voice_client.is_playing() or voice_client.is_paused():
            print(f"[PREVIOUS] Instant stopping current audio for manual skip...")
            voice_client.stop()
            # Brief wait to ensure stop is processed
            await asyncio.sleep(0.2)
        
        if self.is_playing.get(ctx.guild.id, False):
            await ctx.send(f"⏮️ Going back to previous song...")
            # Use skip_cleanup=True since we already did cleanup above
            await self._play_current_song(ctx.guild.id, skip_cleanup=True)
        else:
            await ctx.send(f"⏮️ Previous song queued. Use `!start` to play.")
        
        # Clear manual skip flag after a longer delay to avoid race conditions
        await asyncio.sleep(1.0)  # Give time for the old song's callback to finish
        self.manual_skip_in_progress[ctx.guild.id] = False
    
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
        
        # Try to get the actual song title using YouTube API
        try:
            if youtube_api:
                video_id = youtube_api.extract_video_id(current_url)
                if video_id:
                    video_details = await youtube_api.get_video_details(video_id)
                    title = video_details['snippet']['title'] if video_details else 'Unknown Title'
                else:
                    title = 'Unknown Title'
            else:
                title = 'Unknown Title (YouTube API not configured)'
        except:
            # Fallback to extracting from URL
            if 'youtube.com/watch?v=' in current_url:
                video_id = current_url.split('v=')[1].split('&')[0]
                title = f"YouTube Video ({video_id})"
            elif 'youtu.be/' in current_url:
                video_id = current_url.split('youtu.be/')[1].split('?')[0]
                title = f"YouTube Video ({video_id})"
            else:
                title = "Unknown Title"
        
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
        
        # Check if voice client is still connected - improved detection
        if not voice_client or not hasattr(voice_client, 'is_connected') or not voice_client.is_connected():
            print(f"[VOICE] Voice client disconnected or invalid for guild {guild_id}")
            
            # Try to sync and find the actual voice client first
            if self._sync_voice_clients(guild_id):
                voice_client = self.voice_clients[guild_id]
                print(f"[VOICE] Successfully resynced voice client for guild {guild_id}")
            else:
                print(f"[VOICE] No valid voice client found, stopping playback for guild {guild_id}")
                self.is_playing[guild_id] = False
                return
        
        # Only clean up if not already done by manual skip commands
        if not skip_cleanup:
            # Ultra-minimal cleanup for instant transitions
            if voice_client.is_playing() or voice_client.is_paused():
                print(f"[INSTANT_STOP] Instant stopping for next song...")
                voice_client.stop()
                # No delay - instant transition
        else:
            # Even with skip_cleanup=True, do instant safety check
            if voice_client.is_playing() or voice_client.is_paused():
                print(f"[SKIP_CLEANUP] Instant safety check - forcing stop...")
                voice_client.stop()
                # No delay - instant transition
        
        max_retries = 5  # More retries for better reliability on cloud platforms
        retries = 0
        last_error = None
        
        while retries < max_retries and self.is_playing.get(guild_id, False):
            try:
                # Get current song URL from shuffled playlist
                url = self._get_current_song_url(guild_id)
                if not url:
                    print(f"No URL available for guild {guild_id} at position {self.shuffle_positions.get(guild_id, 0)}")
                    # Try to regenerate playlist if we hit empty URLs
                    self._generate_shuffle_playlist(guild_id)
                    url = self._get_current_song_url(guild_id)
                    
                    if not url:
                        print(f"Still no URL after playlist regeneration for guild {guild_id}")
                        retries += 1
                        continue
                    
                print(f"[RENDER_MUSIC] Attempting to play: {url}")
                
                # Create audio source with enhanced error handling
                try:
                    player = await YouTubeAudioSource.from_url(url, loop=self.bot.loop, stream=True)
                    print(f"[RENDER_MUSIC] Audio source created successfully: {player.title}")
                except Exception as source_error:
                    error_str = str(source_error).lower()
                    print(f"[RENDER_MUSIC] Failed to create audio source: {source_error}")
                    
                    # Handle video unavailable errors - skip immediately and continue
                    if any(keyword in error_str for keyword in ['video is unavailable', 'private video', 'video has been removed', 'this video is not available']):
                        print(f"[VIDEO_UNAVAILABLE] Video unavailable, skipping to next song: {url}")
                        current_pos = self.shuffle_positions.get(guild_id, 0)
                        self.shuffle_positions[guild_id] = (current_pos + 1) % len(self.shuffle_playlists.get(guild_id, MUSIC_PLAYLISTS))
                        # Don't increment retries for unavailable videos - just continue to next song immediately
                        continue
                    
                    # Handle network errors more patiently - don't skip songs too quickly
                    elif any(keyword in error_str for keyword in ['tls', 'ssl', 'certificate', 'connection reset', 'network', 'timeout', 'input/output', 'broken pipe', 'end of file', 'io error', 'pull function']):
                        print(f"[NETWORK_ERROR] Network/TLS error detected: {source_error}")
                        print(f"[NETWORK_ERROR] This may be due to YouTube throttling or network instability")
                        
                        # Track network errors for this guild
                        current_time = asyncio.get_event_loop().time()
                        self.network_error_count[guild_id] = self.network_error_count.get(guild_id, 0) + 1
                        self.last_error_time[guild_id] = current_time
                        
                        # Reset error count if it's been a while since last error
                        last_error = self.last_error_time.get(guild_id, 0)
                        if current_time - last_error > 300:  # 5 minutes
                            self.network_error_count[guild_id] = 1
                        
                        # Only skip songs if we have extremely persistent issues (raised threshold)
                        error_count = self.network_error_count.get(guild_id, 0)
                        if error_count >= 12:  # Very patient for TLS errors - allow 12 attempts before skipping
                            print(f"[NETWORK_ERROR] Extremely persistent TLS/network errors ({error_count}), reluctantly skipping this song")
                            current_pos = self.shuffle_positions.get(guild_id, 0)
                            self.shuffle_positions[guild_id] = (current_pos + 1) % len(self.shuffle_playlists.get(guild_id, MUSIC_PLAYLISTS))
                            self.network_error_count[guild_id] = 0  # Reset counter
                        
                        retries += 1
                        # Give even more time for TLS/network recovery, especially on cloud platforms
                        wait_time = min(8 + (error_count * 2), 25)  # Up to 25 seconds for very problematic TLS connections
                        print(f"[NETWORK_ERROR] Waiting {wait_time} seconds for TLS/network recovery...")
                        await asyncio.sleep(wait_time)
                        continue
                    else:
                        # For other extraction errors, skip to next song
                        print(f"[EXTRACTION_ERROR] Skipping to next song due to extraction error: {source_error}")
                        current_pos = self.shuffle_positions.get(guild_id, 0)
                        self.shuffle_positions[guild_id] = (current_pos + 1) % len(self.shuffle_playlists.get(guild_id, MUSIC_PLAYLISTS))
                        # Continue immediately to next song
                        continue
                
                def after_playing(error):
                    if error:
                        error_str = str(error).lower()
                        print(f'🎵 Player error: {error}')
                        
                        # Enhanced TLS/network error detection for cloud deployment
                        if any(keyword in error_str for keyword in [
                            'input/output error', 'end of file', 'connection', 'network', 'broken pipe', 
                            'tls', 'ssl', 'connection reset', 'io error', 'pull function', 'error in the pull function',
                            'connection reset by peer', 'will reconnect', 'stream ended', 'broken', 'reset'
                        ]):
                            print(f"[CLOUD_RECOVERY] Network/TLS error detected (common on cloud): {error}")
                            print(f"[CLOUD_RECOVERY] Treating as normal completion to maintain continuous playback")
                        else:
                            print(f"[PLAYER_ERROR] Non-network error: {error}")
                    else:
                        print(f"🎵 Song finished playing normally for guild {guild_id}")
                    
                    # Enhanced memory cleanup for cloud deployment
                    try:
                        if hasattr(player, 'cleanup'):
                            player.cleanup()
                        elif hasattr(player, 'source') and hasattr(player.source, 'cleanup'):
                            player.source.cleanup()
                        # Force garbage collection in cloud environment
                        import gc
                        gc.collect()
                    except Exception as cleanup_error:
                        print(f"[MEMORY] Player cleanup error: {cleanup_error}")
                    
                    # Auto-advance logic with cloud-specific improvements
                    if (self.is_playing.get(guild_id, False) and 
                        not self.manual_skip_in_progress.get(guild_id, False)):
                        
                        # Check voice client status before advancing
                        try:
                            if guild_id in self.voice_clients:
                                current_voice_client = self.voice_clients[guild_id]
                                
                                # Don't advance if already playing or if disconnected
                                if current_voice_client.is_playing():
                                    print(f"[AUTO-ADVANCE] Voice client already playing, skipping auto-advance")
                                    return
                                elif not current_voice_client.is_connected():
                                    print(f"[AUTO-ADVANCE] Voice client disconnected, stopping playback")
                                    self.is_playing[guild_id] = False
                                    return
                        except Exception as voice_check_error:
                            print(f"[AUTO-ADVANCE] Error checking voice client status: {voice_check_error}")
                        
                        # Cloud-optimized delay logic for different error types
                        delay = 0.0
                        advance_mode = "normal"
                        
                        if error:
                            error_lower = str(error).lower()
                            if any(keyword in error_lower for keyword in ['tls', 'ssl', 'connection reset', 'pull function', 'reset by peer']):
                                delay = 2.0  # Shorter delay for cloud TLS recovery
                                advance_mode = "TLS recovery"
                            elif any(keyword in error_lower for keyword in ['network', 'input/output', 'connection', 'io error']):
                                delay = 1.0  # Quick recovery for network errors
                                advance_mode = "network recovery"
                            else:
                                delay = 0.5  # Brief delay for other errors
                                advance_mode = "error recovery"
                        else:
                            # Normal song completion - instant transition
                            delay = 0.0
                            advance_mode = "normal"
                        
                        print(f"[AUTO-ADVANCE] Moving to next song automatically ({advance_mode} mode)")
                        
                        # Move to next position in shuffle (thread-safe)
                        current_shuffle_pos = self.shuffle_positions.get(guild_id, 0)
                        next_shuffle_pos = current_shuffle_pos + 1
                        
                        # Check if we need to regenerate shuffle (infinite loop)
                        if guild_id not in self.shuffle_playlists or next_shuffle_pos >= len(self.shuffle_playlists[guild_id]):
                            print(f"🔄 End of shuffle reached for guild {guild_id}, regenerating for infinite playback...")
                            self._generate_shuffle_playlist(guild_id)
                            next_shuffle_pos = 0
                        
                        self.shuffle_positions[guild_id] = next_shuffle_pos
                        print(f"⏭️ Auto-advancing to shuffle position {next_shuffle_pos + 1} for continuous playback")
                        
                        # Schedule next song with cloud-optimized delay handling
                        async def play_next_song():
                            try:
                                # Apply calculated delay for recovery
                                if delay > 0:
                                    await asyncio.sleep(delay)
                                
                                # Verify we're still supposed to be playing before continuing
                                if (guild_id in self.voice_clients and 
                                    self.is_playing.get(guild_id, False) and 
                                    not self.manual_skip_in_progress.get(guild_id, False)):
                                    
                                    await self._play_current_song(guild_id)
                                if self.is_playing.get(guild_id, False) and not self.manual_skip_in_progress.get(guild_id, False):
                                    if error:
                                        print(f"[RECOVERY_CONTINUE] Starting next song after error recovery")
                                    else:
                                        print(f"[NORMAL_CONTINUE] Starting next song after normal completion")
                                    await self._play_current_song(guild_id)
                                else:
                                    print(f"[ADVANCE_ABORT] Playback was stopped during transition")
                            except Exception as e:
                                print(f"❌ Error playing next song during recovery: {e}")
                                # Enhanced recovery attempt - try one more time with longer delay
                                if self.is_playing.get(guild_id, False):
                                    print(f"🔄 Enhanced recovery attempt for guild {guild_id}")
                                    await asyncio.sleep(5)  # Longer recovery delay for Render.com
                                    try:
                                        if self.is_playing.get(guild_id, False):  # Double-check before retry
                                            current_pos = self.shuffle_positions.get(guild_id, 0)
                                            # Try next song in case current one is problematic
                                            self.shuffle_positions[guild_id] = (current_pos + 1) % len(self.shuffle_playlists.get(guild_id, MUSIC_PLAYLISTS))
                                            print(f"[RECOVERY_SKIP] Skipping potentially problematic song, trying next")
                                            await self._play_current_song(guild_id)
                                    except Exception as recovery_error:
                                        print(f"❌ Enhanced recovery also failed: {recovery_error}")
                                        print(f"❌ Stopping playback to prevent infinite error loops for guild {guild_id}")
                        
                        asyncio.run_coroutine_threadsafe(
                            play_next_song(), 
                            self.bot.loop
                        )
                    else:
                        if self.manual_skip_in_progress.get(guild_id, False):
                            print(f"⏭️ Manual skip in progress for guild {guild_id} - skipping auto-advance")
                        else:
                            print(f"⏹️ Playback stopped for guild {guild_id} - not auto-advancing")
                
                # Enhanced play method with better error detection and handling
                try:
                    # Final connection stability check before playing
                    if not voice_client.is_connected():
                        print(f"[VOICE_ERROR] Voice client disconnected before playing for guild {guild_id}")
                        self.is_playing[guild_id] = False
                        return
                    
                    # Additional check - make sure Discord can receive audio
                    if hasattr(voice_client, 'channel') and voice_client.channel:
                        print(f"[VOICE_CHECK] Connected to {voice_client.channel.name}, starting playback...")
                    else:
                        print(f"[VOICE_ERROR] No valid voice channel for guild {guild_id}")
                        self.is_playing[guild_id] = False
                        return
                    # Instant check before playing to avoid "already playing" errors
                    if voice_client.is_playing() or voice_client.is_paused():
                        print(f"[INSTANT_CHECK] Audio still playing before new play attempt, forcing stop...")
                        voice_client.stop()
                        # No delay - instant override
                    
                    voice_client.play(player, after=after_playing)
                    print(f"[CLOUD_MUSIC] Successfully started playing: {player.title}")
                    print(f"[DEBUG] Voice client playing status: {voice_client.is_playing()}")
                    print(f"[DEBUG] Voice client connected: {voice_client.is_connected()}")
                    return  # Success! Exit the retry loop
                    
                except Exception as play_error:
                    error_str = str(play_error).lower()
                    last_error = play_error
                    
                    if "already playing" in error_str or "source is already playing audio" in error_str:
                        print(f"[ALREADY_PLAYING_FIX] Detected 'already playing' error, attempting aggressive cleanup...")
                        
                        # More aggressive cleanup approach
                        try:
                            voice_client.stop()
                            await asyncio.sleep(2.5)  # Longer wait
                            
                            # Multiple stop attempts if needed
                            for attempt in range(3):
                                if not voice_client.is_playing() and not voice_client.is_paused():
                                    break
                                print(f"[ALREADY_PLAYING_FIX] Cleanup attempt {attempt + 1}")
                                voice_client.stop()
                                await asyncio.sleep(1.0)
                            
                            # Final attempt to play
                            if not voice_client.is_playing() and not voice_client.is_paused():
                                voice_client.play(player, after=after_playing)
                                print(f"[ALREADY_PLAYING_FIX] Successfully played after aggressive cleanup: {player.title}")
                                return
                            else:
                                print(f"[ALREADY_PLAYING_FIX] Could not clean up audio state, skipping to next song")
                                raise ValueError("Could not resolve 'already playing' state")
                                
                        except Exception as cleanup_error:
                            print(f"[ALREADY_PLAYING_FIX] Cleanup failed: {cleanup_error}")
                            # Skip to next song rather than retry with same song
                            current_pos = self.shuffle_positions.get(guild_id, 0)
                            self.shuffle_positions[guild_id] = (current_pos + 1) % len(MUSIC_PLAYLISTS)
                            retries += 1
                            await asyncio.sleep(2)
                            continue
                    else:
                        print(f"[PLAY_ERROR] Non-'already playing' error: {play_error}")
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
        
        # Test if the URL is valid using YouTube API
        try:
            if youtube_api:
                video_id = youtube_api.extract_video_id(url)
                if video_id:
                    video_details = await youtube_api.get_video_details(video_id)
                    title = video_details['snippet']['title'] if video_details else 'Unknown Title'
                else:
                    title = 'Unknown Title'
            else:
                title = 'Unknown Title (YouTube API not configured)'
        except Exception as e:
            await ctx.send(f"❌ Failed to validate URL: {str(e)[:100]}...")
            return
        
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
            if youtube_api:
                video_id = youtube_api.extract_video_id(url)
                if video_id:
                    video_details = await youtube_api.get_video_details(video_id)
                    title = video_details['snippet']['title'] if video_details else 'Unknown Title'
                else:
                    title = 'Unknown Title'
            else:
                title = 'Unknown Title (YouTube API not configured)'
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
        
        embed.set_footer(text="� Infinite loop enabled • Music plays forever • Auto-shuffle on playlist end")
        
        await ctx.send(embed=embed)
    
    def _sync_voice_clients(self, guild_id):
        """Sync voice client records with actual Discord voice clients - conservative approach"""
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
                        if hasattr(vc, 'is_connected') and vc.is_connected():
                            print(f"[VOICE_SYNC] Found connected voice client for guild {guild_id}")
                            found_voice_client = vc
                            break
                except Exception:
                    # Skip any voice clients that cause errors
                    continue
            
            if found_voice_client:
                # Update our record with the actual voice client
                self.voice_clients[guild_id] = found_voice_client
                return True
            else:
                # If no voice client found, just report - don't automatically clean up
                if guild_id in self.voice_clients:
                    print(f"[VOICE_SYNC] Voice client record exists but no active connection found for guild {guild_id}")
                return False
                
        except Exception as e:
            print(f"[VOICE_SYNC] Error syncing voice clients: {e}")
            return False

    async def voice_health_check(self):
        """Enhanced health check with auto-reconnection for cloud deployment stability"""
        reconnection_attempts = {}  # guild_id -> attempt_count
        last_reconnection_time = {}  # guild_id -> timestamp
        
        while True:
            try:
                current_time = asyncio.get_event_loop().time()
                
                for guild_id in list(self.voice_clients.keys()):
                    try:
                        voice_client = self.voice_clients[guild_id]
                        
                        # Enhanced connection validation
                        if not voice_client or not hasattr(voice_client, 'is_connected'):
                            print(f"[HEALTH_CHECK] Invalid voice client for guild {guild_id}")
                            continue
                            
                        if not voice_client.is_connected():
                            print(f"[HEALTH_CHECK] Voice client disconnected for guild {guild_id}")
                            
                            # Check if we should attempt auto-reconnection
                            should_reconnect = self.is_playing.get(guild_id, False)
                            attempts = reconnection_attempts.get(guild_id, 0)
                            last_attempt = last_reconnection_time.get(guild_id, 0)
                            
                            # Only attempt reconnection if:
                            # 1. We were supposed to be playing
                            # 2. We haven't exceeded max attempts (3 for cloud stability)
                            # 3. At least 60 seconds have passed since last attempt
                            if (should_reconnect and attempts < 3 and 
                                current_time - last_attempt > 60):
                                
                                print(f"[AUTO_RECONNECT] Attempting auto-reconnection for guild {guild_id} (attempt {attempts + 1}/3)")
                                
                                try:
                                    # Try to find the guild and a suitable voice channel
                                    guild = self.bot.get_guild(guild_id)
                                    if guild and hasattr(voice_client, 'channel') and voice_client.channel:
                                        # Attempt to reconnect to the same channel
                                        new_voice_client = await voice_client.channel.connect()
                                        self.voice_clients[guild_id] = new_voice_client
                                        
                                        # Reset attempt counter on successful reconnection
                                        reconnection_attempts[guild_id] = 0
                                        
                                        print(f"[AUTO_RECONNECT] Successfully reconnected to {voice_client.channel.name}")
                                        
                                        # Resume playback after short delay
                                        await asyncio.sleep(3)
                                        await self._play_current_song(guild_id)
                                        
                                except Exception as reconnect_error:
                                    print(f"[AUTO_RECONNECT] Failed to reconnect: {reconnect_error}")
                                    reconnection_attempts[guild_id] = attempts + 1
                                    last_reconnection_time[guild_id] = current_time
                                    
                                    # If max attempts reached, stop trying and clean up
                                    if reconnection_attempts[guild_id] >= 3:
                                        print(f"[AUTO_RECONNECT] Max attempts reached for guild {guild_id}, giving up")
                                        self.is_playing[guild_id] = False
                                        if guild_id in self.voice_clients:
                                            del self.voice_clients[guild_id]
                            else:
                                # If not reconnecting, clean up immediately
                                print(f"[HEALTH_CHECK] Cleaning up disconnected voice client for guild {guild_id}")
                                self.is_playing[guild_id] = False
                                if guild_id in self.voice_clients:
                                    del self.voice_clients[guild_id]
                            
                            continue
                        
                        # Reset reconnection attempts if connection is stable
                        if guild_id in reconnection_attempts:
                            reconnection_attempts[guild_id] = 0
                        
                        # Check if playback should be active but isn't (less aggressive)
                        if self.is_playing.get(guild_id, False):
                            if not voice_client.is_playing() and not voice_client.is_paused():
                                # Only restart if no manual operations are in progress
                                if not self.manual_skip_in_progress.get(guild_id, False):
                                    print(f"[HEALTH_CHECK] Playback stopped for guild {guild_id}, restarting...")
                                    await asyncio.sleep(2)  # Brief delay for network recovery
                                    
                                    # Double-check before restarting
                                    if (guild_id in self.voice_clients and 
                                        self.voice_clients[guild_id].is_connected() and
                                        self.is_playing.get(guild_id, False) and
                                        not self.voice_clients[guild_id].is_playing() and
                                        not self.manual_skip_in_progress.get(guild_id, False)):
                                        
                                        try:
                                            await self._play_current_song(guild_id)
                                        except Exception as restart_error:
                                            print(f"[HEALTH_CHECK] Failed to restart playback: {restart_error}")
                        
                    except Exception as guild_error:
                        print(f"[HEALTH_CHECK] Error checking guild {guild_id}: {guild_error}")
                        continue
                
                # Sleep for 90 seconds between health checks (less aggressive for cloud)
                await asyncio.sleep(90)
                
            except Exception as e:
                print(f"[HEALTH_CHECK] Error in health check loop: {e}")
                await asyncio.sleep(45)  # Shorter sleep on error
    
    # ...existing code...
@bot.command()
async def playback(ctx):
    """Check current playback status and duration"""
    if not music_bot:
        await ctx.send("❌ Music bot is not initialized!")
        return
    
    if ctx.guild.id not in music_bot.voice_clients:
        await ctx.send("❌ I'm not in a voice channel!")
        return
    
    voice_client = music_bot.voice_clients[ctx.guild.id]
    
    embed = discord.Embed(
        title="🎵 [RENDER.COM] Playback Status",
        color=discord.Color.blue()
    )
    
    # Connection status
    embed.add_field(
        name="Connection",
        value=f"{'✅ Connected' if voice_client.is_connected() else '❌ Disconnected'}",
        inline=True
    )
    
    # Audio status
    if voice_client.is_playing():
        status = "▶️ Playing"
    elif voice_client.is_paused():
        status = "⏸️ Paused"
    else:
        status = "⏹️ Stopped"
    
    embed.add_field(name="Audio State", value=status, inline=True)
    
    # Channel info
    if voice_client.is_connected():
        embed.add_field(
            name="Voice Channel",
            value=voice_client.channel.name,
            inline=True
        )
    
    # Auto-play status
    auto_play = music_bot.is_playing.get(ctx.guild.id, False)
    embed.add_field(
        name="Auto-Play",
        value=f"{'🔄 Enabled' if auto_play else '❌ Disabled'}",
        inline=True
    )
    
    embed.set_footer(text="Use this to debug audio issues on Render.com")
    
    await ctx.send(embed=embed)

# Initialize music bot
music_bot = None

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
    
    # Start HTTP server for Render.com port binding
    try:
        await start_http_server()
    except Exception as e:
        print(f"❌ Failed to start HTTP server: {e}")
    
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
    
    # Start voice health check task
    asyncio.create_task(music_bot.voice_health_check())
    print("Voice health check started")

    # Start HTTP server for health checks
    if os.getenv('RENDER_SERVICE_NAME'):
        await start_http_server()

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

@bot.event
async def on_voice_state_update(member, before, after):
    """Track voice state changes to detect when the bot is disconnected"""
    if member == bot.user:
        if before.channel and not after.channel:
            # Bot was disconnected from voice channel
            guild_id = before.channel.guild.id
            print(f"[VOICE_STATE] Bot was disconnected from {before.channel.name} in guild {guild_id}")
            
            # Add a small delay to avoid race conditions with reconnection attempts
            await asyncio.sleep(2)
            
            # Clean up music bot state if it exists, but be more conservative
            if music_bot and guild_id in music_bot.voice_clients:
                print(f"[VOICE_STATE] Cleaning up music bot state for guild {guild_id}")
                # Clean up voice client reference
                del music_bot.voice_clients[guild_id]
                # Stop playback flag to prevent health check conflicts
                if guild_id in music_bot.is_playing:
                    music_bot.is_playing[guild_id] = False
                # Keep other state (shuffle playlists, positions, etc.) for potential manual reconnection
                print(f"[VOICE_STATE] State cleaned up, manual reconnection will be required")
        elif not before.channel and after.channel:
            # Bot connected to voice channel
            print(f"[VOICE_STATE] Bot connected to {after.channel.name}")
            # Add a short delay to let the connection stabilize
            await asyncio.sleep(1)

# Helper function to check for admin/moderator permissions
def has_admin_or_moderator_role(ctx):
    """Check if user has Admin or Moderator role"""
    user_roles = [role.name.lower() for role in ctx.author.roles]
    return any(role in ['admin', 'moderator', 'administrator'] for role in user_roles)

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
    
    voice_client = music_bot.voice_clients[ctx.guild.id]
    
    embed = discord.Embed(
        title="🎧 Bluetooth Audio Optimization",
        description="Bot is now optimized for Bluetooth speakers with:",
        color=discord.Color.blue()
    )
    
    embed.add_field(
        name="🎵 Audio Quality",
        value="• High-quality AAC/M4A format preferred\n• 48kHz sample rate\n• 320kbps bitrate\n• Enhanced stereo output",
        inline=False
    )
    
    embed.add_field(
        name="🔊 Volume Settings",
        value="• Default volume increased to 70%\n• Use `!volume [0-100]` to adjust\n• Consider 80-90% for most Bluetooth speakers",
        inline=False
    )
    
    embed.add_field(
        name="💡 Bluetooth Tips",
        value="• Make sure your device is close to the Bluetooth speaker\n• Reduce interference from other devices\n• Check your speaker's codec support (AAC preferred)\n• Some speakers may have slight audio delay",
        inline=False
    )
    
    # Auto-adjust volume if currently playing
    if voice_client.source:
        current_vol = voice_client.source.volume
        if current_vol < 0.8:  # If volume is less than 80%
            voice_client.source.volume = 0.8  # Set to 80% for Bluetooth
            embed.add_field(
                name="🔧 Auto-Adjustment",
                value="Volume automatically set to 80% for optimal Bluetooth experience",
                inline=False
            )
    
    embed.set_footer(text="🎧 Enhanced audio settings are now active for better Bluetooth playback")
    await ctx.send(embed=embed)
