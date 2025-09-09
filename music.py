import discord
from discord.ext import commands
import asyncio
import os
import random
import yt_dlp
from playlist import MUSIC_PLAYLISTS

class YouTubeAudioSource(discord.PCMVolumeTransformer):
    """Simplified audio source for cloud deployment"""
    
    def __init__(self, source, *, data, volume=0.35):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title', 'Unknown Title')
        self.url = data.get('url')

    @classmethod
    async def from_url(cls, url, *, loop=None, retry_count=0):
        """Create audio source with minimal options for cloud reliability"""
        loop = loop or asyncio.get_event_loop()

        # yt-dlp extraction options
        format_selector = 'bestaudio/best' if retry_count < 2 else 'best'
        ytdl_options = {
            'format': format_selector,
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'cookiefile': 'cookies.txt' if os.path.isfile('cookies.txt') else None,
            'socket_timeout': 30,
            'retries': 3,
            'force_ipv4': True,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'
            },
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

            # FFmpeg options tuned to reduce initial distortion and improve stability
            before_opts = (
                ' -nostdin'
                ' -reconnect 1'
                ' -reconnect_streamed 1'
                ' -reconnect_at_eof 1'
                ' -reconnect_delay_max 5'
                ' -reconnect_on_http_error 403,404,429,500,502,503,504'
                ' -rw_timeout 60000000'
                ' -probesize 256k'
                ' -analyzeduration 0'
            )
            audio_opts = (
                ' -vn -sn -dn'
                ' -nostats -hide_banner -loglevel warning'
                ' -ac 2 -ar 48000'
                ' -af aresample=async=1:min_hard_comp=0.100:first_pts=0'
            )
            source = discord.FFmpegPCMAudio(
                data['url'],
                before_options=before_opts,
                options=audio_opts,
            )
            return cls(source, data=data)

        except Exception as e:
            error_str = str(e).lower()
            # Retry once for network-related errors
            if retry_count < 1 and any(k in error_str for k in ("connection", "network", "timeout", "tls")):
                print(f"[MUSIC] Network error, retrying: {e}")
                await asyncio.sleep(1)
                return await cls.from_url(url, loop=loop, retry_count=retry_count + 1)
            # Fallback if requested format isn't available
            if retry_count < 2 and any(k in error_str for k in ("requested format is not available", "format is not available", "no video formats", "no such format")):
                print(f"[MUSIC] Format unavailable, falling back to more permissive format: {e}")
                await asyncio.sleep(0.5)
                return await cls.from_url(url, loop=loop, retry_count=retry_count + 1)
            print(f"Audio source error: {e}")
            raise ValueError(f"Failed to create audio source: {str(e)[:100]}")

