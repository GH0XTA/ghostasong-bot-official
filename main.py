import discord
from discord.ext import commands
import yt_dlp
import asyncio
import os
from keep_alive import keep_alive
from dotenv import load_dotenv
import nacl


load_dotenv()

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='g!', intents=intents)
bot.remove_command("help")

song_queue = {}
now_playing = {}
autoplay_enabled = {}
leave_tasks = {}
guild_owners = {}
skip_votes = {}

YDL_OPTIONS = {'format': 'bestaudio', 'noplaylist': 'True', 'cookiefile': 'cookies.txt'}
FFMPEG_OPTIONS = {'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5', 'options': '-vn'}

def get_queue(guild_id):
    if guild_id not in song_queue:
        song_queue[guild_id] = asyncio.Queue()
    return song_queue[guild_id]

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")

@bot.command()
async def join(ctx):
    if ctx.author.voice:
        vc = discord.utils.get(bot.voice_clients, guild=ctx.guild)
        if vc and vc.is_connected():
            return await ctx.send("✅ Already connected.")
        vc = await ctx.author.voice.channel.connect()
        guild_owners[ctx.guild.id] = ctx.author.id
        await ctx.send("✅ Joined the voice channel.")
    else:
        await ctx.send("❌ You're not in a voice channel.")

@bot.command()
async def leave(ctx):
    if ctx.guild.id in guild_owners and ctx.author.id != guild_owners[ctx.guild.id]:
        return await ctx.send("❌ Only the session owner can make me leave.")
    if ctx.voice_client:
        await ctx.voice_client.disconnect()
        guild_owners.pop(ctx.guild.id, None)
        await ctx.send("👋 Left the voice channel.")
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
                return await ctx.send("❌ Failed to join voice channel.")
        else:
            return await ctx.send("❌ You're not in a voice channel.")

    with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
        info = ydl.extract_info(search if "youtube.com" in search else f"ytsearch:{search}", download=False)
        if 'entries' in info:
            info = info['entries'][0]

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
        return await ctx.send("❌ No active session.")

    if ctx.author.id == guild_owners[guild_id]:
        ctx.voice_client.stop()
        return await ctx.send("⏭️ Skipped by owner.")

    voters = skip_votes.setdefault(guild_id, set())
    if ctx.author.id in voters:
        return await ctx.send("❌ You've already voted.")
    voters.add(ctx.author.id)

    members = [m for m in ctx.voice_client.channel.members if not m.bot]
    if len(voters) >= max(1, len(members) // 2):
        ctx.voice_client.stop()
        skip_votes[guild_id] = set()
        await ctx.send("⏭️ Vote passed.")
    else:
        await ctx.send(f"🗳️ Voted to skip. ({len(voters)}/{max(1, len(members) // 2)} needed)")

@bot.command()
async def queue(ctx):
    queue = get_queue(ctx.guild.id)
    if queue.empty():
        return await ctx.send("📭 Queue is empty.")
    queue_list = list(queue._queue)
    msg = "\n".join([f"{i+1}. {item['title']}" for i, item in enumerate(queue_list)])
    await ctx.send(f"📜 Queue:\n{msg}")

@bot.command()
async def nowplaying(ctx):
    song = now_playing.get(ctx.guild.id)
    if song:
        await ctx.send(f"🎧 Now playing: **{song['title']}** — requested by {song['requester']}")
    else:
        await ctx.send("❌ Nothing is playing.")

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
        return await ctx.send("❌ Only the owner can stop playback.")
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
        return await ctx.send("❌ Only the owner can clear queue.")
    get_queue(ctx.guild.id)._queue.clear()
    await ctx.send("🧹 Queue cleared.")

@bot.command()
async def help(ctx):
    embed = discord.Embed(title="🎵 Music Bot Help", color=discord.Color.green())
    embed.add_field(name="g!play [song]", value="Add song to queue", inline=False)
    embed.add_field(name="g!skip", value="Vote to skip song", inline=False)
    embed.add_field(name="g!stop", value="Stop playback", inline=False)
    embed.add_field(name="g!pause / g!resume", value="Pause/Resume", inline=False)
    embed.add_field(name="g!queue", value="Show song queue", inline=False)
    embed.add_field(name="g!leave", value="Leave voice channel", inline=False)
    embed.add_field(name="g!clear", value="Clear queue", inline=False)
    await ctx.send(embed=embed)

async def play_next(ctx):
    guild_id = ctx.guild.id
    queue = get_queue(guild_id)

    if queue.empty():
        now_playing[guild_id] = None

        async def delayed_leave():
            await asyncio.sleep(300)
            vc = discord.utils.get(bot.voice_clients, guild=ctx.guild)
            if queue.empty() and vc and vc.is_connected():
                await vc.disconnect()
                guild_owners.pop(guild_id, None)
                await ctx.send("👋 Left due to inactivity.")

        leave_tasks[guild_id] = asyncio.create_task(delayed_leave())
        return

    if not autoplay_enabled.get(guild_id, True):
        return

    song = await queue.get()
    now_playing[guild_id] = song

    vc = discord.utils.get(bot.voice_clients, guild=ctx.guild)
    if not vc:
        try:
            if ctx.author.voice:
                vc = await ctx.author.voice.channel.connect()
        except discord.ClientException:
            return

    def after_play(error):
        fut = asyncio.run_coroutine_threadsafe(play_next(ctx), bot.loop)
        try:
            fut.result()
        except Exception as e:
            print(f"Error in playback: {e}")

    source = discord.FFmpegPCMAudio(song["url"], **FFMPEG_OPTIONS)
    vc.play(source, after=after_play)
    await ctx.send(f"🎶 Now playing: **{song['title']}** — requested by {song['requester']}")

keep_alive()
bot.run(os.getenv("DISCORD_TOKEN"))
