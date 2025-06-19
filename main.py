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
guild_contexts = {} 
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
    if not ctx.author.voice or not ctx.author.voice.channel:
        return await ctx.send("❌ You're not in a voice channel.")

    vc = discord.utils.get(bot.voice_clients, guild=ctx.guild)
    
    if vc and vc.is_connected():
        if vc.channel == ctx.author.voice.channel:
            return await ctx.send("✅ I'm already in your voice channel.")
        else:
            return await ctx.send(f"❌ I'm already connected in **{vc.channel}**.")

    await ctx.author.voice.channel.connect()
    await ctx.send(f"✅ Joined **{ctx.author.voice.channel}**.")



# Global dictionary to store the first user who used the bot per guild
guild_owners = {}

@bot.command()
async def leave(ctx):
    guild_id = ctx.guild.id

    # Only set owner if not already set
    if guild_id not in guild_owners:
        guild_owners[guild_id] = ctx.author.id

    # Check if the author is the first user who used the bot
    if ctx.author.id != guild_owners[guild_id]:
        return await ctx.send("❌ Only the user who started the bot can make it leave the channel.")

    vc = discord.utils.get(bot.voice_clients, guild=ctx.guild)

    if vc and vc.is_connected():
        await vc.disconnect()
        await ctx.send("👋 Left the voice channel.")
        # Optionally clear ownership when leaving
        guild_owners.pop(guild_id, None)
    else:
        await ctx.send("❌ I'm not connected to any voice channel in this server.")



@bot.command(name="p", aliases=["play"])
async def play(ctx, *, search: str):
    guild_id = ctx.guild.id
    guild_contexts[guild_id] = ctx  # Track last context per guild

    # ✅ Set owner if first use in this guild
    if guild_id not in guild_owners:
        guild_owners[guild_id] = ctx.author.id

    # Cancel leave task if music is playing again
    task = leave_tasks.get(guild_id)
    if task and not task.done():
        task.cancel()

    # Check if user is in a voice channel
    if not ctx.author.voice or not ctx.author.voice.channel:
        return await ctx.send("❌ You're not in a voice channel.")

    # Connect to voice if not already connected
    vc = discord.utils.get(bot.voice_clients, guild=ctx.guild)
    if not vc or not vc.is_connected():
        vc = await ctx.author.voice.channel.connect()
    elif vc.channel != ctx.author.voice.channel:
        return await ctx.send("❌ I'm already playing music in another voice channel.")

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





# Dictionary to track owner and skip votes per guild
guild_owners = {}
skip_votes = {}

@bot.command()
async def skip(ctx):
    guild_id = ctx.guild.id
    vc = discord.utils.get(bot.voice_clients, guild=ctx.guild)

    if not vc or not vc.is_playing():
        return await ctx.send("❌ Nothing is playing.")

    # Register owner if not yet
    if guild_id not in guild_owners:
        guild_owners[guild_id] = ctx.author.id

    # Allow owner to skip instantly
    if ctx.author.id == guild_owners[guild_id]:
        vc.stop()
        skip_votes[guild_id] = set()  # reset votes
        return await ctx.send("⏭️ Skipping current song (by owner).")

    # Voting required
    voice_channel = ctx.author.voice.channel if ctx.author.voice else None
    if not voice_channel or voice_channel != vc.channel:
        return await ctx.send("❌ You must be in the same voice channel as the bot to vote.")

    # Track votes
    if guild_id not in skip_votes:
        skip_votes[guild_id] = set()

    if ctx.author.id in skip_votes[guild_id]:
        return await ctx.send("🗳️ You've already voted to skip.")

    skip_votes[guild_id].add(ctx.author.id)

    # Count human users in channel
    total_listeners = len([m for m in voice_channel.members if not m.bot])
    current_votes = len(skip_votes[guild_id])

    if current_votes / total_listeners >= 0.5:
        vc.stop()
        skip_votes[guild_id] = set()
        await ctx.send("✅ Vote passed! Skipping the song.")
    else:
        await ctx.send(f"🗳️ {current_votes}/{total_listeners} voted to skip (50% needed).")



@bot.command()
async def queue(ctx):
    guild_id = ctx.guild.id
    queue = get_queue(guild_id)

    if queue.empty():
        await ctx.send("📭 Queue is empty.")
        return

    # Safely copy the queue contents for display
    try:
        queue_list = list(queue._queue)  # still technically protected, but common in Discord bots
    except Exception as e:
        return await ctx.send(f"⚠️ Failed to read the queue: `{e}`")

    msg = "\n".join([f"{i+1}. {item['title']}" for i, item in enumerate(queue_list)])
    await ctx.send(f"📜 Queue for **{ctx.guild.name}**:\n{msg}")


@bot.command()
async def nowplaying(ctx):
    current = now_playing.get(ctx.guild.id)
    if current:
        await ctx.send(f"🎧 Now playing: **{current['title']}** — requested by {current['requester']}")
    else:
        await ctx.send("❌ Nothing is playing right now.")


