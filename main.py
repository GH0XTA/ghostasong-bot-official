import discord
from discord.ext import commands
import yt_dlp
from keep_alive import keep_alive
import asyncio
import os

song_queue = {}
autoplay_enabled = {}
now_playing = {}
leave_tasks = {}


def get_queue(guild_id):
    if guild_id not in song_queue:
        song_queue[guild_id] = asyncio.Queue()
    return song_queue[guild_id]


intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='g!', intents=intents)
bot.remove_command("help")


YDL_OPTIONS = {'format': 'bestaudio',
               'noplaylist': 'True',
               'cookiefile': 'cookies.txt'
              }
FFMPEG_OPTIONS = {
    'before_options':
    '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}


@bot.event
async def on_ready():
    print(f'✅ Logged in as {bot.user}')

@bot.event
async def on_voice_state_update(member, before, after):
    # Only trigger when a member leaves a voice channel
    if before.channel != after.channel and before.channel is not None:
        voice_client = member.guild.voice_client
        if voice_client and voice_client.channel == before.channel:
            # Check if there are any human users left
            non_bots = [m for m in before.channel.members if not m.bot]
            await asyncio.sleep(3)
            if len(non_bots) == 0:
                await voice_client.disconnect()
                channel = before.channel
                text_channels = member.guild.text_channels
                if text_channels:
                    await text_channels[0].send("👋 Left the voice channel — no one was left listening.")



@bot.command()
async def join(ctx):
    if ctx.author.voice:
        await ctx.author.voice.channel.connect()
        await ctx.send("✅ Joined the voice channel.")
    else:
        await ctx.send("❌ You're not in a voice channel.")


@bot.command()
async def leave(ctx):
    if ctx.voice_client:
        await ctx.voice_client.disconnect()
        await ctx.send("👋 Left the voice channel.")
    else:
        await ctx.send("❌ I'm not in a voice channel.")


@bot.command(name="p", aliases=["play"])
async def play(ctx, *, search: str):
    guild_id = ctx.guild.id

    # Cancel leave task if music is playing again
    task = leave_tasks.get(guild_id)
    if task and not task.done():
        task.cancel()

    # Connect to voice if not already
    vc = discord.utils.get(bot.voice_clients, guild=ctx.guild)
    if not vc:
        if ctx.author.voice:
            vc = await ctx.author.voice.channel.connect()
        else:
            return await ctx.send("❌ You're not in a voice channel.")

    # Download or search YouTube
    with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
        if "youtube.com" in search or "youtu.be" in search:
            info = ydl.extract_info(search, download=False)
        else:
            info = ydl.extract_info(f"ytsearch:{search}", download=False)['entries'][0]

    info['requester'] = ctx.author.mention

    # Add to queue for this guild
    queue = get_queue(guild_id)
    await queue.put(info)

    await ctx.send(f"🎵 Added to queue: **{info['title']}**")

    # Only start playback if not already playing
    if not vc.is_playing() and not now_playing.get(guild_id):
        autoplay_enabled[guild_id] = True
        await play_next(ctx)



@bot.command()
async def skip(ctx):
    vc = discord.utils.get(bot.voice_clients, guild=ctx.guild)
    if vc and vc.is_playing():
        vc.stop()
        await ctx.send("⏭️ Skipping current song.")
    else:
        await ctx.send("❌ Nothing is playing.")

@bot.command()
async def queue(ctx):
    queue = get_queue(ctx.guild.id)
    if queue.empty():
        await ctx.send("📭 Queue is empty.")
    else:
        queue_list = list(queue._queue)
        msg = "\n".join([f"{i+1}. {item['title']}" for i, item in enumerate(queue_list)])
        await ctx.send(f"📜 Queue:\n{msg}")

@bot.command()
async def nowplaying(ctx):
    current = now_playing.get(ctx.guild.id)
    if current:
        await ctx.send(f"🎧 Now playing: **{current}**")
    else:
        await ctx.send("❌ Nothing is playing right now.")



    vc.stop()

    def after_playing(error):
        coro = disconnect_if_idle(vc)
        fut = asyncio.run_coroutine_threadsafe(coro, bot.loop)
        try:
            fut.result()
        except:
            pass

    source = discord.FFmpegPCMAudio(url, **FFMPEG_OPTIONS)
    vc.play(source, after=after_playing)
    await ctx.send(f"🎶 Now playing: **{title}**")


async def disconnect_if_idle(vc, delay: int = 10):
    await asyncio.sleep(delay)
    if not vc.is_playing():
        await vc.disconnect()


@bot.command()
async def pause(ctx):
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.pause()
        await ctx.send("⏸️ Paused.")
    else:
        await ctx.send("❌ Nothing is playing.")


@bot.command()
async def resume(ctx):
    if ctx.voice_client and ctx.voice_client.is_paused():
        ctx.voice_client.resume()
        await ctx.send("▶️ Resumed.")
    else:
        await ctx.send("❌ Nothing to resume.")


@bot.command()
async def stop(ctx):
    vc = discord.utils.get(bot.voice_clients, guild=ctx.guild)
    if vc and vc.is_playing():
        autoplay_enabled[ctx.guild.id] = False  # Pause autoplay
        vc.stop()  # Stop current song
        await ctx.send("⏹️ Playback stopped.")
    else:
        await ctx.send("❌ Nothing is playing.")

@bot.command()
async def clear(ctx):
    queue = get_queue(ctx.guild.id)
    queue._queue.clear()
    await ctx.send("🧹 Cleared the queue.")

@bot.command()
async def help(ctx):
    embed = discord.Embed(
        title="📚 Music Bot Help",
        description="Here are the commands you can use:",
        color=discord.Color.green()
    )

    embed.add_field(name="g!play [song or link]", value="🎵 Play a song or add to queue", inline=False)
    embed.add_field(name="g!skip", value="⏭️ Skip the current song", inline=False)
    embed.add_field(name="g!stop", value="⏹️ Stop the music but keep the queue", inline=False)
    embed.add_field(name="g!queue", value="📜 Show the current queue", inline=False)
    embed.add_field(name="g!nowplaying", value="🎧 Show the song that's currently playing", inline=False)
    embed.add_field(name="g!leave", value="👋 Leave the voice channel", inline=False)
    embed.add_field(name="g!clear", value="🧹 Clear the queue", inline=False)

    await ctx.send(embed=embed)


keep_alive()
async def play_next(ctx):
    guild_id = ctx.guild.id
    queue = get_queue(guild_id)

    if queue.empty():
        now_playing[guild_id] = None

        # Wait 5 minutes before leaving
        async def delayed_leave():
            await asyncio.sleep(300)  # 5 minutes
            if queue.empty():
                vc = discord.utils.get(bot.voice_clients, guild=ctx.guild)
                if vc and vc.is_connected():
                    await vc.disconnect()
                    await ctx.send("👋 Left voice channel after 5 minutes of inactivity.")

        task = asyncio.create_task(delayed_leave())
        leave_tasks[guild_id] = task
        return

    if not autoplay_enabled.get(guild_id, True):
        return

    # Get next song
    song = await queue.get()
    now_playing[guild_id] = {
        "title": song["title"],
        "url": song["webpage_url"],
        "duration": song.get("duration"),
        "thumbnail": song.get("thumbnail"),
        "requester": song["requester"],
    }

    source = discord.FFmpegPCMAudio(song["url"], **FFMPEG_OPTIONS)

    def after_play(err):
        fut = asyncio.run_coroutine_threadsafe(play_next(ctx), bot.loop)
        try:
            fut.result()
        except:
            pass

    ctx.voice_client.play(source, after=after_play)
    await ctx.send(f"🎶 Now playing: **{song['title']}** — requested by {song['requester']}")

bot.run(os.getenv("DISCORD_TOKEN"))



