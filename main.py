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
import yt_dlp
import shutil

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

bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

dogs_role_name = "Dogs"
cats_role_name = "Cats"
lizards_role_name = "Lizards"
pvp_role_name = "PVP"
dnd_role_name = "DND"
dnd1_role_name = "DND1"
dnd2_role_name = "DND2"
dnd3_role_name = "DND3"

# Music Bot Configuration
MUSIC_PLAYLISTS = [
    # Existing tracks
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",  # Rick Astley - Never Gonna Give You Up
    "https://www.youtube.com/watch?v=L_jWHffIx5E",  # Smash Mouth - All Star
    "https://www.youtube.com/watch?v=9bZkp7q19f0",  # PSY - Gangnam Style
    "https://www.youtube.com/watch?v=fJ9rUzIMcZQ",  # Queen - Bohemian Rhapsody
    "https://www.youtube.com/watch?v=hTWKbfoikeg",  # Smash Mouth - All Star (alternate upload)
    "https://www.youtube.com/watch?v=60ItHLz5WEA",  # Alan Walker - Faded
    "https://www.youtube.com/watch?v=Zi_XLOBDo_Y",  # Michael Jackson - Billie Jean
    "https://www.youtube.com/watch?v=A_MjCqQoLLA",  # The Beatles - Hey Jude
    "https://youtu.be/96ZzJP1psKg?si=dwMnHI4FuBILY60s", # Ella baila sola Ángel Aispuro - Ver. Extendida
    "https://www.youtube.com/watch?v=3MAxltiSJUE",  # Calvin Harris & Rag'n'Bone Man - Stay With Me
    "https://youtu.be/P3cffdsEXXw?si=P_QyVqHDivCvOCw4", # Harry Styles - Golden (Official Video)
    "https://youtu.be/bd-MRcTbx7k?si=AvvPPqRO3ECaoJY3", # Cannons – Golden (Harry Styles Cover) 
    "https://youtu.be/1VGfW2n01nM?si=08Bk2WydIGVGyiM9", # Daddy - Devin Townsend · Ché Aimee Dorval
    "https://youtu.be/AGM8BMqBcTo?si=AnnJ2NFWJo80V3bx", # Gorillaz - Plastic Beach - Plastic Beach
    "https://youtu.be/VCkFSe3voRc?si=mppyaq3Mdm1aEEWf", # Gorillaz - Kids With Guns (Official Video)
    "https://youtu.be/H5v3kku4y6Q?si=w2vLtWtCJdA7Fx7n", # Harry Styles - As It Was (Official Video)
    "https://youtu.be/bzZjG9B9_Ug?si=ylFYFUc3SYOdY2qS", # Cannons - Purple Sun (Living Room Sessions)
    "https://youtu.be/CMWLX0KXwF4?si=N2emMk8cv9z-f5_q", # Tove Lo - No One Dies From Love (Official Music Video)
    "https://youtu.be/yIQui6Y9Ho4?si=_13S-ic6M-kkvZYg", # Chris Isaak - Wicked Game (Lyrics)
    "https://youtu.be/2yHGUoozvLI?si=G7jrGwPpKvneYOpA", # DVBBS - GOMF feat. BRIDGE (Lyric Video) [Ultra Music]
    "https://youtu.be/kPa7bsKwL-c?si=8_BAoMayMDgtYKNv", # Lady Gaga, Bruno Mars - Die With A Smile (Official Music Video)
    "https://youtu.be/9tC-FOXioDo?si=mhBVtIeTPjf-w5a5", # Sunbeam Sound Machine - In Your Arms (Music Video)
    "https://youtu.be/gxmILdU2O6U?si=Uz-p4d9oT2T4jdru", # Daya - Left Me Yet
    "https://youtu.be/qod03PVTLqk?si=cuCu6-u2TA3Of7IS", # Elton John, Dua Lipa - Cold Heart (PNAU Remix) (Official Video)
    "https://youtu.be/vuzkn8nQfqY?si=Gs_TvWoV1K7H_SB_", # internetBoi - Jet Plane
    "https://youtu.be/SXF-Eu8XwC8?si=8rv44tSF6xTwJ9_b", # Cannons - Talk Talk (Official Video)
    "https://youtu.be/E07s5ZYygMg?si=kmp-wu410nLhGnR9", # Harry Styles - Watermelon Sugar (Official Video)
    "https://youtu.be/0WxDrVUrSvI?si=_EXWUaTWwIljM2gc", # Lily Allen | Smile (Official Video)
    "https://youtu.be/7IK_safV6pc?si=13dH__vqQgEjw_Tl", # Gus Dapperton - Ditch
    "https://youtu.be/egni6PAGEUM?si=W6FYseFrW17NbbJU", # Lost At Sea - Dawg Yawp
    "https://youtu.be/wGsSAVz1BBQ?si=E20h1MtVD6zSiI1q", # Steve Monite - Only You
    "https://youtu.be/28tZ-S1LFok?si=-BhvmPEGWMscg7cN", # Phantogram "When I'm Small" [Official Video]
    "https://youtu.be/TJAfLE39ZZ8?si=2k22gunJGd8z7Vm2", # Amy Winehouse - Back To Black
    "https://youtu.be/MS67xk4LKK8?si=DLRbzXoxvWFQF4ZC", # ROYA - CRUISE | INSTAGRAM EDIT | NOT OFFICIAL
    "https://youtu.be/n5yZNu0ATjk?si=I9FEmJ-f-hj-MZK2", # Cheat Codes - Be The One (with Kaskade) [Official Music Video]
    "https://youtu.be/y8SD-TsgHOI?si=2ZmV5hH3D4DIkV6E", # Hippie Sabotage - "Straight To My Head" [Official Audio]
    "https://youtu.be/zXbky7eU3qg?si=6UJHn_7ZtafgQ5Sm", # Kaskade, Rebecca & Fiona - Turn it Down (Official Music Video)
    "https://youtu.be/HPc8QMycGno?si=mcYRJz2j2AteDlWJ", # Virtual Self - Ghost Voices (Official Music Video)
    "https://youtu.be/mIMMZQJ1H6E?si=jVi39E9PfifBfZaJ", # Santigold - Disparate Youth (Official Music Video)
    "https://youtu.be/nSQXH8otFGQ?si=IGaA8M9D4gFPWqCP", # Just A Gent - Open Spaces (feat. Nevve) [Monstercat Lyric Video]
    "https://youtu.be/bmitvsoXgaI?si=SlWPwMSvbx1Cnuxt", # Cannons - Tunnel of You (Official Video)
    "https://youtu.be/jdxMcKI2_Gw?si=R9X2kBQjidMwj5ex", # Chase & Status and Bou - Baddadan ft. IRAH, Flowdan, Trigga, Takura (Lyrics)
    "https://youtu.be/m4_9TFeMfJE?si=pPPKw9B87votYrkn", # Doja Cat - Paint The Town Red (Official Video)
    "https://youtu.be/TLiGA_wrNp0?si=7YGfdVHKOUEh4P6X", # Doja Cat - Go To Town (Official Video)
    "https://youtu.be/pQsF3pzOc54?si=n9hn2BSoQdHjq-gV", # Chamber Of Reflection - Mac DeMarco
    "https://youtu.be/B9FzVhw8_bY?si=B9SN4y0_K2F9iLar", # The Dead South - In Hell I'll Be In Good Company [Official Music Video]
    "https://youtu.be/wOwblaKmyVw?si=RhjLaWK0u59fmHWU", # Miley Cyrus - The Backyard Sessions - "Jolene"
    "https://youtu.be/f2JuxM-snGc?si=XDqGTrN9gS25QwIV", # Lorde - Team
    "https://youtu.be/9gWIIIr2Asw?si=SGei3f_24XnweXPX", # Teddy Swims - Lose Control (The Village Sessions)
    
]
# FFmpeg Configuration for Cloud Deployment (Render.com)
def get_ffmpeg_executable():
    """Find FFmpeg executable for cloud deployment"""
    # Check if FFmpeg is in PATH (Render.com has it pre-installed)
    ffmpeg_path = shutil.which('ffmpeg')
    if ffmpeg_path:
        return ffmpeg_path
    
    # Fallback paths for common cloud platforms
    common_paths = [
        '/usr/bin/ffmpeg',
        '/usr/local/bin/ffmpeg', 
        '/opt/bin/ffmpeg'
    ]
    
    for path in common_paths:
        if os.path.exists(path):
            return path
    
    # If not found, return 'ffmpeg' and hope it's in PATH
    return 'ffmpeg'

