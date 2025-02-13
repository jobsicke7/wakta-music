import discord
from discord.ext import commands
from discord import FFmpegPCMAudio
from yt_dlp import YoutubeDL
from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi
import certifi  
import logging
import asyncio
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import googleapiclient.discovery
import googleapiclient.errors
import os
import json
import re
import isodate
from discord import app_commands
from urllib.parse import urlparse, parse_qs
import random
from discord.ui import Button, View, Modal, TextInput

API_KEY = ""

MONGO_URI = ""
client = MongoClient(MONGO_URI, tls=True, tlsCAFile=certifi.where())
db = client['discord_music_bot']
player_data = db['player_data']
queue_collection = db['music_queue']
noti = db['notice']
playing = db['now_playing']
repeat_modes = {}
pause_states = {}
REPEAT_MODES = ["반복 안함", "한 곡 반복", "전체 반복", "왁타버스 모드", "이세돌 모드", "고멤 모드"]
notice_collection = db['notice']
notices = notice_collection.find()
logging.getLogger('discord.gateway').setLevel(logging.ERROR)

intents = discord.Intents.all()
activity = discord.Game(name="음악 재생")
bot = commands.Bot(command_prefix="!", intents=intents, activity=activity, status=discord.Status.idle)

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}')
    await bot.tree.sync()
    #player_data.delete_many({})
    queue_collection.delete_many({})

@bot.event
async def on_voice_state_update(member, before, after):
    for vc in bot.voice_clients:
        if vc.channel == before.channel and len(vc.channel.members) == 1:
            await vc.disconnect()
            guild_id = member.guild.id
            player_data = db['player_data'].find_one({'guild_id': member.guild.id})
            if not player_data:
                return
            channel_id = player_data['channel_id']
            message_id = player_data['message_id']
            channel = bot.get_channel(channel_id)
            message = await channel.fetch_message(message_id)
            await message.delete()
            result = db['player_data'].update_one(
                {'guild_id': guild_id},
                {'$set': {'message_id': None}}
            )
            queue_collection.delete_many({'guild_id': guild_id})
            pause_states[guild_id] = False

TARGET_CHANNEL_ID = 1313031234795868180

class AnnouncementModal(Modal):
    def __init__(self, title):
        super().__init__(title="공지 작성")
        self.title = title
        self.content_input = TextInput(label="공지 내용", style=discord.TextStyle.paragraph, required=True)
        self.add_item(self.content_input)

    async def on_submit(self, interaction: discord.Interaction):
        
        
        for notice in notices:
            guild_id = notice.get('guild_id')
            channel_id = notice.get('channel_id')
            print(f"Guild ID: {guild_id}, Channel ID: {channel_id}")
            guild = bot.get_guild(guild_id)
            channel = guild.get_channel(channel_id)

            embed = discord.Embed(title=self.title, description=self.content_input.value, color=0xffffff)
            await channel.send(embed=embed)
        
        await interaction.message.delete()
        await interaction.response.send_message("공지 작성 완료!", ephemeral=True)

class AnnouncementView(View):
    def __init__(self, message):
        super().__init__(timeout=60)
        self.message = message

    @discord.ui.button(label="네", style=discord.ButtonStyle.primary)
    async def yes_button(self, interaction: discord.Interaction, button: Button):
        modal = AnnouncementModal(title=self.message.content)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="아니요", style=discord.ButtonStyle.secondary)
    async def no_button(self, interaction: discord.Interaction, button: Button):
        await self.message.delete()
        await interaction.response.send_message("취소되었습니다.", ephemeral=True)


