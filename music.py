import discord
from discord.ext import commands
import asyncio
import os
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
    async def from_url(cls, url, *, loop=None, retry_count=0):
        """Create audio source with minimal options for cloud reliability"""
        loop = loop or asyncio.get_event_loop()
        
        # Enhanced yt-dlp options for cloud deployment with network resilience
        ytdl_options = {
            'format': 'bestaudio',
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'cookiefile': 'cookies.txt' if os.path.isfile('cookies.txt') else None,
            'socket_timeout': 30,
            'retries': 2,
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

            # Enhanced FFmpeg options for cloud deployment with network resilience
            # Added minimal reconnection options for network stability
            source = discord.FFmpegPCMAudio(
                data['url'],
                before_options='-nostdin -reconnect 1 -reconnect_streamed 1 -reconnect_at_eof 1 -reconnect_delay_max 2',
                options='-vn -nostats -hide_banner -loglevel error -ignore_io_errors 1'
            )
            
            return cls(source, data=data)
        
        except Exception as e:
            error_str = str(e).lower()
            # Retry once for network-related errors
            if retry_count == 0 and any(keyword in error_str for keyword in ["connection", "network", "timeout", "tls"]):
                print(f"[MUSIC] Network error, retrying: {e}")
                await asyncio.sleep(1)
                return await cls.from_url(url, loop=loop, retry_count=1)
            
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
                'current_index': 0,
                'connection_failures': 0,
                'last_failure_time': 0
            }
        return self.guild_states[guild_id]

    def _cleanup_guild_state(self, guild_id):
        """Clean up guild state"""
        if guild_id in self.guild_states:
            del self.guild_states[guild_id]

    async def join_voice_channel(self, ctx, announce=True):
        """Join the invoking user's voice channel"""
        # Check if already connected properly
        if ctx.voice_client and ctx.voice_client.is_connected():
            # Simple connection check - if it's connected, trust it
            return True
        
        # Determine channel to join: prefer user's voice channel, otherwise saved channel
        state = self._get_guild_state(ctx.guild.id)
        # Check if user is in a voice channel
        user_voice = getattr(ctx.author, 'voice', None)
        if user_voice and user_voice.channel:
            channel = user_voice.channel
        else:
            # Fallback to previously used voice channel
            channel_id = state.get('voice_channel_id')
            channel = ctx.guild.get_channel(channel_id) if channel_id else None
        if not channel:
            if announce:
                await ctx.send("❌ Join a voice channel first!")
            return False
        
        try:
            # Only disconnect if we need to connect to a different channel
            existing_vc = ctx.voice_client or ctx.guild.voice_client
            if existing_vc and existing_vc.channel != channel:
                try:
                    print(f"[MUSIC] Switching from {existing_vc.channel.name} to {channel.name}")
                    await existing_vc.disconnect()
                    await asyncio.sleep(0.5)
                except Exception as cleanup_e:
                    print(f"[MUSIC] Cleanup error (continuing): {cleanup_e}")
            
            # Connect if not already connected
            if not (ctx.voice_client and ctx.voice_client.is_connected()):
                print(f"[MUSIC] Connecting to {channel.name}")
                vc = await channel.connect()
                # Store voice channel in state for reconnect logic
                state['voice_channel_id'] = channel.id
                print(f"[MUSIC] Successfully connected to {channel.name}")
                if announce:
                    await ctx.send(f"✅ Connected to **{channel.name}**")
            return True
        except discord.ClientException as e:
            if "already connected" in str(e).lower():
                print(f"[MUSIC] Already connected, continuing...")
                return True
            else:
                print(f"[MUSIC] Connection failed: {e}")
                if announce:
                    await ctx.send(f"❌ Could not connect: {str(e)[:100]}")
                return False
        except Exception as e:
            print(f"[MUSIC] Connection error: {e}")
            if announce:
                await ctx.send(f"❌ Could not join voice channel: {str(e)[:100]}")
            return False

    async def leave_voice_channel(self, ctx):
        """Leave voice channel and cleanup"""
        try:
            if ctx.voice_client:
                # Stop any current playback
                if getattr(ctx.voice_client, 'is_playing', lambda: False)():
                    ctx.voice_client.stop()
                await ctx.voice_client.disconnect()
                self._cleanup_guild_state(ctx.guild.id)
                await ctx.send("👋 Left the voice channel!")
            else:
                await ctx.send("❌ I'm not connected to a voice channel!")
        except Exception as e:
            await ctx.send(f"❌ Error leaving voice channel: {str(e)[:100]}")

    async def play_music(self, ctx, playlist_name="main"):
        """Improved music playback with better voice connection handling"""
        try:
            # Ensure connected using join logic (supports previous channels)
            if not await self.join_voice_channel(ctx, announce=False):
                return
            voice_client = ctx.voice_client or ctx.guild.voice_client
            # Confirm connection
            if not voice_client or not voice_client.is_connected():
                await ctx.send("❌ Voice connection failed! Please ensure I can connect to a voice channel.")
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
            # Simple voice client check
            voice_client = ctx.voice_client or ctx.guild.voice_client
            
            if not voice_client or not voice_client.is_connected():
                print("[MUSIC] Voice client not connected, attempting to reconnect")
                # Try reconnection once with a delay
                await asyncio.sleep(1)
                reconnected = await self.join_voice_channel(ctx, announce=False)
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
                
                # Check if it's a network-related error that might resolve with retry
                if any(keyword in err_msg.lower() for keyword in ["connection", "network", "timeout", "tls", "io error"]):
                    print(f"[MUSIC] Network error detected, will retry this song later")
                    # Don't skip immediately, try next song and come back to this one
                    state = self._get_guild_state(ctx.guild.id)
                    current_url = state['current_playlist'][state['current_index']]
                    # Move failed song to end of playlist for retry
                    state['current_playlist'].append(current_url)
                
                # Suppressed per-song load failure notification to avoid spam
                await self._advance_to_next_song(ctx)
                return
            
            def after_playing(error):
                if error:
                    error_str = str(error).lower()
                    if any(keyword in error_str for keyword in ["connection reset", "tls", "io error", "network"]):
                        print(f"[MUSIC] Network error during playback: {error}")
                    else:
                        print(f"[MUSIC] Player error: {error}")
                else:
                    print(f"[MUSIC] Song finished normally")
                
                # Schedule next song only if state still exists (not after leave)
                if ctx.guild.id in self.guild_states:
                    try:
                        # Add a longer delay to prevent rapid transitions and connection stress
                        # Increase delay after network errors
                        delay = 3 if error and any(keyword in str(error).lower() for keyword in ["connection", "tls", "network"]) else 2
                        async def delayed_next():
                            await asyncio.sleep(delay)
                            await self._advance_to_next_song(ctx)
                        
                        self.bot.loop.create_task(delayed_next())
                    except Exception as sched_err:
                        print(f"[MUSIC] Error scheduling next song: {sched_err}")
    
            try:
                # Simple connection check before playing
                if not voice_client.is_connected():
                    print("[MUSIC] Voice client disconnected during playback attempt")
                    # Try to reconnect once
                    if not await self.join_voice_channel(ctx, announce=False):
                        raise Exception("Could not reconnect to voice channel")
                    voice_client = ctx.voice_client or ctx.guild.voice_client
                
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
                
                # Don't mark every playback issue as a connection failure
                error_str = str(e).lower()
                if any(keyword in error_str for keyword in ["not connected", "no channel", "connection"]):
                    import time
                    state = self._get_guild_state(ctx.guild.id)
                    state['connection_failures'] = state.get('connection_failures', 0) + 1
                    state['last_failure_time'] = time.time()
                    print(f"[MUSIC] Connection failure #{state['connection_failures']} detected")
                elif any(keyword in error_str for keyword in ["tls", "network", "io error", "reset by peer"]):
                    # Network errors are often temporary, don't count them as harshly
                    print(f"[MUSIC] Network error detected (not counting as connection failure): {e}")
                
                # Try to advance to next song with a longer delay
                await asyncio.sleep(3 if "network" in error_str or "tls" in error_str else 2)
                await self._advance_to_next_song(ctx)
            
        except Exception as e:
            print(f"[MUSIC] Error in _play_current_song: {e}")
            await ctx.send(f"❌ Error playing song: {str(e)[:100]}")
            # Try next song on error
            await self._advance_to_next_song(ctx)

    async def _advance_to_next_song(self, ctx):
        """Advance to next song with circuit breaker to prevent infinite loops"""
        import time
        
        try:
            state = self._get_guild_state(ctx.guild.id)
            
            # Circuit breaker: if we've had too many failures recently, stop
            current_time = time.time()
            if current_time - state.get('last_failure_time', 0) < 60:  # Within last minute
                failure_count = state.get('connection_failures', 0)
                if failure_count >= 5:
                    print(f"[MUSIC] Circuit breaker activated: {failure_count} failures in last minute, stopping")
                    await ctx.send("🚫 Music stopped due to repeated connection failures. Use `!start` to try again.")
                    self._cleanup_guild_state(ctx.guild.id)
                    return
            else:
                # Reset failure count if it's been more than a minute
                state['connection_failures'] = 0
            
            # Check if still connected to voice
            voice_client = ctx.voice_client or ctx.guild.voice_client
            if not voice_client or not voice_client.is_connected():
                print("[MUSIC] Voice client disconnected, attempting to reconnect before next song")
                reconnected = await self.join_voice_channel(ctx, announce=False)
                if not reconnected:
                    print("[MUSIC] Could not reconnect, incrementing failure count")
                    state['connection_failures'] = state.get('connection_failures', 0) + 1
                    state['last_failure_time'] = current_time
                    
                    # If we've failed too many times, wait longer before trying again
                    if state['connection_failures'] >= 5:
                        print("[MUSIC] Multiple connection failures, pausing for recovery")
                        await ctx.send("⚠️ Connection issues detected. Pausing briefly for recovery...")
                        await asyncio.sleep(10)
                        # Reset failure count after pause
                        state['connection_failures'] = 0
                    else:
                        # Wait longer before next attempt
                        await asyncio.sleep(3)
                        return
                
            # Reset failure count on successful connection
            state['connection_failures'] = 0
            state['current_index'] += 1
            await self._play_current_song(ctx)
            
        except Exception as e:
            print(f"[MUSIC] Error advancing to next song: {e}")
            state = self._get_guild_state(ctx.guild.id)
            state['connection_failures'] = state.get('connection_failures', 0) + 1
            state['last_failure_time'] = time.time()
            
            # Try to continue anyway, but with limits
            if state['connection_failures'] < 5:
                try:
                    state['current_index'] += 1
                    await asyncio.sleep(5)  # Longer delay before retry
                    await self._play_current_song(ctx)
                except Exception as retry_e:
                    print(f"[MUSIC] Retry also failed: {retry_e}")
                    state['connection_failures'] += 1
            else:
                print(f"[MUSIC] Too many failures, stopping")
                await ctx.send("❌ Music stopped due to repeated errors.")
                self._cleanup_guild_state(ctx.guild.id)

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
        # Save current playlist state to resume later
        prev_state = self.guild_states.get(ctx.guild.id)
        saved_state = None
        if prev_state:
            saved_state = {
                'current_playlist': list(prev_state['current_playlist']),
                'current_index': prev_state['current_index']
            }
        # Remove state so playlist callbacks are suppressed
        self.guild_states.pop(ctx.guild.id, None)
        # Stop any current playback
        if voice_client.is_playing():
            voice_client.stop()
        try:
            player = await YouTubeAudioSource.from_url(url)
        except Exception as e:
            # Restore previous playlist state on failure
            if saved_state is not None:
                self.guild_states[ctx.guild.id] = saved_state
            await ctx.send(f"❌ Failed to load URL: {e}")
            return
        def after(error):
            if error:
                print(f"[MUSIC] URL playback error: {error}")
            # Restore previous playlist state
            if saved_state is not None:
                restored_index = saved_state['current_index'] + 1
                playlist = saved_state['current_playlist']
                if restored_index >= len(playlist):
                    restored_index = 0
                    random.shuffle(playlist)
                self.guild_states[ctx.guild.id] = {
                    'current_playlist': playlist,
                    'current_index': restored_index
                }
            # Advance to next song from restored state
            try:
                print(f"[MUSIC] Resuming playlist after URL playback in guild {ctx.guild.id}")
                self.bot.loop.create_task(self._advance_to_next_song(ctx))
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
        """Temporarily disabled to prevent connection conflicts"""
        await self.bot.wait_until_ready()
        print("[MUSIC] Voice health check disabled to prevent conflicts with auto-rejoin")
        # Disabled to prevent conflicts with the new connection validation system
        return

    def get_available_playlists(self):
        """Get list of available playlists"""
        return ["main"]  # Simplified for cloud deployment
