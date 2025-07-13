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
    """Minimal, stable music bot that only connects on !join and stays until !leave."""
    def __init__(self, bot):
        self.bot = bot
        self.queues = {}  # guild_id -> list of URLs

    def _get_queue(self, guild_id):
        # Initialize or return existing queue
        if guild_id not in self.queues or not self.queues[guild_id]:
            q = MUSIC_PLAYLISTS.copy()
            random.shuffle(q)
            self.queues[guild_id] = q
        return self.queues[guild_id]

    async def join_voice_channel(self, ctx):
        # User must be in a channel
        vc = ctx.guild.voice_client
        channel = ctx.author.voice and ctx.author.voice.channel
        if not channel:
            return await ctx.send("❌ You need to join a voice channel first!")
        try:
            if not vc:
                vc = await channel.connect()
                await ctx.send(f"✅ Joined **{channel.name}**")
            elif vc.channel.id != channel.id:
                await vc.move_to(channel)
                await ctx.send(f"✅ Moved to **{channel.name}**")
            return True
        except Exception as e:
            return await ctx.send(f"❌ Could not join: {e}")

    async def leave_voice_channel(self, ctx):
        vc = ctx.guild.voice_client
        if not vc:
            return await ctx.send("❌ I'm not in a voice channel.")
        await vc.disconnect()
        self.queues.pop(ctx.guild.id, None)
        await ctx.send("👋 Left voice channel!")

    async def play_music(self, ctx, _=None):
        # Make sure we’re already connected
        vc = ctx.guild.voice_client
        if not vc or not vc.is_connected():
            return await ctx.send("❌ Not connected. Use `!join` first.")
        queue = self._get_queue(ctx.guild.id)
        # Kick off the first track
        await self._play_next(ctx)

    async def _play_next(self, ctx):
        vc = ctx.guild.voice_client
        if not vc:
            return  # nothing to do

        queue = self._get_queue(ctx.guild.id)
        url = queue.pop(0)
        # Replenish and reshuffle when empty
        if not queue:
            queue.extend(MUSIC_PLAYLISTS)
            random.shuffle(queue)

        try:
            source = await YouTubeAudioSource.from_url(url)
        except Exception:
            return await self._play_next(ctx)

        def _after(err):
            # schedule next even if error
            self.bot.loop.create_task(self._play_next(ctx))

        vc.play(source, after=_after)
        await ctx.send(f"▶️ Now playing: **{source.title}**")

    async def skip_song(self, ctx):
        vc = ctx.guild.voice_client
        if not vc or not vc.is_playing():
            return await ctx.send("❌ Nothing is playing!")
        vc.stop()  # triggers _after and plays next
        await ctx.send("⏭️ Skipped.")

    async def pause_music(self, ctx):
        vc = ctx.guild.voice_client
        if vc and vc.is_playing():
            vc.pause()
            return await ctx.send("⏸️ Paused.")
        await ctx.send("❌ Nothing to pause.")

    async def resume_music(self, ctx):
        vc = ctx.guild.voice_client
        if vc and vc.is_paused():
            vc.resume()
            return await ctx.send("▶️ Resumed.")
        await ctx.send("❌ Nothing to resume.")

    async def now_playing(self, ctx):
        vc = ctx.guild.voice_client
        if not vc or not vc.source:
            return await ctx.send("❌ Nothing is playing.")
        src = vc.source
        state = self.queues.get(ctx.guild.id, [])
        idx = len(MUSIC_PLAYLISTS) - len(state)  # approximate position
        await ctx.send(f"ℹ️ Now playing: **{src.title}** ({idx}/{len(MUSIC_PLAYLISTS)})")
