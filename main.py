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
dnd_role_name = "DND"

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
            
            # Create the audio source with improved buffering for cloud deployment
            source = discord.FFmpegPCMAudio(
                filename,
                before_options='-re -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 10 -probesize 64M -analyzeduration 32M',
                options='-vn -bufsize 1024k'
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
                
            # Use improved FFmpeg options for cloud deployment fallback
            source = discord.FFmpegPCMAudio(
                data['url'],
                before_options='-re -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 10 -probesize 64M -analyzeduration 32M',
                options='-vn -bufsize 1024k'
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
    
    def _generate_shuffle_playlist(self, guild_id):
        """Generate a new shuffled playlist for the guild"""
        if not MUSIC_PLAYLISTS:
            return
            
        # Create a shuffled copy of the playlist
        shuffled = MUSIC_PLAYLISTS.copy()
        random.shuffle(shuffled)
        
        self.shuffle_playlists[guild_id] = shuffled
        self.shuffle_positions[guild_id] = 0
        print(f"Generated new shuffle playlist for guild {guild_id} with {len(shuffled)} songs")
    
    def _get_current_song_url(self, guild_id):
        """Get the current song URL from the shuffled playlist"""
        if guild_id not in self.shuffle_playlists or not self.shuffle_playlists[guild_id]:
            self._generate_shuffle_playlist(guild_id)
        
        if guild_id not in self.shuffle_playlists or not self.shuffle_playlists[guild_id]:
            return None
            
        position = self.shuffle_positions.get(guild_id, 0)
        playlist = self.shuffle_playlists[guild_id]
        
        if position >= len(playlist):
            # Regenerate shuffle when we reach the end
            self._generate_shuffle_playlist(guild_id)
            position = 0
            playlist = self.shuffle_playlists[guild_id]
        
        return playlist[position] if playlist else None
        
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
                    await voice_client.move_to(channel)
                    if auto_start:
                        await ctx.send(f"🎵 Moved to {channel.name} and starting music!")
                        if not self.is_playing.get(ctx.guild.id, False):
                            await self.play_music(ctx)
                    else:
                        await ctx.send(f"🎵 Moved to {channel.name}!")
                    return voice_client
            else:
                # Clean up disconnected voice client
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
            
            if auto_start:
                await ctx.send(f"🎵 Joined {channel.name} and starting music in shuffle mode!")
                await self.play_music(ctx)
            else:
                await ctx.send(f"🎵 Joined {channel.name}! Ready to play music in shuffle mode!")
            return voice_client
        except Exception as e:
            await ctx.send(f"❌ Failed to join voice channel: {e}")
            return None
    
    async def leave_voice_channel(self, ctx):
        """Leave the current voice channel"""
        if ctx.guild.id not in self.voice_clients:
            await ctx.send("❌ I'm not in a voice channel!")
            return
            
        voice_client = self.voice_clients[ctx.guild.id]
        await voice_client.disconnect()
        
        # Clean up all data for this guild
        del self.voice_clients[ctx.guild.id]
        if ctx.guild.id in self.current_songs:
            del self.current_songs[ctx.guild.id]
        if ctx.guild.id in self.is_playing:
            del self.is_playing[ctx.guild.id]
        if ctx.guild.id in self.shuffle_playlists:
            del self.shuffle_playlists[ctx.guild.id]
        if ctx.guild.id in self.shuffle_positions:
            del self.shuffle_positions[ctx.guild.id]
            
        await ctx.send("🎵 Left the voice channel!")
    
    async def play_music(self, ctx):
        """Start playing music from the shuffled playlist"""
        if ctx.guild.id not in self.voice_clients:
            await ctx.send("❌ I'm not in a voice channel! Use `!join` first.")
            return
            
        voice_client = self.voice_clients[ctx.guild.id]
        
        # Check if voice client is still connected
        if not voice_client.is_connected():
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
        
        # Stop current song if playing
        if voice_client.is_playing():
            voice_client.stop()
        
        # Move to next song in shuffle
        if ctx.guild.id not in self.shuffle_positions:
            self._generate_shuffle_playlist(ctx.guild.id)
        
        current_pos = self.shuffle_positions.get(ctx.guild.id, 0)
        next_pos = current_pos + 1
        
        # Check if we need to regenerate shuffle
        if ctx.guild.id not in self.shuffle_playlists or next_pos >= len(self.shuffle_playlists[ctx.guild.id]):
            self._generate_shuffle_playlist(ctx.guild.id)
            next_pos = 0
            await ctx.send(f"🔀 Reshuffling playlist! ⏭️ Skipping to next song...")
        else:
            await ctx.send(f"⏭️ Skipping to next song...")
        
        self.shuffle_positions[ctx.guild.id] = next_pos
        
        if self.is_playing.get(ctx.guild.id, False):
            await self._play_current_song(ctx.guild.id)
        else:
            await ctx.send(f"⏭️ Next song queued. Use `!start` to play.")
    
    async def previous_song(self, ctx):
        """Go back to the previous song in the shuffled playlist"""
        if ctx.guild.id not in self.voice_clients:
            await ctx.send("❌ I'm not in a voice channel!")
            return
            
        if not MUSIC_PLAYLISTS:
            await ctx.send("❌ No music playlist configured!")
            return
            
        voice_client = self.voice_clients[ctx.guild.id]
        
        # Stop current song if playing
        if voice_client.is_playing():
            voice_client.stop()
        
        # Move to previous song in shuffle
        if ctx.guild.id not in self.shuffle_positions:
            self._generate_shuffle_playlist(ctx.guild.id)
        
        current_pos = self.shuffle_positions.get(ctx.guild.id, 0)
        previous_pos = current_pos - 1
        
        # Handle wrap-around for previous
        if previous_pos < 0:
            if ctx.guild.id not in self.shuffle_playlists:
                self._generate_shuffle_playlist(ctx.guild.id)
            previous_pos = len(self.shuffle_playlists[ctx.guild.id]) - 1
        
        self.shuffle_positions[ctx.guild.id] = previous_pos
        
        if self.is_playing.get(ctx.guild.id, False):
            await ctx.send(f"⏮️ Going back to previous song...")
            await self._play_current_song(ctx.guild.id)
        else:
            await ctx.send(f"⏮️ Previous song queued. Use `!start` to play.")
    
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
        embed.add_field(name="URL", value=f"[Link]({current_url})", inline=False)
        embed.set_footer(text="🔀 Shuffle is enabled - songs play in random order")
        
        await ctx.send(embed=embed)
    
    async def _play_current_song(self, guild_id):
        """Play the current song (helper method for next/previous)"""
        if guild_id not in self.voice_clients or not self.is_playing.get(guild_id, False):
            return
            
        voice_client = self.voice_clients[guild_id]
        
        # Check if voice client is still connected
        if not voice_client.is_connected():
            print(f"Voice client disconnected for guild {guild_id}")
            self.is_playing[guild_id] = False
            return
        
        max_retries = len(MUSIC_PLAYLISTS)  # Try all songs once
        retries = 0
        current_pos = self.shuffle_positions.get(guild_id, 0)
        
        while retries < max_retries and self.is_playing.get(guild_id, False):
            try:
                # Get current song URL from shuffled playlist
                url = self._get_current_song_url(guild_id)
                if not url:
                    print(f"No URL available for guild {guild_id}")
                    break
                    
                print(f"Attempting to play: {url}")
                
                player = await YouTubeAudioSource.from_url(url, loop=self.bot.loop, stream=True)
                
                def after_playing(error):
                    if error:
                        print(f'Player error: {error}')
                    else:
                        print("Song finished playing normally")
                    
                    # Auto-advance to next song if we're still supposed to be playing
                    if self.is_playing.get(guild_id, False):
                        # Move to next position in shuffle
                        current_shuffle_pos = self.shuffle_positions.get(guild_id, 0)
                        next_shuffle_pos = current_shuffle_pos + 1
                        
                        # Check if we need to regenerate shuffle
                        if guild_id not in self.shuffle_playlists or next_shuffle_pos >= len(self.shuffle_playlists[guild_id]):
                            print(f"End of shuffle reached for guild {guild_id}, regenerating...")
                            self._generate_shuffle_playlist(guild_id)
                            next_shuffle_pos = 0
                        
                        self.shuffle_positions[guild_id] = next_shuffle_pos
                        print(f"Auto-advancing to shuffle position {next_shuffle_pos + 1}")
                        
                        # Schedule next song to play without blocking
                        async def play_next_song():
                            try:
                                await asyncio.sleep(0.5)  # Brief pause for smooth transition
                                await self._play_current_song(guild_id)
                            except Exception as e:
                                print(f"Error playing next song: {e}")
                        
                        asyncio.run_coroutine_threadsafe(
                            play_next_song(), 
                            self.bot.loop
                        )
                
                # Enhanced audio cleanup for playlist transitions (cloud-friendly)
                if voice_client.is_playing() or voice_client.is_paused():
                    print(f"[RENDER.COM] Stopping playlist audio for clean transition...")
                    voice_client.stop()
                    await asyncio.sleep(0.8)  # Cloud-friendly cleanup delay
                    
                    # Double-check cleanup
                    if voice_client.is_playing():
                        print(f"[RENDER.COM] Forcing second stop for playlist...")
                        voice_client.stop()
                        await asyncio.sleep(0.5)
                
                # Try to play with cloud-aware error handling
                try:
                    voice_client.play(player, after=after_playing)
                    print(f"[RENDER.COM] Playlist: Successfully started playing: {player.title}")
                except Exception as play_error:
                    if "already playing" in str(play_error).lower():
                        print(f"[RENDER.COM] Playlist 'already playing' error, forcing cleanup...")
                        voice_client.stop()
                        await asyncio.sleep(1.5)
                        voice_client.play(player, after=after_playing)
                        print(f"[RENDER.COM] Playlist retry successful")
                    else:
                        raise play_error
                        
                return  # Success! Exit the retry loop
                
            except Exception as e:
                current_url = self._get_current_song_url(guild_id) or "unknown"
                print(f"Error playing music from {current_url}: {e}")
                retries += 1
                
                # Skip to next song and try again
                current_shuffle_pos = self.shuffle_positions.get(guild_id, 0)
                next_shuffle_pos = current_shuffle_pos + 1
                
                # Check if we need to regenerate shuffle
                if guild_id not in self.shuffle_playlists or next_shuffle_pos >= len(self.shuffle_playlists[guild_id]):
                    self._generate_shuffle_playlist(guild_id)
                    next_shuffle_pos = 0
                
                self.shuffle_positions[guild_id] = next_shuffle_pos
                
                # Add a small delay before retrying
                await asyncio.sleep(1)
        
        # If we exhausted all retries
        if self.is_playing.get(guild_id, False):
            print(f"Failed to play any songs after {max_retries} attempts")
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
        if not MUSIC_PLAYLISTS:
            await ctx.send("📝 Playlist is empty! Use `!add <youtube_url>` to add songs.")
            return
        
        embed = discord.Embed(
            title="🎵 Current Playlist",
            description=f"Total songs: {len(MUSIC_PLAYLISTS)}",
            color=discord.Color.blue()
        )
        
        # Show up to 10 songs to avoid embed limits
        display_count = min(len(MUSIC_PLAYLISTS), 10)
        
        for i in range(display_count):
            url = MUSIC_PLAYLISTS[i]
            
            # Try to get the actual song title using YouTube API
            try:
                if youtube_api:
                    video_id = youtube_api.extract_video_id(url)
                    if video_id:
                        video_details = await youtube_api.get_video_details(video_id)
                        title = video_details['snippet']['title'] if video_details else f"Song {i + 1}"
                    else:
                        title = f"Song {i + 1}"
                else:
                    title = f"Song {i + 1} (YouTube API not configured)"
            except:
                # Fallback to extracting from URL or use generic name
                if 'youtube.com/watch?v=' in url:
                    video_id = url.split('v=')[1].split('&')[0]
                    title = f"YouTube Video ({video_id})"
                elif 'youtu.be/' in url:
                    video_id = url.split('youtu.be/')[1].split('?')[0]
                    title = f"YouTube Video ({video_id})"
                else:
                    title = f"Song {i + 1}"
            
            current_indicator = "▶️ " if i == self.current_songs.get(ctx.guild.id, 0) else ""
            embed.add_field(
                name=f"{current_indicator}{i + 1}. {title}",
                value=f"[Link]({url})",
                inline=False
            )
        
        if len(MUSIC_PLAYLISTS) > 10:
            embed.set_footer(text=f"Showing first 10 of {len(MUSIC_PLAYLISTS)} songs")
        
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
        
        # Auto-repeat status
        auto_repeat = "🔄 Enabled" if self.is_playing.get(guild_id, False) else "❌ Disabled"
        embed.add_field(name="Auto-Repeat", value=auto_repeat, inline=True)
        
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
        
        embed.set_footer(text="🔀 Shuffle enabled • Auto-repeat keeps music playing continuously")
        
        await ctx.send(embed=embed)

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
        
        # Create campaign table for shared D&D sessions
        await db.execute("""
            CREATE TABLE IF NOT EXISTS campaign_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                user_name TEXT NOT NULL,
                character_name TEXT,
                message TEXT NOT NULL,
                response TEXT NOT NULL,
                is_active INTEGER DEFAULT 1,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create undo stack table for universal undo/redo
        await db.execute("""
            CREATE TABLE IF NOT EXISTS undo_stack (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                action_type TEXT NOT NULL,  -- 'chat' or 'campaign'
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
            await db.execute("ALTER TABLE undo_stack ADD COLUMN action_type TEXT DEFAULT 'campaign'")
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

async def save_campaign_history(channel_id: str, user_id: str, user_name: str, character_name: str | None, message: str, response: str) -> int:
    """Save campaign interaction to shared channel history, returns the action ID"""
    async with aiosqlite.connect("chat_history.db") as db:
        cursor = await db.execute(
            "INSERT INTO campaign_history (channel_id, user_id, user_name, character_name, message, response, is_active) VALUES (?, ?, ?, ?, ?, ?, 1)",
            (channel_id, user_id, user_name, character_name, message, response)
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

async def get_campaign_history(channel_id: str, limit: int = 10):
    """Get recent campaign history for a channel (shared between all players) - only active actions"""
    async with aiosqlite.connect("chat_history.db") as db:
        cursor = await db.execute(
            "SELECT user_name, character_name, message, response FROM campaign_history WHERE channel_id = ? AND is_active = 1 ORDER BY timestamp ASC LIMIT ?",
            (channel_id, limit)
        )
        rows = await cursor.fetchall()
        return [(str(row[0]), str(row[1]) if row[1] else None, str(row[2]), str(row[3])) for row in rows]

async def undo_last_action(channel_id: str, user_id: str) -> tuple[bool, str]:
    """Undo the last action (chat or campaign) by the user in the channel. Returns (success, message)"""
    async with aiosqlite.connect("chat_history.db") as db:
        # Try campaign action first (most recent)
        cursor = await db.execute(
            "SELECT id, user_name, character_name, message FROM campaign_history WHERE channel_id = ? AND user_id = ? AND is_active = 1 ORDER BY timestamp DESC LIMIT 1",
            (channel_id, user_id)
        )
        campaign_row = await cursor.fetchone()
        
        # Try chat action
        cursor = await db.execute(
            "SELECT id, user_name, message FROM chat_history WHERE channel_id = ? AND user_id = ? ORDER BY timestamp DESC LIMIT 1",
            (channel_id, user_id)
        )
        chat_row = await cursor.fetchone()
        
        campaign_action = None
        chat_action = None
        
        if campaign_row:
            campaign_action = {
                'id': campaign_row[0],
                'user_name': campaign_row[1],
                'character_name': campaign_row[2],
                'message': campaign_row[3],
                'type': 'campaign'
            }
        if chat_row:
            chat_action = {
                'id': chat_row[0],
                'user_name': chat_row[1],
                'message': chat_row[2],
                'type': 'chat'
            }
        
        # Choose the most recent action (simplified - assumes IDs are sequential)
        action_to_undo = None
        if campaign_action and chat_action:
            action_to_undo = campaign_action if campaign_action['id'] > chat_action['id'] else chat_action
        elif campaign_action:
            action_to_undo = campaign_action
        elif chat_action:
            action_to_undo = chat_action
        
        if not action_to_undo:
            return False, "No actions to undo!"
        
        if action_to_undo['type'] == 'campaign':
            # Mark campaign action as inactive
            await db.execute(
                "UPDATE campaign_history SET is_active = 0 WHERE id = ?",
                (action_to_undo['id'],)
            )
            
            player_display = action_to_undo['user_name']
            if action_to_undo['character_name']:
                player_display += f" ({action_to_undo['character_name']})"
            
            message = f"Undone campaign action by {player_display}: {action_to_undo['message'][:100]}..."
        else:
            # Delete chat action
            await db.execute(
                "DELETE FROM chat_history WHERE id = ?",
                (action_to_undo['id'],)
            )
            
            message = f"Undone chat message by {action_to_undo['user_name']}: {action_to_undo['message'][:100]}..."
        
        # Add to undo stack
        await db.execute(
            "INSERT INTO undo_stack (channel_id, user_id, action_type, action_id) VALUES (?, ?, ?, ?)",
            (channel_id, user_id, action_to_undo['type'], action_to_undo['id'])
        )
        
        await db.commit()
        return True, message

async def redo_last_undo(channel_id: str, user_id: str) -> tuple[bool, str]:
    """Redo the last undone action by the user. Returns (success, message)"""
    async with aiosqlite.connect("chat_history.db") as db:
        # Get the most recent undo by this user
        cursor = await db.execute(
            "SELECT action_type, action_id FROM undo_stack WHERE channel_id = ? AND user_id = ? ORDER BY timestamp DESC LIMIT 1",
            (channel_id, user_id)
        )
        row = await cursor.fetchone()
        
        if not row:
            return False, "No actions to redo!"
        
        action_type, action_id = row
        
        if action_type == 'campaign':
            # Get campaign action details
            cursor = await db.execute(
                "SELECT user_name, character_name, message FROM campaign_history WHERE id = ?",
                (action_id,)
            )
            action_row = await cursor.fetchone()
            
            if not action_row:
                return False, "Action not found!"
            
            user_name, char_name, action = action_row
            
            # Reactivate the action
            await db.execute(
                "UPDATE campaign_history SET is_active = 1 WHERE id = ?",
                (action_id,)
            )
            
            player_display = user_name
            if char_name:
                player_display += f" ({char_name})"
            
            message = f"Redone campaign action by {player_display}: {action[:100]}..."
        else:
            # For chat actions, we need to restore them (this is complex since we deleted them)
            # For now, just inform that chat actions can't be redone
            return False, "Chat actions cannot be redone once undone!"
        
        # Remove from undo stack
        await db.execute(
            "DELETE FROM undo_stack WHERE channel_id = ? AND user_id = ? AND action_type = ? AND action_id = ? ORDER BY timestamp DESC LIMIT 1",
            (channel_id, user_id, action_type, action_id)
        )
        
        await db.commit()
        return True, message

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

async def get_ai_response_with_campaign_history(channel_id: str, user_name: str, character_name: str | None, prompt: str, max_tokens: int = 500) -> str:
    """Get response from Venice AI using shared campaign history"""
    if not venice_api_key:
        return "AI features are disabled. Please set VENICE_API_KEY environment variable."
    
    messages = []
    
    # Add campaign context
    campaign_context = f"""You are the Dungeon Master for a D&D campaign with a friendly, engaging personality! 🎲⚔️🏰🐉 

Use Discord formatting to make the adventure more immersive:
- **Bold** for important actions, names, and dramatic moments
- *Italics* for descriptions, thoughts, and atmospheric details  
- `Code blocks` for game mechanics, dice rolls, and stats
- > Quotes for NPC dialogue and special narration
- Emojis frequently to enhance the storytelling experience

Remember all characters, their actions, the story so far, and maintain consistency across the adventure.

When you need a player to make a roll (skill checks, saving throws, attack rolls, etc.), simply ask them to "roll a d20" and they will use the !roll command. You can then interpret their roll result based on the context and difficulty of the task.

Current player: {user_name}"""
    
    if character_name:
        campaign_context += f" (playing as {character_name})"
    
    messages.append({"role": "system", "content": campaign_context})
    
    # Add campaign history for context
    history = await get_campaign_history(channel_id, limit=8)  # More history for campaigns
    for player_name, char_name, user_msg, ai_response in history:
        player_display = f"{player_name}"
        if char_name:
            player_display += f" ({char_name})"
        
        messages.append({"role": "user", "content": f"{player_display}: {user_msg}"})
        messages.append({"role": "assistant", "content": ai_response})
    
    # Add current message
    current_player = f"{user_name}"
    if character_name:
        current_player += f" ({character_name})"
    
    messages.append({"role": "user", "content": f"{current_player}: {prompt}"})
    
    headers = {
        "Authorization": f"Bearer {venice_api_key}",
        "Content-Type": "application/json"
    }
    
    data = {
        "model": VENICE_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.8  # Slightly higher for creativity in storytelling
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
        import subprocess
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
        import discord.opus
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

# Helper function to check for admin/moderator permissions
def has_admin_or_moderator_role(ctx):
    """Check if user has Admin or Moderator role"""
    user_roles = [role.name.lower() for role in ctx.author.roles]
    return any(role in ['admin', 'moderator', 'administrator'] for role in user_roles)

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
    """Show playback status"""
    if not music_bot:
        await ctx.send("❌ Music bot is not initialized!")
        return
    await music_bot.get_playback_status(ctx)

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

# Character storage for D&D campaigns
character_names = {}  # user_id -> character_name

@bot.command()
async def character(ctx, *, name):
    """Set your character name for D&D campaigns"""
    user_id = str(ctx.author.id)
    character_names[user_id] = name
    await ctx.send(f"🎭 Character name set to: **{name}**")

@bot.command()
async def dnd(ctx, *, action):
    """Take action in D&D campaign"""
    user_id = str(ctx.author.id)
    user_name = ctx.author.display_name
    channel_id = str(ctx.channel.id)
    character_name = character_names.get(user_id)
    
    response = await get_ai_response_with_campaign_history(channel_id, user_name, character_name, action)
    
    # Save to campaign history
    await save_campaign_history(channel_id, user_id, user_name, character_name, action, response)
    
    await ctx.send(response)

@bot.command()
async def campaign(ctx):
    """View campaign history"""
    channel_id = str(ctx.channel.id)
    history = await get_campaign_history(channel_id, limit=10)
    
    if not history:
        await ctx.send("📜 No campaign history found in this channel!")
        return
    
    embed = discord.Embed(
        title="📜 Campaign History",
        description="Recent actions in this campaign:",
        color=discord.Color.purple()
    )
    
    for user_name, char_name, message, response in history[-5:]:  # Show last 5
        player = user_name
        if char_name:
            player += f" ({char_name})"
        
        embed.add_field(
            name=f"🎭 {player}",
            value=f"**Action:** {message[:100]}...\n**DM:** {response[:150]}...",
            inline=False
        )
    
    await ctx.send(embed=embed)

@bot.command()
async def clearcampaign(ctx):
    """Clear campaign history for this channel (Admin/Moderator only)"""
    if not has_admin_or_moderator_role(ctx):
        await ctx.send("❌ You need Admin or Moderator role to use this command.")
        return
    
    channel_id = str(ctx.channel.id)
    
    async with aiosqlite.connect("chat_history.db") as db:
        await db.execute("DELETE FROM campaign_history WHERE channel_id = ?", (channel_id,))
        await db.execute("DELETE FROM undo_stack WHERE channel_id = ?", (channel_id,))
        await db.commit()
    
    await ctx.send("🗑️ Campaign history cleared for this channel!")

@bot.command()
async def roll(ctx):
    """Roll a d20"""
    roll_result = random.randint(1, 20)
    
    if roll_result == 20:
        await ctx.send(f"🎲 {ctx.author.mention} rolled a **{roll_result}**! 🌟 **CRITICAL SUCCESS!** 🌟")
    elif roll_result == 1:
        await ctx.send(f"🎲 {ctx.author.mention} rolled a **{roll_result}**! 💥 **CRITICAL FAILURE!** 💥")
    elif roll_result >= 15:
        await ctx.send(f"🎲 {ctx.author.mention} rolled a **{roll_result}**! ✨ Great roll!")
    elif roll_result <= 5:
        await ctx.send(f"🎲 {ctx.author.mention} rolled a **{roll_result}**! 😬 Ouch...")
    else:
        await ctx.send(f"🎲 {ctx.author.mention} rolled a **{roll_result}**!")

@bot.command()
async def undo(ctx):
    """Undo last action"""
    channel_id = str(ctx.channel.id)
    user_id = str(ctx.author.id)
    
    success, message = await undo_last_action(channel_id, user_id)
    
    if success:
        await ctx.send(f"↩️ {message}")
    else:
        await ctx.send(f"❌ {message}")

@bot.command()
async def redo(ctx):
    """Redo last undone action"""
    channel_id = str(ctx.channel.id)
    user_id = str(ctx.author.id)
    
    success, message = await redo_last_undo(channel_id, user_id)
    
    if success:
        await ctx.send(f"↪️ {message}")
    else:
        await ctx.send(f"❌ {message}")

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
        import subprocess
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
    embed.add_field(name="🐕 Basic", value="`!hello` - Greet the bot\n`!help` - Show this help\n\n🤖 **AI Commands:**\n`!ask <question>` - Ask AI anything\n`!chat <message>` - Chat with AI (with memory)\n`!undo` - Undo last action\n`!redo` - Redo last undone action", inline=False)
    embed.add_field(name="🎵 Music Bot", value="`!join` - Join voice channel and auto-start music\n`!leave` - Leave voice channel\n`!start` - Start/resume music\n`!stop` - Stop music\n`!next` - Skip to next song\n`!previous` - Go to previous song\n`!play` - Resume current playlist\n`!play <youtube_link>` - Play specific song immediately (returns to playlist after)\n`!playlist` - Show current playlist\n`!add <youtube_url>` - Add song to playlist\n`!remove <youtube_url>` - Remove song from playlist\n`!nowplaying` - Show current song info\n`!status` - Show playback and auto-repeat status\n`!reshuffle` - Generate new shuffle order", inline=False)
    
    embed.add_field(name="🎭 Roles", value="`!catsrole` - Get Cats role\n`!dogsrole` - Get Dogs role\n`!lizardsrole` - Get Lizards role\n`!pvprole` - Get PVP role\n`!dndrole` - Get DND role\n`!remove<role>` - Remove any role (e.g., `!removecatsrole`)", inline=False)
    embed.add_field(name="🗳️ Utility", value="`!poll <question>` - Create a poll\n`!say <message>` - Make the bot say something", inline=False)
    embed.add_field(name="🎲 D&D Campaign", value="`!dnd <action>` - Take action in campaign\n`!character <n>` - Set your character name\n`!campaign` - View campaign history\n`!clearcampaign` - Clear channel campaign\n`!roll` - Roll a d20", inline=False)

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
              "`!assigndndrole @user` - Assign DND role\n"
              "`!assignpvprole @user` - Assign PVP role", 
        inline=False
    )
    
    embed.add_field(
        name="🚫 Role Removal", 
        value="`!removedogsrolefrom @user` - Remove Dogs role\n"
              "`!removecatsrolefrom @user` - Remove Cats role\n"
              "`!removelizardsrolefrom @user` - Remove Lizards role\n"
              "`!removedndrolefrom @user` - Remove DND role\n"
              "`!removepvprolefrom @user` - Remove PVP role", 
        inline=False
    )
    
    embed.add_field(
        name="🔧 YouTube Configuration", 
        value="`!ytdlstatus` - Show YouTube API configuration", 
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
async def dndrole(ctx):
    role = discord.utils.get(ctx.guild.roles, name=dnd_role_name)
    if role:
        await ctx.author.add_roles(role)
        await ctx.send(f"🎲 Assigned {role.name} role to {ctx.author.name}!")
    else:
        await ctx.send("DND role not found. Please ensure the role exists in this server.")

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
async def removedndrole(ctx):
    role = discord.utils.get(ctx.guild.roles, name=dnd_role_name)
    if role:
        if role in ctx.author.roles:
            await ctx.author.remove_roles(role)
            await ctx.send(f"🎲 Removed {role.name} role from {ctx.author.name}!")
        else:
            await ctx.send(f"You don't have the {role.name} role to remove.")
    else:
        await ctx.send("DND role not found. Please ensure the role exists in this server.")

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
async def assigndndrole(ctx, member: Optional[discord.Member] = None):
    """Admin/Moderator command to assign DND role to a user"""
    if not has_admin_or_moderator_role(ctx):
        await ctx.send("❌ You need Admin or Moderator role to use this command.")
        return
    
    if member is None:
        await ctx.send("❌ Please mention a user to assign the role to. Usage: `!assigndndrole @username`")
        return
    
    role = discord.utils.get(ctx.guild.roles, name=dnd_role_name)
    if role:
        if role not in member.roles:
            await member.add_roles(role)
            await ctx.send(f"🎲 Assigned {role.name} role to {member.mention}!")
        else:
            await ctx.send(f"{member.mention} already has the {role.name} role.")
    else:
        await ctx.send("DND role not found. Please ensure the role exists in this server.")

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
async def removedndrolefrom(ctx, member: Optional[discord.Member] = None):
    """Admin/Moderator command to remove DND role from a user"""
    if not has_admin_or_moderator_role(ctx):
        await ctx.send("❌ You need Admin or Moderator role to use this command.")
        return
    
    if member is None:
        await ctx.send("❌ Please mention a user to remove the role from. Usage: `!removedndrolefrom @username`")
        return
    
    role = discord.utils.get(ctx.guild.roles, name=dnd_role_name)
    if role:
        if role in member.roles:
            await member.remove_roles(role)
            await ctx.send(f"🎲 Removed {role.name} role from {member.mention}!")
        else:
            await ctx.send(f"{member.mention} doesn't have the {role.name} role to remove.")
    else:
        await ctx.send("DND role not found. Please ensure the role exists in this server.")

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

if __name__ == "__main__":
    # Start HTTP server for Render health checks
    port = int(os.getenv("PORT", 1000))
    app = web.Application()
    async def handle_root(request):
        return web.Response(text="Dogbot is running!")
    app.router.add_get('/', handle_root)
    runner = web.AppRunner(app)
    loop = asyncio.get_event_loop()
    loop.run_until_complete(runner.setup())
    site = web.TCPSite(runner, '0.0.0.0', port)
    loop.run_until_complete(site.start())
    print(f"🐕 Dogbot web server listening on 0.0.0.0:{port}")

    # Run Discord bot
    bot.run(token)