class MusicBot:
    """Simplified music bot for cloud deployment"""
    
    def __init__(self, bot):
        self.bot = bot
        # Minimal state management
        self.guild_states = {}  # guild_id -> {'current_playlist': [], 'current_index': 0}
        # Per-guild connection locks to prevent concurrent connects/loops
        self._connect_locks = {}

    def _get_connect_lock(self, guild_id):
        lock = self._connect_locks.get(guild_id)
        if lock is None:
            lock = asyncio.Lock()
            self._connect_locks[guild_id] = lock
        return lock

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
        """Join the invoking user's voice channel (debounced and locked)."""
        return await self._ensure_voice(ctx, announce=announce)

    async def _ensure_voice(self, ctx, *, announce=False, max_retries=5):
        """Ensure we have a stable voice connection for the guild.
        Returns True on success, False otherwise.
        """
        guild = ctx.guild
        state = self._get_guild_state(guild.id)
        lock = self._get_connect_lock(guild.id)

        # Track consecutive fake connections
        if 'fake_connect_count' not in state:
            state['fake_connect_count'] = 0

        # Determine target channel: user voice > saved voice
        user_voice = getattr(ctx.author, 'voice', None)
        preferred_channel = user_voice.channel if user_voice and user_voice.channel else None
        if not preferred_channel and state.get('voice_channel_id'):
            preferred_channel = guild.get_channel(state['voice_channel_id'])
        if preferred_channel is None:
            if announce:
                await ctx.send("❌ Join a voice channel first!")
            return False

        async with lock:
            for attempt in range(1, max_retries + 1):
                try:
                    vc = guild.voice_client
                    if vc and vc.is_connected():
                        # Already connected; if to a different channel, move
                        if vc.channel != preferred_channel:
                            print(f"[MUSIC] Moving from {vc.channel.name} to {preferred_channel.name}")
                            try:
                                await vc.move_to(preferred_channel)
                                # give Discord a moment to stabilize the voice state
                                await asyncio.sleep(0.8)
                                # re-check that we're still connected and in the expected channel
                                if not vc.is_connected() or vc.channel != preferred_channel:
                                    print(f"[MUSIC] Move did not stabilize, continuing attempts")
                                    # allow outer loop to retry the connection
                                    continue
                                state['voice_channel_id'] = preferred_channel.id
                            except Exception as move_exc:
                                print(f"[MUSIC] Error moving voice client: {move_exc}")
                                # let the outer loop handle retry/backoff
                                continue
                        # Check for fake connections (connected but never playing)
                        # Only count once playback had started recently
                        if not vc.is_playing() and not vc.is_paused() and state.get('play_started_recently'):
                            state['fake_connect_count'] += 1
                            print(f"[MUSIC] Fake connect count: {state['fake_connect_count']}")
                            if state['fake_connect_count'] >= 5:
                                print("[MUSIC] HARD CIRCUIT BREAKER: Too many fake connections, forcing disconnect and internal reconnect.")
                                try:
                                    await vc.disconnect(force=True)
                                except Exception:
                                    pass
                                state['fake_connect_count'] = 0
                                await asyncio.sleep(1)
                                # Continue loop to try fresh connect
                                continue
                        else:
                            state['fake_connect_count'] = 0
                        return True

                    # Connect fresh
                    # prevent super-rapid retries by enforcing a small gap between connect attempts
                    last_try = state.get('last_connect_time', 0)
                    now = asyncio.get_event_loop().time()
                    if now - last_try < 0.5:
                        await asyncio.sleep(0.5)
                    state['last_connect_time'] = now

                    print(f"[MUSIC] Connecting to {preferred_channel.name} (attempt {attempt})")
                    try:
                        vc = await preferred_channel.connect()
                    except Exception as conn_exc:
                        print(f"[MUSIC] Connect raised exception: {conn_exc}")
                        await asyncio.sleep(0.6 * attempt)
                        continue

                    # Give Discord a short moment to finalize the voice state
                    await asyncio.sleep(0.9 + 0.25 * attempt)

                    # Verify the connection stabilized
                    if not vc or not vc.is_connected() or (vc.channel != preferred_channel):
                        print(f"[MUSIC] Connection did not stabilize on attempt {attempt}, retrying")
                        # Try to disconnect any partial connection to avoid zombie state
                        try:
                            if vc and getattr(vc, 'is_connected', lambda: False)():
                                await vc.disconnect(force=True)
                        except Exception:
                            pass
                        await asyncio.sleep(0.6 * attempt)
                        continue

                    state['voice_channel_id'] = preferred_channel.id
                    state['fake_connect_count'] = 0
                    # Silent success
                    print(f"[MUSIC] Successfully connected to {preferred_channel.name}")
                    return True
                except discord.ClientException as e:
                    msg = str(e).lower()
                    if 'already connected' in msg:
                        print("[MUSIC] Already connected, continuing...")
                        if state.get('play_started_recently'):
                            state['fake_connect_count'] = state.get('fake_connect_count', 0) + 1
                            print(f"[MUSIC] Fake connect count: {state['fake_connect_count']}")
                        if state.get('fake_connect_count', 0) >= 5:
                            print("[MUSIC] HARD CIRCUIT BREAKER: Too many fake connections, forcing disconnect and internal reconnect.")
                            try:
                                if guild.voice_client:
                                    await guild.voice_client.disconnect(force=True)
                            except Exception:
                                pass
                            state['fake_connect_count'] = 0
                            await asyncio.sleep(1)
                            continue
                        await asyncio.sleep(1.5 * attempt)
                        continue
                    # Other client exceptions
                    print(f"[MUSIC] Connection failed: {e}")
                except Exception as e:
                    print(f"[MUSIC] Connection error: {e}")
                await asyncio.sleep(1.5 * attempt)  # exponential backoff
            state['fake_connect_count'] = 0
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
            # Confirm connection (silent)
            if not voice_client or not voice_client.is_connected():
                # Defer to playback which will re-ensure/retry silently
                print("[MUSIC] Voice client not confirmed after join; proceeding to playback with auto-retry")

            print(f"[MUSIC] Voice client confirmed: {voice_client} (connected: {voice_client.is_connected()})")

            # Check playlist availability
            if not MUSIC_PLAYLISTS:
                print("[MUSIC] No songs in playlist; nothing to play")
                return

            # Use the MUSIC_PLAYLISTS list directly
            playlist = MUSIC_PLAYLISTS.copy()
            
            # Set up guild state
            state = self._get_guild_state(ctx.guild.id)
            state['current_playlist'] = playlist
            state['current_index'] = 0
            
            # Shuffle playlist
            random.shuffle(state['current_playlist'])
            
            # No user notification on start
            
            # Start playing
            await self._play_current_song(ctx)
            
        except Exception as e:
            # Silent on error starting playlist
            print(f"[MUSIC] Error in play_music: {e}")
            import traceback
            traceback.print_exc()

    async def _play_current_song(self, ctx, ffmpeg_retries=2):
        """Play current song with improved error handling"""
        try:
            # Ensure voice connection
            if not await self._ensure_voice(ctx, announce=False):
                print("[MUSIC] Could not ensure voice connection, will retry next song after short delay")
                await asyncio.sleep(3)
                await self._advance_to_next_song(ctx)
                return
            voice_client = ctx.guild.voice_client
            
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
                # Silent reshuffle and restart
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
            player = None
            ffmpeg_error = None
            for ffmpeg_attempt in range(ffmpeg_retries + 1):
                try:
                    player = await YouTubeAudioSource.from_url(url)
                    print(f"[MUSIC] Audio source created: {player.title}")
                    ffmpeg_error = None
                    break
                except Exception as e:
                    ffmpeg_error = e
                    err_msg = str(e)
                    print(f"[MUSIC] Failed to create audio source (attempt {ffmpeg_attempt+1}): {e}")
                    # Check if it's a network-related error that might resolve with retry
                    if ffmpeg_attempt < ffmpeg_retries and any(keyword in err_msg.lower() for keyword in ["connection", "network", "timeout", "tls", "io error", "reset by peer"]):
                        print(f"[MUSIC] Network/FFmpeg error, retrying after delay...")
                        await asyncio.sleep(2.5 * (ffmpeg_attempt + 1))
                        continue
                    # If last attempt, move failed song to end of playlist for retry
                    if any(keyword in err_msg.lower() for keyword in ["connection", "network", "timeout", "tls", "io error", "reset by peer"]):
                        print(f"[MUSIC] Network error detected, will retry this song later")
                        state = self._get_guild_state(ctx.guild.id)
                        current_url = state['current_playlist'][state['current_index']]
                        state['current_playlist'].append(current_url)
                    # Silent failure; advance to next song
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
                        delay = 3 if error and any(keyword in str(error).lower() for keyword in ["connection", "tls", "network"]) else 2
                        async def delayed_next():
                            await asyncio.sleep(delay)
                            # Mark that playback ended to avoid false fake counts
                            try:
                                st = self._get_guild_state(ctx.guild.id)
                                st['play_started_recently'] = False
                            except Exception:
                                pass
                            await self._advance_to_next_song(ctx)
                        # Thread-safe scheduling from FFmpeg thread
                        self.bot.loop.call_soon_threadsafe(lambda: asyncio.create_task(delayed_next()))
                    except Exception as sched_err:
                        print(f"[MUSIC] Error scheduling next song: {sched_err}")
    
            # Only proceed if player was successfully created
            if player:
                try:
                    # Simple connection check before playing
                    if not voice_client or not voice_client.is_connected():
                        print("[MUSIC] Voice client disconnected during playback attempt")
                        # Try to reconnect with backoff (silent)
                        if not await self._ensure_voice(ctx, announce=False, max_retries=5):
                            return
                        voice_client = ctx.guild.voice_client
                    try:
                        voice_client.play(player, after=after_playing)
                    except Exception as play_err:
                        # If play fails due to stale connection, force reconnect once and retry
                        if 'not connected' in str(play_err).lower():
                            print("[MUSIC] Play failed due to stale connection; forcing reconnect and retry")
                            try:
                                if ctx.guild.voice_client:
                                    await ctx.guild.voice_client.disconnect(force=True)
                            except Exception:
                                pass
                            if await self._ensure_voice(ctx, announce=False, max_retries=3):
                                voice_client = ctx.guild.voice_client
                                voice_client.play(player, after=after_playing)
                            else:
                                raise play_err
                        else:
                            raise play_err
                    # Mark that playback started to inform connection health
                    state['play_started_recently'] = True
                    print(f"[MUSIC] Successfully started playback: {player.title}")

                    # Announce now playing in a relevant text channel
                    try:
                        voice_chan = ctx.voice_client.channel if ctx.voice_client else None
                        target_chan = None
                        if voice_chan:
                            for text_chan in ctx.guild.text_channels:
                                if text_chan.name == voice_chan.name and text_chan.permissions_for(ctx.guild.me).send_messages:
                                    target_chan = text_chan
                                    break
                        if not target_chan:
                            target_chan = ctx.channel
                        # Compose link and position info
                        link = getattr(player, 'data', {}).get('webpage_url') or getattr(player, 'url', None) or ''
                        idx = state.get('current_index', 0)
                        total = len(state.get('current_playlist', [])) or 0
                        pos = f" ({idx + 1}/{total})" if total else ""
                        msg = f"🎵 Now playing: **{player.title}**{pos}"
                        if link:
                            msg = f"🎵 Now playing: **[{player.title}]({link})**{pos}"
                        await target_chan.send(msg)
                    except Exception as announce_err:
                        print(f"[MUSIC] Failed to announce now playing: {announce_err}")
                except Exception as e:
                    print(f"[MUSIC] Failed to start playback: {e}")
                    error_str = str(e).lower()
                    if any(keyword in error_str for keyword in ["not connected", "no channel", "connection"]):
                        import time
                        state = self._get_guild_state(ctx.guild.id)
                        state['connection_failures'] = state.get('connection_failures', 0) + 1
                        state['last_failure_time'] = time.time()
                        print(f"[MUSIC] Connection failure #{state['connection_failures']} detected")
                    elif any(keyword in error_str for keyword in ["tls", "network", "io error", "reset by peer"]):
                        print(f"[MUSIC] Network error detected (not counting as connection failure): {e}")
                    await asyncio.sleep(3 if "network" in error_str or "tls" in error_str else 2)
                    await self._advance_to_next_song(ctx)
            
        except Exception as e:
            print(f"[MUSIC] Error in _play_current_song: {e}")
            # Silent error on play
            # Try next song on error
            await self._advance_to_next_song(ctx)

    async def _advance_to_next_song(self, ctx):
        """Advance to next song with circuit breaker to prevent infinite loops"""
        import time
        
        try:
            state = self._get_guild_state(ctx.guild.id)

            # Circuit breaker: if we've had too many failures recently, back off silently
            current_time = time.time()
            if current_time - state.get('last_failure_time', 0) < 60:  # Within last minute
                failure_count = state.get('connection_failures', 0)
                if failure_count >= 5:
                    print(f"[MUSIC] Circuit breaker: {failure_count} failures in last minute; backing off")
                    await asyncio.sleep(15)
                    state['connection_failures'] = 0
            else:
                # Reset failure count if it's been more than a minute
                state['connection_failures'] = 0

            # Check if still connected to voice
            voice_client = ctx.guild.voice_client
            if not voice_client or not voice_client.is_connected():
                print("[MUSIC] Voice client disconnected, attempting to reconnect before next song")
                reconnected = await self._ensure_voice(ctx, announce=False)
                if not reconnected:
                    print("[MUSIC] Could not reconnect, incrementing failure count")
                    state['connection_failures'] = state.get('connection_failures', 0) + 1
                    state['last_failure_time'] = current_time

                    # If we've failed too many times, wait longer before trying again
                    if state['connection_failures'] >= 5:
                        print("[MUSIC] Multiple connection failures, pausing for recovery (silent)")
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
                print(f"[MUSIC] Too many failures; backing off and continuing silently")
                await asyncio.sleep(15)
                state['connection_failures'] = 0

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
        # Ensure voice connection using stabilized path
        if not await self._ensure_voice(ctx, announce=True):
            return
        voice_client = ctx.guild.voice_client
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
        if voice_client and voice_client.is_playing():
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
                self.bot.loop.call_soon_threadsafe(lambda: asyncio.create_task(self._advance_to_next_song(ctx)))
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