# Get FFmpeg executable path
FFMPEG_EXECUTABLE = get_ffmpeg_executable()
print(f"Using FFmpeg: {FFMPEG_EXECUTABLE}")

# yt-dlp options for audio extraction with improved YouTube support
YTDL_OPTIONS = {
    'format': 'bestaudio/best',
    'extractaudio': True,
    'audioformat': 'mp3',
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
    # YouTube-specific options to avoid authentication issues
    'extractor_args': {
        'youtube': {
            'player_client': ['mweb', 'web'],  # Use mobile web and web clients
            'player_skip': ['configs'],  # Skip some config requests
        }
    },
    # Cookie handling (optional - can be enabled if needed)
    # 'cookiesfrombrowser': ('chrome',),  # Uncomment to use browser cookies
    # Rate limiting to avoid "This content isn't available" errors
    'sleep_interval': 1,  # Sleep 1 second between requests
    'max_sleep_interval': 5,  # Max sleep interval
}

FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn',
    'executable': FFMPEG_EXECUTABLE
}

class YTDLSource(discord.PCMVolumeTransformer):
    """Audio source for YouTube/music streaming"""
    
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=False):
        """Create audio source from URL"""
        loop = loop or asyncio.get_event_loop()
        
        try:
            with yt_dlp.YoutubeDL(YTDL_OPTIONS) as ytdl:
                data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))
                
                if data and 'entries' in data and data['entries']:
                    # Take first item from a playlist
                    data = data['entries'][0]
                
                if not data:
                    raise ValueError("Could not extract video information")
                
                filename = data['url'] if stream else ytdl.prepare_filename(data)
                
            return cls(discord.FFmpegPCMAudio(
                filename, 
                before_options=FFMPEG_OPTIONS['before_options'], 
                options=FFMPEG_OPTIONS['options'],
                executable=FFMPEG_OPTIONS['executable']
            ), data=data)
        except yt_dlp.utils.DownloadError as e:
            error_msg = str(e)
            if any(phrase in error_msg.lower() for phrase in [
                "sign in to confirm you're not a bot", 
                "requires authentication",
                "po token",
                "this content isn't available"
            ]):
                print(f"YouTube authentication/rate limit error for {url}: {error_msg}")
                raise ValueError(f"YouTube requires authentication or rate limited: {url}")
            elif any(phrase in error_msg.lower() for phrase in [
                "video unavailable", 
                "private video",
                "deleted video",
                "not available"
            ]):
                print(f"Video unavailable for {url}: {error_msg}")
                raise ValueError(f"Video unavailable: {url}")
            elif "age-restricted" in error_msg.lower():
                print(f"Age-restricted video for {url}: {error_msg}")
                raise ValueError(f"Age-restricted video: {url}")
            else:
                print(f"Download error for {url}: {error_msg}")
                raise ValueError(f"Cannot download video: {error_msg}")
        except Exception as e:
            print(f"Error creating audio source from {url}: {e}")
            raise ValueError(f"Failed to create audio source: {str(e)}")

