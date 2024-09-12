import discord
from discord.ext import commands, tasks
import asyncio
import yt_dlp as youtube_dl
from youtubesearchpython import VideosSearch
import nacl
import os
import logging

# Define intents
intents = discord.Intents.default()
intents.voice_states = True
intents.message_content = True  # Enable the messages intent
intents.guild_messages = True  # Enable the guild messages intent

# Bot prefix
bot = commands.Bot(command_prefix='!', intents=intents)
voice_clients = {}
queues = {}
bot_sent_messages = {}

logging.getLogger('discord.gateway').setLevel(logging.ERROR)
logging.getLogger('discord.voice_state').setLevel(logging.ERROR)
logging.getLogger('discord.client').setLevel(logging.CRITICAL)
logging.getLogger('discord.player').setLevel(logging.ERROR)
logging.getLogger('discord.voice_client').setLevel(logging.CRITICAL)

# Define youtube-dl options
ytdl_opts = {
    'format': 'bestaudio/best',
    'quiet': True,
    'no_warnings': True,
    'extract_flat': True
}

ytdl = youtube_dl.YoutubeDL(ytdl_opts)

@tasks.loop(minutes=5)  # Check every minute
async def check_voice_channels():
    # check each voice channel the bot is connected to and disconnect the bot if it's alone using the stop function
    for guild in bot.guilds:
        for channel in guild.voice_channels:
            # check if the bot is connected to the channel
            if channel.guild.voice_client is not None:
                # check if the bot is the only one in the channel
                if len(channel.members) == 1:
                    # stop the bot aWnd clear the queue
                    await channel.guild.voice_client.disconnect()
                    queues[channel.guild.id] = []

# Event: Bot is ready
@bot.event
async def on_ready():
    print(f'{bot.user.name} has connected to Discord!')
    await bot.change_presence(activity=discord.Game(name="/play to queue a song"))
    check_voice_channels.start()  
    try:
        synced = await bot.tree.sync()
    except Exception as e:
        print(e)

# Command: Play a YouTube video
@bot.tree.command(name="play", description="Play a YouTube video")
async def play(interaction: discord.Interaction, query: str):

    if interaction.user.voice is None or interaction.user.voice.channel is None:
        await interaction.response.send_message("You are not in a voice channel.", ephemeral=True)
        return
    
    # Check if has permission for channel
    if not interaction.user.voice.channel.permissions_for(interaction.guild.me).connect:
        await interaction.response.send_message("I don't have permission to join the voice channel.", ephemeral=True)
        return

    # Check if a query is specified
    if not query:
        await interaction.response.send_message("Please specify a YouTube link or a search query.", ephemeral=True)
        return
    
    await interaction.response.send_message(f"Searching for **{query}**...")

    # Check if the query is a YouTube URL
    if query.startswith('https://www.youtube.com/') or query.startswith('https://youtu.be/'):
        url = query
        if 'playlist' in url:
            url = url
        elif '&list=' in url:
            url = url[:url.index('&list=')]
    else:
        # Search for the query on YouTube
        videosSearch = VideosSearch(query, limit=1)
        result = videosSearch.result()['result']
        if result:
            url = result[0]['link']
        else:
            await interaction.edit_original_response(content="No search results found.")
            return
        
    # Create queue for the guild if it doesn't exist
    if interaction.guild.id not in queues:
        queues[interaction.guild.id] = []

    try:
        with ytdl:
            info = ytdl.extract_info(url, download=False)
            # if playlist = True, add all songs in the playlist to the queue
            if 'entries' in info:
                for entry in info['entries']:
                    video_title = entry['title']
                    audio_url = entry['url']
                    # Add each song to the queue
                    queues[interaction.guild.id].append((audio_url, video_title))
                    print(f"Added to queue: {video_title}")
            else:
                video_title = info['title']
                audio_url = url
                # Add song to the queue
                queues[interaction.guild.id].append((audio_url, video_title))
                print(f"Added to queue: {video_title}")
    except Exception as e:
        print(e)
        await interaction.edit_original_response(content="An error occurred while processing the YouTube link.")
        return

    # Get url of youtube video thumbnail image depending on the on youtube.com or youtu.be
    if 'youtu.be' in url:
        video_id = url.split('/')[-1].split('?')[0]
    else:
        video_id = url.split('=')[-1]
    # if playlist set image to first video in playlist 
    if 'playlist' in url:
        thumbnail_url = f"https://i.ytimg.com/vi/{info['entries'][0]['id']}/mqdefault.jpg"
        description = f"**[{info['title']}]({url})**"
        fields = [{"name": "Songs", "value": len(info['entries']), "inline": True}]
    else:
        thumbnail_url = f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg"
        description = f"**[{video_title}]({url})**"
    embed=discord.Embed(title="Added to queue", description=description, color=10038562)
    embed.set_thumbnail(url=thumbnail_url)
    if 'playlist' in url:
        for field in fields:
            embed.add_field(name=field['name'], value=field['value'], inline=False)
    await interaction.edit_original_response(embed=embed, content="")
    # Add song to the queue and send a response as imbed with a thumbnail
    # queues[interaction.guild.id].append((audio_url, video_title))

    # Get the voice client for the guild
    voice_client = interaction.guild.voice_client

    # Join the user's voice channel if the bot is not already in one
    if voice_client is None:
        voice_client = await interaction.user.voice.channel.connect()
        await voice_client.guild.change_voice_state(channel=voice_client.channel, self_deaf=True)

    # If bot is not already playing, start playing
    if not voice_client.is_playing():
        await play_next(interaction.guild, voice_client, interaction.channel)

