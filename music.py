import discord
from discord.ext import commands
import asyncio
import random
import yt_dlp
from playlist import MUSIC_PLAYLISTS

class YouTubeAudioSource(discord.PCMVolumeTransformer):
    """Simplified audio source for cloud deployment"""
    
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title', 'Unknown Title')
        self.url = data.get('url')

    @classmethod
    async def from_url(cls, url, *, loop=None):
        """Create audio source with minimal options for cloud reliability"""
        loop = loop or asyncio.get_event_loop()
        
        # Minimal yt-dlp options for cloud deployment
        ytdl_options = {
            'format': 'bestaudio',
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'cookiefile': 'cookies.txt' if 'cookies.txt' else None,
        }

        ytdl = yt_dlp.YoutubeDL(ytdl_options)

        try:
            data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=False))
            
            if not data:
                raise ValueError("No data extracted")
                
            if 'entries' in data:
                data = data['entries'][0]

            if not data.get('url'):
                raise ValueError("No playable URL found")

            # Minimal FFmpeg options for cloud deployment
            source = discord.FFmpegPCMAudio(
                data['url'],
                before_options='-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
                options='-vn'
            )
            
            return cls(source, data=data)
            
        except Exception as e:
            print(f"Audio source error: {e}")
            raise ValueError(f"Failed to create audio source: {str(e)[:100]}")