class MusicBot:
    """Music bot functionality"""
    
    def __init__(self, bot):
        self.bot = bot
        self.voice_clients = {}  # guild_id -> voice_client
        self.current_songs = {}  # guild_id -> current_song_index
        self.is_playing = {}  # guild_id -> bool
        
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
            self.current_songs[ctx.guild.id] = 0
            self.is_playing[ctx.guild.id] = False
            
            if auto_start:
                await ctx.send(f"🎵 Joined {channel.name} and starting music!")
                await self.play_music(ctx)
            else:
                await ctx.send(f"🎵 Joined {channel.name}! Ready to play music!")
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
        
        # Clean up
        del self.voice_clients[ctx.guild.id]
        if ctx.guild.id in self.current_songs:
            del self.current_songs[ctx.guild.id]
        if ctx.guild.id in self.is_playing:
            del self.is_playing[ctx.guild.id]
            
        await ctx.send("🎵 Left the voice channel!")
    
    async def play_music(self, ctx):
        """Start playing music from the playlist"""
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
            
        self.is_playing[ctx.guild.id] = True
        
        # Get current song info for feedback
        current_index = self.current_songs.get(ctx.guild.id, 0)
        total_songs = len(MUSIC_PLAYLISTS)
        
        await ctx.send(f"🎵 Starting music stream... Playing song {current_index + 1} of {total_songs}")
        
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
        """Skip to the next song in the playlist"""
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
        
        # Move to next song
        current_index = self.current_songs.get(ctx.guild.id, 0)
        next_index = (current_index + 1) % len(MUSIC_PLAYLISTS)
        self.current_songs[ctx.guild.id] = next_index
        
        if self.is_playing.get(ctx.guild.id, False):
            await ctx.send(f"⏭️ Skipping to next song...")
            await self._play_current_song(ctx.guild.id)
        else:
            await ctx.send(f"⏭️ Next song queued. Use `!start` to play.")
    
    async def previous_song(self, ctx):
        """Go back to the previous song in the playlist"""
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
        
        # Move to previous song
        current_index = self.current_songs.get(ctx.guild.id, 0)
        previous_index = (current_index - 1) % len(MUSIC_PLAYLISTS)
        self.current_songs[ctx.guild.id] = previous_index
        
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
        
        current_index = self.current_songs.get(ctx.guild.id, 0)
        total_songs = len(MUSIC_PLAYLISTS)
        current_url = MUSIC_PLAYLISTS[current_index]
        
        # Try to get the actual song title
        try:
            with yt_dlp.YoutubeDL({'quiet': True, 'no_warnings': True}) as ytdl:
                info = ytdl.extract_info(current_url, download=False)
                title = info.get('title', 'Unknown Title') if info else 'Unknown Title'
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
            title="🎵 Current Song Info",
            color=discord.Color.blue()
        )
        embed.add_field(name="Title", value=title, inline=False)
        embed.add_field(name="Position", value=f"{current_index + 1} of {total_songs}", inline=True)
        embed.add_field(name="Status", value="▶️ Playing" if self.is_playing.get(ctx.guild.id, False) else "⏸️ Stopped", inline=True)
        embed.add_field(name="URL", value=f"[Link]({current_url})", inline=False)
        
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
            
        current_index = self.current_songs.get(guild_id, 0)
        max_retries = len(MUSIC_PLAYLISTS)  # Try all songs once
        retries = 0
        
        while retries < max_retries and self.is_playing.get(guild_id, False):
            try:
                url = MUSIC_PLAYLISTS[current_index]
                print(f"Attempting to play: {url}")
                
                player = await YTDLSource.from_url(url, loop=self.bot.loop, stream=True)
                
                def after_playing(error):
                    if error:
                        print(f'Player error: {error}')
                    else:
                        print("Song finished playing normally")
                    
                    # Auto-advance to next song if we're still supposed to be playing
                    if self.is_playing.get(guild_id, False):
                        # Move to next song
                        next_index = (current_index + 1) % len(MUSIC_PLAYLISTS)
                        self.current_songs[guild_id] = next_index
                        print(f"Auto-advancing to song {next_index + 1}")
                        
                        # Schedule next song to play
                        future = asyncio.run_coroutine_threadsafe(
                            self._play_current_song(guild_id), 
                            self.bot.loop
                        )
                        try:
                            future.result(timeout=10)  # Wait up to 10 seconds
                        except Exception as e:
                            print(f"Error scheduling next song: {e}")
                
                # Stop any currently playing audio
                if voice_client.is_playing():
                    voice_client.stop()
                
                voice_client.play(player, after=after_playing)
                print(f"Successfully started playing: {player.title}")
                return  # Success! Exit the retry loop
                
            except Exception as e:
                url = MUSIC_PLAYLISTS[current_index] if current_index < len(MUSIC_PLAYLISTS) else "unknown"
                print(f"Error playing music from {url}: {e}")
                retries += 1
                
                # Skip to next song and try again
                current_index = (current_index + 1) % len(MUSIC_PLAYLISTS)
                self.current_songs[guild_id] = current_index
                
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
        
        # Test if the URL is valid by trying to extract info
        try:
            with yt_dlp.YoutubeDL({'quiet': True}) as ytdl:
                info = ytdl.extract_info(url, download=False)
                title = info.get('title', 'Unknown Title') if info else 'Unknown Title'
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
            
            # Try to get the actual song title
            try:
                with yt_dlp.YoutubeDL({'quiet': True, 'no_warnings': True}) as ytdl:
                    info = ytdl.extract_info(url, download=False)
                    title = info.get('title', 'Unknown Title') if info else f"Song {i + 1}"
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