async def print_queue(ctx):
    if ctx.guild.id in queues and queues[ctx.guild.id]:
        embed = discord.Embed(title="Queue", color=discord.Color.blurple())
        queue_list = "\n".join([f"{index}. {title}" for index, (_, title) in enumerate(queues[ctx.guild.id], start=1)])
        embed.description = queue_list
        await ctx.send(embed=embed)
    else:
        await ctx.send("The queue is empty.")

# Play the next song in the queue
async def play_next(guild, voice_client, channel):
    if queues.get(guild.id):
        if queues[guild.id]:
            url, title = queues[guild.id][0]
            ffmpeg_options = {
                'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
                'options': '-vn'
            }
            
            # Define a callback function to handle queue popping after the song finishes playing
            def after_playing(error):
                if error:
                    print("Error occurred while playing:", error)
                else:
                    if queues[guild.id]:
                        queues[guild.id].pop(0)  # Remove the top item from the queue
                        asyncio.run_coroutine_threadsafe(play_next(guild, voice_client, channel), bot.loop)
            # wait for a small buffer before playing the next song
            source = discord.FFmpegOpusAudio(ytdl.extract_info(url,download=False)['url'], **ffmpeg_options)
            voice_client.play(source, after=after_playing)
            print(f"Playing: {title} in {guild.name}")
        else:
            print("Queue is empty")
    else:
        print("Queue not found for guild")

# Command: Stop playing and clear the queue
@bot.tree.command(name="stop", description="Clear the queue and leave the voice channel")
async def stop(interaction: discord.Interaction):
    if interaction.guild.voice_client is None:
        await interaction.response.send_message("I'm not in a voice channel.", ephemeral=True)
        return

    await interaction.response.send_message("Stopped playing and cleared the queue.", ephemeral=True)
    interaction.guild.voice_client.stop()
    queues[interaction.guild.id] = []
    await interaction.guild.voice_client.disconnect()


# Command: Skip the current song
@bot.tree.command(name="skip", description="Skip the current song")
async def skip(interaction: discord.Interaction):
    if interaction.guild.voice_client is None or not interaction.guild.voice_client.is_playing():
        await interaction.response.send_message("I am not currently playing anything.", ephemeral=True)
        return

    # clear the current song from the queue and play the next one
    interaction.guild.voice_client.stop()
    await interaction.response.send_message("Skipped the current song.", ephemeral=True)

# Run the bot with your token
bot.run(os.environ['DISCORD_TOKEN'])