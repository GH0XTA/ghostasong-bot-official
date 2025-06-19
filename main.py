import discord
from discord.ext import commands
import yt_dlp
from keep_alive import keep_alive
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

song_queue = {}
autoplay_enabled = {}
now_playing = {}
leave_tasks = {}
guild_owners = {}
skip_votes = {}

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
               'cookiefile': 'cookies.txt'}
FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

@bot.event
async def on_ready():
    print(f'✅ Logged in as {bot.user}')

@bot.event
async def on_voice_state_update(member, before, after):
    if before.channel != after.channel and before.channel is not None:
        voice_client = member.guild.voice_client
        if voice_client and voice_client.channel == before.channel:
            non_bots = [m for m in before.channel.members if not m.bot]
            await asyncio.sleep(3)
            if len(non_bots) == 0:
                await voice_client.disconnect()
                text_channels = member.guild.text_channels
                if text_channels:
                    await text_channels[0].send("👋 Left the voice channel — no one was left listening.")

@bot.command()
async def join(ctx):
    if ctx.author.voice:
        vc = discord.utils.get(bot.voice_clients, guild=ctx.guild)
        if vc and vc.is_connected():
            return await ctx.send("✅ Already connected to a voice channel.")
        vc = await ctx.author.voice.channel.connect()
        guild_owners[ctx.guild.id] = ctx.author.id
        await ctx.send("✅ Joined the voice channel.")
    else:
        await ctx.send("❌ You're not in a voice channel.")

@bot.command()
async def leave(ctx):
    if ctx.guild.id in guild_owners and ctx.author.id != guild_owners[ctx.guild.id]:
        return await ctx.send("❌ Only the user who started the session can make me leave.")
    if ctx.voice_client:
        await ctx.voice_client.disconnect()
        await ctx.send("👋 Left the voice channel.")
        guild_owners.pop(ctx.guild.id, None)
    else:
        await ctx.send("❌ I'm not in a voice channel.")

@bot.command(name="p", aliases=["play"])
async def play(ctx, *, search: str):
    guild_id = ctx.guild.id

    if guild_id not in guild_owners:
        guild_owners[guild_id] = ctx.author.id

    task = leave_tasks.get(guild_id)
    if task and not task.done():
        task.cancel()

    vc = discord.utils.get(bot.voice_clients, guild=ctx.guild)
    if not vc:
        if ctx.author.voice:
            try:
                vc = await ctx.author.voice.channel.connect()
            except discord.ClientException:
                vc = discord.utils.get(bot.voice_clients, guild=ctx.guild)
        else:
            return await ctx.send("❌ You're not in a voice channel.")

    with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
        if "youtube.com" in search or "youtu.be" in search:
            info = ydl.extract_info(search, download=False)
        else:
            info = ydl.extract_info(f"ytsearch:{search}", download=False)['entries'][0]

    info['requester'] = ctx.author.mention

    queue = get_queue(guild_id)
    await queue.put(info)
    await ctx.send(f"🎵 Added to queue: **{info['title']}**")

    if not vc.is_playing() and not now_playing.get(guild_id):
        autoplay_enabled[guild_id] = True
        await play_next(ctx)

