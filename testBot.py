###############################################################################
#   Imports & Environment
###############################################################################

from collections import defaultdict
import json
import pathlib
from typing import List, Optional, Tuple
from discord import Interaction, app_commands
import discord
from discord.ext import commands
import yt_dlp
import asyncio
from dotenv import load_dotenv
import os

load_dotenv()
token: str | None = os.getenv("DISCORD_TOKEN")
if not token:
    raise RuntimeError("DISCORD_TOKEN not found in environment / .env file")

intents = discord.Intents.default()
intents.message_content = True          # 메시지 읽기 권한 필요
intents.voice_states = True             # on_voice_state_update 를 위해 필요

bot = commands.Bot(command_prefix='!', intents=intents)

###############################################################################
#   Auto‑Leave 설정 (길드별)
###############################################################################

CFG_FILE = pathlib.Path("auto_leave.json")
auto_leave: dict[int, bool] = defaultdict(lambda: True)  # true=기본 on
AUTO_DISCONNECT_SEC = 10 # 봇 혼자 남은 뒤 퇴장까지 유예 시간(초)

def load_settings() -> None:
    if CFG_FILE.exists():
        with CFG_FILE.open() as f:
            auto_leave.update({int(k): v for k, v in json.load(f).items()})

def save_settings() -> None:
    with CFG_FILE.open("w") as f:
        json.dump(auto_leave, f)

###############################################################################
#   /autoleave on|off  (관리자 전용 슬래시 명령)
###############################################################################

