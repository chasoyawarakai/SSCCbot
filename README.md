# SSCCbot_sourcecord
```python
# SSCCbot Ver.3.2.1
import discord
from discord import app_commands
from discord.ext import tasks
import json
import os
import random
import uuid
import asyncio
from datetime import time, datetime, timedelta

# --- 設定エリア ---
TOKEN = "botのトークンを入力"

NOTIFY_CHANNEL_ID = "フォーラム新規投稿通知を送るチャンネルのIDを入力"  # フォーラム新規投稿通知を送るチャンネルのID
RANKING_CHANNEL_ID = "ランキング通知を送るチャンネルのIDを入力" # ランキング通知を送るチャンネルのID
INTRO_CHANNEL_ID = "自己紹介チャンネルのIDを入力"   # 自己紹介チャンネルのID
BIRTHDAY_NOTIFY_CHANNEL_ID = "誕生日の通知を送るチャンネルのIDを入力"  # 誕生日の通知を送るチャンネルのID

FORUM_ROLE_MAP = {
    "分野1のフォーラムのIDを入力": "分野1のロールのIDを入力",  # 分野1
    "分野2のフォーラムのIDを入力": "分野2のロールのIDを入力",  # 分野2
    "分野3のフォーラムのIDを入力": "分野3のロールのIDを入力",  # 分野3
}

ADMIN_ROLE_ID = "管理者ロールのIDを入力"      # 管理者ロールのID

ATTENDANCE_FILE = "attendance_data.json"
VOTES_FILE = "persistent_votes.json"
BIRTHDAYS_FILE = "birthdays.json"
REACTION_ROLES_FILE = "reaction_roles.json"
# ------------------

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
    with open(BIRTHDAYS_FILE, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False, indent=4)
@tasks.loop(hours=24)
async def check_birthdays():
    now = datetime.now()
    data = load_birthdays()
    b_users = []
    for uid_str, b in data.items():
        if b["month"] == now.month and b["day"] == now.day:
            b_users.append(int(uid_str))
    if b_users:
        channel = client.get_channel(BIRTHDAY_NOTIFY_CHANNEL_ID)
        if channel:
            mentions = " ".join([f"<@{uid}>" for uid in b_users])
            await channel.send(embed=discord.Embed(title="🎉 本日の主役！", description=f"今日は {mentions} さんの誕生日です！おめでとうございます！🎂✨", color=discord.Color.gold()))
@check_birthdays.before_loop
async def before_check_birthdays():
    await client.wait_until_ready()

async def restore_persistent_views(bot):
    data = load_votes_data()
    for msg_id_str in data.get("schedules", {}):
        bot.add_view(ScheduleView(restored=True), message_id=int(msg_id_str))
    for msg_id_str in data.get("polls", {}):
        bot.add_view(PollView(restored=True), message_id=int(msg_id_str))
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
class MyClient(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync()
client = MyClient()
@client.event
async def on_ready():
    print(f"ログインしました: {client.user}")
    if not monthly_ranking_task.is_running():
        monthly_ranking_task.start()
    if not yearly_ranking_task.is_running():
        yearly_ranking_task.start()
    if not check_birthdays.is_running():
        check_birthdays.start()

# ==========================================
# 1. フォーラム新規投稿通知
# ==========================================
@client.event
async def on_thread_create(thread: discord.Thread):
    if thread.parent_id in FORUM_ROLE_MAP:
        notify_channel = client.get_channel(NOTIFY_CHANNEL_ID)
        if notify_channel is not None:
            role_id = FORUM_ROLE_MAP[thread.parent_id]
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
profile_group = app_commands.Group(name="profile", description="プロフィールに関するコマンド")
@profile_group.command(name="member", description="指定したメンバーの自己紹介を表示します")
@app_commands.describe(member="自己紹介を見たいメンバーを選択（またはIDを入力）")
async def profile_member(interaction: discord.Interaction, member: discord.Member):
    await interaction.response.defer(ephemeral=True)
    intro_channel = client.get_channel(INTRO_CHANNEL_ID)
    if intro_channel is None:
        await interaction.followup.send("自己紹介チャンネルが見つかりませんでした。IDを確認してください。", ephemeral=True)
        return
    found_message = None
    async for message in intro_channel.history(limit=500):
        if message.author.id == member.id:
            found_message = message
            break
    if found_message:
        embed = discord.Embed(
            title=member.display_name,
            description=found_message.content,
            color=discord.Color.blue()
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        await interaction.followup.send(embed=embed, ephemeral=True)
    else:
        await interaction.followup.send(f"**{member.display_name}** さんの自己紹介は見つかりませんでした。", ephemeral=True)
@profile_group.command(name="grade", description="指定した期（例：30期）のメンバーの自己紹介をまとめて自分だけに表示します")
@app_commands.describe(term_name="表示したい期（例: 30期）")
async def profile_grade(interaction: discord.Interaction, term_name: str):
    await interaction.response.defer(ephemeral=True)
    intro_channel = client.get_channel(INTRO_CHANNEL_ID)
    if intro_channel is None:
        await interaction.followup.send("自己紹介チャンネルが見つかりませんでした。IDを確認してください。", ephemeral=True)
        return
    matched_members = []
    for member in intro_channel.guild.members:
        if any(term_name in role.name for role in member.roles):
            matched_members.append(member)
    if not matched_members:
        await interaction.followup.send(f"「{term_name}」に該当するメンバーが見つかりませんでした。", ephemeral=True)
        return
    found_entries = []
    async for message in intro_channel.history(limit=1000):
        for member in matched_members:
            if message.author.id == member.id:
                if not any(e['member'].id == member.id for e in found_entries):
                    found_entries.append({
                        'member': member,
                        'content': message.content,
                        'url': message.jump_url
                    })
    if not found_entries:
        await interaction.followup.send(f"「{term_name}」のメンバーの自己紹介が見つかりませんでした。", ephemeral=True)
        return
    desc_lines = []
    for entry in found_entries[:10]:
        desc_lines.append(f"**{entry['member'].display_name}**\n{entry['content'][:100]}...\n[メッセージへジャンプ]({entry['url']})\n")
    embed = discord.Embed(
        title=f"📋 {term_name} の自己紹介一覧",
        description="\n".join(desc_lines),
        color=discord.Color.green()
    )
    await interaction.followup.send(embed=embed, ephemeral=True)
client.tree.add_command(profile_group)

# ==========================================
# 3. 日程調整・投票システム (/schedule)
# ==========================================
class ScheduleView(discord.ui.View):
    def __init__(self, title: str, dates: list[str], deadline_str: str, deadline_dt: datetime, admin_role_id: int, restored: bool = False):
        super().__init__(timeout=None)
        self.title = title
        self.dates = dates
        self.deadline_str = deadline_str
        self.deadline_dt = deadline_dt
        self.admin_role_id = admin_role_id
        self.votes: dict[int, set[int]] = {i: set() for i in range(len(dates))}
        self.admin_voters: set[int] = set()
        self.uid = uuid.uuid4().hex[:8]
        self.is_closed = restored
        self.message: discord.Message = None
        for idx, date in enumerate(dates):
            button = discord.ui.Button(
                label=f"{date} (0票)", 
                style=discord.ButtonStyle.primary, 
                custom_id=f"vote_{self.uid}_{idx}",
                disabled=restored
            )
            button.callback = self.make_vote_callback(idx)
            self.add_item(button)
        close_btn = discord.ui.Button(
            label="締め切って結果発表", 
            style=discord.ButtonStyle.danger, 
            custom_id=f"close_{self.uid}",
            disabled=restored
        )
        close_btn.callback = self.close_callback
        self.add_item(close_btn)
    def make_vote_callback(self, idx: int):
        async def callback(interaction: discord.Interaction):
            if self.is_closed:
                await interaction.response.send_message("❌ この日程調整はすでに締め切られています。", ephemeral=True)
                return
            user = interaction.user
            is_admin = any(role.id == self.admin_role_id for role in user.roles)
            if is_admin:
                self.admin_voters.add(user.id)
            if user.id in self.votes[idx]:
                self.votes[idx].remove(user.id)
            else:
                self.votes[idx].add(user.id)
            self.admin_voters.clear()
            for date_idx, user_ids in self.votes.items():
                for uid in user_ids:
                    member = interaction.guild.get_member(uid)
                    if member and any(role.id == self.admin_role_id for role in member.roles):
                        self.admin_voters.add(uid)
            await self.update_message(interaction=interaction)
        return callback
    async def close_callback(self, interaction: discord.Interaction):
        if not any(role.id == self.admin_role_id for role in interaction.user.roles):
            await interaction.response.send_message("❌ 締め切り操作は管理者ロールを持つ人だけが行えます。", ephemeral=True)
            return
        if self.is_closed:
            await interaction.response.send_message("❌ すでに締め切られています。", ephemeral=True)
            return
        self.is_closed = True
        for child in self.children:
            child.disabled = True
        await self.update_message(interaction=interaction, closed=True)
        embed = self.build_result_embed()
        await interaction.channel.send(content=f"📅 **{self.title}** の日程調整結果発表！", embed=embed)
        self.stop()
    def build_embed(self, closed: bool = False):
        embed = discord.Embed(
            title=f"📅 日程調整: {self.title}", 
            color=discord.Color.orange() if not closed else discord.Color.green()
        )
        embed.add_field(name="⏳ 締め切り", value=self.deadline_str if self.deadline_str else "なし", inline=False)
        embed.add_field(name="📌 ステータス", value="🟢 投票受付中" if not closed else "🔴 投票締め切り済み", inline=False)
        description_lines = ["行ける日のボタンを押して投票してください（複数選択可）\n"]
        for idx, date in enumerate(self.dates):
            voters = self.votes[idx]
            count = len(voters)
            if idx < len(self.children) - 1:
                self.children[idx].label = f"{date} ({count}票)"
                if closed:
                    self.children[idx].disabled = True
            voter_mentions = " ".join([f"<@{uid}>" for uid in voters]) if voters else "なし"
            description_lines.append(f"**{date}**: {count}票\n   ↳ 投票者: {voter_mentions}")
        embed.description = "\n".join(description_lines)
        return embed
    def build_result_embed(self):
        best_date = None
        max_votes = -1
        description_lines = []
        for idx, date in enumerate(self.dates):
            voters = self.votes[idx]
            count = len(voters)
            voter_mentions = " ".join([f"<@{uid}>" for uid in voters]) if voters else "なし"
            description_lines.append(f"**{date}**: {count}票\n   ↳ 投票者: {voter_mentions}")
            if count > max_votes:
                max_votes = count
                best_date = date
        result_msg = f"🏆 **最有力候補: {best_date}** (最多 {max_votes}票)" if max_votes > 0 else "🏆 有効な投票はありませんでした。"       
        embed = discord.Embed(
            title=f"📅 日程調整結果: {self.title}",
            description=f"{result_msg}\n\n" + "\n".join(description_lines),
            color=discord.Color.green()
        )
        return embed
    async def update_message(self, interaction: discord.Interaction, closed: bool = False):
        embed = self.build_embed(closed=closed)
        if interaction.response.is_done():
            if self.message:
                await self.message.edit(embed=embed, view=self)
        else:
            await interaction.response.edit_message(embed=embed, view=self)
    async def start_auto_close_timer(self):
        if not self.deadline_dt:
            return
        remaining = (self.deadline_dt - datetime.now()).total_seconds()
        if remaining > 0:
            await asyncio.sleep(remaining)
        if not self.is_closed:
            self.is_closed = True
            for child in self.children:
                child.disabled = True
            if self.message:
                try:
                    await self.message.edit(embed=self.build_embed(closed=True), view=self)
                    embed = self.build_result_embed()
                    await self.message.channel.send(content=f"📅 **{self.title}** の日程調整が自動締め切りされ、結果が発表されました！", embed=embed)
                except Exception as e:
                    print(f"自動締め切りエラー: {e}")
@client.tree.command(name="schedule", description="管理者参加必須の日程調整を作成します（自動締め切り対応）")
@app_commands.describe(title="イベント名", dates="候補日をカンマ区切り（例: 11/20, 2026-11-20, 2/29）", deadline="締め切り日時（例: 11/18 23:59）")
async def create_schedule(interaction: discord.Interaction, title: str, dates: str, deadline: str = None):
    date_list = [d.strip() for d in dates.replace("、", ",").split(",") if d.strip()]
    if len(date_list) < 2 or len(date_list) > 20:
        await interaction.response.send_message("候補日は2つ以上、20個以内でカンマ区切りで入力してください。", ephemeral=True)
        return   
    for d in date_list:
        valid = False
        # うるう年（2024年）を基準にすることで、2/29などの日付も正しく通るようにする
        base_year = 2024
        for fmt in ("%m/%d", "%Y-%m-%d", "%Y/%m/%d", "%m月%d日", "%Y年%m月%d日"):
            try:
                if fmt == "%m/%d":
                    target = f"{base_year}/{d}"
                    actual = "%Y/%m/%d"
                elif fmt == "%m月%d日":
                    target = f"{base_year}年{d}"
                    actual = "%Y年%m月%d日"
                else:
                    target = d
                    actual = fmt
                datetime.strptime(target, actual)
                valid = True
                break
            except ValueError:
                continue          
        if not valid:
            await interaction.response.send_message(f"❌ 「{d}」は正しい日付として認識できません。\n「11/20」「2026-11-20」「2/29」等の形式で入力してください。", ephemeral=True)
            return
    deadline_dt = None
    if deadline:
        cleaned = deadline.replace("まで", "").strip()
        for fmt in ("%Y-%m-%d %H:%M", "%m/%d %H:%M", "%Y/%m/%d %H:%M"):
            try:
                parsed = datetime.strptime(cleaned, fmt)
                if fmt == "%m/%d %H:%M":
                    parsed = parsed.replace(year=datetime.now().year)
                deadline_dt = parsed
                break
            except ValueError:
                continue
    view = ScheduleView(title=title, dates=date_list, deadline_str=deadline, deadline_dt=deadline_dt, admin_role_id=ADMIN_ROLE_ID)
    embed = view.build_embed(closed=False)
    await interaction.response.send_message(embed=embed, view=view)
    msg = await interaction.original_response()
    view.message = msg
    if deadline_dt:
        asyncio.create_task(view.start_auto_close_timer())

# ==========================================
# 4. 出席管理システム (/attend pass, /attend entry, /attend ranking, /attend reset)
# ==========================================
def load_attendance_data():
    if os.path.exists(ATTENDANCE_FILE):
        with open(ATTENDANCE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if "dates" not in data:
                data["dates"] = {}
            if "users" not in data:
                data["users"] = {}
            return data
    return {"last_date": "", "today_passcode": None, "dates": {}, "users": {}}
def save_attendance_data(data):
    with open(ATTENDANCE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
def get_fiscal_year(dt: datetime) -> int:
    return dt.year if dt.month >= 4 else dt.year - 1
def is_in_fiscal_year(date_str: str, target_fy: int) -> bool:
    start_prefix = f"{target_fy}-"
    end_prefix = f"{target_fy + 1}-"
    month = int(date_str[5:7])
    return (date_str.startswith(start_prefix) and month >= 4) or (date_str.startswith(end_prefix) and month <= 3)
attend_group = app_commands.Group(name="attend", description="出席管理に関するコマンド")
@attend_group.command(name="pass", description="【管理者用】本日の出席受付を開始し、パスワードを確認・発行します")
async def attend_pass(interaction: discord.Interaction):
    is_admin = any(role.id == ADMIN_ROLE_ID for role in interaction.user.roles)
    if not is_admin:
        await interaction.response.send_message("このコマンドは管理者ロールを持つ人のみ実行できます。", ephemeral=True)
        return    
    today_str = datetime.now().strftime("%Y-%m-%d")
    data = load_attendance_data()    
    if data.get("last_date") == today_str and data.get("today_passcode"):
        passcode = data["today_passcode"]
        is_new = False
    else:
        passcode = f"{random.randint(1000, 9999)}"
        data["last_date"] = today_str
        data["today_passcode"] = passcode
        if today_str not in data["dates"]:
            data["dates"][today_str] = []
        save_attendance_data(data)
        is_new = True       
    status_msg = "新しく本日のパスワードを発行しました！" if is_new else "本日はすでに受付中です（同じパスワードを表示しています）"    
    await interaction.response.send_message(
        f"📋 **{status_msg}**\n"
        f"🔑 本日のパスワード: `{passcode}`\n\n"
        f"メンバーにパスワードを伝えて、`/attend entry <パスワード>` で入力してもらってください。",
        ephemeral=True
    )
@attend_group.command(name="entry", description="本日のパスワードを入力して出席を登録します")
@app_commands.describe(passcode="管理者に教えてもらった4桁のパスワード")
async def attend_entry(interaction: discord.Interaction, passcode: str):
    today_str = datetime.now().strftime("%Y-%m-%d")
    data = load_attendance_data()
    current_passcode = data.get("today_passcode")    
    if not current_passcode or data.get("last_date") != today_str:
        await interaction.response.send_message("現在、本日の出席受付はまだ開始されていません。", ephemeral=True)
        return        
    if passcode != current_passcode:
        await interaction.response.send_message("❌ パスワードが違います。", ephemeral=True)
        return        
    user_id_str = str(interaction.user.id)
    if user_id_str in data["dates"].get(today_str, []):
        await interaction.response.send_message("⚠️ あなたはすでに出席登録済みです！", ephemeral=True)
        return        
    if today_str not in data["dates"]:
        data["dates"][today_str] = []
    data["dates"][today_str].append(user_id_str)    
    if user_id_str not in data["users"]:
        data["users"][user_id_str] = {"name": interaction.user.display_name}
    data["users"][user_id_str]["name"] = interaction.user.display_name    
    save_attendance_data(data)   
    await interaction.response.send_message(f"✅ **出席が完了しました！**（本日の出席者数: {len(data['dates'][today_str])}名）", ephemeral=True)
@attend_group.command(name="ranking", description="出席ランキングを自分だけに表示します")
@app_commands.describe(period="表示する期間を選択してください")
@app_commands.choices(period=[
    app_commands.Choice(name="今月", value="month"),
    app_commands.Choice(name="今年度（4月〜3月）", value="year"),
    app_commands.Choice(name="総合（全期間）", value="total")
])
async def attend_ranking(interaction: discord.Interaction, period: str = "month"):
    data = load_attendance_data()
    dates_dict = data["dates"]
    users_dict = data["users"]
    now = datetime.now()
    current_month_str = now.strftime("%Y-%m")
    current_fy = get_fiscal_year(now)    
    target_dates = []
    for date_str in dates_dict.keys():
        if period == "month" and date_str.startswith(current_month_str):
            target_dates.append(date_str)
        elif period == "year" and is_in_fiscal_year(date_str, current_fy):
            target_dates.append(date_str)
        elif period == "total":
            target_dates.append(date_str)            
    total_days = len(target_dates)
    if total_days == 0 or not dates_dict:
        period_name = "今月" if period == "month" else (f"{current_fy}年度" if period == "year" else "全期間")
        await interaction.response.send_message(f"まだ{period_name}の出席データがありません。", ephemeral=True)
        return       
    user_counts = {}
    for date_str in target_dates:
        for uid in dates_dict[date_str]:
            user_counts[uid] = user_counts.get(uid, 0) + 1           
    if not user_counts:
        await interaction.response.send_message("集計できる出席データがありません。", ephemeral=True)
        return      
    sorted_users = sorted(user_counts.items(), key=lambda x: x[1], reverse=True)
    ranking_lines = []
    current_rank = 1
    for i, (uid, count) in enumerate(sorted_users[:10]):
        if i > 0 and count < sorted_users[i - 1][1]:
            current_rank = i + 1
        u_name = users_dict.get(uid, {}).get("name", "メンバー")
        rate = (count / total_days) * 100
        medal = "🥇" if current_rank == 1 else "🥈" if current_rank == 2 else "🥉" if current_rank == 3 else f"{current_rank}."
        ranking_lines.append(f"{medal} **{u_name}** : {count}回 出席 ({rate:.1f}%)")       
    period_title = "今月" if period == "month" else (f"{current_fy}年度" if period == "year" else "総合")
    embed = discord.Embed(
        title=f"🏆 出席ランキング 【{period_title}】 (全 {total_days} 回開催)",
        description="\n".join(ranking_lines),
        color=discord.Color.orange()
    )   
    user_id_str = str(interaction.user.id)
    my_count = user_counts.get(user_id_str, 0)
    my_rate = (my_count / total_days) * 100 if total_days > 0 else 0
    embed.set_footer(text=f"あなたの記録: {my_count}回出席 ({my_rate:.1f}%)") 
    await interaction.response.send_message(embed=embed, ephemeral=True)
@attend_group.command(name="reset", description="【管理者用】すべての出席データをリセットします")
async def attend_reset(interaction: discord.Interaction):
    is_admin = any(role.id == ADMIN_ROLE_ID for role in interaction.user.roles)
    if not is_admin:
        await interaction.response.send_message("このコマンドは管理者ロールを持つ人のみ実行できます。", ephemeral=True)
        return
    empty_data = {"last_date": "", "today_passcode": None, "dates": {}, "users": {}}
    save_attendance_data(empty_data)
    await interaction.response.send_message("🗑️ すべての出席データをリセットしました！", ephemeral=True)
client.tree.add_command(attend_group)
@tasks.loop(time=time(hour=9, minute=0))
async def monthly_ranking_task():
    now = datetime.now()
    if now.day == 1:
        channel = client.get_channel(RANKING_CHANNEL_ID)
        if channel is None:
            return
        first_day_of_this_month = now.replace(day=1)
        last_day_of_prev_month = first_day_of_this_month - timedelta(days=1)
        prev_month_str = last_day_of_prev_month.strftime("%Y-%m")
        data = load_attendance_data()
        dates_dict = data["dates"]
        users_dict = data["users"]
        target_dates = [d for d in dates_dict.keys() if d.startswith(prev_month_str)]
        total_days = len(target_dates)
        if total_days == 0:
            return
        user_counts = {}
        for date_str in target_dates:
            for uid in dates_dict[date_str]:
                user_counts[uid] = user_counts.get(uid, 0) + 1
        sorted_users = sorted(user_counts.items(), key=lambda x: x[1], reverse=True)
        ranking_lines = []
        current_rank = 1
        for i, (uid, count) in enumerate(sorted_users[:10]):
            if i > 0 and count < sorted_users[i - 1][1]:
                current_rank = i + 1
            u_name = users_dict.get(uid, {}).get("name", "メンバー")
            rate = (count / total_days) * 100
            medal = "🥇" if current_rank == 1 else "🥈" if current_rank == 2 else "🥉" if current_rank == 3 else f"{current_rank}."
            ranking_lines.append(f"{medal} **{u_name}** : {count}回 出席 ({rate:.1f}%)")
        embed = discord.Embed(
            title=f"📢 【月例】前月（{prev_month_str}）の出席ランキング発表！ (全 {total_days} 回)",
            description="先月の出席状況のまとめです！\n\n" + "\n".join(ranking_lines),
            color=discord.Color.gold()
        )
        await channel.send(embed=embed)
@tasks.loop(time=time(hour=9, minute=10))
async def yearly_ranking_task():
    now = datetime.now()
    if now.month == 4 and now.day == 1:
        channel = client.get_channel(RANKING_CHANNEL_ID)
        if channel is None:
            return
        prev_fy = now.year - 1
        data = load_attendance_data()
        dates_dict = data["dates"]
        users_dict = data["users"]
        target_dates = [d for d in dates_dict.keys() if is_in_fiscal_year(d, prev_fy)]
        total_days = len(target_dates)
        if total_days == 0:
            return
        user_counts = {}
        for date_str in target_dates:
            for uid in dates_dict[date_str]:
                user_counts[uid] = user_counts.get(uid, 0) + 1
        sorted_users = sorted(user_counts.items(), key=lambda x: x[1], reverse=True)
        ranking_lines = []
        current_rank = 1
        for i, (uid, count) in enumerate(sorted_users[:10]):
            if i > 0 and count < sorted_users[i - 1][1]:
                current_rank = i + 1
            u_name = users_dict.get(uid, {}).get("name", "メンバー")
            rate = (count / total_days) * 100
            medal = "🥇" if current_rank == 1 else "🥈" if current_rank == 2 else "🥉" if current_rank == 3 else f"{current_rank}."
            ranking_lines.append(f"{medal} **{u_name}** : {count}回 出席 ({rate:.1f}%)")
        embed = discord.Embed(
            title=f"👑 【年度末】{prev_fy}年度 年間出席ランキング発表！ (全 {total_days} 回)",
            description=f"{prev_fy}年度（4月〜3月）を最も盛り上げてくれたメンバーたちです！\n\n" + "\n".join(ranking_lines),
            color=discord.Color.purple()
        )
        await channel.send(embed=embed)

# ==========================================
# 5. リアクションロールシステム (/newrole)
# ==========================================
def load_reaction_roles():
    if os.path.exists(REACTION_ROLES_FILE):
        with open(REACTION_ROLES_FILE, "r", encoding="utf-8") as f:
            return {int(msg_id): val for msg_id, val in json.load(f).items()}
    return {}
def save_reaction_roles(mapping):
    with open(REACTION_ROLES_FILE, "w", encoding="utf-8") as f:
        json.dump({str(k): v for k, v in mapping.items()}, f, ensure_ascii=False, indent=4)
@client.tree.command(name="newrole", description="【管理者用】複数のリアクションロールを一度に作成します")
@app_commands.describe(role_names="ロール名をカンマ区切り（例: 1年, 2年）", emojis="絵文字をカンマ区切り（例: 🍎, 🍊）")
async def newrole(interaction: discord.Interaction, role_names: str, emojis: str):
    if not any(role.id == ADMIN_ROLE_ID for role in interaction.user.roles):
        await interaction.response.send_message("管理者ロールを持つ人のみ実行できます。", ephemeral=True); return
    guild = interaction.guild
    if guild is None:
        await interaction.response.send_message("サーバー内で実行してください。", ephemeral=True); return
    r_list = [r.strip() for r in role_names.replace("、", ",").split(",") if r.strip()]
    e_list = [e.strip() for e in emojis.replace("、", ",").split(",") if e.strip()]
    if len(r_list) != len(e_list):
        await interaction.response.send_message("❌ ロールの数と絵文字の数が一致していません！", ephemeral=True); return
    role_map = {}; desc_lines = ["下のリアクションを押すとロールがもらえます！\n"]
    for r_name, emoji in zip(r_list, e_list):
        role = discord.utils.get(guild.roles, name=r_name)
        if role is None:
            try: role = await guild.create_role(name=r_name, reason="リアクションロール自動作成")
            except discord.Forbidden:
                await interaction.response.send_message(f"❌ 「{r_name}」を作成する権限がありません。", ephemeral=True); return
        role_map[emoji] = role.id; desc_lines.append(f"{emoji} : **{role.name}**")
    embed = discord.Embed(title="✨ ロール付与パネル", description="\n".join(desc_lines), color=discord.Color.purple())
    await interaction.response.send_message("リアクションロールパネルを作成しました！", ephemeral=True)
    msg = await interaction.channel.send(embed=embed)
    for emoji in e_list:
        try: await msg.add_reaction(emoji)
        except discord.HTTPException: pass
    mapping = load_reaction_roles(); mapping[msg.id] = role_map; save_reaction_roles(mapping)
@client.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if payload.user_id == client.user.id: return
    mapping = load_reaction_roles()
    if payload.message_id in mapping:
        guild = client.get_guild(payload.guild_id)
        if guild is None: return
        emoji_str = str(payload.emoji); role_map = mapping[payload.message_id]
        if emoji_str in role_map:
            role = guild.get_role(role_map[emoji_str]); member = guild.get_member(payload.user_id)
            if member is None:
                try: member = await guild.fetch_member(payload.user_id)
                except discord.HTTPException: return
            if role and member:
                try: await member.add_roles(role)
                except discord.Forbidden: pass
@client.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    if payload.user_id == client.user.id: return
    mapping = load_reaction_roles()
    if payload.message_id in mapping:
        guild = client.get_guild(payload.guild_id)
        if guild is None: return
        emoji_str = str(payload.emoji); role_map = mapping[payload.message_id]
        if emoji_str in role_map:
            role = guild.get_role(role_map[emoji_str]); member = guild.get_member(payload.user_id)
            if member is None:
                try: member = await guild.fetch_member(payload.user_id)
                except discord.HTTPException: return
            if role and member:
                try: await member.remove_roles(role)
                except discord.Forbidden: pass

# ==========================================
# 6. 誰でも作れる簡易投票機能 (/poll) 【自動締め切り対応】
# ==========================================
class PollView(discord.ui.View):
    def __init__(self, question: str = "", options: list[str] = [], author_id: int = 0, deadline_str: str = "", restored: bool = False):
        super().__init__(timeout=None)
        self.question = question
        self.options = options
        self.author_id = author_id
        self.deadline_str = deadline_str
        for idx, option in enumerate(options if not restored else []):
            btn = discord.ui.Button(
                label=f"{option} (0票)", 
                style=discord.ButtonStyle.primary, 
                custom_id=f"poll_vote_{idx}",
                disabled=restored
            )
            btn.callback = self.make_vote_callback(idx)
            self.add_item(btn)
        if not restored and options:
            close_btn = discord.ui.Button(
                label="投票を締め切る", 
                style=discord.ButtonStyle.danger, 
                custom_id="poll_close"
            )
            close_btn.callback = self.close_callback
            self.add_item(close_btn)
    def make_vote_callback(self, idx: int):
        async def callback(interaction: discord.Interaction):
            # まずインタラクションを安全にデファード（保留）してタイムアウトを防ぐ
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
            # メッセージの更新
            await self.update_message(interaction, p_data)
        return callback
    async def close_callback(self, interaction: discord.Interaction):
        data_all = load_votes_data()
        msg_id_str = str(interaction.message.id)
        p_data = data_all.get("polls", {}).get(msg_id_str)
        if not p_data:
            await interaction.response.send_message("❌ データが見つかりません。", ephemeral=True)
            return
        if interaction.user.id != p_data["author_id"] and not any(r.id == ADMIN_ROLE_ID for r in interaction.user.roles):
            await interaction.response.send_message("❌ 作成者か管理者のみ実行できます。", ephemeral=True)
            return
        if p_data.get("is_closed", False):
            await interaction.response.send_message("❌ すでに締め切られています。", ephemeral=True)
            return
        p_data["is_closed"] = True
        save_votes_data(data_all)
        for child in self.children:
            child.disabled = True
        await self.update_message(interaction, p_data, closed=True)
        # 結果発表を新しくチャンネルに送信（勝者・メンション付き）
        embed = self.build_result_embed(p_data)
        await interaction.channel.send(content=f"📊 **投票：{self.question}** の結果発表！", embed=embed)
        self.stop()
    def build_embed(self, p_data: dict, closed: bool = False):
        options = p_data["options"]
        votes = {int(k): set(v) for k, v in p_data["votes"].items()}  
        for item in self.children:
            if isinstance(item, discord.ui.Button) and item.custom_id and item.custom_id.startswith("poll_vote_"):
                idx = int(item.custom_id.split("_")[-1])
                if idx < len(options):
                    item.label = f"{options[idx]} ({len(votes.get(idx, set()))}票)"
                    if closed:
                        item.disabled = True
        lines = []
        for idx, option in enumerate(options):
            voters = votes.get(idx, set())
            mentions = " ".join(f"<@{uid}>" for uid in voters) if voters else "なし"
            lines.append(f"**{option}**: {len(voters)}票\n└ 投票者: {mentions}")
        embed = discord.Embed(
            title=f"📊 投票：{p_data['question']}" + (" 【受付終了】" if closed else ""), 
            description="\n\n".join(lines) + (f"\n⏳ 期限: {p_data['deadline_str']}" if p_data['deadline_str'] else ""), 
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
            # 既にdeferされている場合などのフォールバック
            try:
                await interaction.edit_original_response(embed=embed, view=self)
            except Exception:
                pass
@client.tree.command(name="poll", description="誰でも自由に作れる簡易投票を作成します（永続化対応）")
@app_commands.describe(question="質問", options="選択肢（カンマ区切り）", deadline="締め切り日時")
async def create_poll(interaction: discord.Interaction, question: str, options: str, deadline: str = None):
    opt_list = [o.strip() for o in options.replace("、", ",").split(",") if o.strip()]
    if len(opt_list) < 2 or len(opt_list) > 10:
        await interaction.response.send_message("選択肢は2〜10個で指定してください。", ephemeral=True); return
    view = PollView(question=question, options=opt_list, author_id=interaction.user.id, deadline_str=deadline)
    embed = view.build_embed({"question": question, "options": opt_list, "votes": {i: [] for i in range(len(opt_list))}, "deadline_str": deadline or "", "is_closed": False}, closed=False)
    await interaction.response.send_message(embed=embed, view=view)
    msg = await interaction.original_response()
    data_all = load_votes_data()
    data_all.setdefault("polls", {})[str(msg.id)] = {"question": question, "options": opt_list, "author_id": interaction.user.id, "votes": {str(i): [] for i in range(len(opt_list))}, "deadline_str": deadline or "", "is_closed": False}
    save_votes_data(data_all)

# ==========================================
# 7. 誕生日機能 (/birthday entry, /birthday show)
# ==========================================
birthday_group = app_commands.Group(name="birthday", description="誕生日に関するコマンド")
@birthday_group.command(name="entry", description="自分の誕生日を登録します")
@app_commands.describe(month="誕生月の数字（例: 5）", day="誕生日の数字（例: 15）")
async def birthday_register(interaction: discord.Interaction, month: int, day: int):
    # 月ごとの最大日数チェック（2月はうるう年を考慮して29日まで許容）
    days_in_month = [0, 31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    if month < 1 or month > 12 or day < 1 or day > days_in_month[month]:
        await interaction.response.send_message("❌ 正しい月日を入力してください。（2/29も登録可能です）", ephemeral=True)
        return
    data = load_birthdays()
    data[str(interaction.user.id)] = {"month": month, "day": day}
    save_birthdays(data)
    await interaction.response.send_message(f"🎂 誕生日に **{month}月{day}日** を登録しました！", ephemeral=True)
@birthday_group.command(name="show", description="指定したメンバー（または自分）の誕生日を確認します")
@app_commands.describe(member="確認したいメンバー（省略した場合は自分）")
async def birthday_show(interaction: discord.Interaction, member: discord.Member = None):
    target = member or interaction.user
    data = load_birthdays()
    b = data.get(str(target.id))
    if b:
        await interaction.response.send_message(f"👤 **{target.display_name}** さんの誕生日は **{b['month']}月{b['day']}日** です！", ephemeral=True)
    else:
        await interaction.response.send_message(f"❌ **{target.display_name}** さんの誕生日はまだ登録されていません。", ephemeral=True)
@birthday_group.command(name="everyone", description="登録されている全員の誕生日を一覧で表示します")
async def birthday_everyone(interaction: discord.Interaction):
    data = load_birthdays()
    if not data:
        await interaction.response.send_message("❌ 登録されている誕生日はまだありません。", ephemeral=True)
        return
    # 月日順にソートする (month, day でソート)
    sorted_birthdays = sorted(data.items(), key=lambda x: (x[1]["month"], x[1]["day"]))
    lines = []
    for uid_str, b in sorted_birthdays:
        lines.append(f"🎂 **{b['month']}月{b['day']}日** : <@{uid_str}>")
    embed = discord.Embed(
        title="👥 登録メンバー誕生日一覧",
        description="\n".join(lines),
        color=discord.Color.gold()
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)
client.tree.add_command(birthday_group)

# ==========================================
# 8. ヘルプコマンド (/commands)
# ==========================================
@client.tree.command(name="commands", description="Botのコマンド一覧と使い方を確認します")
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
            "└ 管理者必須の日程調整（自動締め切り・永続化）\n"
            "**/poll** `[質問]` `[選択肢]` `[期限]`\n"
            "└ 簡易投票パネル（永続化対応）"
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
            "└ 出席ランキング（今月/今年/総合）\n"
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
```