# Plays the current track for a guild
async def play_current(ctx, song):
    guild_id = ctx.guild.id
    vc = ctx.voice_client

    if not vc or not vc.is_connected():
        return await ctx.send("❌ Bot is not connected to a voice channel.")

    url = song["url"]
    title = song["title"]
    requester = song["requester"]

    source = discord.FFmpegPCMAudio(url, **FFMPEG_OPTIONS)

    def after_playing(error):
        coro = disconnect_if_idle(vc, guild_id)
        fut = asyncio.run_coroutine_threadsafe(coro, bot.loop)
        try:
            fut.result()
        except:
            pass

    vc.play(source, after=after_playing)
    await ctx.send(f"🎶 Now playing: **{title}** — requested by {requester}")


# Automatically disconnect after being idle
async def disconnect_if_idle(vc, guild_id, delay: int = 10):
    await asyncio.sleep(delay)
    if not vc.is_playing():
        if vc.is_connected():
            await vc.disconnect()
            channel = vc.channel
            if channel and channel.guild:
                text_channels = channel.guild.text_channels
                if text_channels:
                    await text_channels[0].send("👋 Left due to inactivity.")
        now_playing[guild_id] = None


@bot.command()
async def pause(ctx):
    guild_id = ctx.guild.id
    owner_id = guild_owners.get(guild_id)

    if ctx.author.id != owner_id:
        return await ctx.send("❌ Only the original user who started the bot can pause the music.")

    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.pause()
        await ctx.send("⏸️ Paused.")
    else:
        await ctx.send("❌ Nothing is playing.")



@bot.command()
async def resume(ctx):
    guild_id = ctx.guild.id
    owner_id = guild_owners.get(guild_id)

    # Only the original user who used 'play' can resume
    if owner_id and ctx.author.id != owner_id:
        return await ctx.send("❌ Only the user who started the bot can resume the music.")

    # Ensure bot is connected and paused
    if ctx.voice_client and ctx.voice_client.is_paused():
        ctx.voice_client.resume()
        await ctx.send("▶️ Resumed.")
    else:
        await ctx.send("❌ Nothing to resume.")



@bot.command()
async def stop(ctx):
    guild_id = ctx.guild.id
    owner_id = guild_owners.get(guild_id)

    # Check if author is in a voice channel
    if not ctx.author.voice or not ctx.author.voice.channel:
        return await ctx.send("❌ You must be in a voice channel to use this command.")

    # Ownership check
    if owner_id and ctx.author.id != owner_id:
        return await ctx.send("❌ Only the user who started the music can stop it.")

    vc = discord.utils.get(bot.voice_clients, guild=ctx.guild)
    if vc and vc.is_playing():
        autoplay_enabled[guild_id] = False
        vc.stop()
        await ctx.send("⏹️ Playback stopped.")
    else:
        await ctx.send("❌ Nothing is playing.")



@bot.command()
async def clear(ctx):
    guild_id = ctx.guild.id
    owner_id = guild_owners.get(guild_id)

    # Check if author is in a voice channel
    if not ctx.author.voice or not ctx.author.voice.channel:
        return await ctx.send("❌ You must be in a voice channel to use this command.")

    # Check ownership
    if owner_id and ctx.author.id != owner_id:
        return await ctx.send("❌ Only the user who started the music session can clear the queue.")

    # Clear the queue
    queue = get_queue(guild_id)
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
async def play_next(ctx=None):
    for guild_id, queue in song_queue.items():
        ctx = guild_contexts.get(guild_id)
        if ctx is None:
            continue

        queue = get_queue(guild_id)
        if queue.empty():
            now_playing[guild_id] = None

            async def delayed_leave():
                await asyncio.sleep(300)  # 5 minutes
                vc = discord.utils.get(bot.voice_clients, guild=ctx.guild)
                if vc and vc.is_connected():
                    await vc.disconnect()
                    await ctx.send("👋 Left voice channel after 5 minutes of inactivity.")
                # Clear ownership
                guild_owners.pop(guild_id, None)

            task = asyncio.create_task(delayed_leave())
            leave_tasks[guild_id] = task
            return

        # Ensure autoplay is enabled for this guild
        if not autoplay_enabled.get(guild_id, True):
            return

        # Pop the next song
        song = await queue.get()
        now_playing[guild_id] = {
            "title": song.get("title"),
            "url": song.get("webpage_url"),
            "duration": song.get("duration"),
            "thumbnail": song.get("thumbnail"),
            "requester": song.get("requester"),
        }

        vc = discord.utils.get(bot.voice_clients, guild=ctx.guild)
        if not vc or not vc.is_connected():
            return  # Skip if bot somehow left

        source = discord.FFmpegPCMAudio(song["url"], **FFMPEG_OPTIONS)

        def after_play(error):
            if error:
                print(f"Error during playback: {error}")
            bot.loop.create_task(play_next(ctx))

        vc.play(source, after=after_play)
        await ctx.send(f"🎶 Now playing: **{song['title']}** — requested by {song['requester']}")



bot.run(os.getenv("DISCORD_TOKEN"))



