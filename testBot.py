import discord
from discord.ext import commands
import yt_dlp
import asyncio
from dotenv import load_dotenv
import os

load_dotenv()
token = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True          # 메시지 읽기 권한 필요!
bot = commands.Bot(command_prefix='!', intents=intents)

music_queue = []
current_song = None
is_playing = False

@bot.event
async def on_ready():
    print(f"✅ 로그인 완료: {bot.user}")
    
async def play_music(ctx):
    global is_playing, current_song
    
    if not music_queue:
        is_playing = False
        current_song = None
        return
    
    is_playing = True
    current_song, url = music_queue.pop(0)
    
    vc = ctx.voice_client
    if not vc or not vc.is_connected():
        if ctx.author.voice:
            channel = ctx.author.voice.channel
            vc = await channel.connect()
        else:
            await ctx.send("음성 채널에 연결할 수 없습니다.")
            is_playing = False
            return
        
    vc.play(discord.FFmpegPCMAudio(url, before_options='-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5', options='-vn -loglevel quiet -bufsize 512k'), after=lambda e: asyncio.run_coroutine_threadsafe(play_music(ctx), bot.loop))
 
        
@bot.command()
async def 재생(ctx, *, 검색어):
    global music_queue, is_playing
    
    if not ctx.author.voice:
        await ctx.send(" 먼저 음성 채널에 접속해주세요.")
        return
    
    def fetch_info():
        ydl_opts = {
            'format': 'bestaudio/best',
            'quiet': True,
            'default_search': 'ytsearch',
            'noplaylist': True,
            'extract_flat': False,
            'forceurl': True,
            'cachedir': False,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(f"ytsearch:{검색어}", download=False)['entries'][0]
    
    info = await asyncio.to_thread(lambda: fetch_info())
    url = info['url']
    title = info['title']
    music_queue.append((title, url))
        
    await ctx.send(f" 큐에 추가됨: **{title}**")
    
    if not is_playing:
        await play_music(ctx)
        
@bot.command()
async def 현재곡(ctx):
    if current_song:
        await ctx.send(f"지금 재생 중인 곡: **{current_song}**")
    else:
        await ctx.send("현재 재생 중인 노래가 없습니다.")
        
@bot.command()
async def 목록(ctx):
    if music_queue:
        message = "대기 중인 노래 목록:\n"
        for i, (title, _) in enumerate(music_queue):
            message += f"{i+1}. {title}\n"
        await ctx.send(message)
    else:
        await ctx.send("재생 대기 중인 노래가 없습니다.")   
   
@bot.command()
async def 스킵(ctx):
    vc = ctx.voice_client
    if not vc or not vc.is_playing():
        await ctx.send("현재 재생 중인 음악이 없습니다.")
        return

    await ctx.send(f"⏭️  **{current_song}** 을(를) 스킵합니다.")
    vc.stop()
    
    await play_music(ctx)
        
@bot.command()
async def 종료(ctx):
    if ctx.voice_client:
        await ctx.voice_client.disconnect()
        music_queue.clear()
        await ctx.send("봇이 음성 채널에서 나갔습니다.")
    else:
        await ctx.send("봇이 음성 채널에 없습니다.")
        
        
bot.run(token)