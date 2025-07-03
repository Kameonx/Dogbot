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

bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

dogs_role_name = "Dogs"
cats_role_name = "Cats"
lizards_role_name = "Lizards"
pvp_role_name = "PVP"

# YouTube Data API v3 Configuration
YOUTUBE_API_BASE_URL = "https://www.googleapis.com/youtube/v3"

class YouTubeAudioSource(discord.PCMVolumeTransformer):
    """Audio source for YouTube streaming using yt-dlp"""
    
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=True):
        """Create audio source from YouTube URL using yt-dlp"""
        loop = loop or asyncio.get_event_loop()
        
        ytdl_format_options = {
            'format': 'bestaudio[ext=webm]/bestaudio[ext=m4a]/bestaudio[acodec=opus]/bestaudio',  # Prefer opus/webm for stability
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
            'user_agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',  # Cloud-friendly user agent
            'http_chunk_size': 1048576,  # 1MB chunks for better cloud stability
            'socket_timeout': 30,  # Reduced timeout for cloud environment
            'retries': 5,  # More retries for cloud reliability
            'fragment_retries': 5,  # More fragment retries
        }

        # For cloud deployment (Render.com), use minimal FFmpeg options
        # Let Discord.py handle most of the configuration automatically
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
            
            # Create the audio source with optimized settings for Render.com
            source = discord.FFmpegPCMAudio(
                filename,
                before_options='-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -probesize 16M -analyzeduration 8M',
                options='-vn -bufsize 256k -ar 48000 -ac 2'
            )
            print(f"FFmpegPCMAudio source created successfully")
            
            return cls(source, data=data)
            
        except Exception as e:
            print(f"Error in YouTubeAudioSource.from_url: {e}")
            # Check if this is likely a FFmpeg issue
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
                    "• Make sure cookies.txt is in the bot directory\n"
                    "• Export fresh cookies from your browser\n"
                    "• Use browser extension like 'Get cookies.txt' for Chrome/Firefox"
                )
            elif 'sign in' in error_str or 'login' in error_str or 'private' in error_str:
                raise ValueError(
                    "❌ Video requires sign-in or is private!\n"
                    "💡 Try:\n"
                    "• Update your cookies.txt file\n"
                    "• Use a different video\n"
                    "• Check if video is age-restricted"
                )
            
            # If yt-dlp fails, try fallback method
            try:
                return await cls.from_url_fallback(url, loop=loop)
            except Exception as fallback_error:
                print(f"Fallback also failed: {fallback_error}")
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
            
        # Simple fallback - try with better quality settings
        try:
            ytdl_simple = yt_dlp.YoutubeDL({
                'format': 'bestaudio[ext=webm]/bestaudio[ext=m4a]/bestaudio',
                'quiet': True,
                'no_warnings': True,
                'cookiefile': 'cookies.txt',  # Use cookies file for fallback too
                'prefer_ffmpeg': True,
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
                
            # Use optimized FFmpeg options for Render.com cloud deployment
            source = discord.FFmpegPCMAudio(
                data['url'],
                before_options='-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -probesize 16M -analyzeduration 8M',
                options='-vn -bufsize 256k -ar 48000 -ac 2'
            )
            return cls(source, data=data)
            
        except Exception as e:
            raise ValueError(f"All extraction methods failed: {str(e)}")

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
    
    def _generate_shuffle_playlist(self, guild_id):
        """Generate a new shuffled playlist for the guild"""
        if not MUSIC_PLAYLISTS:
            print(f"⚠️ No songs in MUSIC_PLAYLISTS for guild {guild_id}")
            return
            
        # Create a shuffled copy of the playlist
        shuffled = MUSIC_PLAYLISTS.copy()
        random.shuffle(shuffled)
        
        self.shuffle_playlists[guild_id] = shuffled
        self.shuffle_positions[guild_id] = 0
        print(f"🔀 Generated new shuffle playlist for guild {guild_id} with {len(shuffled)} songs")
        
        # Ensure continuous playback - if we're currently playing, this is a regeneration
        if self.is_playing.get(guild_id, False):
            print(f"🔄 Playlist regenerated during playback - continuous music ensured")
    
    def _get_current_song_url(self, guild_id):
        """Get the current song URL from the shuffled playlist"""
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
        
        if ctx.guild.id in self.voice_clients:
            voice_client = self.voice_clients[ctx.guild.id]
            # Check if voice client is still connected
            if voice_client.is_connected():
                if voice_client.channel == channel:
                    if auto_start:
                        await ctx.send("🎵 I'm already in your voice channel! Starting music...")
                        if not self.is_playing.get(ctx.guild.id, False):
                            await self.play_music(ctx)
                    else:
                        await ctx.send("🎵 I'm already in your voice channel!")
                    return voice_client
                else:
                    try:
                        await voice_client.move_to(channel)
                        if auto_start:
                            await ctx.send(f"🎵 Moved to {channel.name} and starting music!")
                            if not self.is_playing.get(ctx.guild.id, False):
                                await self.play_music(ctx)
                        else:
                            await ctx.send(f"🎵 Moved to {channel.name}!")
                        return voice_client
                    except Exception as e:
                        print(f"[VOICE] Failed to move to channel {channel.name}: {e}")
                        # Clean up and try fresh connection
                        del self.voice_clients[ctx.guild.id]
            else:
                # Clean up disconnected voice client
                print(f"[VOICE] Cleaning up disconnected voice client for guild {ctx.guild.id}")
                del self.voice_clients[ctx.guild.id]
        
        try:
            voice_client = await channel.connect()
            self.voice_clients[ctx.guild.id] = voice_client
            
            # Generate initial shuffle playlist and start at random position
            self._generate_shuffle_playlist(ctx.guild.id)
            # Start at a random position in the shuffled playlist
            if self.shuffle_playlists.get(ctx.guild.id):
                self.shuffle_positions[ctx.guild.id] = random.randint(0, len(self.shuffle_playlists[ctx.guild.id]) - 1)
            
            self.current_songs[ctx.guild.id] = 0
            self.is_playing[ctx.guild.id] = False
            self.manual_skip_in_progress[ctx.guild.id] = False  # Initialize flag
            
            if auto_start:
                await ctx.send(f"🎵 Joined {channel.name} and starting music in shuffle mode!")
                # Give a moment for voice client to fully connect
                await asyncio.sleep(1)
                await self.play_music(ctx)
            else:
                await ctx.send(f"🎵 Joined {channel.name}! Ready to play music in shuffle mode!")
            return voice_client
        except Exception as e:
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
    
    async def play_music(self, ctx):
        """Start playing music from the shuffled playlist"""
        # First try to sync voice clients in case of connection issues
        if not self._sync_voice_clients(ctx.guild.id):
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
            
        # Ensure we have a shuffle playlist
        if ctx.guild.id not in self.shuffle_playlists:
            self._generate_shuffle_playlist(ctx.guild.id)
            
        self.is_playing[ctx.guild.id] = True
        
        # Get current song info for feedback
        current_pos = self.shuffle_positions.get(ctx.guild.id, 0)
        total_songs = len(MUSIC_PLAYLISTS)
        
        await ctx.send(f"🎵 Starting shuffled music stream... Playing song {current_pos + 1} of shuffle")
        
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
        
        # Comprehensive cleanup for manual skip to prevent corrupted audio
        if voice_client.is_playing() or voice_client.is_paused():
            print(f"[NEXT] Stopping current audio for manual skip...")
            voice_client.stop()
            
            # Wait for voice client to fully stop
            print(f"[NEXT] Waiting for complete audio cleanup...")
            await asyncio.sleep(2.0)  # Increased wait time
            
            # Double-check that audio is fully stopped
            retry_count = 0
            while (voice_client.is_playing() or voice_client.is_paused()) and retry_count < 5:
                print(f"[NEXT] Audio still playing, forcing stop (attempt {retry_count + 1})")
                voice_client.stop()
                await asyncio.sleep(0.5)
                retry_count += 1
        
        if self.is_playing.get(ctx.guild.id, False):
            # Use skip_cleanup=True since we already did comprehensive cleanup above
            await self._play_current_song(ctx.guild.id, skip_cleanup=True)
        else:
            await ctx.send(f"⏭️ Next song queued. Use `!start` to play.")
        
        # Clear manual skip flag after a small delay to ensure playback starts
        await asyncio.sleep(0.5)
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
        
        # Comprehensive cleanup for manual skip to prevent corrupted audio
        if voice_client.is_playing() or voice_client.is_paused():
            print(f"[PREVIOUS] Stopping current audio for manual skip...")
            voice_client.stop()
            
            # Wait for voice client to fully stop
            print(f"[PREVIOUS] Waiting for complete audio cleanup...")
            await asyncio.sleep(2.0)  # Increased wait time
            
            # Double-check that audio is fully stopped
            retry_count = 0
            while (voice_client.is_playing() or voice_client.is_paused()) and retry_count < 5:
                print(f"[PREVIOUS] Audio still playing, forcing stop (attempt {retry_count + 1})")
                voice_client.stop()
                await asyncio.sleep(0.5)
                retry_count += 1
        
        if self.is_playing.get(ctx.guild.id, False):
            await ctx.send(f"⏮️ Going back to previous song...")
            # Use skip_cleanup=True since we already did comprehensive cleanup above
            await self._play_current_song(ctx.guild.id, skip_cleanup=True)
        else:
            await ctx.send(f"⏮️ Previous song queued. Use `!start` to play.")
        
        # Clear manual skip flag after a small delay to ensure playback starts
        await asyncio.sleep(0.5)
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
        if guild_id not in self.voice_clients or not self.is_playing.get(guild_id, False):
            return
            
        voice_client = self.voice_clients[guild_id]
        
        # Check if voice client is still connected - improved detection
        if not voice_client or not hasattr(voice_client, 'is_connected') or not voice_client.is_connected():
            print(f"[VOICE] Voice client disconnected or invalid for guild {guild_id}")
            
            # Try to sync and find the actual voice client
            if self._sync_voice_clients(guild_id):
                voice_client = self.voice_clients[guild_id]
                print(f"[VOICE] Successfully resynced voice client for guild {guild_id}")
            else:
                # Try to get guild and channel for reconnection attempt
                guild = self.bot.get_guild(guild_id)
                if guild and guild.me.voice and guild.me.voice.channel:
                    try:
                        print(f"[VOICE] Attempting auto-reconnect to {guild.me.voice.channel.name}")
                        new_voice_client = await guild.me.voice.channel.connect()
                        self.voice_clients[guild_id] = new_voice_client
                        voice_client = new_voice_client
                        print(f"[VOICE] Successfully auto-reconnected to voice channel")
                    except Exception as e:
                        print(f"[VOICE] Auto-reconnect failed: {e}")
                        self.is_playing[guild_id] = False
                        return
                else:
                    print(f"[VOICE] No suitable voice channel found for auto-reconnect")
                    self.is_playing[guild_id] = False
                    return
        
        # Only clean up if not already done by manual skip commands
        if not skip_cleanup:
            # Clean up any existing audio BEFORE trying to play new song
            if voice_client.is_playing() or voice_client.is_paused():
                print(f"[RENDER.COM] Stopping existing audio for clean transition...")
                voice_client.stop()
                await asyncio.sleep(1.0)  # Longer delay for complete cleanup
        else:
            # Even with skip_cleanup=True, do a final safety check to prevent audio overlap
            if voice_client.is_playing() or voice_client.is_paused():
                print(f"[SKIP_CLEANUP] Final safety check - audio still playing, forcing stop...")
                voice_client.stop()
                await asyncio.sleep(0.5)  # Brief wait to ensure stop takes effect
        
        max_retries = 3  # Reduced for cloud stability
        retries = 0
        
        while retries < max_retries and self.is_playing.get(guild_id, False):
            try:
                # Get current song URL from shuffled playlist
                url = self._get_current_song_url(guild_id)
                if not url:
                    print(f"No URL available for guild {guild_id} at position {self.shuffle_positions.get(guild_id, 0)}")
                    # Move to next position and try again
                    current_pos = self.shuffle_positions.get(guild_id, 0)
                    self.shuffle_positions[guild_id] = (current_pos + 1) % len(MUSIC_PLAYLISTS)
                    retries += 1
                    continue
                    
                print(f"[RENDER.COM] Attempting to play: {url}")
                
                # Create audio source with better error handling for Render.com
                try:
                    player = await YouTubeAudioSource.from_url(url, loop=self.bot.loop, stream=True)
                    print(f"[RENDER.COM] Audio source created successfully: {player.title}")
                except Exception as source_error:
                    print(f"[RENDER.COM] Failed to create audio source: {source_error}")
                    # Skip to next song if source creation fails
                    current_pos = self.shuffle_positions.get(guild_id, 0)
                    self.shuffle_positions[guild_id] = (current_pos + 1) % len(MUSIC_PLAYLISTS)
                    retries += 1
                    await asyncio.sleep(2)  # Brief delay before retry
                    continue
                
                def after_playing(error):
                    if error:
                        print(f'🎵 Player error: {error}')
                    else:
                        print(f"🎵 Song finished playing normally for guild {guild_id}")
                    
                    # Clean up player object to free memory on Render.com
                    try:
                        if hasattr(player, 'cleanup'):
                            player.cleanup()
                        elif hasattr(player, 'source') and hasattr(player.source, 'cleanup'):
                            player.source.cleanup()
                    except Exception as cleanup_error:
                        print(f"[MEMORY] Player cleanup error: {cleanup_error}")
                    
                    # Auto-advance to next song if we're still supposed to be playing
                    # BUT ONLY if no manual skip is in progress (prevents race conditions)
                    if (self.is_playing.get(guild_id, False) and 
                        not self.manual_skip_in_progress.get(guild_id, False)):
                        
                        print(f"[AUTO-ADVANCE] Moving to next song automatically")
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
                        
                        # Schedule next song to play without blocking (ensures infinite loop)
                        async def play_next_song():
                            try:
                                await asyncio.sleep(2.0)  # Reasonable pause for Render.com
                                
                                # Simple check - if we're still playing, continue
                                if self.is_playing.get(guild_id, False):
                                    await self._play_current_song(guild_id)
                            except Exception as e:
                                print(f"❌ Error playing next song for infinite loop: {e}")
                                # Only try recovery once per song to prevent loops
                                if self.is_playing.get(guild_id, False):
                                    print(f"🔄 Single recovery attempt for guild {guild_id}")
                                    self.shuffle_positions[guild_id] = 0  # Reset to start
                                    await asyncio.sleep(3)  # Longer delay for Render.com
                                    try:
                                        await self._play_current_song(guild_id)
                                    except:
                                        print(f"❌ Recovery failed, stopping playback for guild {guild_id}")
                                        self.is_playing[guild_id] = False
                        
                        asyncio.run_coroutine_threadsafe(
                            play_next_song(), 
                            self.bot.loop
                        )
                    else:
                        if self.manual_skip_in_progress.get(guild_id, False):
                            print(f"⏭️ Manual skip in progress for guild {guild_id} - skipping auto-advance")
                        else:
                            print(f"⏹️ Playback stopped for guild {guild_id} - not auto-advancing")
                
                # Play the new audio with improved error handling
                try:
                    voice_client.play(player, after=after_playing)
                    print(f"[RENDER.COM] Playlist: Successfully started playing: {player.title}")
                    return  # Success! Exit the retry loop
                except Exception as play_error:
                    error_str = str(play_error).lower()
                    if "already playing" in error_str or "source is already playing audio" in error_str:
                        print(f"[AUDIO_FIX] 'Already playing' error detected, forcing comprehensive cleanup...")
                        
                        # Force stop and wait longer
                        voice_client.stop()
                        await asyncio.sleep(2.0)  # Longer wait for cleanup
                        
                        # Check again if still playing and force stop multiple times if needed
                        cleanup_attempts = 0
                        while (voice_client.is_playing() or voice_client.is_paused()) and cleanup_attempts < 3:
                            print(f"[AUDIO_FIX] Still playing after stop, forcing again (attempt {cleanup_attempts + 1})")
                            voice_client.stop()
                            await asyncio.sleep(1.0)
                            cleanup_attempts += 1
                        
                        # Try to play again after comprehensive cleanup
                        try:
                            voice_client.play(player, after=after_playing)
                            print(f"[AUDIO_FIX] Successfully started playing after cleanup: {player.title}")
                            return  # Success after retry
                        except Exception as retry_error:
                            print(f"[AUDIO_FIX] Retry failed: {retry_error}")
                            raise retry_error
                    else:
                        raise play_error
                        
            except Exception as e:
                current_url = self._get_current_song_url(guild_id) or "unknown"
                print(f"Error playing music from {current_url}: {e}")
                retries += 1
                
                # Skip to next song and try again (without regenerating shuffle every time)
                current_shuffle_pos = self.shuffle_positions.get(guild_id, 0)
                next_shuffle_pos = (current_shuffle_pos + 1) % len(MUSIC_PLAYLISTS)
                self.shuffle_positions[guild_id] = next_shuffle_pos
                
                # Add a delay before retrying
                await asyncio.sleep(2)
        
        # If we exhausted all retries, stop gracefully instead of infinite recovery
        if self.is_playing.get(guild_id, False):
            print(f"❌ Failed to play any songs after {max_retries} attempts for guild {guild_id}")
            print(f"❌ Stopping playback to prevent infinite loops")
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
        player = await YouTubeAudioSource.from_url(url, loop=self.bot.loop, stream=True)

        # Clean up any existing audio for a clean start
        if voice_client.is_playing() or voice_client.is_paused():
            voice_client.stop()
            await asyncio.sleep(0.5)
        
        # Temporarily disable shuffled playlist auto-play
        was_playing = was_playing_playlist
        self.is_playing[ctx.guild.id] = False
        
        # Play the specific track with resume callback
        def after_specific(error):
            if error:
                print(f"Error playing specific URL: {error}")
            elif was_playing:
                # Resume shuffled playlist immediately
                async def resume_playlist():
                    self.is_playing[ctx.guild.id] = True
                    await self._play_current_song(ctx.guild.id)
                asyncio.run_coroutine_threadsafe(resume_playlist(), self.bot.loop)
        
        voice_client.play(player, after=after_specific)
        return

    # NOTE: play_specific_url method disabled - was causing issues
    # Use !add <url> then !start instead for now
    
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
        """Sync voice client records with actual Discord voice clients"""
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
                # If no voice client found, clean up our record
                if guild_id in self.voice_clients:
                    print(f"[VOICE_SYNC] Cleaning up stale voice client record for guild {guild_id}")
                    del self.voice_clients[guild_id]
                return False
                
        except Exception as e:
            print(f"[VOICE_SYNC] Error syncing voice clients: {e}")
            return False

    async def voice_health_check(self):
        """Periodic health check for voice connections"""
        while True:
            try:
                await asyncio.sleep(45)  # Check every 45 seconds - not too frequent
                
                for guild_id in list(self.voice_clients.keys()):
                    if not self.is_playing.get(guild_id, False):
                        continue  # Skip if not supposed to be playing
                    
                    voice_client = self.voice_clients.get(guild_id)
                    if not voice_client:
                        continue
                    
                    # Check if voice client is still connected
                    if not voice_client.is_connected():
                        print(f"[HEALTH_CHECK] Voice client disconnected for guild {guild_id}")
                        # Try to auto-reconnect but don't be too aggressive
                        guild = self.bot.get_guild(guild_id)
                        if guild and guild.me.voice and guild.me.voice.channel:
                            try:
                                print(f"[HEALTH_CHECK] Attempting gentle reconnect for guild {guild_id}")
                                await asyncio.sleep(2)  # Brief wait
                                new_voice_client = await guild.me.voice.channel.connect()
                                self.voice_clients[guild_id] = new_voice_client
                                await asyncio.sleep(2)  # Wait before restarting music
                                await self._play_current_song(guild_id)
                                print(f"[HEALTH_CHECK] Successfully reconnected and restarted music for guild {guild_id}")
                            except Exception as e:
                                print(f"[HEALTH_CHECK] Auto-reconnect failed for guild {guild_id}: {e}")
                                # Don't immediately disable - let user commands handle it
                    
                    # Only restart music if it's been stopped for a while
                    elif not voice_client.is_playing() and not voice_client.is_paused():
                        if not self.manual_skip_in_progress.get(guild_id, False):
                            # Give some time for natural song transitions
                            await asyncio.sleep(10)
                            # Check again after waiting
                            if (not voice_client.is_playing() and not voice_client.is_paused() and 
                                not self.manual_skip_in_progress.get(guild_id, False)):
                                print(f"[HEALTH_CHECK] Music appears stuck for guild {guild_id}, gentle restart...")
                                try:
                                    await self._play_current_song(guild_id)
                                    print(f"[HEALTH_CHECK] Successfully restarted music for guild {guild_id}")
                                except Exception as e:
                                    print(f"[HEALTH_CHECK] Failed to restart music for guild {guild_id}: {e}")
                
            except Exception as e:
                print(f"[HEALTH_CHECK] Error in voice health check: {e}")
    
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
            print(f"[VOICE] Bot was disconnected from {before.channel.name} in guild {guild_id}")
            
            # Clean up music bot state if it exists
            if music_bot and guild_id in music_bot.voice_clients:
                print(f"[VOICE] Cleaning up music bot state for guild {guild_id}")
                # Clean up all data for this guild
                del music_bot.voice_clients[guild_id]
                if guild_id in music_bot.current_songs:
                    del music_bot.current_songs[guild_id]
                if guild_id in music_bot.is_playing:
                    music_bot.is_playing[guild_id] = False
                # Keep shuffle playlists and positions for potential reconnection
                print(f"[VOICE] State cleaned up, ready for reconnection")
        elif not before.channel and after.channel:
            # Bot connected to voice channel
            print(f"[VOICE] Bot connected to {after.channel.name}")

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

# AI and Chat Commands
@bot.command()
async def ask(ctx, *, question):
    """Ask AI a question (no memory)"""
    response = await get_ai_response(str(ctx.author.id), question)
    await ctx.send(response)

@bot.command()
async def chat(ctx, *, message):
    """Chat with AI (with memory)"""
    user_id = str(ctx.author.id)
    user_name = ctx.author.display_name
    channel_id = str(ctx.channel.id)
    
    response = await get_ai_response_with_history(user_id, message)
    
    # Save to chat history
    await save_chat_history(user_id, user_name, channel_id, message, response)
    
    await ctx.send(response)

# Utility Commands
@bot.command()
async def poll(ctx, *, question):
    """Create a poll"""
    embed = discord.Embed(
        title="📊 Poll",
        description=question,
        color=discord.Color.blue()
    )
    embed.set_footer(text=f"Poll created by {ctx.author.display_name}")
    
    message = await ctx.send(embed=embed)
    await message.add_reaction("👍")
    await message.add_reaction("👎")

@bot.command()
async def say(ctx, *, message):
    """Make the bot say something"""
    await ctx.message.delete()  # Delete the command message
    await ctx.send(message)

@bot.command()
async def ytdlstatus(ctx):
    """Show YouTube API configuration (Admin/Moderator only)"""
    if not has_admin_or_moderator_role(ctx):
        await ctx.send("❌ You need Admin or Moderator role to use this command.")
        return
    
    embed = discord.Embed(
        title="🔧 YouTube Configuration Status",
        color=discord.Color.blue()
    )
    
    # Check YouTube API
    if youtube_api_key:
        embed.add_field(name="YouTube API Key", value="✅ Configured", inline=True)
    else:
        embed.add_field(name="YouTube API Key", value="❌ Not Set", inline=True)
    
    # Check yt-dlp
    try:
        import yt_dlp
        embed.add_field(name="yt-dlp", value="✅ Available", inline=True)
    except ImportError:
        embed.add_field(name="yt-dlp", value="❌ Not Installed", inline=True)
    
    # Check FFmpeg
    try:
        result = subprocess.run(['ffmpeg', '-version'], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            embed.add_field(name="FFmpeg", value="✅ Available", inline=True)
        else:
            embed.add_field(name="FFmpeg", value="⚠️ Error", inline=True)
    except:
        embed.add_field(name="FFmpeg", value="❌ Not Found", inline=True)
    
    await ctx.send(embed=embed)

@bot.command()
async def help(ctx):
    embed = discord.Embed(
        title="🐶 Dog Bot Commands", 
        description="Here are all available commands:",
        color=discord.Color.blue()
    )
    embed.add_field(name="🐕 Basic", value="`!hello` - Greet the bot\n`!help` - Show this help\n`!test` - Test bot functionality\n\n🤖 **AI Commands:**\n`!ask <question>` - Ask AI anything\n`!chat <message>` - Chat with AI (with memory)\n`!undo` - Undo last action\n`!redo` - Redo last undone action", inline=False)
    embed.add_field(name="🎵 Music Bot", value="`!join` - Join voice channel and auto-start music\n`!leave` - Leave voice channel\n`!start` - Start/resume music\n`!stop` - Stop music\n`!next` - Skip to next song\n`!previous` - Go to previous song\n`!play` - Resume current playlist\n`!play <youtube_link>` - Play specific song immediately (returns to playlist after)\n`!playlist` - Show current playlist\n`!add <youtube_url>` - Add song to playlist\n`!remove <youtube_url>` - Remove song from playlist\n`!nowplaying` - Show current song info\n`!status` - Show playback and auto-repeat status", inline=False)
    
    embed.add_field(name="🎭 Roles", value="`!catsrole` - Get Cats role\n`!dogsrole` - Get Dogs role\n`!lizardsrole` - Get Lizards role\n`!pvprole` - Get PVP role\n`!remove<role>` - Remove any role (e.g., `!removecatsrole`)", inline=False)

    # Add note about modhelp for admins/moderators
    if has_admin_or_moderator_role(ctx):
        embed.add_field(name="👑 Admin/Moderator", value="`!modhelp` - View admin/moderator commands", inline=False)

    await ctx.send(embed=embed)

@bot.command()
async def modhelp(ctx):
    """Admin/Moderator only help command"""
    if not has_admin_or_moderator_role(ctx):
        await ctx.send("❌ You need Admin or Moderator role to use this command.")
        return
    
    embed = discord.Embed(
        title="👑 Admin/Moderator Commands", 
        description="Commands available to Admins and Moderators:",
        color=discord.Color.gold()
    )
    
    embed.add_field(
        name="🎭 Role Assignment", 
        value="`!assigndogsrole @user` - Assign Dogs role\n"
              "`!assigncatsrole @user` - Assign Cats role\n"
              "`!assignlizardsrole @user` - Assign Lizards role\n"
              "`!assignpvprole @user` - Assign PVP role", 
        inline=False
    )
    
    embed.add_field(
        name="🚫 Role Removal", 
        value="`!removedogsrolefrom @user` - Remove Dogs role\n"
              "`!removecatsrolefrom @user` - Remove Cats role\n"
              "`!removelizardsrolefrom @user` - Remove Lizards role\n"
              "`!removepvprolefrom @user` - Remove PVP role", 
        inline=False
    )
    
    embed.add_field(
        name="🔧 YouTube Configuration", 
        value="`!ytdlstatus` - Show YouTube API configuration", 
        inline=False
    )
    
    embed.add_field(
        name="🗳️ Utility Commands", 
        value="`!poll <question>` - Create a poll\n"
              "`!say <message>` - Make the bot say something", 
        inline=False
    )
    
    embed.add_field(
        name="🎵 Advanced Music", 
        value="`!loop` - Show infinite loop status\n"
              "`!reshuffle` - Generate new shuffle order\n"
              "`!voicefix` - Fix voice connection issues\n"
              "`!reconnect` - Force reconnect to voice channel", 
        inline=False
    )
    
    embed.set_footer(text="💡 Tip: Use @username or user mentions to specify the target user\n🎵 Music commands are now available to everyone!")
    await ctx.send(embed=embed)

@bot.command()
async def dogsrole(ctx):
    role = discord.utils.get(ctx.guild.roles, name=dogs_role_name)
    if role:
        await ctx.author.add_roles(role)
        await ctx.send(f"🐶 Assigned {role.name} role to {ctx.author.name}!")
    else:
        await ctx.send("Dogs role not found. Please ensure the role exists in this server.")

@bot.command()
async def catsrole(ctx):
    role = discord.utils.get(ctx.guild.roles, name=cats_role_name)
    if role:
        await ctx.author.add_roles(role)
        await ctx.send(f"🐱 Assigned {role.name} role to {ctx.author.name}!")
    else:
        await ctx.send("Cats role not found. Please ensure the role exists in this server.")

@bot.command()
async def lizardsrole(ctx):
    role = discord.utils.get(ctx.guild.roles, name=lizards_role_name)
    if role:
        await ctx.author.add_roles(role)
        await ctx.send(f"🦎 Assigned {role.name} role to {ctx.author.name}!")
    else:
        await ctx.send("Lizards role not found. Please ensure the role exists in this server.")

@bot.command()
async def pvprole(ctx):
    role = discord.utils.get(ctx.guild.roles, name=pvp_role_name)
    if role:
        await ctx.author.add_roles(role)
        await ctx.send(f"⚔️ Assigned {role.name} role to {ctx.author.name}!")
    else:
        await ctx.send("PVP role not found. Please ensure the role exists in this server.")

@bot.command()
async def removedogsrole(ctx):
    role = discord.utils.get(ctx.guild.roles, name=dogs_role_name)
    if role:
        if role in ctx.author.roles:
            await ctx.author.remove_roles(role)
            await ctx.send(f"🐶 Removed {role.name} role from {ctx.author.name}!")
        else:
            await ctx.send(f"You don't have the {role.name} role to remove.")
    else:
        await ctx.send("Dogs role not found. Please ensure the role exists in this server.")

@bot.command()
async def removecatsrole(ctx):
    role = discord.utils.get(ctx.guild.roles, name=cats_role_name)
    if role:
        if role in ctx.author.roles:
            await ctx.author.remove_roles(role)
            await ctx.send(f"🐱 Removed {role.name} role from {ctx.author.name}!")
        else:
            await ctx.send(f"You don't have the {role.name} role to remove.")
    else:
        await ctx.send("Cats role not found. Please ensure the role exists in this server.")

@bot.command()
async def removelizardsrole(ctx):
    role = discord.utils.get(ctx.guild.roles, name=lizards_role_name)
    if role:
        if role in ctx.author.roles:
            await ctx.author.remove_roles(role)
            await ctx.send(f"🦎 Removed {role.name} role from {ctx.author.name}!")
        else:
            await ctx.send(f"You don't have the {role.name} role to remove.")
    else:
        await ctx.send("Lizards role not found. Please ensure the role exists in this server.")

@bot.command()
async def removepvprole(ctx):
    role = discord.utils.get(ctx.guild.roles, name=pvp_role_name)
    if role:
        if role in ctx.author.roles:
            await ctx.author.remove_roles(role)
            await ctx.send(f"⚔️ Removed {role.name} role from {ctx.author.name}!")
        else:
            await ctx.send(f"You don't have the {role.name} role to remove.")
    else:
        await ctx.send("PVP role not found. Please ensure the role exists in this server.")

# Admin/Moderator role assignment commands
@bot.command()
async def assigndogsrole(ctx, member: Optional[discord.Member] = None):
    """Admin/Moderator command to assign Dogs role to a user"""
    if not has_admin_or_moderator_role(ctx):
        await ctx.send("❌ You need Admin or Moderator role to use this command.")
        return
    
    if member is None:
        await ctx.send("❌ Please mention a user to assign the role to. Usage: `!assigndogsrole @username`")
        return
    
    role = discord.utils.get(ctx.guild.roles, name=dogs_role_name)
    if role:
        if role not in member.roles:
            await member.add_roles(role)
            await ctx.send(f"🐶 Assigned {role.name} role to {member.mention}!")
        else:
            await ctx.send(f"{member.mention} already has the {role.name} role.")
    else:
        await ctx.send("Dogs role not found. Please ensure the role exists in this server.")

@bot.command()
async def assigncatsrole(ctx, member: Optional[discord.Member] = None):
    """Admin/Moderator command to assign Cats role to a user"""
    if not has_admin_or_moderator_role(ctx):
        await ctx.send("❌ You need Admin or Moderator role to use this command.")
        return
    
    if member is None:
        await ctx.send("❌ Please mention a user to assign the role to. Usage: `!assigncatsrole @username`")
        return
    
    role = discord.utils.get(ctx.guild.roles, name=cats_role_name)
    if role:
        if role not in member.roles:
            await member.add_roles(role)
            await ctx.send(f"🐱 Assigned {role.name} role to {member.mention}!")
        else:
            await ctx.send(f"{member.mention} already has the {role.name} role.")
    else:
        await ctx.send("Cats role not found. Please ensure the role exists in this server.")

@bot.command()
async def assignlizardsrole(ctx, member: Optional[discord.Member] = None):
    """Admin/Moderator command to assign Lizards role to a user"""
    if not has_admin_or_moderator_role(ctx):
        await ctx.send("❌ You need Admin or Moderator role to use this command.")
        return
    
    if member is None:
        await ctx.send("❌ Please mention a user to assign the role to. Usage: `!assignlizardsrole @username`")
        return
    
    role = discord.utils.get(ctx.guild.roles, name=lizards_role_name)
    if role:
        if role not in member.roles:
            await member.add_roles(role)
            await ctx.send(f"🦎 Assigned {role.name} role to {member.mention}!")
        else:
            await ctx.send(f"{member.mention} already has the {role.name} role.")
    else:
        await ctx.send("Lizards role not found. Please ensure the role exists in this server.")

@bot.command()
@bot.command()
async def assignpvprole(ctx, member: Optional[discord.Member] = None):
    """Admin/Moderator command to assign PVP role to a user"""
    if not has_admin_or_moderator_role(ctx):
        await ctx.send("❌ You need Admin or Moderator role to use this command.")
        return
    
    if member is None:
        await ctx.send("❌ Please mention a user to assign the role to. Usage: `!assignpvprole @username`")
        return
    
    role = discord.utils.get(ctx.guild.roles, name=pvp_role_name)
    if role:
        if role not in member.roles:
            await member.add_roles(role)
            await ctx.send(f"⚔️ Assigned {role.name} role to {member.mention}!")
        else:
            await ctx.send(f"{member.mention} already has the {role.name} role.")
    else:
        await ctx.send("PVP role not found. Please ensure the role exists in this server.")

# Admin/Moderator role removal commands
@bot.command()
async def removedogsrolefrom(ctx, member: Optional[discord.Member] = None):
    """Admin/Moderator command to remove Dogs role from a user"""
    if not has_admin_or_moderator_role(ctx):
        await ctx.send("❌ You need Admin or Moderator role to use this command.")
        return
    
    if member is None:
        await ctx.send("❌ Please mention a user to remove the role from. Usage: `!removedogsrolefrom @username`")
        return
    
    role = discord.utils.get(ctx.guild.roles, name=dogs_role_name)
    if role:
        if role in member.roles:
            await member.remove_roles(role)
            await ctx.send(f"🐶 Removed {role.name} role from {member.mention}!")
        else:
            await ctx.send(f"{member.mention} doesn't have the {role.name} role to remove.")
    else:
        await ctx.send("Dogs role not found. Please ensure the role exists in this server.")

@bot.command()
async def removecatsrolefrom(ctx, member: Optional[discord.Member] = None):
    """Admin/Moderator command to remove Cats role from a user"""
    if not has_admin_or_moderator_role(ctx):
        await ctx.send("❌ You need Admin or Moderator role to use this command.")
        return
    
    if member is None:
        await ctx.send("❌ Please mention a user to remove the role from. Usage: `!removecatsrolefrom @username`")
        return
    
    role = discord.utils.get(ctx.guild.roles, name=cats_role_name)
    if role:
        if role in member.roles:
            await member.remove_roles(role)
            await ctx.send(f"🐱 Removed {role.name} role from {member.mention}!")
        else:
            await ctx.send(f"{member.mention} doesn't have the {role.name} role to remove.")
    else:
        await ctx.send("Cats role not found. Please ensure the role exists in this server.")

@bot.command()
async def removelizardsrolefrom(ctx, member: Optional[discord.Member] = None):
    """Admin/Moderator command to remove Lizards role from a user"""
    if not has_admin_or_moderator_role(ctx):
        await ctx.send("❌ You need Admin or Moderator role to use this command.")
        return
    
    if member is None:
        await ctx.send("❌ Please mention a user to remove the role from. Usage: `!removelizardsrolefrom @username`")
        return
    
    role = discord.utils.get(ctx.guild.roles, name=lizards_role_name)
    if role:
        if role in member.roles:
            await member.remove_roles(role)
            await ctx.send(f"🦎 Removed {role.name} role from {member.mention}!")
        else:
            await ctx.send(f"{member.mention} doesn't have the {role.name} role to remove.")
    else:
        await ctx.send("Lizards role not found. Please ensure the role exists in this server.")

@bot.command()
async def removepvprolefrom(ctx, member: Optional[discord.Member] = None):
    """Admin/Moderator command to remove PVP role from a user"""
    if not has_admin_or_moderator_role(ctx):
        await ctx.send("❌ You need Admin or Moderator role to use this command.")
        return
    
    if member is None:
        await ctx.send("❌ Please mention a user to remove the role from. Usage: `!removepvprolefrom @username`")
        return
    
    role = discord.utils.get(ctx.guild.roles, name=pvp_role_name)
    if role:
        if role in member.roles:
            await member.remove_roles(role)
            await ctx.send(f"⚔️ Removed {role.name} role from {member.mention}!")
        else:
            await ctx.send(f"{member.mention} doesn't have the {role.name} role to remove.")
    else:
        await ctx.send("PVP role not found. Please ensure the role exists in this server.")

@bot.command()
async def voicefix(ctx):
    """Fix voice connection issues and resync"""
    if not music_bot:
        await ctx.send("❌ Music bot is not initialized!")
        return
    
    guild_id = ctx.guild.id
    
    embed = discord.Embed(
        title="🔧 Voice Connection Diagnostics & Fix",
        color=discord.Color.orange()
    )
    
    # Check Discord's view of bot's voice state
    bot_voice_state = ctx.guild.me.voice
    discord_voice_channel = bot_voice_state.channel.name if bot_voice_state and bot_voice_state.channel else "None"
    
    # Check our internal voice client records
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
    
    embed.add_field(name="Discord Voice Channel", value=discord_voice_channel, inline=True)
    embed.add_field(name="Has Voice Client Record", value="✅ Yes" if has_voice_client else "❌ No", inline=True)
    embed.add_field(name="Voice Client Connected", value="✅ Yes" if voice_client_connected else "❌ No", inline=True)
    embed.add_field(name="Total Voice Clients", value=str(len(discord_voice_clients)), inline=True)
    
    # Attempt to fix issues
    fixes_applied = []
    
    # Fix 1: Sync voice clients
    if music_bot._sync_voice_clients(guild_id):
        fixes_applied.append("✅ Synced voice client records")
    
    # Fix 2: If we have a Discord voice connection but no internal record, restore it
    if not has_voice_client and discord_voice_clients:
        music_bot.voice_clients[guild_id] = discord_voice_clients[0]
        fixes_applied.append("✅ Restored internal voice client record")
    
    # Fix 3: If music was playing but stopped, restart it
    was_playing = music_bot.is_playing.get(guild_id, False)
    if was_playing and guild_id in music_bot.voice_clients:
        voice_client = music_bot.voice_clients[guild_id]
        if not voice_client.is_playing() and not voice_client.is_paused():
            try:
                await music_bot._play_current_song(guild_id)
                fixes_applied.append("✅ Restarted music playback")
            except Exception as e:
                fixes_applied.append(f"❌ Failed to restart music: {str(e)[:50]}...")
    
    if fixes_applied:
        embed.add_field(name="Fixes Applied", value="\n".join(fixes_applied), inline=False)
    else:
        embed.add_field(name="Status", value="🟢 No issues detected", inline=False)
    
    embed.set_footer(text="Use this command if music stops randomly or voice commands don't work")
    await ctx.send(embed=embed)

@bot.command()
async def reconnect(ctx):
    """Force reconnect to voice channel if having issues"""
    if not music_bot:
        await ctx.send("❌ Music bot is not initialized!")
        return
    
    guild_id = ctx.guild.id
    
    # Check if user is in a voice channel
    if not ctx.author.voice:
        await ctx.send("❌ You need to be in a voice channel to use this command!")
        return
    
    target_channel = ctx.author.voice.channel
    was_playing = music_bot.is_playing.get(guild_id, False)
    
    await ctx.send("🔄 Force reconnecting to voice channel...")
    
    try:
        # Disconnect from current voice channel if connected
        if guild_id in music_bot.voice_clients:
            try:
                await music_bot.voice_clients[guild_id].disconnect()
                await ctx.send("🔌 Disconnected from old voice channel")
            except:
                pass  # Ignore disconnect errors
            
            # Clean up state
            del music_bot.voice_clients[guild_id]
        
        # Also try to disconnect any Discord native voice clients
        for vc in bot.voice_clients:
            try:
                vc_guild = getattr(vc, 'guild', None)
                if vc_guild and getattr(vc_guild, 'id', None) == guild_id:
                    await vc.disconnect(force=True)
                    break
            except:
                pass
        
        # Wait a moment for cleanup
        await asyncio.sleep(3)
        
        # Reconnect
        voice_client = await target_channel.connect()
        music_bot.voice_clients[guild_id] = voice_client
        
        await ctx.send(f"✅ Reconnected to {target_channel.name}!")
        
        # Restart music if it was playing
        if was_playing:
            music_bot.is_playing[guild_id] = True
            await ctx.send("🎵 Restarting music...")
            await music_bot._play_current_song(guild_id)
        
    except Exception as e:
        await ctx.send(f"❌ Reconnection failed: {str(e)}")

# Web server for Render.com health checks
async def health_check(request):
    """Health check endpoint for Render.com"""
    return web.Response(text="Bot is running!", status=200)

async def bot_status(request):
    """Bot status endpoint"""
    if bot.is_ready():
        # Calculate total users safely, filtering out None values
        total_users = sum(guild.member_count for guild in bot.guilds if guild.member_count is not None)
        status = {
            "bot_name": "Dogbot",
            "status": "online",
            "guilds": len(bot.guilds),
            "users": total_users
        }
    else:
        status = {
            "bot_name": "Dogbot", 
            "status": "starting",
            "guilds": 0,
            "users": 0
        }
    return web.json_response(status)

async def start_web_server():
    """Start the web server for Render.com"""
    app = web.Application()
    app.router.add_get('/', health_check)
    app.router.add_get('/health', health_check)
    app.router.add_get('/status', bot_status)
    
    # Get port from environment variable (Render.com sets this)
    port = int(os.getenv('PORT', 10000))
    
    print(f"[RENDER.COM] Starting web server on port {port}")
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f"[RENDER.COM] Web server started successfully on 0.0.0.0:{port}")

async def main():
    """Main function to run both bot and web server"""
    print("[RENDER.COM] Starting Dogbot for Render.com deployment...")
    
    # Validate token
    if not token:
        print("[RENDER.COM] ERROR: DISCORD_TOKEN environment variable not set!")
        return
    
    # Start the web server
    await start_web_server()
    
    # Start the bot
    print("[RENDER.COM] Starting Discord bot...")
    await bot.start(token)

# Start everything
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("[RENDER.COM] Bot stopped by user")
    except Exception as e:
        print(f"[RENDER.COM] Failed to start bot: {e}")
        raise
