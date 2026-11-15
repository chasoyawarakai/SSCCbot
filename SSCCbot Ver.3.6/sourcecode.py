#SSCCbot Ver.3.6
import discord
from discord import app_commands
from discord.ext import tasks
import json
import os
import random
import asyncio
from datetime import time, datetime, timedelta, timezone

# --- ⚙️ タイムゾーン（日本時間）の定義 ---
JST = timezone(timedelta(hours=9))

# --- ⚙️ 設定エリア（サーバーごとにIDを紐付ける場所） ---
TOKEN = 1234567891234567890 #botのトークンを入力

# サーバーごとの設定を管理する辞書
SERVER_CONFIGS = {
    # サーバーの名前を入力(メモ用)
    1234567891234567890: {  #サーバーのIDを入力
        # 💬 テキストチャンネルのID
        "notify_channel_id": 1234567891234567890, #フォーラム作成通知を送るチャンネルのIDを入力
        "ranking_channel_id": 1234567891234567890, #出席率ランキング通知を送るチャンネルのIDを入力
        "intro_channel_id": 1234567891234567890, #自己紹介チャンネルのIDを入力
        "birthday_notify_channel_id": 1234567891234567890, #誕生日通知を送るチャンネルのIDを入力
        
        # 🏷️ ロールのID
        "admin_role_id": 1234567891234567890, #管理者ロールのIDを入力
        
        # 📁 フォーラムID と 🏷️ メンションしたいロールID のペア
        "forum_role_map": {
            1234567891234567890: 1234567891234567890, #一つ目の分野のフォーラムのIDを入力: 一つ目の分野のロールのIDを入力
            1234567891234567890: 1234567891234567890, #二つ目の分野のフォーラムのIDを入力: 二つ目の分野のロールのIDを入力
            # 同様の形式で追加可能
        }
    },
    # 同様の形式で二つ目以降のサーバーも追加可能
}

# 永続化ファイル名
ATTENDANCE_FILE = "attendance_data.json"
VOTES_FILE = "persistent_votes.json"
BIRTHDAYS_FILE = "birthdays.json"
REACTION_ROLES_FILE = "reaction_roles.json"
# ----------------------------------------------------