@bot.command()
async def skip(ctx):
    guild_id = ctx.guild.id
    if guild_id not in guild_owners:
        return await ctx.send("❌ No music session active.")

    if ctx.author.id == guild_owners[guild_id]:
        ctx.voice_client.stop()
        return await ctx.send("⏭️ Skipped by session owner.")

    voters = skip_votes.setdefault(guild_id, set())
    if ctx.author.id in voters:
        return await ctx.send("❌ You've already voted to skip.")
    voters.add(ctx.author.id)

    vc = ctx.voice_client
    if vc:
        members = [m for m in vc.channel.members if not m.bot]
        if len(voters) >= max(1, len(members) // 2):
            vc.stop()
            skip_votes[guild_id] = set()
            await ctx.send("⏭️ Vote passed. Skipping song.")
        else:
            await ctx.send(f"🗳️ Voted to skip. ({len(voters)}/{max(1, len(members)//2)} needed)")

@bot.command()
async def queue(ctx):
    queue = get_queue(ctx.guild.id)
    if queue.empty():
        await ctx.send("📍 Queue is empty.")
    else:
        queue_list = list(queue._queue)
        msg = "\n".join([f"{i+1}. {item['title']}" for i, item in enumerate(queue_list)])
        await ctx.send(f"📜 Queue:\n{msg}")

@bot.command()
async def nowplaying(ctx):
    current = now_playing.get(ctx.guild.id)
    if current:
        await ctx.send(f"🎧 Now playing: **{current['title']}**")
    else:
        await ctx.send("❌ Nothing is playing right now.")

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
    if ctx.guild.id in guild_owners and ctx.author.id != guild_owners[ctx.guild.id]:
        return await ctx.send("❌ Only the session owner can stop playback.")

    vc = discord.utils.get(bot.voice_clients, guild=ctx.guild)
    if vc and vc.is_playing():
        autoplay_enabled[ctx.guild.id] = False
        vc.stop()
        await ctx.send("⏹️ Playback stopped.")
    else:
        await ctx.send("❌ Nothing is playing.")

@bot.command()
async def clear(ctx):
    if ctx.guild.id in guild_owners and ctx.author.id != guild_owners[ctx.guild.id]:
        return await ctx.send("❌ Only the session owner can clear the queue.")

    queue = get_queue(ctx.guild.id)
    queue._queue.clear()
    await ctx.send("🪯 Cleared the queue.")

@bot.command()
async def help(ctx):
    embed = discord.Embed(title="📚 Music Bot Help", description="Commands you can use:", color=discord.Color.green())
    embed.add_field(name="g!play [song]", value="🎵 Play a song", inline=False)
    embed.add_field(name="g!skip", value="⏭️ Vote to skip", inline=False)
    embed.add_field(name="g!stop", value="⏹️ Stop music", inline=False)
    embed.add_field(name="g!queue", value="📜 Show queue", inline=False)
    embed.add_field(name="g!nowplaying", value="🎧 What's playing now", inline=False)
    embed.add_field(name="g!leave", value="👋 Leave voice channel", inline=False)
    embed.add_field(name="g!clear", value="🪯 Clear queue", inline=False)
    await ctx.send(embed=embed)

async def play_next(ctx):
    guild_id = ctx.guild.id
    queue = get_queue(guild_id)

    if queue.empty():
        now_playing[guild_id] = None

        async def delayed_leave():
            await asyncio.sleep(300)
            if queue.empty():
                vc = discord.utils.get(bot.voice_clients, guild=ctx.guild)
                if vc and vc.is_connected():
                    await vc.disconnect()
                    await ctx.send("👋 Left voice channel after 5 minutes of inactivity.")
                    guild_owners.pop(guild_id, None)

        task = asyncio.create_task(delayed_leave())
        leave_tasks[guild_id] = task
        return

    if not autoplay_enabled.get(guild_id, True):
        return

    song = await queue.get()
    now_playing[guild_id] = song

    vc = discord.utils.get(bot.voice_clients, guild=ctx.guild)
    if not vc or not vc.is_connected():
        if ctx.author.voice:
            try:
                vc = await ctx.author.voice.channel.connect()
            except discord.ClientException:
                return

    def after_play(error):
        fut = asyncio.run_coroutine_threadsafe(play_next(ctx), bot.loop)
        try:
            fut.result()
        except:
            pass

    source = discord.FFmpegPCMAudio(song['url'], **FFMPEG_OPTIONS)
    vc.play(source, after=after_play)
    await ctx.send(f"🎶 Now playing: **{song['title']}** — requested by {song['requester']}")

keep_alive()
bot.run(os.getenv("DISCORD_TOKEN"))
