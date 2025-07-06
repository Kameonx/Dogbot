import discord
from discord.ext import commands
import asyncio
import random
import yt_dlp
from playlist import MUSIC_PLAYLISTS

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
            # Prefer high-quality m4a/aac for better Bluetooth compatibility over opus/webm
            'format': 'bestaudio[ext=m4a][acodec=aac]/bestaudio[acodec=aac]/bestaudio[ext=mp4]/bestaudio[ext=webm]/bestaudio',
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
            'user_agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            # Larger chunks for better quality on stable connections
            'http_chunk_size': 1048576,  # 1MB chunks for better audio quality
            'socket_timeout': 60,  # Increased timeout for better network reliability
            'retries': 10,  # More retries for cloud reliability
            'fragment_retries': 10,  # More fragment retries
            'retry_sleep': 3,  # Sleep between retries
            'max_sleep_interval': 5,
            'sleep_interval_requests': 1,
            'sleep_interval_subtitles': 1,
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
            
            # Enhanced FFmpeg options for better Bluetooth audio quality
            # Optimized for AAC/M4A sources with better Bluetooth codec compatibility
            before_options = (
                '-reconnect 1 '
                '-rw_timeout 20000000 '
                '-loglevel fatal '
                '-fflags +discardcorrupt '  # Handle corrupted packets better
                '-analyzeduration 2147483647 '  # Better stream analysis
                '-probesize 2147483647 '  # Better stream probing
            )
            
            # Enhanced audio processing optimized for Render.com deployment
            # Removed -ac and -ar options to avoid conflicts with platform defaults
            # Let the environment handle sample rate and channels to avoid "Multiple options" warnings
            options = (
                '-vn '  # No video
                '-ab 320k '  # Force high bitrate (320kbps) for quality
                '-acodec pcm_s16le '  # High-quality PCM encoding for Discord
                '-f s16le '  # Force 16-bit signed little-endian format
                '-bufsize 512k '  # Audio buffer size for smooth playback
            )
            
            print(f"[RENDER] Using FFmpeg options: {options}")
            print(f"[RENDER] Using before_options: {before_options}")
            
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

    @classmethod
    async def from_url_fallback(cls, url, *, loop=None):
        """Fallback method with even more basic options for problematic videos"""
        loop = loop or asyncio.get_event_loop()
        
        basic_options = {
            'format': 'bestaudio',
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True
        }
        
        ytdl = yt_dlp.YoutubeDL(basic_options)
        
        def extract_simple():
            return ytdl.extract_info(url, download=False)
        
        try:
            data = await loop.run_in_executor(None, extract_simple)
            
            if data is None:
                raise ValueError("No data from fallback extraction")
            if 'entries' in data and data['entries']:
                data = data['entries'][0]
            
            if not data or 'url' not in data:
                raise ValueError("No playable URL in fallback data")
                
            # Enhanced fallback FFmpeg options - minimal for Render.com compatibility
            source = discord.FFmpegPCMAudio(
                data['url'],
                before_options=(
                    '-reconnect 1 '
                    '-rw_timeout 20000000 '
                    '-loglevel fatal'
                ),
                options='-vn'
            )
            return cls(source, data=data)
            
        except Exception as e:
            raise ValueError(f"All extraction methods failed: {str(e)}")

    @classmethod
    async def from_url_minimal(cls, url, *, loop=None):
        """Minimal extraction for maximum compatibility"""
        loop = loop or asyncio.get_event_loop()
        
        minimal_options = {
            'quiet': True,
            'no_warnings': True
        }
        
        ytdl = yt_dlp.YoutubeDL(minimal_options)
        
        def extract_minimal():
            return ytdl.extract_info(url, download=False)
        
        try:
            data = await loop.run_in_executor(None, extract_minimal)
            if data is None:
                raise ValueError("No data from minimal extraction")
            if 'entries' in data and data['entries']:
                data = data['entries'][0]
            if not data or 'url' not in data:
                raise ValueError("No playable URL in minimal data")
            # Minimal FFmpeg options for maximum compatibility with Render.com
            source = discord.FFmpegPCMAudio(
                data['url'],
                before_options=(
                    '-reconnect 1 '
                    '-rw_timeout 20000000 '
                    '-loglevel fatal'
                ),
                options='-vn'
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
        self.playing_specific_url = {}  # guild_id -> bool (prevents playlist interference)
    
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
            if guild_id not in self.playing_specific_url:
                self.playing_specific_url[guild_id] = False
            
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
        if guild_id in self.playing_specific_url:
            del self.playing_specific_url[guild_id]
        
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
        
        # Try to get the actual song title
        try:
            # Fallback to extracting from URL
            if 'youtube.com/watch?v=' in current_url:
                video_id = current_url.split('v=')[1].split('&')[0]
                title = f"YouTube Video ({video_id})"
            elif 'youtu.be/' in current_url:
                video_id = current_url.split('youtu.be/')[1].split('?')[0]
                title = f"YouTube Video ({video_id})"
            else:
                title = "Unknown Title"
        except:
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
        
        # Check if we're currently playing a specific URL - don't interfere
        if self.playing_specific_url.get(guild_id, False):
            print(f"[PLAY_CURRENT] ⏸️ Specific URL playing, skipping playlist playback for guild {guild_id}")
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
                    else:
                        # For other extraction errors, skip to next song
                        print(f"[EXTRACTION_ERROR] Skipping to next song due to extraction error: {source_error}")
                        current_pos = self.shuffle_positions.get(guild_id, 0)
                        self.shuffle_positions[guild_id] = (current_pos + 1) % len(self.shuffle_playlists.get(guild_id, MUSIC_PLAYLISTS))
                        # Continue immediately to next song
                        continue
                
                def after_playing(error):
                    import time
                    play_start_time = getattr(player, '_play_start_time', time.time())
                    play_duration = time.time() - play_start_time
                    
                    if error:
                        error_str = str(error).lower()
                        print(f'🎵 Player error after {play_duration:.1f}s: {error}')
                        
                        # Check for common network/stream errors that should trigger retry
                        if any(keyword in error_str for keyword in ['connection', 'network', 'timeout', 'reset', 'eof']):
                            print(f"[NETWORK_ERROR] Detected network issue, will retry with next song")
                        else:
                            print(f"[AUDIO_ERROR] Non-network audio error: {error}")
                    else:
                        if play_duration < 10:  # Song finished too quickly, likely an error
                            print(f"🎵 Song finished suspiciously quickly ({play_duration:.1f}s) for guild {guild_id} - possible stream failure")
                        else:
                            print(f"🎵 Song finished playing normally after {play_duration:.1f}s for guild {guild_id}")
                    
                    # Clean up player object to free memory on Render.com
                    try:
                        if hasattr(player, 'cleanup'):
                            player.cleanup()
                        elif hasattr(player, 'source') and hasattr(player.source, 'cleanup'):
                            player.source.cleanup()
                    except Exception as cleanup_error:
                        print(f"[MEMORY] Player cleanup error: {cleanup_error}")
                    
                    # Only auto-advance if we're supposed to be playing AND the song played for a reasonable duration
                    # This prevents rapid cycling due to immediate stream failures
                    should_advance = (self.is_playing.get(guild_id, False) and 
                                    not self.manual_skip_in_progress.get(guild_id, False))
                    
                    if should_advance:
                        if play_duration < 5 and error:  # Very short play time with error suggests stream failure
                            print(f"[STREAM_FAILURE] Song played for only {play_duration:.1f}s with error, will retry after delay")
                            retry_delay = 3.0  # Wait longer before retry
                        else:
                            print(f"[AUTO-ADVANCE] Moving to next song automatically")
                            retry_delay = 0.1  # Normal advance
                        
                        # Move to next position in shuffle (thread-safe)
                        current_shuffle_pos = self.shuffle_positions.get(guild_id, 0)
                        next_shuffle_pos = current_shuffle_pos + 1
                        
                        # Check if we need to regenerate shuffle (infinite loop)
                        if guild_id not in self.shuffle_playlists or next_shuffle_pos >= len(self.shuffle_playlists[guild_id]):
                            print(f"🔄 End of shuffle reached for guild {guild_id}, regenerating for infinite playback...")
                            self._generate_shuffle_playlist(guild_id)
                            next_shuffle_pos = 0
                        
                        self.shuffle_positions[guild_id] = next_shuffle_pos
                        print(f"⏭️ Auto-advancing to shuffle position {next_shuffle_pos + 1} for continuous playbook")
                        
                        # Schedule next song to play without blocking (ensures infinite loop)
                        async def play_next_song():
                            try:
                                await asyncio.sleep(retry_delay)  # Use adaptive delay
                                if self.is_playing.get(guild_id, False) and not self.manual_skip_in_progress.get(guild_id, False):
                                    await self._play_current_song(guild_id)
                                else:
                                    print(f"[AUTO-ADVANCE] Playback stopped or manual skip in progress for guild {guild_id}")
                            except Exception as e:
                                print(f"❌ Error playing next song: {e}")
                        
                        asyncio.run_coroutine_threadsafe(
                            play_next_song(), 
                            self.bot.loop
                        )
                
                # Enhanced play method with better error detection and handling
                try:
                    # Final connection stability check before playing
                    if not voice_client.is_connected():
                        print(f"[VOICE_ERROR] Voice client disconnected before playing for guild {guild_id}")
                        self.is_playing[guild_id] = False
                        return
                    
                    # Instant check before playing to avoid "already playing" errors
                    if voice_client.is_playing() or voice_client.is_paused():
                        print(f"[INSTANT_CHECK] Audio still playing before new play attempt, forcing stop...")
                        voice_client.stop()
                        # No delay - instant override
                    
                    voice_client.play(player, after=after_playing)
                    
                    # Track when playback actually starts for duration monitoring
                    import time
                    player._play_start_time = time.time()
                    
                    print(f"[CLOUD_MUSIC] Successfully started playing: {player.title}")
                    return  # Success! Exit the retry loop
                    
                except Exception as play_error:
                    error_str = str(play_error).lower()
                    last_error = play_error
                    print(f"[PLAY_ERROR] Error: {play_error}")
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
                # Skip to next song and try again
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
        
        # Add to playlist
        MUSIC_PLAYLISTS.append(url)
        
        embed = discord.Embed(
            title="🎵 Song Added to Playlist",
            color=discord.Color.green()
        )
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
        
        # Create audio source for specific URL
        try:
            player = await YouTubeAudioSource.from_url(url, loop=self.bot.loop, stream=True)
            # Send now playing with video title instead of URL
            await ctx.send(f"🎵 Now Playing: \"{player.title}\"")
        except Exception as e:
            await ctx.send(f"❌ Failed to load URL: {str(e)[:100]}...")
            return

        # Clean stop of any existing audio for smooth transition
        if voice_client.is_playing() or voice_client.is_paused():
            print(f"[SPECIFIC_URL] Stopping current audio for smooth transition...")
            voice_client.stop()
            # Wait until audio fully stops to prevent overlap
            while voice_client.is_playing() or voice_client.is_paused():
                await asyncio.sleep(0.1)
            print(f"[SPECIFIC_URL] Current audio fully stopped")
        else:
            print(f"[SPECIFIC_URL] No audio currently playing")

        # Disable playlist playback and set flag for specific URL
        self.is_playing[ctx.guild.id] = False
        self.playing_specific_url[ctx.guild.id] = True
        print(f"[SPECIFIC_URL] Set playing_specific_url flag for guild {ctx.guild.id}")

        # Capture guild_id and original playing state for callback
        guild_id = ctx.guild.id
        was_playing = was_playing_playlist

        # Define callback to resume playlist if it was playing
        def after_specific(error):
            # Clear the specific URL flag
            self.playing_specific_url[guild_id] = False
            print(f"[SPECIFIC_URL] Cleared playing_specific_url flag for guild {guild_id}")

            if error:
                print(f"[SPECIFIC_URL] Error playing specific URL: {error}")
            else:
                print(f"[SPECIFIC_URL] Specific URL finished playing")

            # Resume playlist if it was playing before
            if was_playing:
                print(f"[SPECIFIC_URL] Resuming playlist after specific URL")
                self.is_playing[guild_id] = True
                asyncio.run_coroutine_threadsafe(
                    self._play_current_song(guild_id),
                    self.bot.loop
                )

        # Play the specific track
        try:
            voice_client.play(player, after=after_specific)
            print(f"[SPECIFIC_URL] Started playing specific URL {url}")
        except Exception as play_error:
            # Clear flag on failure
            self.playing_specific_url[guild_id] = False
            print(f"[SPECIFIC_URL] Failed to start playback: {play_error}")
            await ctx.send(f"❌ Failed to start playback: {str(play_error)[:100]}...")
        return
    
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
        """Simple health check to clean up disconnected voice clients"""
        while True:
            try:
                await asyncio.sleep(300)  # Every 5 minutes - simple check
                for guild_id in list(self.voice_clients.keys()):
                    voice_client = self.voice_clients.get(guild_id)
                    if voice_client and not voice_client.is_connected():
                        print(f"[HEALTH_CHECK] Cleaning up disconnected voice client for guild {guild_id}")
                        del self.voice_clients[guild_id]
                        self.is_playing[guild_id] = False
            except Exception as e:
                print(f"[HEALTH_CHECK] Error in health check: {e}")
                await asyncio.sleep(60)