# --- データ読み書き関数 ---
def load_attendance_data():
    if os.path.exists(ATTENDANCE_FILE):
        with open(ATTENDANCE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_attendance_data(data):
    with open(ATTENDANCE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def load_votes_data():
    if os.path.exists(VOTES_FILE):
        with open(VOTES_FILE, "r", encoding="utf-8") as f: return json.load(f)
    return {"schedules": {}, "polls": {}}

def save_votes_data(data):
    with open(VOTES_FILE, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False, indent=4)

def load_birthdays():
    if os.path.exists(BIRTHDAYS_FILE):
        with open(BIRTHDAYS_FILE, "r", encoding="utf-8") as f: return json.load(f)
    return {}

def save_birthdays(data):
    with open(BIRTHDAYS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def load_reaction_roles():
    if os.path.exists(REACTION_ROLES_FILE):
        with open(REACTION_ROLES_FILE, "r", encoding="utf-8") as f:
            return {int(msg_id): val for msg_id, val in json.load(f).items()}
    return {}

def save_reaction_roles(data):
    with open(REACTION_ROLES_FILE, "w", encoding="utf-8") as f:
        json.dump({str(k): v for k, v in data.items()}, f, ensure_ascii=False, indent=4)

def get_fiscal_year(dt: datetime) -> int:
    return dt.year if dt.month >= 4 else dt.year - 1


intents = discord.Intents.default()
intents.message_content = True
intents.members = True

class MyClient(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync()
        await restore_persistent_views(self)

client = MyClient()

@client.event
async def on_ready():
    print(f"ログインしました: {client.user}")
    if not monthly_ranking_task.is_running(): monthly_ranking_task.start()
    if not yearly_ranking_task.is_running(): yearly_ranking_task.start()
    if not check_birthdays.is_running(): check_birthdays.start()

async def restore_persistent_views(bot):
    await bot.wait_until_ready() # 起動時のキャッシュ未ロードによる取得失敗を防止
    data = load_votes_data()
    now = datetime.now(JST)
    
    for msg_id_str, s_data in data.get("schedules", {}).items():
        view = ScheduleView(
            title=s_data["title"],
            dates=s_data["dates"],
            deadline_str=s_data["deadline_str"],
            deadline_dt=datetime.fromisoformat(s_data["deadline_dt"]) if s_data.get("deadline_dt") else None,
            is_closed=s_data.get("is_closed", False),
            restored=True
        )
        bot.add_view(view, message_id=int(msg_id_str))
        
        if not s_data.get("is_closed") and s_data.get("deadline_dt"):
            dt = datetime.fromisoformat(s_data["deadline_dt"])
            if now >= dt:
                asyncio.create_task(ScheduleView.auto_close_expired_schedule(bot, msg_id_str, s_data))
            else:
                asyncio.create_task(ScheduleView.start_timer_static(bot, msg_id_str, dt, "schedule"))

    for msg_id_str, p_data in data.get("polls", {}).items():
        view = PollView(
            question=p_data["question"],
            options=p_data["options"],
            deadline_str=p_data["deadline_str"],
            deadline_dt=datetime.fromisoformat(p_data["deadline_dt"]) if p_data.get("deadline_dt") else None,
            is_closed=p_data.get("is_closed", False),
            restored=True
        )
        bot.add_view(view, message_id=int(msg_id_str))
        
        if not p_data.get("is_closed") and p_data.get("deadline_dt"):
            dt = datetime.fromisoformat(p_data["deadline_dt"])
            if now >= dt:
                asyncio.create_task(PollView.auto_close_expired_poll(bot, msg_id_str, p_data))
            else:
                asyncio.create_task(PollView.start_timer_static(bot, msg_id_str, dt, "poll"))


# ==========================================
# 1. フォーラム新規投稿通知
# ==========================================
@client.event
async def on_thread_create(thread: discord.Thread):
    guild_id = thread.guild.id
    if guild_id in SERVER_CONFIGS:
        config = SERVER_CONFIGS[guild_id]
        forum_role_map = config.get("forum_role_map", {})
        if thread.parent_id in forum_role_map:
            notify_channel = client.get_channel(config["notify_channel_id"])
            if notify_channel is not None:
                role_id = forum_role_map[thread.parent_id]
                mention = f"<@&{role_id}>"
                forum_name = thread.parent.name
                await notify_channel.send(
                    f"{mention}\n"
                    f"【{forum_name}】に新しい質問が投下されたよ！\n"
                    f"有識者のみんな、助けてあげて！\n"
                    f"{thread.jump_url}"
                )


# ==========================================
# 2. プロフィール参照 (/profile member, /profile grade)
# ==========================================
profile_group = app_commands.Group(name="profile", description="プロフィールに関するコマンド", guild_only=True)

@profile_group.command(name="member", description="指定したメンバーの自己紹介を表示します")
@app_commands.describe(member="自己紹介を見たいメンバーを選択（またはIDを入力）")
async def profile_member(interaction: discord.Interaction, member: discord.Member):
    await interaction.response.defer(ephemeral=True)
    guild_id = interaction.guild.id
    if guild_id not in SERVER_CONFIGS:
        await interaction.followup.send("このサーバーはまだBotの設定がされていません。", ephemeral=True)
        return

    config = SERVER_CONFIGS[guild_id]
    intro_channel = client.get_channel(config["intro_channel_id"])
    if intro_channel is None:
        await interaction.followup.send("自己紹介チャンネルが見つかりませんでした。", ephemeral=True)
        return

    found_message = None
    async for message in intro_channel.history(limit=500):
        if message.author.id == member.id:
            found_message = message
            break

    if found_message:
        embed = discord.Embed(
            title=member.display_name,
            description=found_message.content[:4096],
            color=discord.Color.blue()
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        await interaction.followup.send(embed=embed, ephemeral=True)
    else:
        await interaction.followup.send(f"**{member.display_name}** さんの自己紹介は見つかりませんでした。", ephemeral=True)

@profile_group.command(name="grade", description="指定した期のメンバー自己紹介をまとめて表示します")
@app_commands.describe(term_name="表示したい期（例: 30期）")
async def profile_grade(interaction: discord.Interaction, term_name: str):
    await interaction.response.defer(ephemeral=True)
    guild_id = interaction.guild.id
    if guild_id not in SERVER_CONFIGS:
        await interaction.followup.send("このサーバーはまだBotの設定がされていません。", ephemeral=True)
        return

    config = SERVER_CONFIGS[guild_id]
    intro_channel = client.get_channel(config["intro_channel_id"])
    if intro_channel is None:
        await interaction.followup.send("自己紹介チャンネルが見つかりませんでした。", ephemeral=True)
        return

    matched_members = [m for m in intro_channel.guild.members if any(r.name == term_name for r in m.roles)]
    if not matched_members:
        await interaction.followup.send(f"「{term_name}」に該当するメンバーが見つかりませんでした。", ephemeral=True)
        return

    found_entries = []
    async for message in intro_channel.history(limit=1000):
        for member in matched_members:
            if message.author.id == member.id:
                if not any(e['member'].id == member.id for e in found_entries):
                    found_entries.append({'member': member, 'content': message.content, 'url': message.jump_url})

    if not found_entries:
        await interaction.followup.send(f"「{term_name}」のメンバーの自己紹介が見つかりませんでした。", ephemeral=True)
        return

    desc_lines = [f"**{e['member'].display_name}**\n{e['content'][:100]}...\n[メッセージへジャンプ]({e['url']})\n" for e in found_entries[:10]]
    embed = discord.Embed(title=f"📋 {term_name} の自己紹介一覧", description="\n".join(desc_lines), color=discord.Color.green())
    await interaction.followup.send(embed=embed, ephemeral=True)

client.tree.add_command(profile_group)


# ==========================================
# 3. 日程調整システム (/schedule)
# ==========================================
class ScheduleView(discord.ui.View):
    def __init__(self, title: str = "", dates: list[str] = None, deadline_str: str = "", deadline_dt: datetime = None, admin_role_id: int = 0, is_closed: bool = False, restored: bool = False):
        super().__init__(timeout=None)
        self.title = title
        self.dates = dates or []
        self.deadline_str = deadline_str
        self.deadline_dt = deadline_dt
        self.admin_role_id = admin_role_id
        self.is_closed = is_closed
        
        for idx, date in enumerate(self.dates):
            # ボタンラベル上限対策（70文字制限）
            label_text = f"{date[:70]} (0票)"
            btn = discord.ui.Button(
                label=label_text,
                style=discord.ButtonStyle.secondary,
                custom_id=f"schedule_vote_{idx}",
                disabled=self.is_closed
            )
            btn.callback = self.make_vote_callback(idx)
            self.add_item(btn)

        close_btn = discord.ui.Button(
            label="投票を締め切る",
            style=discord.ButtonStyle.danger,
            custom_id="schedule_close",
            disabled=self.is_closed
        )
        close_btn.callback = self.close_callback
        self.add_item(close_btn)
        
        if not restored and deadline_dt:
            asyncio.create_task(self.start_auto_close_timer(deadline_dt))

    def make_vote_callback(self, idx: int):
        async def callback(interaction: discord.Interaction):
            await interaction.response.defer()
            data_all = load_votes_data()
            msg_id_str = str(interaction.message.id)
            s_data = data_all.get("schedules", {}).get(msg_id_str)
            if not s_data or s_data.get("is_closed"):
                await interaction.followup.send("❌ この日程調整はすでに締め切られています。", ephemeral=True)
                return
            
            votes = {int(k): set(v) for k, v in s_data["votes"].items()}
            user_id = interaction.user.id
            if user_id in votes.get(idx, set()):
                votes[idx].remove(user_id)
            else:
                votes.setdefault(idx, set()).add(user_id)
            
            s_data["votes"] = {str(k): list(v) for k, v in votes.items()}
            save_votes_data(data_all)
            await self.update_message(interaction, s_data)
        return callback

    async def close_callback(self, interaction: discord.Interaction):
        data_all = load_votes_data()
        msg_id_str = str(interaction.message.id)
        s_data = data_all.get("schedules", {}).get(msg_id_str)
        if not s_data:
            await interaction.response.send_message("❌ データが見つかりません。", ephemeral=True)
            return
        if s_data.get("is_closed"):
            await interaction.response.send_message("❌ すでに締め切られています。", ephemeral=True)
            return

        guild = interaction.guild
        config = SERVER_CONFIGS.get(guild.id, {}) if guild else {}
        admin_role_id = config.get("admin_role_id", 0)

        if interaction.user.id != s_data["author_id"] and not any(r.id == admin_role_id for r in interaction.user.roles):
            await interaction.response.send_message("❌ 作者か管理者のみ実行できます。", ephemeral=True)
            return

        s_data["is_closed"] = True
        save_votes_data(data_all)

        for child in self.children:
            child.disabled = True

        await self.update_message(interaction, s_data, closed=True)
        embed = self.build_result_embed(s_data, guild)
        await interaction.channel.send(content=f"📅 **{s_data['title']}** の日程調整結果発表！", embed=embed)
        self.stop()

    async def start_auto_close_timer(self, deadline_dt: datetime):
        await client.wait_until_ready()
        now = datetime.now(JST)
        delta = (deadline_dt - now).total_seconds()
        if delta > 0:
            await asyncio.sleep(delta)
        
        data_all = load_votes_data()
        for msg_id_str, s_data in data_all.get("schedules", {}).items():
            if not s_data.get("is_closed") and s_data.get("deadline_dt"):
                dt = datetime.fromisoformat(s_data["deadline_dt"])
                if datetime.now(JST) >= dt:
                    s_data["is_closed"] = True
                    save_votes_data(data_all)
                    try:
                        channel = client.get_channel(s_data["channel_id"])
                        guild = channel.guild if channel else None
                        if channel:
                            msg = await channel.fetch_message(int(msg_id_str))
                            view = ScheduleView(
                                title=s_data["title"],
                                dates=s_data["dates"],
                                deadline_str=s_data["deadline_str"],
                                deadline_dt=dt,
                                is_closed=True,
                                restored=True
                            )
                            embed = view.build_embed(s_data, closed=True)
                            await msg.edit(embed=embed, view=view)
                            
                            res_embed = view.build_result_embed(s_data, guild)
                            await channel.send(content=f"📅 **{s_data['title']}** の日程調整結果発表！", embed=res_embed)
                    except Exception:
                        pass

    @staticmethod
    async def start_timer_static(bot, msg_id_str, deadline_dt, mode):
        await bot.wait_until_ready()
        now = datetime.now(JST)
        delta = (deadline_dt - now).total_seconds()
        if delta > 0:
            await asyncio.sleep(delta)
        
        data_all = load_votes_data()
        if mode == "schedule":
            s_data = data_all.get("schedules", {}).get(msg_id_str)
            if s_data and not s_data.get("is_closed"):
                s_data["is_closed"] = True
                save_votes_data(data_all)
                try:
                    channel = bot.get_channel(s_data["channel_id"])
                    guild = channel.guild if channel else None
                    if channel:
                        msg = await channel.fetch_message(int(msg_id_str))
                        view = ScheduleView(
                            title=s_data["title"],
                            dates=s_data["dates"],
                            deadline_str=s_data["deadline_str"],
                            deadline_dt=deadline_dt,
                            is_closed=True,
                            restored=True
                        )
                        embed = view.build_embed(s_data, closed=True)
                        await msg.edit(embed=embed, view=view)
                        res_embed = view.build_result_embed(s_data, guild)
                        await channel.send(content=f"📅 **{s_data['title']}** の日程調整結果発表！", embed=res_embed)
                except Exception:
                    pass
        elif mode == "poll":
            p_data = data_all.get("polls", {}).get(msg_id_str)
            if p_data and not p_data.get("is_closed"):
                p_data["is_closed"] = True
                save_votes_data(data_all)
                try:
                    channel = bot.get_channel(p_data["channel_id"])
                    if channel:
                        msg = await channel.fetch_message(int(msg_id_str))
                        view = PollView(
                            question=p_data["question"],
                            options=p_data["options"],
                            deadline_str=p_data["deadline_str"],
                            deadline_dt=deadline_dt,
                            is_closed=True,
                            restored=True
                        )
                        embed = view.build_embed(p_data, closed=True)
                        await msg.edit(embed=embed, view=view)
                        res_embed = view.build_result_embed(p_data)
                        await channel.send(content=f"📊 **投票：{p_data['question']}** の結果発表！", embed=res_embed)
                except Exception:
                    pass

    @staticmethod
    async def auto_close_expired_schedule(bot, msg_id_str, s_data):
        if not s_data.get("is_closed"):
            s_data["is_closed"] = True
            data_all = load_votes_data()
            if msg_id_str in data_all.get("schedules", {}):
                data_all["schedules"][msg_id_str]["is_closed"] = True
                save_votes_data(data_all)
            try:
                channel = bot.get_channel(s_data["channel_id"])
                guild = channel.guild if channel else None
                if channel:
                    msg = await channel.fetch_message(int(msg_id_str))
                    view = ScheduleView(
                        title=s_data["title"],
                        dates=s_data["dates"],
                        deadline_str=s_data["deadline_str"],
                        is_closed=True,
                        restored=True
                    )
                    embed = view.build_embed(s_data, closed=True)
                    await msg.edit(embed=embed, view=view)
                    res_embed = view.build_result_embed(s_data, guild)
                    await channel.send(content=f"📅 **{s_data['title']}** の日程調整結果発表！", embed=res_embed)
            except Exception:
                pass

    def build_embed(self, s_data: dict, closed: bool = False):
        dates = s_data["dates"]
        votes = {int(k): set(v) for k, v in s_data["votes"].items()}
        for item in self.children:
            if isinstance(item, discord.ui.Button) and item.custom_id and item.custom_id.startswith("schedule_vote_"):
                idx = int(item.custom_id.split("_")[-1])
                if idx < len(dates):
                    item.label = f"{dates[idx][:70]} ({len(votes.get(idx, set()))}票)"
                if closed:
                    item.disabled = True
        
        lines = ["行ける日のボタンを押して投票してください（複数選択可）\n"]
        for idx, date in enumerate(dates):
            voters = votes.get(idx, set())
            mentions = " ".join(f"<@{uid}>" for uid in voters) if voters else "なし"
            lines.append(f"**{date}**: {len(voters)}票\n└ 投票者: {mentions}")
            
        embed = discord.Embed(
            title=f"📅 日程調整: {s_data['title']}" + (" 【受付終了】" if closed else ""),
            description="\n".join(lines) + (f"\n\n⏳ 期限: {s_data['deadline_str']}" if s_data['deadline_str'] != "なし" else ""),
            color=discord.Color.green() if closed else discord.Color.orange()
        )
        return embed

    def build_result_embed(self, s_data: dict, guild: discord.Guild = None):
        dates = s_data["dates"]
        votes = {int(k): set(v) for k, v in s_data["votes"].items()}
        
        best_date = None
        max_votes = -1
        max_admin_votes = -1
        lines = []

        config = SERVER_CONFIGS.get(guild.id, {}) if guild else {}
        admin_role_id = config.get("admin_role_id", 0)

        for idx, date in enumerate(dates):
            voters = votes.get(idx, set())
            count = len(voters)
            
            admin_count = 0
            if guild and admin_role_id:
                for uid in voters:
                    member = guild.get_member(uid)
                    if member and any(r.id == admin_role_id for r in member.roles):
                        admin_count += 1

            mentions = " ".join(f"<@{uid}>" for uid in voters) if voters else "なし"
            lines.append(f"**{date}**: {count}票 (管理者 {admin_count}票)\n└ 投票者: {mentions}")
            
            if count > max_votes or (count == max_votes and admin_count > max_admin_votes):
                max_votes = count
                max_admin_votes = admin_count
                best_date = date

        result_msg = f"🏆 **最有力候補: {best_date}** (最多 {max_votes}票 / 管理者 {max_admin_votes}票)" if max_votes > 0 else "🏆 有効な投票はありませんでした。"
        embed = discord.Embed(
            title=f"📅 日程調整結果: {s_data['title']}",
            description=f"{result_msg}\n\n" + "\n".join(lines),
            color=discord.Color.green()
        )
        return embed

    async def update_message(self, interaction: discord.Interaction, s_data: dict, closed: bool = False):
        embed = self.build_embed(s_data, closed=closed)
        try:
            if interaction.response.is_done():
                await interaction.edit_original_response(embed=embed, view=self)
            else:
                await interaction.response.edit_message(embed=embed, view=self)
        except Exception:
            pass

@client.tree.command(name="schedule", description="日程調整を作成します（自動締め切り・永続化・管理者優先集計）")
@app_commands.describe(title="日程調整のタイトル", dates="候補日（例: 5/1, 5/2, 5/3）", deadline="期限（例: YYYY-MM-DD HH:MM あるいは なし）")
@app_commands.guild_only()
async def schedule_command(interaction: discord.Interaction, title: str, dates: str, deadline: str = "なし"):
    guild_id = interaction.guild.id
    if guild_id not in SERVER_CONFIGS:
        await interaction.response.send_message("このサーバーはまだBotの設定がされていません。", ephemeral=True)
        return
    config = SERVER_CONFIGS[guild_id]
    admin_role_id = config.get("admin_role_id", 0)

    is_admin = any(role.id == admin_role_id for role in interaction.user.roles)
    if not is_admin:
        await interaction.response.send_message("❌ このコマンドは管理者ロールを持つ人のみ実行できます。", ephemeral=True)
        return

    date_list = [d.strip() for d in dates.split(",")]
    if len(date_list) > 24:
        await interaction.response.send_message("❌ 候補日は最大24個までです。", ephemeral=True)
        return

    deadline_dt = None
    deadline_str = deadline
    if deadline != "なし":
        try:
            deadline_dt = datetime.strptime(deadline, "%Y-%m-%d %H:%M").replace(tzinfo=JST)
            if deadline_dt <= datetime.now(JST):
                await interaction.response.send_message("❌ 未来の日時を指定してください。", ephemeral=True)
                return
        except ValueError:
            await interaction.response.send_message("❌ 日時の形式が違います。`YYYY-MM-DD HH:MM` または `なし` で指定してください。", ephemeral=True)
            return

    await interaction.response.send_message("日程調整パネルを作成中...", ephemeral=True)
    view = ScheduleView(title=title, dates=date_list, deadline_str=deadline_str, deadline_dt=deadline_dt, admin_role_id=admin_role_id)
    
    s_data = {
        "title": title,
        "dates": date_list,
        "deadline_str": deadline_str,
        "deadline_dt": deadline_dt.isoformat() if deadline_dt else None,
        "author_id": interaction.user.id,
        "channel_id": interaction.channel.id,
        "is_closed": False,
        "votes": {str(i): [] for i in range(len(date_list))}
    }
    
    embed = view.build_embed(s_data, closed=False)
    msg = await interaction.channel.send(embed=embed, view=view)
    
    data_all = load_votes_data()
    data_all.setdefault("schedules", {})[str(msg.id)] = s_data
    save_votes_data(data_all)


# ==========================================
# 4. 出席管理システム (/attend pass, entry, ranking, reset)
# ==========================================
attend_group = app_commands.Group(name="attend", description="出席管理に関するコマンド", guild_only=True)

@attend_group.command(name="pass", description="【管理者用】本日の出席受付を開始し、パスワードを発行します")
async def attend_pass(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    guild_id_str = str(guild_id)
    if guild_id not in SERVER_CONFIGS:
        await interaction.response.send_message("このサーバーはまだBotの設定がされていません。", ephemeral=True)
        return
    config = SERVER_CONFIGS[guild_id]
    if not any(role.id == config.get("admin_role_id") for role in interaction.user.roles):
        await interaction.response.send_message("このコマンドは管理者ロールを持つ人のみ実行できます。", ephemeral=True)
        return

    today_str = datetime.now(JST).strftime("%Y-%m-%d")
    data = load_attendance_data()
    server_data = data.setdefault(guild_id_str, {"last_date": "", "today_passcode": None, "dates": {}, "users": {}})

    is_new = False
    if server_data.get("last_date") != today_str:
        server_data["last_date"] = today_str
        server_data["today_passcode"] = f"{random.randint(1000, 9999)}"
        is_new = True
    elif not server_data.get("today_passcode"):
        server_data["today_passcode"] = f"{random.randint(1000, 9999)}"
        is_new = True
    
    save_attendance_data(data)
    passcode = server_data["today_passcode"]
    status_msg = "新しく本日のパスワードを発行しました！" if is_new else "本日はすでに受付中です"
    await interaction.response.send_message(
        f"📋 **{status_msg}**\n🔑 本日のパスワード: `{passcode}`\n\n`/attend entry <パスワード>` で入力してもらってください。",
        ephemeral=True
    )

@attend_group.command(name="entry", description="本日のパスワードを入力して出席を登録します")
@app_commands.describe(passcode="4桁のパスワード")
async def attend_entry(interaction: discord.Interaction, passcode: str):
    guild_id_str = str(interaction.guild.id)
    today_str = datetime.now(JST).strftime("%Y-%m-%d")
    
    data = load_attendance_data()
    server_data = data.get(guild_id_str, {"last_date": "", "today_passcode": None, "dates": {}, "users": {}})

    if passcode != server_data.get("today_passcode") or server_data.get("last_date") != today_str:
        await interaction.response.send_message("❌ パスワードが違うか、受付が開始されていません。", ephemeral=True)
        return

    user_id_str = str(interaction.user.id)
    if user_id_str in server_data["dates"].get(today_str, []):
        await interaction.response.send_message("⚠️ すでに自己出席登録済みです！", ephemeral=True)
        return

    server_data["dates"].setdefault(today_str, []).append(user_id_str)
    server_data["users"][user_id_str] = {"name": interaction.user.display_name}
    
    data[guild_id_str] = server_data
    save_attendance_data(data)
    
    await interaction.response.send_message("✅ 出席登録完了しました！お疲れ様です 🎉", ephemeral=True)

@attend_group.command(name="ranking", description="出席ランキングを表示します")
@app_commands.choices(period=[
    app_commands.Choice(name="今月", value="month"),
    app_commands.Choice(name="今年度（4月〜3月）", value="year"),
    app_commands.Choice(name="総合（全期間）", value="total")
])
async def attend_ranking(interaction: discord.Interaction, period: str = "month"):
    guild_id_str = str(interaction.guild.id)
    data = load_attendance_data()
    server_data = data.get(guild_id_str, {"dates": {}, "users": {}})
    dates_dict = server_data.get("dates", {})
    users_dict = server_data.get("users", {})

    now = datetime.now(JST)
    current_month_str = now.strftime("%Y-%m")
    current_fy = get_fiscal_year(now)

    target_dates = []
    for d_str in dates_dict.keys():
        if period == "month" and d_str.startswith(current_month_str):
            target_dates.append(d_str)
        elif period == "year":
            try:
                dt = datetime.strptime(d_str, "%Y-%m-%d")
                if get_fiscal_year(dt) == current_fy:
                    target_dates.append(d_str)
            except ValueError:
                pass
        elif period == "total":
            target_dates.append(d_str)

    total_days = len(target_dates)
    user_counts = {}
    for d_str in target_dates:
        for uid in dates_dict[d_str]:
            user_counts[uid] = user_counts.get(uid, 0) + 1

    sorted_users = sorted(user_counts.items(), key=lambda x: x[1], reverse=True)
    ranking_lines = []
    period_title = "今月" if period == "month" else "今年度" if period == "year" else "総合"

    for i, (uid, count) in enumerate(sorted_users[:10]):
        rank = i + 1
        medal = "🥇" if rank == 1 else "🥈" if rank == 2 else "🥉" if rank == 3 else f"{rank}."
        u_name = users_dict.get(uid, {}).get("name", "メンバー")
        rate = (count / total_days) * 100 if total_days > 0 else 0
        ranking_lines.append(f"{medal} **{u_name}** : {count}回 出席 ({rate:.1f}%)")

    if not ranking_lines:
        ranking_lines.append("まだ出席データがありません。")

    embed = discord.Embed(title=f"🏆 出席ランキング 【{period_title}】 (全 {total_days} 回開催)", description="\n".join(ranking_lines), color=discord.Color.orange())
    my_count = user_counts.get(str(interaction.user.id), 0)
    my_rate = (my_count / total_days) * 100 if total_days > 0 else 0
    embed.set_footer(text=f"あなたの記録: {my_count}回出席 ({my_rate:.1f}%)")
    await interaction.response.send_message(embed=embed, ephemeral=True)

@attend_group.command(name="reset", description="【管理者用】すべての出席データをリセットします")
async def attend_reset(interaction: discord.Interaction):
    guild_id_str = str(interaction.guild.id)
    if interaction.guild.id not in SERVER_CONFIGS:
        await interaction.response.send_message("このサーバーはまだBotの設定がされていません。", ephemeral=True)
        return
    config = SERVER_CONFIGS[interaction.guild.id]
    if not any(role.id == config.get("admin_role_id") for role in interaction.user.roles):
        await interaction.response.send_message("管理者のみ実行できます。", ephemeral=True)
        return

    data = load_attendance_data()
    data[guild_id_str] = {"last_date": "", "today_passcode": None, "dates": {}, "users": {}}
    save_attendance_data(data)
    await interaction.response.send_message("🗑️ このサーバーの出席データをリセットしました！", ephemeral=True)

client.tree.add_command(attend_group)


# ==========================================
# 5. 自動ランキング通知タスク（JST対応）
# ==========================================
@tasks.loop(time=time(hour=9, minute=0, tzinfo=JST))
async def monthly_ranking_task():
    await client.wait_until_ready()
    now = datetime.now(JST)
    if now.day == 1:
        data = load_attendance_data()
        first_day = now.replace(day=1)
        prev_month_str = (first_day - timedelta(days=1)).strftime("%Y-%m")
        
        for guild_id, config in SERVER_CONFIGS.items():
            guild_id_str = str(guild_id)
            server_data = data.get(guild_id_str, {})
            dates_dict = server_data.get("dates", {})
            users_dict = server_data.get("users", {})
            
            target_dates = [d for d in dates_dict.keys() if d.startswith(prev_month_str)]
            total_days = len(target_dates)
            if total_days == 0:
                continue
            
            user_counts = {}
            for d in target_dates:
                for uid in dates_dict[d]:
                    user_counts[uid] = user_counts.get(uid, 0) + 1
            sorted_users = sorted(user_counts.items(), key=lambda x: x[1], reverse=True)
            
            ranking_lines = []
            for i, (uid, count) in enumerate(sorted_users[:10]):
                rank = i + 1
                medal = "🥇" if rank == 1 else "🥈" if rank == 2 else "🥉" if rank == 3 else f"{rank}."
                u_name = users_dict.get(uid, {}).get("name", "メンバー")
                rate = (count / total_days) * 100
                ranking_lines.append(f"{medal} **{u_name}** : {count}回 出席 ({rate:.1f}%)")

            embed = discord.Embed(title=f"📢 【月例】前月（{prev_month_str}）出席ランキング！ (全 {total_days} 回)", description="\n".join(ranking_lines), color=discord.Color.gold())
            
            ch_id = config.get("ranking_channel_id")
            if ch_id:
                channel = client.get_channel(ch_id)
                if channel:
                    await channel.send(embed=embed)

@tasks.loop(time=time(hour=9, minute=10, tzinfo=JST))
async def yearly_ranking_task():
    await client.wait_until_ready()
    now = datetime.now(JST)
    if now.month == 4 and now.day == 1:
        data = load_attendance_data()
        prev_fy = now.year - 1
        
        for guild_id, config in SERVER_CONFIGS.items():
            guild_id_str = str(guild_id)
            server_data = data.get(guild_id_str, {})
            dates_dict = server_data.get("dates", {})
            users_dict = server_data.get("users", {})
            
            target_dates = [d for d in dates_dict.keys() if get_fiscal_year(datetime.strptime(d, "%Y-%m-%d")) == prev_fy]
            total_days = len(target_dates)
            if total_days == 0:
                continue

            user_counts = {}
            for d in target_dates:
                for uid in dates_dict[d]:
                    user_counts[uid] = user_counts.get(uid, 0) + 1
            sorted_users = sorted(user_counts.items(), key=lambda x: x[1], reverse=True)

            ranking_lines = []
            for i, (uid, count) in enumerate(sorted_users[:10]):
                rank = i + 1
                medal = "🥇" if rank == 1 else "🥈" if rank == 2 else "🥉" if rank == 3 else f"{rank}."
                u_name = users_dict.get(uid, {}).get("name", "メンバー")
                rate = (count / total_days) * 100
                ranking_lines.append(f"{medal} **{u_name}** : {count}回 出席 ({rate:.1f}%)")

            embed = discord.Embed(title=f"👑 【年度末】{prev_fy}年度 年間出席ランキング！ (全 {total_days} 回)", description="\n".join(ranking_lines), color=discord.Color.purple())
            
            ch_id = config.get("ranking_channel_id")
            if ch_id:
                channel = client.get_channel(ch_id)
                if channel:
                    await channel.send(embed=embed)


# ==========================================
# 6. リアクションロールシステム (/newrole)
# ==========================================
@client.tree.command(name="newrole", description="【管理者用】リアクションロールパネルを作成します")
@app_commands.describe(role_names="ロール名（カンマ区切り 例: 30期, 29期）", emojis="絵文字（カンマ区切り 例: 🔴, 🔵）")
@app_commands.guild_only()
async def newrole(interaction: discord.Interaction, role_names: str, emojis: str):
    await interaction.response.defer(ephemeral=True)
    guild_id = interaction.guild.id
    if guild_id not in SERVER_CONFIGS:
        await interaction.followup.send("このサーバーはまだBotの設定がされていません。", ephemeral=True)
        return
    config = SERVER_CONFIGS[guild_id]
    if not any(role.id == config.get("admin_role_id") for role in interaction.user.roles):
        await interaction.followup.send("管理者のみ実行できます。", ephemeral=True)
        return

    r_list = [r.strip() for r in role_names.split(",")]
    e_list = [e.strip() for e in emojis.split(",")]
    if len(r_list) != len(e_list):
        await interaction.followup.send("❌ ロール数と絵文字の数を合わせてください。", ephemeral=True)
        return

    role_map = {}
    desc_lines = []
    for r_name, emoji in zip(r_list, e_list):
        role = discord.utils.get(interaction.guild.roles, name=r_name)
        if role:
            role_map[emoji] = role.id
            desc_lines.append(f"{emoji} : {role.name}")
        else:
            await interaction.followup.send(f"❌ ロール「{r_name}」が見つかりませんでした。", ephemeral=True)
            return

    embed = discord.Embed(title="✨ ロール付与パネル", description="\n".join(desc_lines), color=discord.Color.purple())
    msg = await interaction.channel.send(embed=embed)
    for emoji in e_list:
        try: await msg.add_reaction(emoji)
        except discord.HTTPException: pass

    mapping = load_reaction_roles()
    mapping[msg.id] = role_map
    save_reaction_roles(mapping)
    await interaction.followup.send("リアクションロールパネルを作成しました！", ephemeral=True)

@client.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if payload.member and payload.member.bot: return
    mapping = load_reaction_roles()
    if payload.message_id in mapping:
        role_map = mapping[payload.message_id]
        emoji_str = str(payload.emoji)
        if emoji_str in role_map:
            guild = client.get_guild(payload.guild_id)
            if guild:
                role = guild.get_role(role_map[emoji_str])
                if role:
                    try: await payload.member.add_roles(role)
                    except discord.HTTPException: pass

@client.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    mapping = load_reaction_roles()
    if payload.message_id in mapping:
        role_map = mapping[payload.message_id]
        emoji_str = str(payload.emoji)
        if emoji_str in role_map:
            guild = client.get_guild(payload.guild_id)
            if guild:
                member = guild.get_member(payload.user_id)
                if member and not member.bot:
                    role = guild.get_role(role_map[emoji_str])
                    if role:
                        try: await member.remove_roles(role)
                        except discord.HTTPException: pass


# ==========================================
# 7. 簡易投票システム (/poll)
# ==========================================
class PollView(discord.ui.View):
    def __init__(self, question: str = "", options: list[str] = None, deadline_str: str = "", deadline_dt: datetime = None, is_closed: bool = False, restored: bool = False):
        super().__init__(timeout=None)
        self.question = question
        self.options = options or []
        self.deadline_str = deadline_str
        self.deadline_dt = deadline_dt
        self.is_closed = is_closed

        for idx, option in enumerate(self.options):
            # ボタンラベル上限対策（70文字制限）
            label_text = f"{option[:70]} (0票)"
            btn = discord.ui.Button(
                label=label_text,
                style=discord.ButtonStyle.secondary,
                custom_id=f"poll_vote_{idx}",
                disabled=self.is_closed
            )
            btn.callback = self.make_vote_callback(idx)
            self.add_item(btn)

        close_btn = discord.ui.Button(
            label="投票を締め切る",
            style=discord.ButtonStyle.danger,
            custom_id="poll_close",
            disabled=self.is_closed
        )
        close_btn.callback = self.close_callback
        self.add_item(close_btn)

        if not restored and deadline_dt:
            asyncio.create_task(self.start_auto_close_timer(deadline_dt))

    def make_vote_callback(self, idx: int):
        async def callback(interaction: discord.Interaction):
            await interaction.response.defer()
            data_all = load_votes_data()
            msg_id_str = str(interaction.message.id)
            p_data = data_all.get("polls", {}).get(msg_id_str)
            if not p_data or p_data.get("is_closed"):
                await interaction.followup.send("❌ この投票はすでに締め切られています。", ephemeral=True)
                return

            votes = {int(k): set(v) for k, v in p_data["votes"].items()}
            user_id = interaction.user.id
            if user_id in votes.get(idx, set()):
                votes[idx].remove(user_id)
            else:
                votes.setdefault(idx, set()).add(user_id)

            p_data["votes"] = {str(k): list(v) for k, v in votes.items()}
            save_votes_data(data_all)
            await self.update_message(interaction, p_data)
        return callback

    async def close_callback(self, interaction: discord.Interaction):
        data_all = load_votes_data()
        msg_id_str = str(interaction.message.id)
        p_data = data_all.get("polls", {}).get(msg_id_str)
        if not p_data:
            await interaction.response.send_message("❌ データが見つかりません。", ephemeral=True)
            return
        if p_data.get("is_closed"):
            await interaction.response.send_message("❌ すでに締め切られています。", ephemeral=True)
            return

        guild = interaction.guild
        config = SERVER_CONFIGS.get(guild.id, {}) if guild else {}
        admin_role_id = config.get("admin_role_id", 0)

        if interaction.user.id != p_data["author_id"] and not any(r.id == admin_role_id for r in interaction.user.roles):
            await interaction.response.send_message("❌ 作者か管理者のみ実行できます。", ephemeral=True)
            return

        p_data["is_closed"] = True
        save_votes_data(data_all)

        for child in self.children:
            child.disabled = True

        await self.update_message(interaction, p_data, closed=True)
        embed = self.build_result_embed(p_data)
        await interaction.channel.send(content=f"📊 **投票：{p_data['question']}** の結果発表！", embed=embed)
        self.stop()

    async def start_auto_close_timer(self, deadline_dt: datetime):
        await client.wait_until_ready()
        now = datetime.now(JST)
        delta = (deadline_dt - now).total_seconds()
        if delta > 0:
            await asyncio.sleep(delta)
        
        data_all = load_votes_data()
        for msg_id_str, p_data in data_all.get("polls", {}).items():
            if not p_data.get("is_closed") and p_data.get("deadline_dt"):
                dt = datetime.fromisoformat(p_data["deadline_dt"])
                if datetime.now(JST) >= dt:
                    p_data["is_closed"] = True
                    save_votes_data(data_all)
                    try:
                        channel = client.get_channel(p_data["channel_id"])
                        if channel:
                            msg = await channel.fetch_message(int(msg_id_str))
                            view = PollView(
                                question=p_data["question"],
                                options=p_data["options"],
                                deadline_str=p_data["deadline_str"],
                                deadline_dt=dt,
                                is_closed=True,
                                restored=True
                            )
                            embed = view.build_embed(p_data, closed=True)
                            await msg.edit(embed=embed, view=view)
                            
                            res_embed = view.build_result_embed(p_data)
                            await channel.send(content=f"📊 **投票：{p_data['question']}** の結果発表！", embed=res_embed)
                    except Exception:
                        pass

    @staticmethod
    async def auto_close_expired_poll(bot, msg_id_str, p_data):
        if not p_data.get("is_closed"):
            p_data["is_closed"] = True
            data_all = load_votes_data()
            if msg_id_str in data_all.get("polls", {}):
                data_all["polls"][msg_id_str]["is_closed"] = True
                save_votes_data(data_all)
            try:
                channel = bot.get_channel(p_data["channel_id"])
                if channel:
                    msg = await channel.fetch_message(int(msg_id_str))
                    view = PollView(
                        question=p_data["question"],
                        options=p_data["options"],
                        deadline_str=p_data["deadline_str"],
                        is_closed=True,
                        restored=True
                    )
                    embed = view.build_embed(p_data, closed=True)
                    await msg.edit(embed=embed, view=view)
                    res_embed = view.build_result_embed(p_data)
                    await channel.send(content=f"📊 **投票：{p_data['question']}** の結果発表！", embed=res_embed)
            except Exception:
                pass

    def build_embed(self, p_data: dict, closed: bool = False):
        options = p_data["options"]
        votes = {int(k): set(v) for k, v in p_data["votes"].items()}
        for item in self.children:
            if isinstance(item, discord.ui.Button) and item.custom_id and item.custom_id.startswith("poll_vote_"):
                idx = int(item.custom_id.split("_")[-1])
                if idx < len(options):
                    item.label = f"{options[idx][:70]} ({len(votes.get(idx, set()))}票)"
                if closed:
                    item.disabled = True

        lines = []
        for idx, option in enumerate(options):
            voters = votes.get(idx, set())
            mentions = " ".join(f"<@{uid}>" for uid in voters) if voters else "なし"
            lines.append(f"**{option}**: {len(voters)}票\n└ 投票者: {mentions}")

        embed = discord.Embed(
            title=f"📊 投票：{p_data['question']}" + (" 【受付終了】" if closed else ""),
            description="\n\n".join(lines) + (f"\n⏳ 期限: {p_data['deadline_str']}" if p_data['deadline_str'] != "なし" else ""),
            color=discord.Color.green() if closed else discord.Color.blurple()
        )
        return embed

    def build_result_embed(self, p_data: dict):
        options = p_data["options"]
        votes = {int(k): set(v) for k, v in p_data["votes"].items()}
        best_option = None
        max_votes = -1
        lines = []
        for idx, option in enumerate(options):
            voters = votes.get(idx, set())
            count = len(voters)
            mentions = " ".join(f"<@{uid}>" for uid in voters) if voters else "なし"
            lines.append(f"**{option}**: {count}票\n└ 投票者: {mentions}")
            if count > max_votes:
                max_votes = count
                best_option = option

        result_msg = f"🏆 **勝者: {best_option}** (最多 {max_votes}票)" if max_votes > 0 else "🏆 有効な投票はありませんでした。"
        embed = discord.Embed(
            title=f"📊 投票結果：{p_data['question']}",
            description=f"{result_msg}\n\n" + "\n".join(lines),
            color=discord.Color.green()
        )
        return embed

    async def update_message(self, interaction: discord.Interaction, p_data: dict, closed: bool = False):
        embed = self.build_embed(p_data, closed=closed)
        try:
            if interaction.response.is_done():
                await interaction.edit_original_response(embed=embed, view=self)
            else:
                await interaction.response.edit_message(embed=embed, view=self)
        except Exception:
            pass

@client.tree.command(name="poll", description="誰でも自由に作れる簡易投票を作成します（自動締め切り対応）")
@app_commands.describe(question="投票の質問", options="選択肢（カンマ区切り 例: はい, いいえ）", deadline="期限（例: YYYY-MM-DD HH:MM あるいは なし）")
@app_commands.guild_only()
async def poll_command(interaction: discord.Interaction, question: str, options: str, deadline: str = "なし"):
    opt_list = [o.strip() for o in options.split(",")]
    if len(opt_list) < 2:
        await interaction.response.send_message("❌ 選択肢は2つ以上を指定してください。", ephemeral=True)
        return
    if len(opt_list) > 24:
        await interaction.response.send_message("❌ 選択肢は最大24個までです。", ephemeral=True)
        return

    deadline_dt = None
    deadline_str = deadline
    if deadline != "なし":
        try:
            deadline_dt = datetime.strptime(deadline, "%Y-%m-%d %H:%M").replace(tzinfo=JST)
            if deadline_dt <= datetime.now(JST):
                await interaction.response.send_message("❌ 未来の日時を指定してください。", ephemeral=True)
                return
        except ValueError:
            await interaction.response.send_message("❌ 日時の形式が違います。`YYYY-MM-DD HH:MM` または `なし` で指定してください。", ephemeral=True)
            return

    await interaction.response.send_message("投票パネルを作成中...", ephemeral=True)
    view = PollView(question=question, options=opt_list, deadline_str=deadline_str, deadline_dt=deadline_dt)

    p_data = {
        "question": question,
        "options": opt_list,
        "deadline_str": deadline_str,
        "deadline_dt": deadline_dt.isoformat() if deadline_dt else None,
        "author_id": interaction.user.id,
        "channel_id": interaction.channel.id,
        "is_closed": False,
        "votes": {str(i): [] for i in range(len(opt_list))}
    }

    embed = view.build_embed(p_data, closed=False)
    msg = await interaction.channel.send(embed=embed, view=view)

    data_all = load_votes_data()
    data_all.setdefault("polls", {})[str(msg.id)] = p_data
    save_votes_data(data_all)


# ==========================================
# 8. 誕生日機能 (/birthday)
# ==========================================
birthday_group = app_commands.Group(name="birthday", description="誕生日に関するコマンド", guild_only=True)

@birthday_group.command(name="entry", description="自分の誕生日を登録します（うるう年の2/29も対応）")
@app_commands.describe(month="誕生月の数字（例: 5）", day="誕生日の数字（例: 15）")
async def birthday_register(interaction: discord.Interaction, month: int, day: int):
    guild_id_str = str(interaction.guild.id)
    max_days = {1:31, 2:29, 3:31, 4:30, 5:31, 6:30, 7:31, 8:31, 9:30, 10:31, 11:30, 12:31}
    if month not in max_days or day < 1 or day > max_days[month]:
        await interaction.response.send_message("❌ 正しい日付を入力してください。", ephemeral=True)
        return

    data = load_birthdays()
    server_birthdays = data.setdefault(guild_id_str, {})
    server_birthdays[str(interaction.user.id)] = {"month": month, "day": day}
    save_birthdays(data)
    await interaction.response.send_message(f"🎂 あなたの誕生日を **{month}月{day}日** に登録しました！", ephemeral=True)

@birthday_group.command(name="show", description="誕生日を確認します")
@app_commands.describe(member="確認したいメンバー（省略した場合は自分）")
async def birthday_show(interaction: discord.Interaction, member: discord.Member = None):
    guild_id_str = str(interaction.guild.id)
    target = member or interaction.user
    data = load_birthdays()
    server_birthdays = data.get(guild_id_str, {})
    b = server_birthdays.get(str(target.id))
    if b:
        await interaction.response.send_message(f"👤 **{target.display_name}** さんの誕生日は **{b['month']}月{b['day']}日** です！", ephemeral=True)
    else:
        await interaction.response.send_message(f"❌ **{target.display_name}** さんの誕生日はまだ登録されていません。", ephemeral=True)

@birthday_group.command(name="everyone", description="登録されている全員の誕生日を一覧で表示します")
async def birthday_everyone(interaction: discord.Interaction):
    guild_id_str = str(interaction.guild.id)
    data = load_birthdays()
    server_birthdays = data.get(guild_id_str, {})
    if not server_birthdays:
        await interaction.response.send_message("❌ このサーバーで登録されている誕生日はまだありません。", ephemeral=True)
        return

    sorted_birthdays = sorted(server_birthdays.items(), key=lambda x: (x[1]["month"], x[1]["day"]))
    lines = [f"🎂 **{b['month']}月{b['day']}日** : <@{uid_str}>" for uid_str, b in sorted_birthdays]

    embed = discord.Embed(title="👥 登録メンバー誕生日一覧", description="\n".join(lines), color=discord.Color.gold())
    await interaction.response.send_message(embed=embed, ephemeral=True)

client.tree.add_command(birthday_group)

@tasks.loop(time=time(hour=0, minute=0, tzinfo=JST))
async def check_birthdays():
    await client.wait_until_ready()
    now = datetime.now(JST)
    data = load_birthdays()
    is_leap = (now.year % 4 == 0 and now.year % 100 != 0) or (now.year % 400 == 0)

    for guild_id_str, server_birthdays in data.items():
        guild_id = int(guild_id_str)
        if guild_id not in SERVER_CONFIGS:
            continue
        config = SERVER_CONFIGS[guild_id]
        ch_id = config.get("birthday_notify_channel_id")
        if not ch_id:
            continue

        b_users = []
        for uid_str, b in server_birthdays.items():
            b_month = b["month"]
            b_day = b["day"]
            if b_month == now.month and b_day == now.day:
                b_users.append(int(uid_str))
            elif not is_leap and b_month == 2 and b_day == 29 and now.month == 2 and now.day == 28:
                b_users.append(int(uid_str))

        if b_users:
            channel = client.get_channel(ch_id)
            if channel:
                mentions = " ".join([f"<@{uid}>" for uid in b_users])
                embed = discord.Embed(title="🎉 本日の主役！", description=f"今日は {mentions} さんの誕生日です！おめでとうございます！🎂✨", color=discord.Color.gold())
                await channel.send(embed=embed)


# ==========================================
# 9. ヘルプコマンド (/commands)
# ==========================================
@client.tree.command(name="commands", description="Botのコマンド一覧と使い方を確認します")
@app_commands.guild_only()
async def commands_command(interaction: discord.Interaction):
    embed = discord.Embed(title="🤖 SSCCbot コマンド一覧", description="現在利用できるコマンドと機能のまとめです。", color=discord.Color.blurple())
    embed.add_field(
        name="👤 プロフィール",
        value=(
            "**/profile member** `[メンバー]`\n"
            "└ 指定したメンバーの自己紹介を表示\n"
            "**/profile grade** `[期名]`\n"
            "└ 指定した期のメンバー自己紹介をまとめて表示"
        ),
        inline=False
    )
    embed.add_field(
        name="🎂 誕生日機能",
        value=(
            "**/birthday entry** `[月]` `[日]`\n"
            "└ 自分の誕生日を登録\n"
            "**/birthday show** `[メンバー]`\n"
            "└ 誕生日を確認（自動お祝い通知付き）\n"
            "**/birthday everyone**\n"
            "└ 全員分の誕生日一覧を表示"
        ),
        inline=False
    )
    embed.add_field(
        name="📅 日程調整・投票",
        value=(
            "**/schedule** `[タイトル]` `[候補日]` `[期限]`\n"
            "└ 管理者必須の日程調整（自動締め切り・永続化・管理者優先集計）\n"
            "**/poll** `[質問]` `[選択肢]` `[期限]`\n"
            "└ 簡易投票パネル（自動締め切り・永続化対応）"
        ),
        inline=False
    )
    embed.add_field(
        name="📋 出席管理・ランキング",
        value=(
            "**/attend pass**\n"
            "└ 【管理者用】本日の出席受付を開始\n"
            "**/attend entry** `[パスワード]`\n"
            "└ パスワードで出席登録\n"
            "**/attend ranking** `[期間]`\n"
            "└ 出席ランキング（今月/今年度/総合）\n"
            "**/attend reset**\n"
            "└ 【管理者用】出席データリセット"
        ),
        inline=False
    )
    embed.add_field(
        name="✨ ロール・自動化",
        value=(
            "**/newrole** `[ロール名]` `[絵文字]`\n"
            "└ 【管理者用】複数対応リアクションロール作成\n"
            "📢 **フォーラム新規投稿通知**\n"
            "└ 投稿時に自動メンション通知"
        ),
        inline=False
    )
    embed.set_footer(text="※プライベート表示のコマンドもあります")
    await interaction.response.send_message(embed=embed, ephemeral=True)

client.run(TOKEN)