class MusicBot:
    """Simplified music bot for cloud deployment"""
    
    def __init__(self, bot):
        self.bot = bot
        # Minimal state management
        self.guild_states = {}  # guild_id -> {'current_playlist': [], 'current_index': 0}

    def _get_guild_state(self, guild_id):
        """Get or create guild state"""
        if guild_id not in self.guild_states:
            self.guild_states[guild_id] = {
                'current_playlist': [],
                'current_index': 0
            }
        return self.guild_states[guild_id]

    def _cleanup_guild_state(self, guild_id):
        """Clean up guild state"""
        if guild_id in self.guild_states:
            del self.guild_states[guild_id]

    async def join_voice_channel(self, ctx):
        """Simplified voice channel joining with retry"""
        try:
            # Check if user is in voice channel
            if not ctx.author.voice or not ctx.author.voice.channel:
                await ctx.send("❌ You need to be in a voice channel first!")
                return False

            channel = ctx.author.voice.channel
            
            # If already connected, move to new channel if different
            if ctx.voice_client:
                if ctx.voice_client.channel != channel:
                    await ctx.voice_client.move_to(channel)
                    await ctx.send(f"🔄 Moved to **{channel.name}**")
                else:
                    await ctx.send(f"✅ Already connected to **{channel.name}**")
                return True
            
            # Try to connect to voice channel (with retry)
            for attempt in range(3):
                try:
                    voice_client = await channel.connect()
                    
                    # Small delay to ensure connection is established
                    await asyncio.sleep(1)
                    
                    # Verify connection
                    if voice_client and voice_client.is_connected():
                        await ctx.send(f"✅ Joined 🎵 | **{channel.name}**")
                        return True
                    else:
                        if attempt < 2:  # Don't disconnect on last attempt
                            if voice_client:
                                await voice_client.disconnect()
                            await asyncio.sleep(1)
                        
                except Exception as e:
                    if attempt < 2:  # Only retry if not last attempt
                        print(f"[MUSIC] Connection attempt {attempt + 1} failed: {e}")
                        await asyncio.sleep(1)
                        continue
                    else:
                        raise e
            
            await ctx.send("❌ Failed to establish stable voice connection after 3 attempts!")
            return False
            
        except Exception as e:
            await ctx.send(f"❌ Failed to join voice channel: {str(e)[:100]}")
            return False

    async def leave_voice_channel(self, ctx):
        """Leave voice channel and cleanup"""
        try:
            if ctx.voice_client:
                await ctx.voice_client.disconnect()
                self._cleanup_guild_state(ctx.guild.id)
                await ctx.send("👋 Left the voice channel!")
            else:
                await ctx.send("❌ I'm not connected to a voice channel!")
        except Exception as e:
            await ctx.send(f"❌ Error leaving voice channel: {str(e)[:100]}")

    async def play_music(self, ctx, playlist_name="main"):
        """Simplified music playback"""
        try:
            # Join voice channel if not connected
            if not ctx.voice_client:
                if not await self.join_voice_channel(ctx):
                    return
            
            # Double-check voice connection is still valid
            if not ctx.voice_client or not ctx.voice_client.is_connected():
                await ctx.send("❌ Voice connection failed!")
                return

            # Get the main playlist from MUSIC_PLAYLISTS
            if not MUSIC_PLAYLISTS:
                await ctx.send(f"❌ No songs in playlist!")
                return

            # Use the MUSIC_PLAYLISTS list directly
            playlist = MUSIC_PLAYLISTS.copy()
            
            # Set up guild state
            state = self._get_guild_state(ctx.guild.id)
            state['current_playlist'] = playlist
            state['current_index'] = 0
            
            # Shuffle playlist
            random.shuffle(state['current_playlist'])
            
            await ctx.send(f"🎵 Starting music playlist ({len(playlist)} songs)")
            
            # Start playing
            await self._play_current_song(ctx)
            
        except Exception as e:
            await ctx.send(f"❌ Error starting playlist: {str(e)[:100]}")
            print(f"[MUSIC] Error in play_music: {e}")

    async def _play_current_song(self, ctx):
        """Play current song with auto-advance"""
        try:
            # Check voice client first
            if not ctx.voice_client:
                await ctx.send("❌ Not connected to voice channel!")
                return
                
            state = self._get_guild_state(ctx.guild.id)
            playlist = state['current_playlist']
            index = state['current_index']
            
            # Check if playlist finished
            if index >= len(playlist):
                await ctx.send("🏁 Playlist finished!")
                self._cleanup_guild_state(ctx.guild.id)
                return
            
            url = playlist[index]
            
            # Stop current playback if playing
            if ctx.voice_client.is_playing():
                ctx.voice_client.stop()
            
            # Create and play audio source
            player = await YouTubeAudioSource.from_url(url)
            
            def after_playing(error):
                if error:
                    print(f"Player error: {error}")
                # Schedule next song
                asyncio.create_task(self._advance_to_next_song(ctx))
            
            ctx.voice_client.play(player, after=after_playing)
            await ctx.send(f"🎵 Now playing: **{player.title}**")
            
        except Exception as e:
            await ctx.send(f"❌ Error playing song: {str(e)[:100]}")
            # Try next song on error
            await self._advance_to_next_song(ctx)

    async def _advance_to_next_song(self, ctx):
        """Advance to next song"""
        try:
            # Check if still connected to voice
            if not ctx.voice_client:
                print("Voice client disconnected, stopping music")
                return
                
            state = self._get_guild_state(ctx.guild.id)
            state['current_index'] += 1
            await self._play_current_song(ctx)
        except Exception as e:
            print(f"Error advancing to next song: {e}")

    async def skip_song(self, ctx):
        """Skip current song"""
        try:
            if not ctx.voice_client or not ctx.voice_client.is_playing():
                await ctx.send("❌ Nothing is playing!")
                return
            
            ctx.voice_client.stop()  # This will trigger the after callback
            await ctx.send("⏭️ Skipped song!")
            
        except Exception as e:
            await ctx.send(f"❌ Error skipping song: {str(e)[:100]}")

    async def pause_music(self, ctx):
        """Pause music"""
        try:
            if ctx.voice_client and ctx.voice_client.is_playing():
                ctx.voice_client.pause()
                await ctx.send("⏸️ Music paused!")
            else:
                await ctx.send("❌ Nothing is playing!")
        except Exception as e:
            await ctx.send(f"❌ Error pausing: {str(e)[:100]}")

    async def resume_music(self, ctx):
        """Resume music"""
        try:
            if ctx.voice_client and ctx.voice_client.is_paused():
                ctx.voice_client.resume()
                await ctx.send("▶️ Music resumed!")
            else:
                await ctx.send("❌ Music is not paused!")
        except Exception as e:
            await ctx.send(f"❌ Error resuming: {str(e)[:100]}")

    async def set_volume(self, ctx, volume):
        """Set volume"""
        try:
            if not ctx.voice_client or not ctx.voice_client.source:
                await ctx.send("❌ Nothing is playing!")
                return
            
            if not isinstance(ctx.voice_client.source, discord.PCMVolumeTransformer):
                await ctx.send("❌ Volume control not available for this audio source!")
                return
            
            volume = max(0, min(100, volume)) / 100
            ctx.voice_client.source.volume = volume
            await ctx.send(f"🔊 Volume set to {int(volume * 100)}%")
            
        except Exception as e:
            await ctx.send(f"❌ Error setting volume: {str(e)[:100]}")

    async def now_playing(self, ctx):
        """Show current song info"""
        try:
            if not ctx.voice_client or not ctx.voice_client.source:
                await ctx.send("❌ Nothing is playing!")
                return
            
            source = ctx.voice_client.source
            if hasattr(source, 'title'):
                title = source.title
            else:
                title = "Unknown"
            
            state = self._get_guild_state(ctx.guild.id)
            current_index = state['current_index']
            playlist_length = len(state['current_playlist'])
            
            status = "▶️ Playing" if ctx.voice_client.is_playing() else "⏸️ Paused"
            
            await ctx.send(
                f"{status}: **{title}**\n"
                f"Track {current_index + 1} of {playlist_length}"
            )
            
        except Exception as e:
            await ctx.send(f"❌ Error getting song info: {str(e)[:100]}")

    def get_available_playlists(self):
        """Get list of available playlists"""
        return ["main"]  # Simplified for cloud deployment