#[버튼]
class ButtonTypesView(discord.ui.View):
    def __init__(self, guild_id):
        super().__init__(timeout=None)
        self.guild_id = guild_id
        if guild_id not in repeat_modes:
            repeat_modes[guild_id] = 0 
        if guild_id not in pause_states:
            pause_states[guild_id] = False

        self.update_button_color()

    def update_button_color(self):
        mode = repeat_modes[self.guild_id]
        if mode == 0: # "반복 안함"
            self.repbt.style = discord.ButtonStyle.secondary
        elif mode == 1: # "한 곡 반복"
            self.repbt.style = discord.ButtonStyle.blurple
        elif mode == 2: # "전체 반복"
            self.repbt.style = discord.ButtonStyle.green
        elif mode == 3: # "셔플"
            self.repbt.style = discord.ButtonStyle.red
        elif mode == 4: # "사용자 지정"
            self.repbt.style = discord.ButtonStyle.red
        elif mode == 5: # "사용자 지정"
            self.repbt.style = discord.ButtonStyle.red
    def upd(self):
        pause = pause_states.get(self.guild_id, False)
        if pause:
            self.pausebt.emoji = "<:play:1260790356027637862>"
        else:
            self.pausebt.emoji = "<:pause:1260788624249851944>"
            

    @discord.ui.button(style=discord.ButtonStyle.danger, emoji="<:stop:1260788414840700959>")
    async def stopbt(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()

        guild_id = interaction.guild.id
        voice_client = interaction.guild.voice_client
        if voice_client and (voice_client.is_playing() or voice_client.is_paused()):
            await voice_client.disconnect()
            player_data = db['player_data'].find_one({'guild_id': interaction.guild.id})
            if not player_data:
                return
            channel_id = player_data['channel_id']
            message_id = player_data['message_id']
            channel = bot.get_channel(channel_id)
            message = await channel.fetch_message(message_id)
            await message.delete()
            result = db['player_data'].update_one(
                {'guild_id': guild_id},
                {'$set': {'message_id': None}}
            )
            queue_collection.delete_many({'guild_id': guild_id})
            pause_states[guild_id] = False
        else:
            await voice_client.disconnect()

    @discord.ui.button( style=discord.ButtonStyle.success, emoji="<:pr:1260788471220535316>")
    async def prbt(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(view=self)

    @discord.ui.button( style=discord.ButtonStyle.secondary, emoji="<:pause:1260788624249851944>")
    async def pausebt(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        guild_id = interaction.guild.id       
        voice_client = interaction.guild.voice_client
        if voice_client is None:
            return
        if voice_client.is_playing() and not pause_states.get(guild_id, False):
            voice_client.pause()
            pause_states[guild_id] = True
        elif pause_states.get(guild_id, False):
            voice_client.resume()
            pause_states[guild_id] = False
        self.upd()
        nowplay = playing.find_one({'guild_id': interaction.guild.id})
        info = nowplay['info']
        await editplayer(interaction,info)
        await interaction.edit_original_response(view=self)

    @discord.ui.button(style=discord.ButtonStyle.success, emoji="<:next:1260788515554463774>")
    async def nextbt(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(view=self)
        voice_client = interaction.guild.voice_client
        if voice_client and voice_client.is_playing():
            voice_client.stop()

    @discord.ui.button(style=discord.ButtonStyle.secondary, emoji="<:shuffle:1260792848320565320>")
    async def sufbt(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(view=self)
        guild_id = interaction.guild.id

        queue = list(queue_collection.find({"guild_id": guild_id}))

        if not queue:
            return

        random.shuffle(queue)
        queue_collection.delete_many({"guild_id": guild_id})
        queue_collection.insert_many(queue)
        info1 = playing.find_one({'guild_id': interaction.guild.id})
        info1 = info1['info']
        await editplayer(interaction,info1)

    @discord.ui.button(style=discord.ButtonStyle.secondary, emoji="<:shuffle:1260792848320565320>")
    async def repbt(self, interaction: discord.Interaction, button: discord.ui.Button):
        repeat_modes[self.guild_id] = (repeat_modes[self.guild_id] + 1) % len(REPEAT_MODES)
        new_mode = repeat_modes[self.guild_id]
        nowplay = playing.find_one({'guild_id': interaction.guild.id})
        info = nowplay['info']
        await editplayer(interaction,info)

        self.update_button_color()
        await interaction.response.edit_message(view=self)
        
        
    @discord.ui.button(style=discord.ButtonStyle.secondary, emoji="<:list:1260792716489658502>")
    async def listbt(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_id = interaction.guild.id
        queue = list(queue_collection.find({"guild_id": guild_id}))

        if not queue:
            await interaction.response.send_message("현재 대기열이 비어 있습니다.", ephemeral=True)
            return

        await interaction.response.defer()

        page = 0
        items_per_page = 10

        def create_embed(page: int):
            embed = discord.Embed(
                title="음악 대기열",
                description=f"현재 대기열입니다. (페이지 {page + 1}/{(len(queue) - 1) // items_per_page + 1})",
                color=discord.Color.blurple()
            )
            start = page * items_per_page
            end = start + items_per_page
            for index, item in enumerate(queue[start:end], start=start + 1):
                user = interaction.guild.get_member(int(item["user_id"]))
                user_name = user.display_name if user else "알 수 없음"
                embed.add_field(
                    name=f"{index}. {item['title']}",
                    value=f"요청자: {user_name}",
                    inline=False
                )
            return embed

        embed = create_embed(page)

        message = await interaction.followup.send(embed=embed)

        await message.add_reaction("⬅️")
        await message.add_reaction("➡️")
        await message.add_reaction("❌")

        def check(reaction, user):
            return (
                user == interaction.user
                and str(reaction.emoji) in ["⬅️", "➡️", "❌"]
                and reaction.message.id == message.id
            )

        while True:
            try:
                reaction, user = await bot.wait_for("reaction_add", check=check)

                if str(reaction.emoji) == "⬅️" and page > 0:
                    page -= 1
                elif str(reaction.emoji) == "➡️" and (page + 1) * items_per_page < len(queue):
                    page += 1
                elif str(reaction.emoji) == "❌":
                    await message.delete()
                    break
                else:
                    await reaction.remove(user)
                    continue
                embed = create_embed(page)
                await message.edit(embed=embed)
                await reaction.remove(user)

            except Exception as e:
                await interaction.followup.send(f"문제가 발생했습니다: {str(e)}", ephemeral=True)
                break

#[함수]

def randv(name):
    collection = db[name]
    documents = list(collection.find())
    if not documents:
        return None
    random_document = random.choice(documents)
    return random_document.get('url')


def plrd(playlist_url):
    playlist_id_match = re.search(r"list=([\w-]+)", playlist_url)
    if not playlist_id_match:
        raise ValueError("Invalid YouTube playlist URL")
    
    playlist_id = playlist_id_match.group(1)
    youtube = build("youtube", "v3", developerKey=API_KEY)
    video_ids = []
    next_page_token = None

    while True:
        response = youtube.playlistItems().list(
            part="contentDetails",
            playlistId=playlist_id,
            maxResults=50,
            pageToken=next_page_token
        ).execute()

        video_ids.extend([item["contentDetails"]["videoId"] for item in response["items"]])
        next_page_token = response.get("nextPageToken")
        
        if not next_page_token:
            break

    if not video_ids:
        raise ValueError("The playlist is empty or invalid")
    random_video_id = random.choice(video_ids)
    video_url = f"https://www.youtube.com/watch?v={random_video_id}"
    return video_url
        
def format_duration(duration: int) -> str:
    """Convert seconds to HH:MM:SS format."""
    hours = duration // 3600
    minutes = (duration % 3600) // 60
    seconds = duration % 60
    if hours > 0:
        return f"{hours:02}:{minutes:02}:{seconds:02}"
    else:
        return f"{minutes:02}:{seconds:02}"
async def editplayer(interaction,info):
    player_data = db['player_data'].find_one({'guild_id': interaction.guild.id})
    if not player_data:
        return
    channel_id = player_data['channel_id']
    message_id = player_data['message_id']
    if isinstance(interaction, discord.Interaction):
        user = interaction.user
        guild = interaction.guild
    elif isinstance(interaction, discord.ext.commands.Context):
        user = interaction.author
        guild = interaction.guild
    else:
        raise TypeError("interaction_or_context는 Interaction 또는 Context여야 합니다.")
    channel = bot.get_channel(channel_id)
    channel1 = user.voice.channel
    queue = list(queue_collection.find({"guild_id": guild.id}))
    if queue:
        nextsn = queue[0]['title']
    else:
        nextsn = "없음"
    print(nextsn)
    duration1 = info.get("duration", 0)
    duration = format_duration(duration1)
    title = info.get('title')
    url = info.get('webpage_url')
    uploader = info.get("uploader", "Unknown Uploader")
    thumbnail_url = info.get('thumbnail', None)
    if guild.id not in repeat_modes:
        repeat_modes[guild.id] = 0 
    mode = repeat_modes[guild.id]
    mode_text = REPEAT_MODES[mode]
    queue = list(queue_collection.find({"guild_id": guild.id}))
    
    embed = discord.Embed(
            title=f"{channel1.name} | 음악 재생중..",
            description=f"**[{title}]({url}) 재생중**\n{uploader}",
            color=0xFFFFFF 
        )
    embed.add_field(
            name=f"노래 길이",
            value=f"{duration}",
            inline=True
        )
    embed.add_field(
            name=f"대기 중인 곡",
            value=f"{len(queue)}",
            inline=True
        )
    embed.add_field(
            name=f"반복",
            value=f"{mode_text}",
            inline=True
        )
    embed.set_image(url=thumbnail_url)
    embed.set_footer(text=f"다음곡 : {nextsn}")

    voice_client = interaction.guild.voice_client
    player_data = db['player_data'].find_one({'guild_id': interaction.guild.id})
    if not player_data:
        return
    channel_id = player_data['channel_id']
    message_id = player_data['message_id']
    channel = bot.get_channel(channel_id)
    view = ButtonTypesView(guild.id) 
    if message_id:
        message = await channel.fetch_message(message_id)
    else:
        message = None
    if message:
        await message.edit(embed=embed, view=view)
    else:
        message = await channel.send(embed=embed, view=view)
        result = db['player_data'].update_one(
            {'guild_id': interaction.guild.id},
            {'$set': {'message_id': message.id}}
        )
async def play_next_song(interaction: discord.Interaction):
    
    next_song = queue_collection.find_one({'guild_id': interaction.guild.id})
    mode = repeat_modes[interaction.guild.id]
    nowplay = playing.find_one({'guild_id': interaction.guild.id})
    if mode == 0:
        if next_song:
            queue_collection.find_one_and_delete({'guild_id': interaction.guild.id})
            await play_music(interaction, next_song['url'])
        else:
            voice_client = interaction.guild.voice_client
            player_data = db['player_data'].find_one({'guild_id': interaction.guild.id})
            if not player_data:
                return
            channel_id = player_data['channel_id']
            message_id = player_data['message_id']
            channel = bot.get_channel(channel_id)
            message = await channel.fetch_message(message_id)
            await message.delete()
            result = db['player_data'].update_one(
                {'guild_id': interaction.guild.id},
                {'$set': {'message_id': None}}
            )
            await voice_client.disconnect()
    if mode == 1:
        await play_music(interaction, nowplay['url'])
    if mode == 2:
        await play_music(interaction, nowplay['url'])
    if mode == 3:
        if next_song:
            nowplay = queue_collection.find_one_and_delete({'guild_id': interaction.guild.id})
            await play_music(interaction, nowplay['url'])
        else:
            url1 = randv('waktaverse')
            await play_music(interaction, url1)
    if mode == 4:
        if next_song:
            nowplay = queue_collection.find_one_and_delete({'guild_id': interaction.guild.id})
            await play_music(interaction, nowplay['url'])
        else:
            url1 = randv('ise')
            await play_music(interaction, url1)
    if mode == 5:
        if next_song:
            nowplay = queue_collection.find_one_and_delete({'guild_id': interaction.guild.id})
            await play_music(interaction, nowplay['url'])
        else:
            url1 = randv('gom')
            await play_music(interaction, url1)
async def chek(link):
    parsed_url = urlparse(link)
    query_params = parse_qs(parsed_url.query)
    if "playlist" in parsed_url.path or "list" in query_params:
        return True
    return False
    
async def play_music(interaction_or_context, url: str):
    if isinstance(interaction_or_context, discord.Interaction):
        user = interaction_or_context.user
        guild = interaction_or_context.guild
        voice_channel = user.voice.channel if user.voice else None
    elif isinstance(interaction_or_context, discord.ext.commands.Context):
        user = interaction_or_context.author
        guild = interaction_or_context.guild
        voice_channel = user.voice.channel if user.voice else None
    else:
        raise TypeError("interaction_or_context는 Interaction 또는 Context여야 합니다.")
    if not voice_channel:
        return "음성 채널에 접속해주세요."
    voice_client = guild.voice_client
    if not voice_client:
        voice_client = await voice_channel.connect()
    chk = await chek(url)
    if chk:
        if voice_client is not None and voice_client.is_playing():
            ydl_opts = {
                'quiet': True,
                'extract_flat': True,
            }
            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)

            if "entries" in info:
                videos = info['entries']
                title = videos[0]['title']
                queue_items_list = []
                for info in videos:
                    queue_items = {
                        'guild_id': guild.id,
                        'guild_name': guild.name,
                        'user_id': user.id,
                        'user_name': user.display_name,
                        'title': info['title'],
                        'url': info['url'],
                        'uploader': info['channel'],
                        'duration': info['duration'],
                    }
                    queue_items_list.append(queue_items)

                if queue_items_list:
                    queue_collection.insert_many(queue_items_list)
                    return title
                info1 = playing.find_one({'guild_id': guild.id})
                info1 = info1['info']
                await editplayer(interaction_or_context,info1)

        ydl_opts = {
            'quiet': True,
            'extract_flat': True,
        }

        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        if "entries" in info:
            videos = info['entries']
            if len(videos) > 1:
                url = videos[0]['url']
                ydl_opts = {
                    "format": "bestaudio/best",
                    "noplaylist": True,
                    "quiet": True,
                    "postprocessors": [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                        'preferredquality': '320',
                    }],
                }

                with YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=False)

                streaming_url = info.get('url')
                title = info.get("title", "알 수 없는 제목")
                info2 = info
                def after_playing(error):
                    if error:
                        print(f"Error occurred: {error}")
                    asyncio.run_coroutine_threadsafe(play_next_song(interaction_or_context), bot.loop)

                before_options = '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5'
                
                voice_client.play(
                    FFmpegPCMAudio(
                        executable="ffmpeg", 
                        source=streaming_url, 
                        before_options=before_options
                    ), 
                    after=after_playing
                )
                playing1 = {
                    'guild_id': guild.id,
                    'title': info['title'],
                    'url': info['url'],
                    'info' : info
                }
                playing.update_one(
                    {"guild_id": guild.id},
                    {"$set": playing1},
                    upsert=True
                )
                queue_items_list = []
                for info in videos[1:]:
                    queue_items = {
                        'guild_id': guild.id,
                        'guild_name': guild.name,
                        'user_id': user.id,
                        'user_name': user.display_name,
                        'title': info['title'],
                        'url': info['url'],
                        'uploader': info['channel'],
                        'duration': info['duration'],
                    }
                    queue_items_list.append(queue_items)
    
                if queue_items_list:
                    queue_collection.insert_many(queue_items_list)
                await editplayer(interaction_or_context, info2)
                return title

    if not url.startswith("http://") and not url.startswith("https://"):
        url = f"ytsearch:{url}"

    if voice_client is not None and voice_client.is_playing():
        ydl_opts = {
            'quiet': True,
            'extract_flat': True,
        }
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        if "entries" in info:
            info = info['entries'][0]
        print(info)
        queue_items = {
            'guild_id': guild.id,
            'guild_name': guild.name,
            'user_id': user.id,
            'user_name': user.display_name,
            'title': info['title'],
            'url': info.get('webpage_url', info.get('url', 'URL 없음')),
            'uploader': info['channel'],
            'duration': info['duration'],
        }
        queue_collection.insert_one(queue_items)
        info1 = playing.find_one({'guild_id': guild.id})
        info1 = info1['info']
        await editplayer(interaction_or_context,info1)
        return info['title']
    

    ydl_opts = {
        "format": "bestaudio/best",
        "noplaylist": True,
        "quiet": True,
        "postprocessors": [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '320',
        }],
    }

    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    if "entries" in info:
        info = info['entries'][0]
    streaming_url = info.get('url')
    title = info.get("title", "알 수 없는 제목")

    def after_playing(error):
        if error:
            print(f"Error occurred: {error}")
        asyncio.run_coroutine_threadsafe(play_next_song(interaction_or_context), bot.loop)

    before_options = '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5'
    voice_client.play(
        FFmpegPCMAudio(
            executable="ffmpeg", 
            source=streaming_url, 
            before_options=before_options
        ), 
        after=after_playing
    )
    playing1 = {
        'guild_id': guild.id,
        'title': info['title'],
        'url': info['webpage_url'],
        'info' : info
    }
    playing.update_one(
        {"guild_id": guild.id},
        {"$set": playing1},
        upsert=True 
    )
    await editplayer(interaction_or_context, info)
    return title

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    if message.channel.id == TARGET_CHANNEL_ID:
        embed = discord.Embed(title="공지 작성", description="이 메세지에 대해 공지를 작성하시겠습니까?", color=discord.Color.blue())
        view = AnnouncementView(message)
        await message.reply(embed=embed, view=view)
    player_data = db['player_data'].find_one({'guild_id': message.guild.id})
    if not player_data:
        return
    channel_id = player_data['channel_id']
    if message.channel.id == channel_id:
        if message.author.bot:
            return
        await message.delete()
        embed = discord.Embed(title="🔎검색 중..", description='노래를 검색하고 있어요!', color=discord.Color.green())
        msg = await message.channel.send(embed=embed)
        interaction = await bot.get_context(message)
        title = await play_music(interaction,message.content)
        embed1 = discord.Embed(title="🔎검색 완료", description=f'**{title}** 곡을 지금 재생할게요!', color=discord.Color.green())
        await msg.edit(embed=embed1)
        await asyncio.sleep(3)
        await msg.delete()
@bot.tree.command(name='넘기기', description='현재 곡을 건너뛰고 다음 곡을 재생합니다.')
async def skip(interaction: discord.Interaction):
    voice_client = interaction.guild.voice_client
    if voice_client and voice_client.is_playing():
        await interaction.response.send_message("현재 곡을 건너뛰었습니다.")
        voice_client.stop()
    else:
        await interaction.response.send_message("재생 중인 곡이 없습니다.")


@bot.tree.command(name='일시정지', description='현재 음악을 일시정지하거나 다시 재생합니다.')
async def pause_or_resume(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    voice_client = interaction.guild.voice_client

    if voice_client is None:
        await interaction.response.send_message("현재 음성 채널에 연결되어 있지 않습니다.")
        return

    if voice_client.is_playing() and not pause_states.get(guild_id, False):
        voice_client.pause()
        pause_states[guild_id] = True  
        await interaction.response.send_message("⏸️ 음악이 일시정지되었습니다.")

    elif pause_states.get(guild_id, False):
        voice_client.resume()
        pause_states[guild_id] = False
        await interaction.response.send_message("▶️ 음악이 다시 재생됩니다.")

    else:
        await interaction.response.send_message("재생 중인 음악이 없습니다.")

@bot.tree.command(name='중지', description='현재 재생을 중지하고 대기열을 초기화합니다.')
async def stop(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    voice_client = interaction.guild.voice_client
    if voice_client and (voice_client.is_playing() or voice_client.is_paused()):
        await voice_client.disconnect()
        player_data = db['player_data'].find_one({'guild_id': interaction.guild.id})
        if not player_data:
            return
        channel_id = player_data['channel_id']
        message_id = player_data['message_id']
        channel = bot.get_channel(channel_id)
        message = await channel.fetch_message(message_id)
        await message.delete()
        result = db['player_data'].update_one(
            {'guild_id': guild_id},
            {'$set': {'message_id': None}}
        )
        queue_collection.delete_many({'guild_id': guild_id})
        pause_states[guild_id] = False
        await interaction.response.send_message("재생이 중지했어요!")
    else:
        await interaction.response.send_message("재생 중인 음악이 없습니다.")
        await voice_client.disconnect()

@bot.tree.command(name='재생', description='곡을 재생합니다.')
async def play(interaction: discord.Interaction, query: str):
    player_data = db['player_data'].find_one({'guild_id': interaction.guild.id})
    if not player_data:
        await interaction.response.send_message("**/등록** 명령어를 사용해 음악 플레이어를 표시할 채널을 지정해주신 후 사용해주세요.")
        return
    embed = discord.Embed(title="🔎검색 중..", description='노래를 검색하고 있어요!', color=discord.Color.green())
    await interaction.response.send_message(embed=embed)
    title = await play_music(interaction,query)
    embed1 = discord.Embed(title="🔎검색 완료", description=f'**{title}** 곡을 지금 재생할게요!', color=discord.Color.green())
    await interaction.edit_original_response(embed=embed1)


@bot.tree.command(name="대기열", description="현재 대기열을 확인합니다.")
async def show_queue(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    queue = list(queue_collection.find({"guild_id": guild_id}))

    if not queue:
        await interaction.response.send_message("현재 대기열이 비어 있습니다.", ephemeral=True)
        return

    await interaction.response.defer()

    page = 0
    items_per_page = 10

    def create_embed(page: int):
        embed = discord.Embed(
            title="음악 대기열",
            description=f"현재 대기열입니다. (페이지 {page + 1}/{(len(queue) - 1) // items_per_page + 1})",
            color=discord.Color.blurple()
        )
        start = page * items_per_page
        end = start + items_per_page
        for index, item in enumerate(queue[start:end], start=start + 1):
            user = interaction.guild.get_member(int(item["user_id"]))
            user_name = user.display_name if user else "알 수 없음"
            embed.add_field(
                name=f"{index}. {item['title']}",
                value=f"요청자: {user_name}",
                inline=False
            )
        return embed

    embed = create_embed(page)

    message = await interaction.followup.send(embed=embed)

    await message.add_reaction("⬅️")
    await message.add_reaction("➡️")
    await message.add_reaction("❌")

    def check(reaction, user):
        return (
            user == interaction.user
            and str(reaction.emoji) in ["⬅️", "➡️", "❌"]
            and reaction.message.id == message.id
        )

    while True:
        try:
            reaction, user = await bot.wait_for("reaction_add", check=check)

            if str(reaction.emoji) == "⬅️" and page > 0:
                page -= 1
            elif str(reaction.emoji) == "➡️" and (page + 1) * items_per_page < len(queue):
                page += 1
            elif str(reaction.emoji) == "❌":
                await message.delete()
                break
            else:
                await reaction.remove(user)
                continue

            embed = create_embed(page)
            await message.edit(embed=embed)
            await reaction.remove(user)

        except Exception as e:
            await interaction.followup.send(f"문제가 발생했습니다: {str(e)}", ephemeral=True)
            break
@bot.tree.command(name='셔플', description='대기열을 셔플합니다')
async def shufle(interaction: discord.Interaction):
    guild_id = interaction.guild.id

    queue = list(queue_collection.find({"guild_id": guild_id}))

    if not queue:
        return

    random.shuffle(queue)

    queue_collection.delete_many({"guild_id": guild_id})
    queue_collection.insert_many(queue)

@bot.tree.command(name='플레이어등록', description='플레이어를 설정할 채널을 등록합니다.')
async def register_channel(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    channel_id = interaction.channel.id

    existing_entry = db['player_data'].find_one({'guild_id': guild_id})
    if existing_entry:
        await interaction.response.send_message("이 서버에 이미 등록된 플레이어가 있습니다.", ephemeral=True)
        return
    db['player_data'].insert_one({
        'guild_id': guild_id,
        'channel_id': channel_id,
        'message_id': None
    })

    await interaction.response.send_message(f"플레이어가 **{interaction.channel.name}** 채널에 성공적으로 등록되었습니다.", ephemeral=True)

@bot.tree.command(name='공지채널등록', description='공지를 받을 채널을 등록합니다.')
async def register_channel1(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    channel_id = interaction.channel.id

    existing_entry = db['notice'].find_one({'guild_id': guild_id})
    if existing_entry:
        await interaction.response.send_message("이 서버에 이미 등록된 공지 채널이 있습니다.", ephemeral=True)
        return

    db['notice'].insert_one({
        'guild_id': guild_id,
        'channel_id': channel_id
    })

    await interaction.response.send_message(f"공지채널이 **{interaction.channel.name}** 채널에 성공적으로 등록되었습니다.", ephemeral=True)

@bot.tree.command(name="청소", description="특정 유저의 메시지 또는 전체 메시지를 삭제합니다.")
@app_commands.describe(user="메시지를 삭제할 유저", count="삭제할 메시지의 개수")
async def clean(interaction: discord.Interaction, user: discord.User = None, count: int = 1):
    if not interaction.user.guild_permissions.manage_messages:
        await interaction.response.send_message("이 명령을 사용하기 위한 권한이 없습니다.", ephemeral=True)
        return
    
    channel = interaction.channel
    messages_to_delete = []
    
    if user:
        async for message in channel.history(limit=100):
            if message.author == user:
                messages_to_delete.append(message)
            if len(messages_to_delete) >= count:
                break
    else:
        async for message in channel.history(limit=100):
            messages_to_delete.append(message)
            if len(messages_to_delete) >= count:
                break

    if messages_to_delete:
        try:
            await channel.delete_messages(messages_to_delete)
            await interaction.channel.send(f"{len(messages_to_delete)}개의 메시지를 삭제했습니다.", delete_after=1)
        except discord.Forbidden:
            await interaction.response.send_message("메시지를 삭제할 권한이 없습니다.", ephemeral=True)
        except discord.HTTPException:
            await interaction.response.send_message("메시지 삭제 중 오류가 발생했습니다.", ephemeral=True)
    else:
        await interaction.response.send_message("삭제할 메시지가 없습니다.", ephemeral=True)

bot.run("token")