class Admin(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        
    @app_commands.command(name="autoleave", description="봇 혼자 남으면 퇴장 기능을 켜거나 끕니다.")
    @app_commands.describe(mode="on 또는 off")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def autoleave(self, interaction: Interaction, mode: str):
        mode = mode.lower()
        if mode not in ("on", "off"):
            await interaction.response.send_message("사용법: /autoleave on|off", ephemeral=True)
            return
        
        enabled = mode == "on"
        auto_leave[interaction.guild_id] = enabled
        save_settings()
        state = "활성화" if enabled else "비활성화"
        await interaction.response.send_message(f"✅ ‘혼자 남으면 퇴장’ 기능이 **{state}**되었습니다.", ephemeral=True)
        
###############################################################################
#   Music Queue / Playback
###############################################################################        

#music_queue = []
music_queue: List[Tuple[str, str]] = [] # (title, url)
current_song = None
is_playing = False

async def ensure_voice(ctx: commands.Context) -> Optional[discord.VoiceClient]:
    """유저가 있는 채널로 연결하거나 기존 연결 반환"""
    vc = ctx.voice_client
    if vc and vc.is_connected():
        return vc
    if not ctx.author.voice:
        await ctx.send("먼저 음성 채널에 접속해주세요.")
        return None
    channel = ctx.author.voice.channel
    return await channel.connect()
 
async def play_music(ctx: commands.context):
    global is_playing, current_song
    
    if not music_queue:
        is_playing = False
        current_song = None
        return
    
    is_playing = True
    current_song, url = music_queue.pop(0)
    
    vc = await ensure_voice(ctx)
    if not vc:
        is_playing = False
        return
    
    def _after(_: Optional[Exception]):
        fut = asyncio.run_coroutine_threadsafe(play_music(ctx), bot.loop)
        try:
            fut.result()
        except Exception:
            pass
        
    ff_opts = {
        "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
        "options": "-vn -loglevel quiet -bufsize 512k",
    }
    
    try:
        audio = discord.FFmpegPCMAudio(url, **ff_opts)
        vc.play(audio, after=_after)
        await ctx.send(f"🎶 지금 재생 중: **{current_song}**")
    except Exception as e:
        await ctx.send(f"⚠️ 음악 재생에 실패했습니다: `{e}`")
        is_playing = False
        current_song = None
        # 다음 곡 재생 시도 (큐가 남아 있다면)
        if music_queue:
            await play_music(ctx)
    
    # 25..7.18 오류가 나서 코드 수정
    # vc.play(discord.FFmpegPCMAudio(url, **ff_opts), after=_after)
    # await ctx.send(f"🎶 지금 재생 중: **{current_song}**")
    
    # 기존 코드
    # vc = ctx.voice_client
    # if not vc or not vc.is_connected():
    #     if ctx.author.voice:
    #         channel = ctx.author.voice.channel
    #         vc = await channel.connect()
    #     else:
    #         await ctx.send("음성 채널에 연결할 수 없습니다.")
    #         is_playing = False
    #         return
        
    # vc.play(discord.FFmpegPCMAudio(url, before_options='-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5', options='-vn -loglevel quiet -bufsize 512k'), after=lambda e: asyncio.run_coroutine_threadsafe(play_music(ctx), bot.loop))
 
def fetch_info_sync(query: str):
    """yt‑dlp 를 비동기로 호출해 YouTube 오디오 URL 가져오기"""
    ydl_opts = {
       "format": "bestaudio[ext=m4a]/bestaudio/best",
       "quiet": True,
       "default_search": "ytsearch",
       "noplaylist": True,
       "extract_flat": False,
       "forceurl": True,
       "cachedir": False,
       "no_warnings": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(f"ytsearch:{query}", download=False)["entries"][0]
        return info["title"], info["url"]
     
async def fetch_info(query: str):
    return await asyncio.to_thread(fetch_info_sync, query)
 
###############################################################################
#   Bot Commands (prefix '!')
###############################################################################

@bot.command(name="재생")
async def play_cmd(ctx: commands.Context, *, 검색어: str):
    global is_playing

    try:
        # title, url = await asyncio.to_thread(fetch_info, 검색어)
        title, url = await fetch_info(검색어)
    except Exception:
        await ctx.send("해당 영상을 재생할 수 없습니다. 다른 검색어를 시도해주세요.")
        return

    music_queue.append((title, url))
    await ctx.send(f"🎵 큐에 추가됨: **{title}**")

    if not is_playing:
        await play_music(ctx)

@bot.command(name="현재곡")
async def nowplaying(ctx: commands.Context):
    if current_song:
        await ctx.send(f"지금 재생 중인 곡: **{current_song}**")
    else:
        await ctx.send("현재 재생 중인 노래가 없습니다.")


@bot.command(name="목록")
async def queue_list(ctx: commands.Context):
    if music_queue:
        lines = ["대기 중인 노래 목록:"]
        lines += [f"{i+1}. {title}" for i, (title, _) in enumerate(music_queue)]
        await ctx.send("\n".join(lines))
    else:
        await ctx.send("재생 대기 중인 노래가 없습니다.")


@bot.command(name="스킵")
async def skip(ctx: commands.Context):
    vc = ctx.voice_client
    if not vc or not vc.is_playing():
        await ctx.send("현재 재생 중인 음악이 없습니다.")
        return
    await ctx.send(f"⏭️  **{current_song}** 을(를) 스킵합니다.")
    vc.stop()


@bot.command(name="종료")
async def stop(ctx: commands.Context):
    if ctx.voice_client:
        await ctx.voice_client.disconnect()
        music_queue.clear()
        await ctx.send("봇이 음성 채널에서 나갔습니다.")
    else:
        await ctx.send("봇이 음성 채널에 없습니다.")


@bot.command(name="명령어")
async def help_cmd(ctx: commands.Context):
    await ctx.send(
        """🛠️ **사용 가능한 명령어 목록:**\n"""
        "🎵 `!재생 [검색어]` - 유튜브에서 노래를 검색하여 재생\n"
        "📃 `!목록` - 현재 대기열에 있는 노래 목록 표시\n"
        "🎧 `!현재곡` - 지금 재생 중인 노래 정보\n"
        "⏭️ `!스킵` - 현재 곡 스킵\n"
        "🛑 `!종료` - 봇이 음성 채널에서 나가고 대기열 초기화\n"
        "❓ `!명령어` - 이 도움말\n"
    )

###############################################################################
#   Auto‑Leave Event
###############################################################################

@bot.event
async def on_voice_state_update(member: discord.Member, before, after):
    vc = discord.utils.get(bot.voice_clients, guild=member.guild)
    if not vc or vc.channel != before.channel:
        return
    if auto_leave[member.guild.id] and len(vc.channel.members) == 1:
        await asyncio.sleep(AUTO_DISCONNECT_SEC)
        if len(vc.channel.members) == 1:
            await vc.disconnect(force=True)

###############################################################################
#   Bot Lifecycle
###############################################################################

@bot.event
async def on_ready():
    print(f"✅ 로그인 완료: {bot.user} (ID: {bot.user.id})")


async def setup_hook():
    await bot.add_cog(Admin(bot))
    await bot.tree.sync()

bot.setup_hook = setup_hook

if __name__ == "__main__":
    load_settings()
    bot.run(token)   
    

# @bot.command()
# async def 재생(ctx, *, 검색어):
#     global music_queue, is_playing
    
#     if not ctx.author.voice:
#         await ctx.send(" 먼저 음성 채널에 접속해주세요.")
#         return
    
#     def fetch_info(query):
#         ydl_opts = {
#             'format': 'bestaudio[ext=m4a]/bestaudio/best',
#             'quiet': True,
#             'default_search': 'ytsearch',
#             'noplaylist': True,
#             'extract_flat': False,
#             'forceurl': True,
#             'cachedir': False,
#             'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
#             'no_warnings': True,
#         }
        
#         with yt_dlp.YoutubeDL(ydl_opts) as ydl:
#             try:
#                 return ydl.extract_info(f"ytsearch:{query}", download=False)['entries'][0]
#             except Exception:
#                 return None
            
    
#     info = await asyncio.to_thread(lambda: fetch_info(검색어))
    
#     # 재시도 로직
#     if not info or 'url' not in info:
#         await ctx.send("해당 영상을 재생할 수 없습니다. 다른 검색어를 시도해주세요.")
#         return
        
    
#     url = info['url']
#     # title = info['title']
#     title = info.get('title', '제목없음')
#     music_queue.append((title, url))
        
#     await ctx.send(f" 큐에 추가됨: **{title}**")
    
#     if not is_playing:
#         await play_music(ctx)
        
# @bot.command()
# async def 현재곡(ctx):
#     if current_song:
#         await ctx.send(f"지금 재생 중인 곡: **{current_song}**")
#     else:
#         await ctx.send("현재 재생 중인 노래가 없습니다.")
        
# @bot.command()
# async def 목록(ctx):
#     if music_queue:
#         message = "대기 중인 노래 목록:\n"
#         for i, (title, _) in enumerate(music_queue):
#             message += f"{i+1}. {title}\n"
#         await ctx.send(message)
#     else:
#         await ctx.send("재생 대기 중인 노래가 없습니다.")   
   
# @bot.command()
# async def 스킵(ctx):
#     vc = ctx.voice_client
#     if not vc or not vc.is_playing():
#         await ctx.send("현재 재생 중인 음악이 없습니다.")
#         return

#     await ctx.send(f"⏭️  **{current_song}** 을(를) 스킵합니다.")
#     vc.stop()
    
#     await play_music(ctx)
        
# @bot.command()
# async def 종료(ctx):
#     if ctx.voice_client:
#         await ctx.voice_client.disconnect()
#         music_queue.clear()
#         await ctx.send("봇이 음성 채널에서 나갔습니다.")
#     else:
#         await ctx.send("봇이 음성 채널에 없습니다.")
        
# @bot.command()
# async def 명령어(ctx):
#     help_text = """    
#         🛠️ **사용 가능한 명령어 목록:**
#         🎵 `!재생 [검색어]` - 유튜브에서 노래를 검색하여 재생합니다.
#         📃 `!목록` - 현재 대기열에 있는 노래 목록을 보여줍니다.
#         🎧 `!현재곡` - 지금 재생 중인 노래 정보를 보여줍니다.
#         ⏭️ `!스킵` - 현재 재생 중인 노래를 스킵하고 다음 곡으로 넘어갑니다.
#         🛑 `!종료` - 봇이 음성 채널에서 나가고 대기열을 초기화합니다.
#         ❓ `!명령어` - 명령어 모음을 표시합니다.
#     """
#     await ctx.send(help_text)
        
# @bot.event
# async def on_ready():
#     print(f"✅ 로그인 완료: {bot.user}")   
       
# bot.run(token)