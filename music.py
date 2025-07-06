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
        """Improved voice channel joining with better diagnostics"""
        try:
            # Check if user is in voice channel
            if not ctx.author.voice or not ctx.author.voice.channel:
                await ctx.send("❌ You need to be in a voice channel first!")
                return False

            channel = ctx.author.voice.channel
            print(f"[MUSIC] Attempting to join channel: {channel.name} (ID: {channel.id})")
            
            # Check bot permissions
            permissions = channel.permissions_for(ctx.guild.me)
            if not permissions.connect:
                await ctx.send("❌ I don't have permission to connect to that voice channel!")
                return False
            if not permissions.speak:
                await ctx.send("❌ I don't have permission to speak in that voice channel!")
                return False
            
            # If already connected, handle appropriately
            if ctx.voice_client:
                if ctx.voice_client.channel == channel:
                    await ctx.send(f"✅ Already connected to **{channel.name}**")
                    return True
                else:
                    # Move to new channel
                    try:
                        await ctx.voice_client.move_to(channel)
                        await ctx.send(f"🔄 Moved to **{channel.name}**")
                        return True
                    except Exception as e:
                        print(f"[MUSIC] Failed to move channels: {e}")
                        # Disconnect and try fresh connection
                        try:
                            await ctx.voice_client.disconnect(force=True)
                            await asyncio.sleep(1)
                        except:
                            pass
            
            # Attempt fresh connection with retries
            for attempt in range(3):
                try:
                    print(f"[MUSIC] Connection attempt {attempt + 1}/3")
                    
                    # Connect to the channel with timeout
                    voice_client = await asyncio.wait_for(
                        channel.connect(reconnect=True, timeout=20.0),
                        timeout=25.0
                    )
                    
                    # Wait for discord.py internal registration
                    await asyncio.sleep(2.0)
                    
                    # Multiple verification methods
                    verifications = []
                    
                    # Method 1: Check the returned voice client
                    if voice_client and voice_client.is_connected():
                        verifications.append("direct")
                    
                    # Method 2: Check via ctx.voice_client
                    if ctx.voice_client and ctx.voice_client.is_connected():
                        verifications.append("ctx")
                    
                    # Method 3: Check via guild voice client
                    guild_vc = ctx.guild.voice_client
                    if guild_vc and guild_vc.is_connected():
                        verifications.append("guild")
                    
                    print(f"[MUSIC] Verification methods passed: {verifications}")
                    
                    # If any verification method passed, consider it successful
                    if verifications:
                        await ctx.send(f"✅ Joined 🎵 | **{channel.name}** (attempt {attempt + 1})")
                        print(f"[MUSIC] Successfully connected to {channel.name}")
                        return True
                    else:
                        print(f"[MUSIC] All verification methods failed on attempt {attempt + 1}")
                        if attempt < 2:  # Don't disconnect on last attempt
                            if voice_client:
                                try:
                                    await voice_client.disconnect(force=True)
                                except:
                                    pass
                            await asyncio.sleep(2)
                        
                except asyncio.TimeoutError:
                    print(f"[MUSIC] Connection timeout on attempt {attempt + 1}")
                    if attempt < 2:
                        await asyncio.sleep(2)
                        
                except Exception as e:
                    print(f"[MUSIC] Connection attempt {attempt + 1} failed: {e}")
                    if attempt < 2:
                        await asyncio.sleep(2)
                        continue
                    else:
                        raise e
            
            await ctx.send("❌ Failed to establish stable voice connection after 3 attempts! Check bot permissions and try again.")
            return False
            
        except Exception as e:
            error_msg = str(e)[:100]
            await ctx.send(f"❌ Failed to join voice channel: {error_msg}")
            print(f"[MUSIC] Error in join_voice_channel: {e}")
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
                await ctx.send(f"❌ Failed to load song, skipping...")
                await self._advance_to_next_song(ctx)
                return
            
            def after_playing(error):
                if error:
                    print(f"[MUSIC] Player error: {error}")
                else:
                    print(f"[MUSIC] Song finished normally")
                # Schedule next song
                asyncio.create_task(self._advance_to_next_song(ctx))
            
            try:
                voice_client.play(player, after=after_playing)
                await ctx.send(f"🎵 Now playing: **{player.title}** ({index + 1}/{len(playlist)})")
                print(f"[MUSIC] Successfully started playback: {player.title}")
            except Exception as e:
                print(f"[MUSIC] Failed to start playback: {e}")
                await ctx.send(f"❌ Playback failed, skipping...")
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
