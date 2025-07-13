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
        """Join the user's voice channel; no-op if already connected"""
        # User must be in a voice channel
        if not ctx.author.voice or not ctx.author.voice.channel:
            await ctx.send("❌ You need to be in a voice channel first!")
            return False
        channel = ctx.author.voice.channel
        vc = ctx.guild.voice_client
        try:
            if not vc or not vc.is_connected():
                await channel.connect()
                await ctx.send(f"✅ Connected to **{channel.name}**")
            return True
        except Exception as e:
            await ctx.send(f"❌ Could not join voice channel: {e}")
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
        """Play the main playlist. Requires prior !join to connect."""
        vc = ctx.guild.voice_client
        if not vc or not vc.is_connected():
            await ctx.send("❌ I'm not connected to a voice channel! Use `!join`.")
            return
        voice_client = vc

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
        
    async def _play_current_song(self, ctx):
        """Play current song with improved error handling"""
        voice_client = ctx.guild.voice_client
         if not voice_client:
             print("[MUSIC] No voice client available, stopping playback")
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
            voice_chan = ctx.guild.voice_client.channel if ctx.guild.voice_client else None
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
            vc = ctx.guild.voice_client
            if not vc or not vc.is_playing():
                await ctx.send("❌ Nothing is playing!")
                return
            
            vc.stop()  # This will trigger the after callback
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
            vc = ctx.guild.voice_client
            if not vc or not vc.source:
                await ctx.send("❌ Nothing is playing!")
                return
            
            source = vc.source
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
        vc = ctx.guild.voice_client
        if not vc or not vc.is_connected():
            if not await self.join_voice_channel(ctx):
                return
            vc = ctx.guild.voice_client
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
        if vc.is_playing():
            vc.stop()
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
            # Restore previous playlist state and resume from next song
            if saved_state is not None:
                # Advance index to next track
                restored_index = saved_state['current_index'] + 1
                playlist = saved_state['current_playlist']
                # Wrap around or reshuffle if at end
                if restored_index >= len(playlist):
                    restored_index = 0
                    random.shuffle(playlist)
                self.guild_states[ctx.guild.id] = {
                    'current_playlist': playlist,
                    'current_index': restored_index
                }
            try:
                # Play next song from restored state
                self.bot.loop.create_task(self._play_current_song(ctx))
            except Exception as err:
                print(f"[MUSIC] Error resuming playlist: {err}")
        vc.play(player, after=after)
        # Send now playing message to appropriate text channel
        msg = f"🎵 Now playing URL: **{player.title}**"
        # Prefer a text channel matching the voice channel name
        voice_chan = ctx.guild.voice_client.channel if ctx.guild.voice_client else None
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


    def get_available_playlists(self):
        """Get list of available playlists"""
        return ["main"]  # Simplified for cloud deployment
