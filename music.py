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
        """Clean up guild state and voice client"""
        if guild_id in self.guild_states:
            del self.guild_states[guild_id]
        
        # Also clean up any stale voice client references
        guild = self.bot.get_guild(guild_id)
        if guild and guild.voice_client:
            try:
                guild.voice_client.cleanup()
            except:
                pass

    async def join_voice_channel(self, ctx):
        """Join the invoking user's voice channel"""
        # First, always check if we have a stale voice client and clean it up
        if ctx.voice_client:
            try:
                # Test if the connection is actually alive
                is_actually_connected = (
                    ctx.voice_client.is_connected() and 
                    ctx.voice_client.channel is not None and
                    ctx.guild.me in ctx.voice_client.channel.members
                )
                
                if is_actually_connected:
                    print(f"[MUSIC] Already connected to voice channel: {ctx.voice_client.channel.name}")
                    return True
                else:
                    print(f"[MUSIC] Cleaning up stale voice client")
                    await ctx.voice_client.disconnect()
                    # Give a moment for the cleanup to complete
                    await asyncio.sleep(0.5)
            except Exception as e:
                print(f"[MUSIC] Error during voice client cleanup: {e}")
                # Force cleanup by setting to None if disconnect fails
                try:
                    ctx.voice_client.cleanup()
                except:
                    pass
        
        # Ensure user is in a voice channel
        user_voice = getattr(ctx.author, 'voice', None)
        if not user_voice or not user_voice.channel:
            await ctx.send("❌ Join a voice channel first!")
            return False
        
        channel = user_voice.channel
        try:
            print(f"[MUSIC] Attempting to connect to channel: {channel.name}")
            vc = await channel.connect()
            # Store voice channel in state for reconnect logic
            state = self._get_guild_state(ctx.guild.id)
            state['voice_channel_id'] = channel.id
            print(f"[MUSIC] Successfully connected to: {channel.name}")
            await ctx.send(f"✅ Connected to **{channel.name}**")
            return True
        except Exception as e:
            err = str(e)
            # Handle specific connection errors
            if 'Already connected to a voice channel' in err:
                print(f"[MUSIC] Already connected (caught exception)")
                # Still store the channel info in state
                state = self._get_guild_state(ctx.guild.id)
                state['voice_channel_id'] = channel.id
                return True
            print(f"[MUSIC] join error: {err}")
            await ctx.send(f"❌ Could not join voice channel: {err[:100]}")
            return False

    async def leave_voice_channel(self, ctx):
        """Leave voice channel and cleanup"""
        try:
            if ctx.voice_client:
                await ctx.voice_client.disconnect()
                # Give a moment for the disconnect to complete
                await asyncio.sleep(0.5)
                self._cleanup_guild_state(ctx.guild.id)
                await ctx.send("👋 Left the voice channel!")
            else:
                await ctx.send("❌ I'm not connected to a voice channel!")
        except Exception as e:
            await ctx.send(f"❌ Error leaving voice channel: {str(e)[:100]}")
            # Force cleanup even if disconnect fails
            self._cleanup_guild_state(ctx.guild.id)

    async def force_cleanup(self, ctx):
        """Force cleanup of voice connection and state"""
        try:
            guild_id = ctx.guild.id
            
            # Force disconnect all voice clients
            if ctx.voice_client:
                try:
                    await ctx.voice_client.disconnect()
                except:
                    pass
                try:
                    ctx.voice_client.cleanup()
                except:
                    pass
            
            # Also check guild voice client
            if ctx.guild.voice_client:
                try:
                    await ctx.guild.voice_client.disconnect()
                except:
                    pass
                try:
                    ctx.guild.voice_client.cleanup()
                except:
                    pass
            
            # Clean up state
            self._cleanup_guild_state(guild_id)
            
            await ctx.send("🧹 Force cleanup completed!")
            
        except Exception as e:
            await ctx.send(f"❌ Error during force cleanup: {str(e)[:100]}")
            # Still try to clean up state
            self._cleanup_guild_state(ctx.guild.id)

    async def play_music(self, ctx, playlist_name="main"):
        """Improved music playback with better voice connection handling"""
        try:
            # Ensure connected using join logic (supports previous channels)
            if not await self.join_voice_channel(ctx):
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

            # Get current guild state
            state = self._get_guild_state(ctx.guild.id)
            
            # Check if music is already playing
            if voice_client.is_playing():
                await ctx.send("🎵 Music is already playing! Use `!stop` to stop current playback first.")
                return
            
            # Only set up new playlist if we don't have one or it's empty
            if not state.get('current_playlist'):
                # Use the MUSIC_PLAYLISTS list directly
                playlist = MUSIC_PLAYLISTS.copy()
                
                # Set up guild state with new playlist
                state['current_playlist'] = playlist
                state['current_index'] = 0
                
                # Shuffle playlist
                random.shuffle(state['current_playlist'])
                
                await ctx.send(f"🎵 Starting music playlist ({len(playlist)} songs)")
            else:
                # Resume existing playlist
                playlist_length = len(state['current_playlist'])
                current_index = state['current_index']
                await ctx.send(f"🎵 Resuming playlist at song {current_index + 1}/{playlist_length}")
            
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
            
            # Check if we need to reconnect
            if not voice_client or not voice_client.is_connected():
                print("[MUSIC] Voice client disconnected, attempting to reconnect...")
                
                # Try to get the stored voice channel first
                state = self._get_guild_state(ctx.guild.id)
                channel_id = state.get('voice_channel_id')
                
                if channel_id:
                    # Try to reconnect to the stored channel
                    channel = ctx.guild.get_channel(channel_id)
                    if channel:
                        try:
                            print(f"[MUSIC] Reconnecting to stored channel: {channel.name}")
                            # Force cleanup first
                            if voice_client:
                                try:
                                    await voice_client.disconnect()
                                except:
                                    pass
                                try:
                                    voice_client.cleanup()
                                except:
                                    pass
                            
                            await channel.connect()
                            voice_client = ctx.voice_client or ctx.guild.voice_client
                        except Exception as e:
                            print(f"[MUSIC] Failed to reconnect to stored channel: {e}")
                            # Clear invalid channel ID
                            state.pop('voice_channel_id', None)
                            voice_client = None
                
                # If we still don't have a connection, try regular join
                if not voice_client or not voice_client.is_connected():
                    print("[MUSIC] Attempting regular join...")
                    reconnected = await self.join_voice_channel(ctx)
                    if not reconnected:
                        print("[MUSIC] Could not reconnect, stopping playback")
                        return
                    voice_client = ctx.voice_client or ctx.guild.voice_client
            
            # Double-check the voice client is valid
            if not voice_client or not voice_client.is_connected():
                print("[MUSIC] Voice client still not connected after reconnection attempts")
                return
            
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
            voice_client = ctx.voice_client or ctx.guild.voice_client
            if not voice_client or not voice_client.is_connected():
                print("[MUSIC] Voice client disconnected during advance, stopping music")
                return
                
            state = self._get_guild_state(ctx.guild.id)
            state['current_index'] += 1
            await self._play_current_song(ctx)
        except Exception as e:
            print(f"[MUSIC] Error advancing to next song: {e}")
            # Try to continue playing if possible
            try:
                await self._play_current_song(ctx)
            except Exception as e2:
                print(f"[MUSIC] Failed to recover from advance error: {e2}")

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
        try:
            # Ensure voice connection
            if not await self.join_voice_channel(ctx):
                return
            
            voice_client = ctx.voice_client or ctx.guild.voice_client
            if not voice_client or not voice_client.is_connected():
                await ctx.send("❌ Voice connection failed!")
                return
            
            # Stop any current playback
            if voice_client.is_playing():
                voice_client.stop()
                await asyncio.sleep(0.5)  # Brief pause to ensure clean stop
            
            # Create player for the URL
            try:
                player = await YouTubeAudioSource.from_url(url)
            except Exception as e:
                await ctx.send(f"❌ Failed to load URL: {str(e)[:100]}")
                return
            
            # Play the URL
            def after_url(error):
                if error:
                    print(f"[MUSIC] URL playback error: {error}")
                # Resume playlist after URL finishes
                try:
                    state = self._get_guild_state(ctx.guild.id)
                    if state.get('current_playlist'):
                        # Continue with current playlist
                        self.bot.loop.create_task(self._play_current_song(ctx))
                except Exception as err:
                    print(f"[MUSIC] Error resuming playlist after URL: {err}")
            
            voice_client.play(player, after=after_url)
            
            # Send now playing message
            await ctx.send(f"🎵 Now playing URL: **{player.title}**")
            
        except Exception as e:
            await ctx.send(f"❌ Error playing URL: {str(e)[:100]}")
            print(f"[MUSIC] Error in play_url: {e}")

    async def start_fresh_playlist(self, ctx):
        """Start a fresh playlist from the beginning"""
        try:
            # Ensure connected using join logic
            if not await self.join_voice_channel(ctx):
                return
            voice_client = ctx.voice_client or ctx.guild.voice_client
            if not voice_client or not voice_client.is_connected():
                await ctx.send("❌ Voice connection failed!")
                return

            # Check playlist availability
            if not MUSIC_PLAYLISTS:
                await ctx.send(f"❌ No songs in playlist!")
                return

            # Stop any current playback
            if voice_client.is_playing():
                voice_client.stop()
                await asyncio.sleep(0.5)

            # Always create a fresh playlist
            playlist = MUSIC_PLAYLISTS.copy()
            
            # Set up guild state with new playlist
            state = self._get_guild_state(ctx.guild.id)
            state['current_playlist'] = playlist
            state['current_index'] = 0
            
            # Shuffle playlist
            random.shuffle(state['current_playlist'])
            
            await ctx.send(f"🎵 Starting fresh playlist ({len(playlist)} songs)")
            
            # Start playing
            await self._play_current_song(ctx)
            
        except Exception as e:
            await ctx.send(f"❌ Error starting fresh playlist: {str(e)[:100]}")
            print(f"[MUSIC] Error in start_fresh_playlist: {e}")

    async def voice_health_check(self):
        """Periodically check voice connection health and reconnect if needed."""
        await self.bot.wait_until_ready()
        print("[MUSIC] Voice health check started")
        
        while not self.bot.is_closed():
            try:
                for guild_id, state in list(self.guild_states.items()):
                    channel_id = state.get('voice_channel_id')
                    guild = self.bot.get_guild(guild_id)
                    
                    if not guild or not channel_id:
                        continue
                    
                    channel = guild.get_channel(channel_id)
                    if not channel:
                        # Channel no longer exists, clean up state
                        print(f"[MUSIC] Cleaning up state for non-existent channel in guild {guild_id}")
                        state.pop('voice_channel_id', None)
                        continue
                    
                    vc = guild.voice_client
                    
                    # Check if we should be connected but aren't, or if connection is stale
                    needs_reconnect = False
                    reason = "unknown"
                    
                    if not vc or not vc.is_connected():
                        needs_reconnect = True
                        reason = "no voice client or not connected"
                    else:
                        # Check if the connection is actually alive by verifying bot is in channel
                        try:
                            if vc.channel != channel or guild.me not in vc.channel.members:
                                needs_reconnect = True
                                reason = "bot not in expected voice channel"
                        except Exception as e:
                            needs_reconnect = True
                            reason = f"error checking connection: {e}"
                    
                    if needs_reconnect:
                        print(f"[MUSIC] Voice client needs reconnection in guild {guild_id}: {reason}")
                        try:
                            # Clean up old connection first
                            if vc:
                                try:
                                    await vc.disconnect()
                                except:
                                    pass
                                await asyncio.sleep(1)  # Wait for cleanup
                            
                            # Reconnect
                            await channel.connect()
                            print(f"[MUSIC] Successfully reconnected to {channel.name} in guild {guild_id}")
                            
                            # If we have a playlist and should be playing, restart playback
                            if (state.get('current_playlist') and 
                                not guild.voice_client.is_playing() and 
                                not guild.voice_client.is_paused()):
                                print(f"[MUSIC] Restarting playback after reconnection in guild {guild_id}")
                                # Create a minimal context for playback
                                class MinimalContext:
                                    def __init__(self, guild, channel):
                                        self.guild = guild
                                        self.channel = channel
                                        self.voice_client = guild.voice_client
                                        self.send = lambda msg: None  # Dummy send function
                                
                                # Find a text channel to send messages to
                                text_channel = None
                                for tc in guild.text_channels:
                                    if tc.name == channel.name:
                                        text_channel = tc
                                        break
                                if not text_channel:
                                    text_channel = guild.text_channels[0] if guild.text_channels else None
                                
                                if text_channel:
                                    minimal_ctx = MinimalContext(guild, text_channel)
                                    self.bot.loop.create_task(self._play_current_song(minimal_ctx))
                                    
                        except Exception as err:
                            print(f"[MUSIC] Health check reconnect failed for guild {guild_id}: {err}")
                            # Clean up state on persistent failure
                            state.pop('voice_channel_id', None)
                            
                await asyncio.sleep(30)  # Check every 30 seconds
                
            except Exception as e:
                print(f"[MUSIC] Voice health check error: {e}")
                await asyncio.sleep(30)  # Continue checking even if there's an error

    def get_available_playlists(self):
        """Get list of available playlists"""
        return ["main"]  # Simplified for cloud deployment