# Initialize music bot
music_bot = None

# Venice AI Configuration
VENICE_API_URL = "https://api.venice.ai/api/v1/chat/completions"
VENICE_MODEL = "venice-uncensored"

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

@bot.command()
async def help(ctx):
    embed = discord.Embed(
        title="🐶 Dog Bot Commands", 
        description="Here are all available commands:",
        color=discord.Color.blue()
    )
    embed.add_field(name="🐕 Basic", value="`!hello` - Greet the bot\n`!help` - Show this help\n\n🤖 **AI Commands:**\n`!ask <question>` - Ask AI anything\n`!chat <message>` - Chat with AI (with memory)\n`!history` - View your recent chat history\n`!clearhistory` - Clear your chat history\n`!undo` - Undo last action\n`!redo` - Redo last undone action", inline=False)
    embed.add_field(name="🎵 Music Bot", value="`!join` - Join voice channel and auto-start music\n`!leave` - Leave voice channel\n`!start` - Start/resume music\n`!stop` - Stop music\n`!next` - Skip to next song\n`!previous` - Go to previous song\n`!play <youtube_link>` - Play specific song immediately\n`!playlist` - Show current playlist\n`!add <youtube_url>` - Add song to playlist\n`!remove <youtube_url>` - Remove song from playlist\n`!nowplaying` - Show current song info\n`!musicstatus` - Show music bot debug status", inline=False)
    
    embed.add_field(name="🎭 Roles", value="`!catsrole` - Get Cats role\n`!dogsrole` - Get Dogs role\n`!lizardsrole` - Get Lizards role\n`!pvprole` - Get PVP role\n`!dndrole` - Get DND role\n`!dnd1role` - Get DND1 role\n`!dnd2role` - Get DND2 role\n`!dnd3role` - Get DND3 role\n`!remove<role>` - Remove any role (e.g., `!removecatsrole`)", inline=False)
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
              "`!assigndnd1role @user` - Assign DND1 role\n"
              "`!assigndnd2role @user` - Assign DND2 role\n"
              "`!assigndnd3role @user` - Assign DND3 role\n"
              "`!assignpvprole @user` - Assign PVP role", 
        inline=False
    )
    
    embed.add_field(
        name="🚫 Role Removal", 
        value="`!removedogsrolefrom @user` - Remove Dogs role\n"
              "`!removecatsrolefrom @user` - Remove Cats role\n"
              "`!removelizardsrolefrom @user` - Remove Lizards role\n"
              "`!removedndrolefrom @user` - Remove DND role\n"
              "`!removednd1rolefrom @user` - Remove DND1 role\n"
              "`!removednd2rolefrom @user` - Remove DND2 role\n"
              "`!removednd3rolefrom @user` - Remove DND3 role\n"
              "`!removepvprolefrom @user` - Remove PVP role", 
        inline=False
    )
    
    embed.add_field(
        name="🔧 YouTube Authentication", 
        value="`!enablecookies [browser]` - Enable YouTube cookies\n"
              "`!disablecookies` - Disable YouTube cookies\n"
              "`!ytdlstatus` - Show yt-dlp configuration", 
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
async def dnd1role(ctx):
    role = discord.utils.get(ctx.guild.roles, name=dnd1_role_name)
    if role:
        await ctx.author.add_roles(role)
        await ctx.send(f"🎲 Assigned {role.name} role to {ctx.author.name}!")
    else:
        await ctx.send("DND1 role not found. Please ensure the role exists in this server.")

@bot.command()
async def dnd2role(ctx):
    role = discord.utils.get(ctx.guild.roles, name=dnd2_role_name)
    if role:
        await ctx.author.add_roles(role)
        await ctx.send(f"🎲 Assigned {role.name} role to {ctx.author.name}!")
    else:
        await ctx.send("DND2 role not found. Please ensure the role exists in this server.")

@bot.command()
async def dnd3role(ctx):
    role = discord.utils.get(ctx.guild.roles, name=dnd3_role_name)
    if role:
        await ctx.author.add_roles(role)
        await ctx.send(f"🎲 Assigned {role.name} role to {ctx.author.name}!")
    else:
        await ctx.send("DND3 role not found. Please ensure the role exists in this server.")

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
async def removednd1role(ctx):
    role = discord.utils.get(ctx.guild.roles, name=dnd1_role_name)
    if role:
        if role in ctx.author.roles:
            await ctx.author.remove_roles(role)
            await ctx.send(f"🎲 Removed {role.name} role from {ctx.author.name}!")
        else:
            await ctx.send(f"You don't have the {role.name} role to remove.")
    else:
        await ctx.send("DND1 role not found. Please ensure the role exists in this server.")

@bot.command()
async def removednd2role(ctx):
    role = discord.utils.get(ctx.guild.roles, name=dnd2_role_name)
    if role:
        if role in ctx.author.roles:
            await ctx.author.remove_roles(role)
            await ctx.send(f"🎲 Removed {role.name} role from {ctx.author.name}!")
        else:
            await ctx.send(f"You don't have the {role.name} role to remove.")
    else:
        await ctx.send("DND2 role not found. Please ensure the role exists in this server.")

@bot.command()
async def removednd3role(ctx):
    role = discord.utils.get(ctx.guild.roles, name=dnd3_role_name)
    if role:
        if role in ctx.author.roles:
            await ctx.author.remove_roles(role)
            await ctx.send(f"🎲 Removed {role.name} role from {ctx.author.name}!")
        else:
            await ctx.send(f"You don't have the {role.name} role to remove.")
    else:
        await ctx.send("DND3 role not found. Please ensure the role exists in this server.")

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
async def assigndnd1role(ctx, member: Optional[discord.Member] = None):
    """Admin/Moderator command to assign DND1 role to a user"""
    if not has_admin_or_moderator_role(ctx):
        await ctx.send("❌ You need Admin or Moderator role to use this command.")
        return
    
    if member is None:
        await ctx.send("❌ Please mention a user to assign the role to. Usage: `!assigndnd1role @username`")
        return
    
    role = discord.utils.get(ctx.guild.roles, name=dnd1_role_name)
    if role:
        if role not in member.roles:
            await member.add_roles(role)
            await ctx.send(f"🎲 Assigned {role.name} role to {member.mention}!")
        else:
            await ctx.send(f"{member.mention} already has the {role.name} role.")
    else:
        await ctx.send("DND1 role not found. Please ensure the role exists in this server.")

@bot.command()
async def assigndnd2role(ctx, member: Optional[discord.Member] = None):
    """Admin/Moderator command to assign DND2 role to a user"""
    if not has_admin_or_moderator_role(ctx):
        await ctx.send("❌ You need Admin or Moderator role to use this command.")
        return
    
    if member is None:
        await ctx.send("❌ Please mention a user to assign the role to. Usage: `!assigndnd2role @username`")
        return
    
    role = discord.utils.get(ctx.guild.roles, name=dnd2_role_name)
    if role:
        if role not in member.roles:
            await member.add_roles(role)
            await ctx.send(f"🎲 Assigned {role.name} role to {member.mention}!")
        else:
            await ctx.send(f"{member.mention} already has the {role.name} role.")
    else:
        await ctx.send("DND2 role not found. Please ensure the role exists in this server.")

@bot.command()
async def assigndnd3role(ctx, member: Optional[discord.Member] = None):
    """Admin/Moderator command to assign DND3 role to a user"""
    if not has_admin_or_moderator_role(ctx):
        await ctx.send("❌ You need Admin or Moderator role to use this command.")
        return
    
    if member is None:
        await ctx.send("❌ Please mention a user to assign the role to. Usage: `!assigndnd3role @username`")
        return
    
    role = discord.utils.get(ctx.guild.roles, name=dnd3_role_name)
    if role:
        if role not in member.roles:
            await member.add_roles(role)
            await ctx.send(f"🎲 Assigned {role.name} role to {member.mention}!")
        else:
            await ctx.send(f"{member.mention} already has the {role.name} role.")
    else:
        await ctx.send("DND3 role not found. Please ensure the role exists in this server.")

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
async def removednd1rolefrom(ctx, member: Optional[discord.Member] = None):
    """Admin/Moderator command to remove DND1 role from a user"""
    if not has_admin_or_moderator_role(ctx):
        await ctx.send("❌ You need Admin or Moderator role to use this command.")
        return
    
    if member is None:
        await ctx.send("❌ Please mention a user to remove the role from. Usage: `!removednd1rolefrom @username`")
        return
    
    role = discord.utils.get(ctx.guild.roles, name=dnd1_role_name)
    if role:
        if role in member.roles:
            await member.remove_roles(role)
            await ctx.send(f"🎲 Removed {role.name} role from {member.mention}!")
        else:
            await ctx.send(f"{member.mention} doesn't have the {role.name} role to remove.")
    else:
        await ctx.send("DND1 role not found. Please ensure the role exists in this server.")

@bot.command()
async def removednd2rolefrom(ctx, member: Optional[discord.Member] = None):
    """Admin/Moderator command to remove DND2 role from a user"""
    if not has_admin_or_moderator_role(ctx):
        await ctx.send("❌ You need Admin or Moderator role to use this command.")
        return
    
    if member is None:
        await ctx.send("❌ Please mention a user to remove the role from. Usage: `!removednd2rolefrom @username`")
        return
    
    role = discord.utils.get(ctx.guild.roles, name=dnd2_role_name)
    if role:
        if role in member.roles:
            await member.remove_roles(role)
            await ctx.send(f"🎲 Removed {role.name} role from {member.mention}!")
        else:
            await ctx.send(f"{member.mention} doesn't have the {role.name} role to remove.")
    else:
        await ctx.send("DND2 role not found. Please ensure the role exists in this server.")

@bot.command()
async def removednd3rolefrom(ctx, member: Optional[discord.Member] = None):
    """Admin/Moderator command to remove DND3 role from a user"""
    if not has_admin_or_moderator_role(ctx):
        await ctx.send("❌ You need Admin or Moderator role to use this command.")
        return
    
    if member is None:
        await ctx.send("❌ Please mention a user to remove the role from. Usage: `!removednd3rolefrom @username`")
        return
    
    role = discord.utils.get(ctx.guild.roles, name=dnd3_role_name)
    if role:
        if role in member.roles:
            await member.remove_roles(role)
            await ctx.send(f"🎲 Removed {role.name} role from {member.mention}!")
        else:
            await ctx.send(f"{member.mention} doesn't have the {role.name} role to remove.")
    else:
        await ctx.send("DND3 role not found. Please ensure the role exists in this server.")

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
async def enablecookies(ctx, browser: str = 'chrome'):
    """Enable YouTube cookies from browser (Admin/Mod only)"""
    if not has_admin_or_moderator_role(ctx):
        await ctx.send("❌ You need Admin or Moderator role to use this command.")
        return
    
    valid_browsers = ['chrome', 'firefox', 'safari', 'edge']
    if browser.lower() not in valid_browsers:
        await ctx.send(f"❌ Invalid browser. Choose from: {', '.join(valid_browsers)}")
        return
    
    try:
        enable_youtube_cookies(browser.lower())
        await ctx.send(f"✅ YouTube cookies enabled from {browser} browser. This may help with authentication issues.")
    except Exception as e:
        await ctx.send(f"❌ Failed to enable cookies: {e}")

@bot.command()
async def disablecookies(ctx):
    """Disable YouTube cookies (Admin/Mod only)"""
    if not has_admin_or_moderator_role(ctx):
        await ctx.send("❌ You need Admin or Moderator role to use this command.")
        return
    
    try:
        disable_youtube_cookies()
        await ctx.send("✅ YouTube cookies disabled.")
    except Exception as e:
        await ctx.send(f"❌ Failed to disable cookies: {e}")

@bot.command()
async def ytdlstatus(ctx):
    """Show yt-dlp configuration status"""
    if not has_admin_or_moderator_role(ctx):
        await ctx.send("❌ You need Admin or Moderator role to use this command.")
        return
    
    embed = discord.Embed(
        title="🔧 yt-dlp Configuration Status",
        color=discord.Color.orange()
    )
    
    # Check cookie status
    cookies_enabled = 'cookiesfrombrowser' in YTDL_OPTIONS
    embed.add_field(
        name="Browser Cookies",
        value=f"✅ Enabled ({YTDL_OPTIONS.get('cookiesfrombrowser', ['none'])[0]})" if cookies_enabled else "❌ Disabled",
        inline=True
    )
    
    # Show player clients
    player_clients = YTDL_OPTIONS.get('extractor_args', {}).get('youtube', {}).get('player_client', ['default'])
    embed.add_field(
        name="Player Clients",
        value=", ".join(player_clients),
        inline=True
    )
    
    # Rate limiting
    sleep_interval = YTDL_OPTIONS.get('sleep_interval', 0)
    embed.add_field(
        name="Rate Limiting",
        value=f"{sleep_interval}s between requests" if sleep_interval > 0 else "Disabled",
        inline=True
    )
    
    embed.add_field(
        name="Recommendations",
        value="• Use `!enablecookies chrome` if videos fail to play\n• Cookies help with age-restricted and some premium content\n• Disable cookies with `!disablecookies` if having issues",
        inline=False
    )
    
    await ctx.send(embed=embed)

# Optional: Functions to manage YouTube cookie authentication
def enable_youtube_cookies(browser='chrome'):
    """
    Enable browser cookie support for YouTube authentication.
    Browsers: 'chrome', 'firefox', 'safari', 'edge'
    """
    global YTDL_OPTIONS
    YTDL_OPTIONS['cookiesfrombrowser'] = (browser,)
    print(f"YouTube cookies enabled from {browser} browser")

def disable_youtube_cookies():
    """Disable browser cookie support"""
    global YTDL_OPTIONS
    if 'cookiesfrombrowser' in YTDL_OPTIONS:
        del YTDL_OPTIONS['cookiesfrombrowser']
        print("YouTube cookies disabled")

# HTTP Server for Render.com
async def health_check(request):
    """Health check endpoint for Render.com"""
    return web.Response(text="🐶 Dogbot is running! Woof woof!")

async def create_app():
    """Create the web application for health checks"""
    app = web.Application()
    app.router.add_get('/', health_check)
    app.router.add_get('/health', health_check)
    return app

async def start_web_server():
    """Start the HTTP server for Render.com"""
    app = await create_app()
    port = int(os.getenv('PORT', 4000))
    
    runner = web.AppRunner(app)
    await runner.setup()
    
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    
    print(f"🌐 Web server running on port {port}")
    return runner

# Main startup function
async def main():
    """Main function to start both the bot and web server"""
    web_runner = None
    try:
        # Start the web server for Render.com
        web_runner = await start_web_server()
        
        # Start the Discord bot
        print("🐕 Starting Dogbot...")
        if token is None:
            raise ValueError("DISCORD_TOKEN environment variable not set")
        await bot.start(token)
        
    except KeyboardInterrupt:
        print("🛑 Bot stopped by user")
    except Exception as e:
        print(f"❌ Error starting bot: {e}")
    finally:
        if web_runner is not None:
            await web_runner.cleanup()

if __name__ == "__main__":
    # Run the main function
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("🛑 Bot shutdown complete")
