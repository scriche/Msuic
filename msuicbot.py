import discord
from discord.ext import commands
import asyncio
import yt_dlp as youtube_dl
import nacl
import os
import logging
import random

# Define intents
intents = discord.Intents.default()
intents.voice_states = True
intents.message_content = True
intents.guild_messages = True

# Bot prefix
bot = commands.Bot(command_prefix='!', intents=intents)
queues = {}

# Suppress discord.py logging
for logger_name in ['discord.gateway', 'discord.voice_state', 'discord.client', 'discord.player', 'discord.voice_client']:
    logging.getLogger(logger_name).setLevel(logging.ERROR)

# Define youtube-dl options
ytdl_opts = {
    'format': 'bestaudio/best',
    'quiet': True,
    'no_warnings': True,
    'extract_flat': True,
    'cachedir': False,
}
ytdl = youtube_dl.YoutubeDL(ytdl_opts)

@bot.event
async def on_ready():
    print(f'{bot.user.name} has connected to Discord!')
    await bot.change_presence(activity=discord.Game(name="Music"))
    try:
        await bot.tree.sync()
    except Exception as e:
        print(f"Error syncing commands: {e}")

@bot.tree.command(name="play", description="Play a YouTube video")
async def play(interaction: discord.Interaction, query: str):
    msg = f"Searching for **{query}**..."
    await queue_song(interaction, query, msg)

async def queue_song(interaction, query, msg):
    if not (interaction.user.voice and interaction.user.voice.channel):
        await interaction.response.send_message("You are not in a voice channel.", ephemeral=True)
        return
    
    if not interaction.user.voice.channel.permissions_for(interaction.guild.me).connect:
        await interaction.response.send_message("I don't have permission to join the voice channel.", ephemeral=True)
        return

    if not query:
        await interaction.response.send_message("Please specify a YouTube link or a search query.", ephemeral=True)
        return

    await interaction.response.send_message(msg)

    url = None
    if query.startswith(('https://www.youtube.com/', 'https://youtu.be/')):
        url = query
        if '&list=' in url and 'playlist' not in url:
            url = url.split('&list=')[0]
    else:
        try:
            search_results = ytdl.extract_info(f"ytsearch:{query}", download=False)
            if 'entries' in search_results and search_results['entries']:
                url = search_results['entries'][0]['url']
            else:
                await interaction.edit_original_response(content="No search results found.")
                return
        except Exception as e:
            print(f"Search error: {e}")
            await interaction.edit_original_response(content="Failed to search YouTube.")
            return

    queues.setdefault(interaction.guild.id, [])

    try:
        info = ytdl.extract_info(url, download=False)
    except Exception as e:
        print(f"YT-DLP extract_info error: {e}")
        await interaction.edit_original_response(content="An error occurred while processing the YouTube link.")
        return

    if 'entries' in info:
        for idx, entry in enumerate(info['entries']):
            try:
                await interaction.edit_original_response(content=f"Adding songs to the queue... {idx + 1} / {len(info['entries'])}")
                audio_info = ytdl.extract_info(entry['url'], download=False)
                audio_url = audio_info['url']
                queues[interaction.guild.id].append((audio_url, entry['title']))
                print(f"Added to queue: {entry['title']}")
            except Exception as e:
                print(f"Error adding song: {e}")
                continue
    else:
        audio_url = info['url']
        queues[interaction.guild.id].append((audio_url, info['title']))
        print(f"Added to queue: {info['title']}")

    if 'youtu.be' in url:
        video_id = url.split('/')[-1].split('?')[0]
    else:
        video_id = url.split('v=')[-1].split('&')[0]

    embed = discord.Embed(title="Added to queue", color=10038562)
    if 'entries' in info:
        thumbnail_url = f"https://i.ytimg.com/vi/{info['entries'][0]['id']}/mqdefault.jpg"
        embed.description = f"**[{info['title']}]({url})**"
        embed.add_field(name="Songs", value=str(len(info['entries'])), inline=False)
    else:
        thumbnail_url = f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg"
        embed.description = f"**[{info['title']}]({url})**"

    embed.set_thumbnail(url=thumbnail_url)
    await interaction.edit_original_response(embed=embed, content="")

    voice_client = interaction.guild.voice_client
    if voice_client is None:
        try:
            voice_client = await interaction.user.voice.channel.connect()
            await voice_client.guild.change_voice_state(channel=voice_client.channel, self_deaf=True)
        except Exception as e:
            print(f"Connection error: {e}")
            return

    if not voice_client.is_playing():
        await play_next(interaction.guild, voice_client, interaction.channel)

async def play_next(guild, voice_client, channel):
    if not queues.get(guild.id):
        return

    audio_url, title = queues[guild.id][0]
    ffmpeg_options = {
        'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
        'options': '-vn -b:a 96k -f opus',
    }

    def after_playing(error):
        if error:
            print(f"Error during playback: {error}")
        if queues[guild.id].__len__() > 1:
            queues[guild.id].pop(0)
        asyncio.run_coroutine_threadsafe(play_next(guild, voice_client, channel), bot.loop)

    try:
        source = discord.FFmpegOpusAudio(audio_url, **ffmpeg_options)
        voice_client.play(source, after=after_playing)
        print(f"Playing: {title} in {guild.name}")
    except Exception as e:
        print(f"Error playing audio: {e}")

@bot.tree.command(name="stop", description="Clear the queue and leave the voice channel")
async def stop(interaction: discord.Interaction):
    voice_client = interaction.guild.voice_client
    if voice_client is None:
        await interaction.response.send_message("I'm not in a voice channel.", ephemeral=True)
        return

    queues[interaction.guild.id] = []
    voice_client.stop()
    await voice_client.disconnect()
    await interaction.response.send_message("Stopped playing and cleared the queue.", ephemeral=True)

@bot.tree.command(name="skip", description="Skip the current song")
async def skip(interaction: discord.Interaction):
    voice_client = interaction.guild.voice_client
    if voice_client is None or not voice_client.is_playing():
        await interaction.response.send_message("I am not currently playing anything.", ephemeral=True)
        return

    voice_client.stop()
    await interaction.response.send_message("Skipped the current song.", ephemeral=True)

@bot.tree.command(name="gaming", description="Its gaming time")
async def gaming(interaction: discord.Interaction):
    playlist_url = "https://www.youtube.com/playlist?list=PL_VhV5m_X3BK-j1rqyOG5j7FraqSEIxVw"
    msg = "**It's Gaming Time**..."
    try:
        info = ytdl.extract_info(playlist_url, download=False)
        if 'entries' in info:
            entry = random.choice(info['entries'])
            url = entry['url']
            await queue_song(interaction, url, msg)
    except Exception as e:
        print(f"Gaming command error: {e}")
        await interaction.response.send_message("Failed to load gaming playlist.", ephemeral=True)

@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot:
        return

    voice_client = member.guild.voice_client
    if voice_client and len(voice_client.channel.members) == 1:
        print(f"Disconnecting from {voice_client.channel.name} in {member.guild.name}")
        await voice_client.disconnect()
        queues.pop(member.guild.id, None)

bot.run(os.getenv("DISCORD_TOKEN"))
