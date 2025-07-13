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
            # Use robust reconnection options to handle transient network errors
            # Robust FFmpeg input with reconnection and read/write timeout
            source = discord.FFmpegPCMAudio(
                data['url'],
                before_options='-nostdin -reconnect 1 -reconnect_streamed 1 -reconnect_at_eof 1 -reconnect_delay_max 5 -rw_timeout 15000000',
                options='-vn -nostats -hide_banner -loglevel panic'
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
        """Join user's voice channel reliably"""
        # If already connected, no need to rejoin
        vc = ctx.voice_client or ctx.guild.voice_client
        if vc and vc.is_connected():
            return True
        # Determine target channel: prefer last known channel, then user's current channel
        state = self._get_guild_state(ctx.guild.id)
        channel = None
        if state.get('voice_channel_id'):
            channel = ctx.guild.get_channel(state['voice_channel_id'])
        elif ctx.author.voice and ctx.author.voice.channel:
            channel = ctx.author.voice.channel
        if not channel:
            await ctx.send("❌ No voice channel found to join.")
            return False
        try:
            vc = ctx.voice_client
            if not vc:
                # Connect to the user's channel
                vc = await channel.connect()
            elif vc.channel.id != channel.id:
                # Move if connected to a different channel
                await vc.move_to(channel)
            # Remember this channel for future reconnects
            state['voice_channel_id'] = channel.id
            # Mark music as active for this guild (enable auto reconnect)
            state['active'] = True
            await ctx.send(f"✅ Connected to **{channel.name}**")
            return True
        except Exception as e:
            print(f"[MUSIC] join_voice_channel error: {e}")
            await ctx.send(f"❌ Could not join your voice channel: {str(e)[:100]}")
            return False

    async def leave_voice_channel(self, ctx):
        """Leave voice channel and cleanup"""
        try:
            if ctx.voice_client:
                await ctx.voice_client.disconnect()
                # Disable music for this guild (prevent auto-reconnect)
                state = self._get_guild_state(ctx.guild.id)
                state['active'] = False
                # Clear playlist state
                state['current_playlist'] = []
                state['current_index'] = 0
                await ctx.send("👋 Left the voice channel!")
            else:
                await ctx.send("❌ I'm not connected to a voice channel!")
        except Exception as e:
            await ctx.send(f"❌ Error leaving voice channel: {str(e)[:100]}")

    async def play_music(self, ctx, playlist_name="main"):
        """Improved music playback with better voice connection handling"""
        try:
            # Multiple methods to check voice connection
            voice_client = ctx.voice_client or ctx.guild.voice_client
            
            # Join voice channel if not connected
            if not voice_client or not voice_client.is_connected():
                print("[MUSIC] No valid voice connection found, attempting to join...")
                if not await self.join_voice_channel(ctx):
                    return
                
                # Re-check voice client after joining with multiple methods
                voice_client = ctx.voice_client or ctx.guild.voice_client
            
            # Final comprehensive verification
            connection_valid = False
            if voice_client:
                try:
                    connection_valid = voice_client.is_connected()
                    print(f"[MUSIC] Voice client connection status: {connection_valid}")
                except Exception as e:
                    print(f"[MUSIC] Error checking voice client status: {e}")
                    connection_valid = False
            
            if not connection_valid:
                await ctx.send("❌ Voice connection failed! Use `!join` first, then try `!start`.")
                return

            print(f"[MUSIC] Voice client confirmed: {voice_client} (connected: {voice_client.is_connected()})")

            # Check playlist availability
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
            import traceback
            traceback.print_exc()

    async def _play_current_song(self, ctx):
        """Play current song with improved error handling"""
        try:
            # Enhanced voice client verification
            voice_client = ctx.voice_client or ctx.guild.voice_client
            if not voice_client or not voice_client.is_connected():
                # Try to reconnect if disconnected
                reconnected = await self.join_voice_channel(ctx)
                if not reconnected:
                    print("[MUSIC] Could not reconnect, stopping playback")
                    return
                voice_client = ctx.voice_client or ctx.guild.voice_client
            
            state = self._get_guild_state(ctx.guild.id)
            playlist = state['current_playlist']
            index = state['current_index']
            
            # Check if playlist finished
            if index >= len(playlist):
                # If playlist is empty, stop playback
                if not playlist:
                    self._cleanup_guild_state(ctx.guild.id)
                    return
                # Otherwise reshuffle and restart
                state['current_index'] = 0
                random.shuffle(state['current_playlist'])
                await ctx.send("🔁 Playlist finished, reshuffling and restarting!")
                await self._play_current_song(ctx)
                return
    
            url = playlist[index]
            # Skip empty or invalid URLs
            if not url or not url.strip().startswith(('http://', 'https://')):
                print(f"[MUSIC] Invalid URL at index {index}: '{url}', skipping.")
                await self._advance_to_next_song(ctx)
                return
            print(f"[MUSIC] Attempting to play song {index + 1}: {url}")
            
            # Stop current playback if playing
            if voice_client.is_playing():
                voice_client.stop()
                await asyncio.sleep(0.5)  # Brief pause to ensure clean stop
            
            # Create and play audio source
            try:
                player = await YouTubeAudioSource.from_url(url)
                print(f"[MUSIC] Audio source created: {player.title}")
            except Exception as e:
                print(f"[MUSIC] Failed to create audio source: {e}")
                err_msg = str(e)
                # Suppressed per-song load failure notification to avoid spam
                await self._advance_to_next_song(ctx)
                return
            
            def after_playing(error):
                if error:
                    print(f"[MUSIC] Player error: {error}")
                else:
                    print(f"[MUSIC] Song finished normally")
                # Schedule next song only if state still exists (not after leave)
                if ctx.guild.id in self.guild_states:
                    try:
                        self.bot.loop.create_task(self._advance_to_next_song(ctx))
                    except Exception as sched_err:
                        print(f"[MUSIC] Error scheduling next song: {sched_err}")
    
            try:
                voice_client.play(player, after=after_playing)
                # Send now playing message to appropriate text channel
                # Prefer a text channel matching the voice channel name
                voice_chan = ctx.voice_client.channel if ctx.voice_client else None
                target_chan = None
                if voice_chan:
                    for text_chan in ctx.guild.text_channels:
                        if text_chan.name == voice_chan.name:
                            target_chan = text_chan
                            break
                # Fallback to command channel
                if not target_chan:
                    target_chan = ctx.channel
                video_link = player.data.get('webpage_url') or player.url
                message_content = f"🎵 Now playing: [{player.title}]({video_link}) ({index + 1}/{len(playlist)})"
                await target_chan.send(message_content)
                print(f"[MUSIC] Successfully started playback: {player.title}")
            except Exception as e:
                print(f"[MUSIC] Failed to start playback: {e}")
                err_msg = str(e)
                # Suppressed per-song playback failure notification to avoid spam
                await self._advance_to_next_song(ctx)
            
        except Exception as e:
            print(f"[MUSIC] Error in _play_current_song: {e}")
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
            title = source.title if hasattr(source, 'title') else "Unknown"
            
            state = self._get_guild_state(ctx.guild.id)
            current_index = state['current_index']
            playlist_length = len(state['current_playlist'])
            
            status = "▶️ Playing" if ctx.voice_client.is_playing() else "⏸️ Paused"

            # Include clickable link and track progress
            video_link = getattr(source, 'data', {}).get('webpage_url') or getattr(source, 'url', None)
            message_content = f"{status}: [{title}]({video_link}) ({current_index + 1}/{playlist_length})"
            await ctx.send(message_content)
        except Exception as e:
            await ctx.send(f"❌ Error getting song info: {str(e)[:100]}")

    async def play_url(self, ctx, url):
        """Play a single URL, then resume the main playlist"""
        # Ensure voice connection
        voice_client = ctx.voice_client or ctx.guild.voice_client
        if not voice_client or not voice_client.is_connected():
            # Try to reconnect to previous channel without requiring user
            state = self._get_guild_state(ctx.guild.id)
            channel_id = state.get('voice_channel_id')
            if channel_id:
                channel = ctx.guild.get_channel(channel_id)
                if channel:
                    try:
                        voice_client = await channel.connect()
                    except Exception as e:
                        print(f"[MUSIC] play_url reconnect error: {e}")
            # Fallback to user-initiated join if still not connected
            if not voice_client or not voice_client.is_connected():
                if not await self.join_voice_channel(ctx):
                    return
                voice_client = ctx.voice_client or ctx.guild.voice_client
        # Temporarily remove playlist state to avoid triggering its after callback
        state_backup = self.guild_states.pop(ctx.guild.id, None)
        # Stop any current playback
        if voice_client.is_playing():
            voice_client.stop()
        try:
            player = await YouTubeAudioSource.from_url(url)
        except Exception as e:
            # Restore previous playlist state on failure
            if state_backup is not None:
                self.guild_states[ctx.guild.id] = state_backup
            await ctx.send(f"❌ Failed to load URL: {e}")
            return
        # After URL, resume main playlist
        def after(error):
            if error:
                print(f"[MUSIC] URL playback error: {error}")
            # Resume playlist
            try:
                self.bot.loop.create_task(self.play_music(ctx))
            except Exception as err:
                print(f"[MUSIC] Error resuming playlist: {err}")
        voice_client.play(player, after=after)
        # Send now playing message to appropriate text channel
        msg = f"🎵 Now playing URL: **{player.title}**"
        # Prefer a text channel matching the voice channel name
        voice_chan = ctx.voice_client.channel if ctx.voice_client else None
        target_chan = None
        if voice_chan:
            for text_chan in ctx.guild.text_channels:
                if text_chan.name == voice_chan.name:
                    target_chan = text_chan
                    break
        # Fallback to command channel
        if not target_chan:
            target_chan = ctx.channel
        await target_chan.send(msg)

    async def voice_health_check(self):
        """Periodically ensure the bot stays connected to its voice channel and send keep-alive silence."""
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            for guild_id, state in list(self.guild_states.items()):
                # Skip health check if music is not active for this guild
                if not state.get('active', False):
                    continue
                channel_id = state.get('voice_channel_id')
                guild = self.bot.get_guild(guild_id)
                if not guild or not channel_id:
                    continue
                vc = guild.voice_client
                # Reconnect if disconnected
                if not vc or not getattr(vc, 'is_connected', lambda: False)():
                    channel = guild.get_channel(channel_id)
                    if channel:
                        try:
                            await channel.connect()
                            print(f"[MUSIC] Reconnected to voice channel {channel.name} in guild {guild_id}")
                        except Exception as err:
                            print(f"[MUSIC] Health check reconnect failed for guild {guild_id}: {err}")
                else:
                    # Skip keep-alive silence to avoid interrupting playback
                    pass
            await asyncio.sleep(60)

    def get_available_playlists(self):
        """Get list of available playlists"""
        return ["main"]  # Simplified for cloud deployment
