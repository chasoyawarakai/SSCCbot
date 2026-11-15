#SSCCbot Ver.3.8
import discord
from discord import app_commands
from discord.ext import tasks
import json
import os
import secrets
import unicodedata
import asyncio
import threading
from datetime import time, datetime, timedelta, timezone

# --- ⚙️ タイムゾーン（日本時間）の定義 ---
JST = timezone(timedelta(hours=9))

# --- ⚙️ 設定エリア（サーバーごとにIDを紐付ける場所） ---
TOKEN = "botのトークンを入力"

# サーバーごとの設定を管理する辞書
SERVER_CONFIGS = {
    # サーバーの名前を入力(メモ用)
    1234567891234567890: {  #サーバーのIDを入力
        # 💬 テキストチャンネルのID
        "notify_channel_id": 1234567891234567890, #フォーラム作成通知を送るチャンネルのIDを入力
        "ranking_channel_id": 1234567891234567890, #出席率ランキング通知を送るチャンネルのIDを入力
        "intro_channel_id": 1234567891234567890, #自己紹介チャンネルのIDを入力
        "birthday_notify_channel_id": 1234567891234567890, #誕生日通知を送るチャンネルのIDを入力
        "vc_notify_channel_id": 1234567891234567890, #VC開店通知を送るチャンネルのIDを入力
        
        # 🏷️ ロールのID
        "admin_role_id": 1234567891234567890, #管理者ロールのIDを入力
        "vc_notify_role_id": 1234567891234567890, #VC開店通知を希望する人のロールのIDを入力
        
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

# ファイル書き込み時の競合を防ぐための排他ロック
file_lock = threading.Lock()

# バックグラウンドタスク消失防止用
_background_tasks = set()

def spawn(coro):
    t = asyncio.create_task(coro)
    _background_tasks.add(t)
    t.add_done_callback(_background_tasks.discard)
    return t

# --- データ読み書き関数（排他制御・原子的書き込み対応） ---
def _read_json(path, default):
    """JSONを読み込む。ファイルが無い場合は default を返す。
    ファイルが壊れていた場合は別名に退避した上で default を返す（起動不能を防ぐ）"""
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        backup = f"{path}.corrupt-{datetime.now(JST).strftime('%Y%m%d-%H%M%S')}"
        try:
            os.replace(path, backup)
        except OSError:
            pass
        print(f"⚠️ {path} が破損していたため {backup} に退避しました: {e}")
        return default

def _write_json_atomic(path, data):
    """一時ファイルに書いてから置き換える（書き込み途中のクラッシュでファイルが壊れない）"""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)

def load_attendance_data():
    with file_lock:
        return _read_json(ATTENDANCE_FILE, {})

def save_attendance_data(data):
    with file_lock:
        _write_json_atomic(ATTENDANCE_FILE, data)

def load_votes_data():
    with file_lock:
        return _read_json(VOTES_FILE, {"schedules": {}, "polls": {}})

def save_votes_data(data):
    with file_lock:
        _write_json_atomic(VOTES_FILE, data)

def load_birthdays():
    with file_lock:
        return _read_json(BIRTHDAYS_FILE, {})

def save_birthdays(data):
    with file_lock:
        _write_json_atomic(BIRTHDAYS_FILE, data)

# リアクションロールは全リアクションで参照されるため、メモリにキャッシュする
_reaction_roles_cache = None

def load_reaction_roles():
    global _reaction_roles_cache
    with file_lock:
        if _reaction_roles_cache is None:
            raw = _read_json(REACTION_ROLES_FILE, {})
            _reaction_roles_cache = {int(msg_id): val for msg_id, val in raw.items()}
        return _reaction_roles_cache

def save_reaction_roles(data):
    global _reaction_roles_cache
    with file_lock:
        _reaction_roles_cache = data
        _write_json_atomic(REACTION_ROLES_FILE, {str(k): v for k, v in data.items()})

# --- 出席パスワードの総当たり対策（メモリ上で管理） ---
ATTEND_MAX_FAILS = 5        # この回数間違えるとロック
ATTEND_LOCK_MINUTES = 10    # ロック（失敗の記録を保持）する分数
_attend_fails = {}

def _recent_fails(key):
    now = datetime.now(JST)
    fails = [t for t in _attend_fails.get(key, []) if now - t < timedelta(minutes=ATTEND_LOCK_MINUTES)]
    _attend_fails[key] = fails
    return fails

# --- 定期通知の「通知済み記録」（再起動後の取りこぼし補完・二重送信防止） ---
NOTIFY_STATE_FILE = "notify_state.json"
NOTIFY_CATCHUP_DAYS = 3   # 月例/年度末ランキングを、予定日時から何日以内なら遅れて送るか

def get_notified(section: str, key: str):
    with file_lock:
        return _read_json(NOTIFY_STATE_FILE, {}).get(section, {}).get(key)

def mark_notified(section: str, key: str, value: str):
    # 毎回最新を読み直して保存する（他の通知の記録を巻き戻さないため）
    with file_lock:
        state = _read_json(NOTIFY_STATE_FILE, {})
        state.setdefault(section, {})[key] = value
        _write_json_atomic(NOTIFY_STATE_FILE, state)

_notify_locks = {}

def _get_notify_lock(name: str) -> asyncio.Lock:
    # イベントループ起動後に生成する（モジュール読み込み時に作るとPython3.9以前で問題になるため）
    lock = _notify_locks.get(name)
    if lock is None:
        lock = _notify_locks[name] = asyncio.Lock()
    return lock

async def _safe_notify(func):
    """通知処理で予期しないエラーが出てもタスクが止まらないようにする"""
    try:
        await func()
    except Exception as e:
        print(f"⚠️ {func.__name__} で予期しないエラー: {e}")

# --- 表示まわりの共通ヘルパー ---
async def resolve_channel(bot, channel_id):
    """キャッシュに無い場合はAPIから取得する（見つからなければ None）"""
    ch = bot.get_channel(channel_id)
    if ch is not None:
        return ch
    try:
        return await bot.fetch_channel(channel_id)
    except discord.HTTPException:
        return None

def format_mentions(voters, limit: int = 900) -> str:
    """投票者のメンションを、メンションの途中で切れないように整形する"""
    if not voters:
        return "なし"
    parts = [f"<@{uid}>" for uid in sorted(voters)]
    result = []
    length = 0
    for i, p in enumerate(parts):
        add = len(p) + (1 if result else 0)
        if length + add > limit:
            return " ".join(result) + f" ... (ほか{len(parts) - i}人)"
        result.append(p)
        length += add
    return " ".join(result)

def clamp_description(text: str, limit: int = 4000) -> str:
    """Embedの文字数制限対策。行単位で切って省略表示を付ける"""
    if len(text) <= limit:
        return text
    cut = text[:limit - 30]
    nl = cut.rfind("\n")
    if nl > 0:
        cut = cut[:nl]
    return cut + "\n...(文字数制限により一部省略)"

def parse_list(text: str) -> list[str]:
    """カンマ区切り（全角の「，」「、」も可）をリスト化。空欄と重複は除く"""
    normalized = text.replace("，", ",").replace("、", ",")
    seen = set()
    result = []
    for item in normalized.split(","):
        item = item.strip()
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result

def get_fiscal_year(dt: datetime) -> int:
    return dt.year if dt.month >= 4 else dt.year - 1

def safe_fiscal_year(date_str: str):
    """日付文字列から年度を返す。不正な形式なら None"""
    try:
        return get_fiscal_year(datetime.strptime(date_str, "%Y-%m-%d"))
    except ValueError:
        return None


intents = discord.Intents.default()
intents.message_content = True
intents.members = True

class MyClient(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await restore_persistent_views(self)
        for gid in SERVER_CONFIGS:
            guild = discord.Object(id=gid)
            self.tree.copy_global_to(guild=guild)
            try:
                await self.tree.sync(guild=guild)
            except discord.HTTPException as e:
                # Botが未参加/権限不足のサーバーがあっても起動を止めない
                print(f"⚠️ コマンド同期に失敗 (guild={gid}): {e}")

        # 過去のバージョンでグローバル登録されたコマンドを削除する
        # （サーバー限定のコマンドと重なって、同じコマンドが2個表示されるのを防ぐ）
        self.tree.clear_commands(guild=None)
        try:
            await self.tree.sync()
        except discord.HTTPException as e:
            print(f"⚠️ グローバルコマンドの整理に失敗: {e}")

client = MyClient()

@client.event
async def on_ready():
    print(f"ログインしました: {client.user}")
    if not monthly_ranking_task.is_running(): monthly_ranking_task.start()
    if not yearly_ranking_task.is_running(): yearly_ranking_task.start()
    if not check_birthdays.is_running(): check_birthdays.start()
    if not notification_catchup_task.is_running(): notification_catchup_task.start()

# ==========================================
# 締め切り・結果発表の共通処理（発表に失敗しても、次回起動時に再試行）
# ==========================================
_announcing = set()  # 同じ投稿の結果発表が同時に二重実行されないための印

def mark_announced(key: str, msg_id_str: str):
    """結果発表が成功したことを記録する"""
    data_all = load_votes_data()
    item = data_all.get(key, {}).get(msg_id_str)
    if item is not None:
        item["announced"] = True
        save_votes_data(data_all)

async def close_and_announce(bot, kind: str, msg_id_str: str):
    """kind は "schedule" か "poll"。
    未締切なら締め切る → メッセージ更新 → 結果発表 → 成功したら announced=True を保存。
    失敗した場合は announced=False のまま残り、起動時の復元処理でもう一度試行される。
    ※ "announced" キーが無い旧データは「発表済み」として扱う（過去分の再投稿を防ぐ）"""
    await bot.wait_until_ready()
    key = "schedules" if kind == "schedule" else "polls"
    lock_key = (key, msg_id_str)
    if lock_key in _announcing:
        return
    _announcing.add(lock_key)
    try:
        data_all = load_votes_data()
        item = data_all.get(key, {}).get(msg_id_str)
        if item is None:
            return
        if not item.get("is_closed"):
            item["is_closed"] = True
            item["announced"] = False
            save_votes_data(data_all)
        elif item.get("announced", True):
            return  # 発表済み（または旧データ）

        try:
            channel = await resolve_channel(bot, item["channel_id"])
            if channel is None:
                print(f"⚠️ チャンネルが見つからず結果発表できません (message_id={msg_id_str})。次回起動時に再試行します")
                return
            msg = await channel.fetch_message(int(msg_id_str))
            guild = getattr(channel, "guild", None)
            if kind == "schedule":
                view = ScheduleView(
                    title=item["title"],
                    dates=item["dates"],
                    deadline_str=item["deadline_str"],
                    is_closed=True,
                    restored=True
                )
                await msg.edit(embed=view.build_embed(item, closed=True), view=view)
                await channel.send(
                    content=f"📅 **{item['title']}** の日程調整結果発表！",
                    embed=view.build_result_embed(item, guild)
                )
            else:
                view = PollView(
                    question=item["question"],
                    options=item["options"],
                    deadline_str=item["deadline_str"],
                    is_closed=True,
                    restored=True
                )
                await msg.edit(embed=view.build_embed(item, closed=True), view=view)
                await channel.send(
                    content=f"📊 **投票：{item['question']}** の結果発表！",
                    embed=view.build_result_embed(item)
                )
        except discord.NotFound:
            # 元のメッセージ/チャンネルが削除されている場合は、再試行しても無駄なので完了扱いにする
            print(f"⚠️ 元のメッセージが削除されていたため結果発表を省略しました (message_id={msg_id_str})")
            mark_announced(key, msg_id_str)
            return
        except Exception as e:
            print(f"⚠️ 結果発表に失敗しました (message_id={msg_id_str})。次回起動時に再試行します: {e}")
            return

        mark_announced(key, msg_id_str)
    finally:
        _announcing.discard(lock_key)

async def deadline_timer(bot, kind: str, msg_id_str: str, deadline_dt: datetime):
    """期限まで待って、締め切り＆結果発表を行う（期限が過去なら即時実行）"""
    await bot.wait_until_ready()
    delta = (deadline_dt - datetime.now(JST)).total_seconds()
    if delta > 0:
        await asyncio.sleep(delta)
    await close_and_announce(bot, kind, msg_id_str)

async def restore_persistent_views(bot):
    data = load_votes_data()

    for msg_id_str, s_data in data.get("schedules", {}).items():
        try:
            view = ScheduleView(
                title=s_data["title"],
                dates=s_data["dates"],
                deadline_str=s_data["deadline_str"],
                deadline_dt=datetime.fromisoformat(s_data["deadline_dt"]) if s_data.get("deadline_dt") else None,
                is_closed=s_data.get("is_closed", False),
                restored=True
            )
            bot.add_view(view, message_id=int(msg_id_str))

            if not s_data.get("is_closed"):
                if s_data.get("deadline_dt"):
                    dt = datetime.fromisoformat(s_data["deadline_dt"])
                    spawn(deadline_timer(bot, "schedule", msg_id_str, dt))  # 期限切れなら即時に締め切り・発表
            elif s_data.get("announced", True) is False:
                spawn(close_and_announce(bot, "schedule", msg_id_str))  # 結果発表の再試行
        except Exception as e:
            print(f"⚠️ 日程調整の復元に失敗 (message_id={msg_id_str}): {e}")

    for msg_id_str, p_data in data.get("polls", {}).items():
        try:
            view = PollView(
                question=p_data["question"],
                options=p_data["options"],
                deadline_str=p_data["deadline_str"],
                deadline_dt=datetime.fromisoformat(p_data["deadline_dt"]) if p_data.get("deadline_dt") else None,
                is_closed=p_data.get("is_closed", False),
                restored=True
            )
            bot.add_view(view, message_id=int(msg_id_str))

            if not p_data.get("is_closed"):
                if p_data.get("deadline_dt"):
                    dt = datetime.fromisoformat(p_data["deadline_dt"])
                    spawn(deadline_timer(bot, "poll", msg_id_str, dt))
            elif p_data.get("announced", True) is False:
                spawn(close_and_announce(bot, "poll", msg_id_str))
        except Exception as e:
            print(f"⚠️ 投票の復元に失敗 (message_id={msg_id_str}): {e}")

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
# 2. プロフィール参照 (/profile member, /profile role)
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

@profile_group.command(name="role", description="指定したロールを持つメンバーの自己紹介をまとめて表示します")
@app_commands.describe(role="表示したいロールを選択（例: 30期）")
async def profile_role(interaction: discord.Interaction, role: discord.Role):
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

    matched_members = [m for m in interaction.guild.members if role in m.roles]
    if not matched_members:
        await interaction.followup.send(f"「{role.name}」のロールを持つメンバーが見つかりませんでした。", ephemeral=True)
        return

    members_by_id = {m.id: m for m in matched_members}
    found_entries = []
    seen = set()
    async for message in intro_channel.history(limit=1000):
        member = members_by_id.get(message.author.id)
        if member and member.id not in seen:
            seen.add(member.id)
            found_entries.append({'member': member, 'content': message.content, 'url': message.jump_url})

    if not found_entries:
        await interaction.followup.send(f"「{role.name}」のメンバーの自己紹介が見つかりませんでした。", ephemeral=True)
        return

    desc_lines = []
    for e in found_entries[:10]:
        snippet = e['content'][:100] + ("..." if len(e['content']) > 100 else "")
        desc_lines.append(f"**{e['member'].display_name}**\n{snippet}\n[メッセージへジャンプ]({e['url']})\n")
    embed = discord.Embed(title=f"📋 {role.name} の自己紹介一覧", description=clamp_description("\n".join(desc_lines)), color=discord.Color.green())
    if len(found_entries) > 10:
        embed.set_footer(text=f"※ 全{len(found_entries)}名のうち10名のみ表示しています")
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
        
        # 自動締め切りタイマーは、メッセージ送信後（msg.id 確定後）に各コマンド側で spawn します

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

        lock_key = ("schedules", msg_id_str)
        _announcing.add(lock_key)  # 自動締め切りと同時に結果発表が二重に出ないための印（保存の前に付ける）
        try:
            s_data["is_closed"] = True
            s_data["announced"] = False
            save_votes_data(data_all)

            for child in self.children:
                child.disabled = True

            await self.update_message(interaction, s_data, closed=True)
            embed = self.build_result_embed(s_data, guild)
            try:
                await interaction.channel.send(content=f"📅 **{s_data['title']}** の日程調整結果発表！", embed=embed)
                mark_announced("schedules", msg_id_str)
            except discord.HTTPException as e:
                print(f"⚠️ 日程調整の結果発表に失敗（次回起動時に再試行します）: {e}")
        finally:
            _announcing.discard(lock_key)
        self.stop()

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
            mentions = format_mentions(voters)
            lines.append(f"**{date}**: {len(voters)}票\n└ 投票者: {mentions}")
            
        description = "\n".join(lines) + (f"\n\n⏳ 期限: {s_data['deadline_str']}" if s_data['deadline_str'] != "なし" else "")
        description = clamp_description(description)

        embed = discord.Embed(
            title=f"📅 日程調整: {s_data['title']}" + (" 【受付終了】" if closed else ""),
            description=description,
            color=discord.Color.green() if closed else discord.Color.orange()
        )
        return embed

    def build_result_embed(self, s_data: dict, guild: discord.Guild = None):
        dates = s_data["dates"]
        votes = {int(k): set(v) for k, v in s_data["votes"].items()}
        
        best_dates = []
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

            mentions = format_mentions(voters)
                
            lines.append(f"**{date}**: {count}票 (管理者 {admin_count}票)\n└ 投票者: {mentions}")
            
            if count > max_votes or (count == max_votes and admin_count > max_admin_votes):
                max_votes = count
                max_admin_votes = admin_count
                best_dates = [date]
            elif count == max_votes and admin_count == max_admin_votes and count > 0:
                best_dates.append(date)  # 票数・管理者票とも同じ場合は同率として併記

        if max_votes <= 0:
            result_msg = "🏆 有効な投票はありませんでした。"
        elif len(best_dates) == 1:
            result_msg = f"🏆 **最有力候補: {best_dates[0]}** (最多 {max_votes}票 / 管理者 {max_admin_votes}票)"
        else:
            result_msg = f"🤝 **同率の候補: {' / '.join(best_dates)}** (各 {max_votes}票 / 管理者 {max_admin_votes}票)"
        description = f"{result_msg}\n\n" + "\n".join(lines)
        description = clamp_description(description)

        embed = discord.Embed(
            title=f"📅 日程調整結果: {s_data['title']}",
            description=description,
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
        except Exception as e:
            print(f"⚠️ メッセージ更新に失敗: {e}")

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

    date_list = parse_list(dates)
    if not date_list:
        await interaction.response.send_message("❌ 候補日を1つ以上指定してください。", ephemeral=True)
        return
    if len(title) > 200 or any(len(d) > 100 for d in date_list):
        await interaction.response.send_message("❌ タイトルは200文字以内、各候補日は100文字以内にしてください。", ephemeral=True)
        return
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

    client.add_view(view, message_id=msg.id)
    if deadline_dt:
        spawn(deadline_timer(client, "schedule", str(msg.id), deadline_dt))


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
        server_data["today_passcode"] = f"{1000 + secrets.randbelow(9000)}"
        is_new = True
    elif not server_data.get("today_passcode"):
        server_data["today_passcode"] = f"{1000 + secrets.randbelow(9000)}"
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
    passcode = unicodedata.normalize("NFKC", passcode).strip()  # 全角数字・前後の空白を揃える
    guild_id_str = str(interaction.guild.id)
    today_str = datetime.now(JST).strftime("%Y-%m-%d")

    fail_key = (interaction.guild.id, interaction.user.id)
    if len(_recent_fails(fail_key)) >= ATTEND_MAX_FAILS:
        await interaction.response.send_message(
            f"⛔ パスワードを{ATTEND_MAX_FAILS}回間違えたため、しばらく入力できません。（約{ATTEND_LOCK_MINUTES}分後に再度お試しください）",
            ephemeral=True
        )
        return
    
    data = load_attendance_data()
    server_data = data.get(guild_id_str, {"last_date": "", "today_passcode": None, "dates": {}, "users": {}})

    if passcode != server_data.get("today_passcode") or server_data.get("last_date") != today_str:
        _attend_fails.setdefault(fail_key, []).append(datetime.now(JST))
        await interaction.response.send_message("❌ パスワードが違うか、受付が開始されていません。", ephemeral=True)
        return
    _attend_fails.pop(fail_key, None)

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

    description = "\n".join(ranking_lines)
    description = clamp_description(description)

    embed = discord.Embed(title=f"🏆 出席ランキング 【{period_title}】 (全 {total_days} 回開催)", description=description, color=discord.Color.orange())
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
# 5. 自動ランキング通知タスク（JST対応・取りこぼし補完つき）
# ==========================================
def build_ranking_lines(user_counts: dict, users_dict: dict, total_days: int) -> list[str]:
    sorted_users = sorted(user_counts.items(), key=lambda x: x[1], reverse=True)
    lines = []
    for i, (uid, count) in enumerate(sorted_users[:10]):
        rank = i + 1
        medal = "🥇" if rank == 1 else "🥈" if rank == 2 else "🥉" if rank == 3 else f"{rank}."
        u_name = users_dict.get(uid, {}).get("name", "メンバー")
        rate = (count / total_days) * 100
        lines.append(f"{medal} **{u_name}** : {count}回 出席 ({rate:.1f}%)")
    return lines

async def send_ranking_embed(config: dict, guild_id: int, embed: discord.Embed) -> bool:
    """ランキングを送信する。成功（または送信先未設定）なら True、失敗なら False（次回再試行）"""
    ch_id = config.get("ranking_channel_id")
    if not ch_id:
        return True
    channel = await resolve_channel(client, ch_id)
    if channel is None:
        print(f"⚠️ ランキング通知先チャンネルが見つかりません (guild={guild_id})")
        return False
    try:
        await channel.send(embed=embed)
        return True
    except discord.HTTPException as e:
        print(f"⚠️ ランキング通知の送信に失敗 (guild={guild_id}): {e}")
        return False

async def notify_monthly_ranking():
    """毎月1日 9:00 以降、NOTIFY_CATCHUP_DAYS 日以内で、前月分が未通知のサーバーに送る"""
    async with _get_notify_lock("monthly_ranking"):
        now = datetime.now(JST)
        due = now.replace(day=1, hour=9, minute=0, second=0, microsecond=0)
        if not (due <= now < due + timedelta(days=NOTIFY_CATCHUP_DAYS)):
            return
        prev_month_str = (now.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
        data = load_attendance_data()

        for guild_id, config in SERVER_CONFIGS.items():
            guild_id_str = str(guild_id)
            if get_notified("monthly_ranking", guild_id_str) == prev_month_str:
                continue
            server_data = data.get(guild_id_str, {})
            dates_dict = server_data.get("dates", {})
            users_dict = server_data.get("users", {})

            target_dates = [d for d in dates_dict.keys() if d.startswith(prev_month_str)]
            total_days = len(target_dates)
            if total_days > 0:
                user_counts = {}
                for d in target_dates:
                    for uid in dates_dict[d]:
                        user_counts[uid] = user_counts.get(uid, 0) + 1
                embed = discord.Embed(
                    title=f"📢 【月例】前月（{prev_month_str}）出席ランキング！ (全 {total_days} 回)",
                    description="\n".join(build_ranking_lines(user_counts, users_dict, total_days)),
                    color=discord.Color.gold()
                )
                if not await send_ranking_embed(config, guild_id, embed):
                    continue  # 失敗: 記録せず、次回（30分後/起動時）に再試行
            mark_notified("monthly_ranking", guild_id_str, prev_month_str)

async def notify_yearly_ranking():
    """4月1日 9:10 以降、NOTIFY_CATCHUP_DAYS 日以内で、前年度分が未通知のサーバーに送る"""
    async with _get_notify_lock("yearly_ranking"):
        now = datetime.now(JST)
        due = datetime(now.year, 4, 1, 9, 10, tzinfo=JST)
        if not (due <= now < due + timedelta(days=NOTIFY_CATCHUP_DAYS)):
            return
        prev_fy = now.year - 1
        data = load_attendance_data()

        for guild_id, config in SERVER_CONFIGS.items():
            guild_id_str = str(guild_id)
            if get_notified("yearly_ranking", guild_id_str) == str(prev_fy):
                continue
            server_data = data.get(guild_id_str, {})
            dates_dict = server_data.get("dates", {})
            users_dict = server_data.get("users", {})

            target_dates = [d for d in dates_dict.keys() if safe_fiscal_year(d) == prev_fy]
            total_days = len(target_dates)
            if total_days > 0:
                user_counts = {}
                for d in target_dates:
                    for uid in dates_dict[d]:
                        user_counts[uid] = user_counts.get(uid, 0) + 1
                embed = discord.Embed(
                    title=f"👑 【年度末】{prev_fy}年度 年間出席ランキング！ (全 {total_days} 回)",
                    description="\n".join(build_ranking_lines(user_counts, users_dict, total_days)),
                    color=discord.Color.purple()
                )
                if not await send_ranking_embed(config, guild_id, embed):
                    continue
            mark_notified("yearly_ranking", guild_id_str, str(prev_fy))

@tasks.loop(time=time(hour=9, minute=0, tzinfo=JST))
async def monthly_ranking_task():
    await client.wait_until_ready()
    await _safe_notify(notify_monthly_ranking)

@tasks.loop(time=time(hour=9, minute=10, tzinfo=JST))
async def yearly_ranking_task():
    await client.wait_until_ready()
    await _safe_notify(notify_yearly_ranking)

# Botの停止中・送信失敗で取りこぼした通知を補完する（起動直後 + 30分ごと）。
# 「通知済み記録」があるので、定時タスクと重なっても二重には送られません。
@tasks.loop(minutes=30)
async def notification_catchup_task():
    await client.wait_until_ready()
    await _safe_notify(notify_birthdays)
    await _safe_notify(notify_monthly_ranking)
    await _safe_notify(notify_yearly_ranking)


# ==========================================
# 6. リアクションロールシステム (/newrole)
# ==========================================
@client.tree.command(name="newrole", description="【管理者用】リアクションロールパネルを作成します")
@app_commands.describe(
    role_names="ロール名（カンマ区切り 例: 30期, 29期）",
    emojis="絵文字（カンマ区切り 例: 🔴, 🔵）",
    title="パネルの題名（省略時は「✨ ロール付与パネル」）"
)
@app_commands.guild_only()
async def newrole(interaction: discord.Interaction, role_names: str, emojis: str, title: str = ""):
    await interaction.response.defer(ephemeral=True)
    guild_id = interaction.guild.id
    if guild_id not in SERVER_CONFIGS:
        await interaction.followup.send("このサーバーはまだBotの設定がされていません。", ephemeral=True)
        return
    config = SERVER_CONFIGS[guild_id]
    if not any(role.id == config.get("admin_role_id") for role in interaction.user.roles):
        await interaction.followup.send("管理者のみ実行できます。", ephemeral=True)
        return

    r_list = parse_list(role_names)
    e_list = parse_list(emojis)
    if len(r_list) != len(e_list):
        await interaction.followup.send("❌ ロール数と絵文字の数を合わせてください。", ephemeral=True)
        return

    panel_title = title.strip() or "✨ ロール付与パネル"
    if len(panel_title) > 256:
        await interaction.followup.send("❌ 題名は256文字以内にしてください。", ephemeral=True)
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

    embed = discord.Embed(title=panel_title, description="\n".join(desc_lines), color=discord.Color.purple())
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
    if payload.guild_id is None:
        return
    guild = client.get_guild(payload.guild_id)
    if guild is None:
        return
    
    member = payload.member
    if member is None:
        try:
            member = await guild.fetch_member(payload.user_id)
        except discord.HTTPException:
            return

    if member.bot:
        return

    mapping = load_reaction_roles()
    if payload.message_id in mapping:
        role_map = mapping[payload.message_id]
        emoji_str = str(payload.emoji)
        if emoji_str in role_map:
            role = guild.get_role(role_map[emoji_str])
            if role:
                try:
                    await member.add_roles(role)
                except discord.HTTPException as e:
                    print(f"⚠️ ロール付与に失敗 (role={role.name}): {e}")

@client.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    if payload.guild_id is None:
        return
    guild = client.get_guild(payload.guild_id)
    if guild is None:
        return
    
    member = guild.get_member(payload.user_id)
    if member is None:
        try:
            member = await guild.fetch_member(payload.user_id)
        except discord.HTTPException:
            return

    if member.bot:
        return

    mapping = load_reaction_roles()
    if payload.message_id in mapping:
        role_map = mapping[payload.message_id]
        emoji_str = str(payload.emoji)
        if emoji_str in role_map:
            role = guild.get_role(role_map[emoji_str])
            if role:
                try:
                    await member.remove_roles(role)
                except discord.HTTPException as e:
                    print(f"⚠️ ロール解除に失敗 (role={role.name}): {e}")


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

        # 自動締め切りタイマーは、メッセージ送信後（msg.id 確定後）に各コマンド側で spawn します

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

        lock_key = ("polls", msg_id_str)
        _announcing.add(lock_key)  # 自動締め切りと同時に結果発表が二重に出ないための印（保存の前に付ける）
        try:
            p_data["is_closed"] = True
            p_data["announced"] = False
            save_votes_data(data_all)

            for child in self.children:
                child.disabled = True

            await self.update_message(interaction, p_data, closed=True)
            embed = self.build_result_embed(p_data)
            try:
                await interaction.channel.send(content=f"📊 **投票：{p_data['question']}** の結果発表！", embed=embed)
                mark_announced("polls", msg_id_str)
            except discord.HTTPException as e:
                print(f"⚠️ 投票の結果発表に失敗（次回起動時に再試行します）: {e}")
        finally:
            _announcing.discard(lock_key)
        self.stop()

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
            mentions = format_mentions(voters)
            lines.append(f"**{option}**: {len(voters)}票\n└ 投票者: {mentions}")

        description = "\n\n".join(lines) + (f"\n\n⏳ 期限: {p_data['deadline_str']}" if p_data['deadline_str'] != "なし" else "")
        description = clamp_description(description)

        embed = discord.Embed(
            title=f"📊 投票：{p_data['question']}" + (" 【受付終了】" if closed else ""),
            description=description,
            color=discord.Color.green() if closed else discord.Color.blurple()
        )
        return embed

    def build_result_embed(self, p_data: dict):
        options = p_data["options"]
        votes = {int(k): set(v) for k, v in p_data["votes"].items()}
        winners = []
        max_votes = 0
        lines = []
        for idx, option in enumerate(options):
            voters = votes.get(idx, set())
            count = len(voters)
            mentions = format_mentions(voters)
            lines.append(f"**{option}**: {count}票\n└ 投票者: {mentions}")
            if count > max_votes:
                max_votes = count
                winners = [option]
            elif count == max_votes and count > 0:
                winners.append(option)  # 同票は同率首位として併記

        if max_votes <= 0:
            result_msg = "🏆 有効な投票はありませんでした。"
        elif len(winners) == 1:
            result_msg = f"🏆 **勝者: {winners[0]}** (最多 {max_votes}票)"
        else:
            result_msg = f"🤝 **同率首位: {' / '.join(winners)}** (各 {max_votes}票)"
        description = f"{result_msg}\n\n" + "\n".join(lines)
        description = clamp_description(description)

        embed = discord.Embed(
            title=f"📊 投票結果：{p_data['question']}",
            description=description,
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
        except Exception as e:
            print(f"⚠️ メッセージ更新に失敗: {e}")

@client.tree.command(name="poll", description="誰でも自由に作れる簡易投票を作成します（自動締め切り対応）")
@app_commands.describe(question="投票の質問", options="選択肢（カンマ区切り 例: はい, いいえ）", deadline="期限（例: YYYY-MM-DD HH:MM あるいは なし）")
@app_commands.guild_only()
async def poll_command(interaction: discord.Interaction, question: str, options: str, deadline: str = "なし"):
    opt_list = parse_list(options)
    if len(opt_list) < 2:
        await interaction.response.send_message("❌ 選択肢は2つ以上を指定してください（空欄・重複は除かれます）。", ephemeral=True)
        return
    if len(question) > 200 or any(len(o) > 100 for o in opt_list):
        await interaction.response.send_message("❌ 質問は200文字以内、各選択肢は100文字以内にしてください。", ephemeral=True)
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

    client.add_view(view, message_id=msg.id)
    if deadline_dt:
        spawn(deadline_timer(client, "poll", str(msg.id), deadline_dt))


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

    description = "\n".join(lines)
    description = clamp_description(description)

    embed = discord.Embed(title="👥 登録メンバー誕生日一覧", description=description, color=discord.Color.gold())
    await interaction.response.send_message(embed=embed, ephemeral=True)

client.tree.add_command(birthday_group)

async def notify_birthdays():
    """今日が誕生日で、まだ今日の通知をしていないサーバーに送る（失敗・停止中の分は次回に再試行）"""
    async with _get_notify_lock("birthday"):
        now = datetime.now(JST)
        today_str = now.strftime("%Y-%m-%d")
        data = load_birthdays()
        is_leap = (now.year % 4 == 0 and now.year % 100 != 0) or (now.year % 400 == 0)

        for guild_id_str, server_birthdays in data.items():
            try:
                guild_id = int(guild_id_str)
            except ValueError:
                continue
            if guild_id not in SERVER_CONFIGS:
                continue
            if get_notified("birthday", guild_id_str) == today_str:
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
                channel = await resolve_channel(client, ch_id)
                if channel is None:
                    print(f"⚠️ 誕生日通知先チャンネルが見つかりません (guild={guild_id})")
                    continue
                mentions = " ".join([f"<@{uid}>" for uid in b_users])
                embed = discord.Embed(title="🎉 本日の主役！", description=f"今日は {mentions} さんの誕生日です！おめでとうございます！🎂✨", color=discord.Color.gold())
                try:
                    await channel.send(embed=embed)
                except discord.HTTPException as e:
                    print(f"⚠️ 誕生日通知の送信に失敗 (guild={guild_id}): {e}")
                    continue  # 記録せず、次回（30分後/起動時）に再試行
            mark_notified("birthday", guild_id_str, today_str)

@tasks.loop(time=time(hour=0, minute=0, tzinfo=JST))
async def check_birthdays():
    await client.wait_until_ready()
    await _safe_notify(notify_birthdays)


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
            "**/profile role** `[ロール]`\n"
            "└ 指定したロールを持つメンバーの自己紹介をまとめて表示"
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
            "**/newrole** `[ロール名]` `[絵文字]` `[題名]`\n"
            "└ 【管理者用】複数対応リアクションロール作成（題名は省略可）\n"
            "📢 **フォーラム新規投稿通知**\n"
            "└ 投稿時に自動メンション通知\n"
            "📞 **VC開店通知**\n"
            "└ 誰もいないVCに最初の人が入ると、希望者にメンション通知"
        ),
        inline=False
    )
    embed.set_footer(text="※プライベート表示のコマンドもあります")
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ==========================================
# 10. VC開店通知（誰もいないVCに最初の人が入ったとき、希望ロールにメンション）
# ==========================================
VC_NOTIFY_COOLDOWN_MINUTES = 10  # 同じVCで入退室を繰り返したときに、連続で通知しない間隔（分）
_vc_last_notified = {}

@client.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    if member.bot:
        return
    # VCに入った（または別のVCへ移動した）ときだけ見る。退出や、同じVC内のミュート操作などは対象外
    if after.channel is None or before.channel == after.channel:
        return
    channel = after.channel
    if not isinstance(channel, discord.VoiceChannel):
        return
    # 人間が自分1人だけ = 誰もいなかったVCに最初の人が入った（音楽Botなどは人数に数えない）
    if len([m for m in channel.members if not m.bot]) != 1:
        return

    config = SERVER_CONFIGS.get(member.guild.id)
    if not config:
        return
    notify_ch_id = config.get("vc_notify_channel_id")
    role_id = config.get("vc_notify_role_id")
    if not notify_ch_id or not role_id:
        return  # 設定されていないサーバーでは何もしない

    now = datetime.now(JST)
    last = _vc_last_notified.get(channel.id)
    if last and now - last < timedelta(minutes=VC_NOTIFY_COOLDOWN_MINUTES):
        return

    notify_ch = await resolve_channel(client, notify_ch_id)
    if notify_ch is None:
        print(f"⚠️ VC開店通知の送信先チャンネルが見つかりません (guild={member.guild.id})")
        return

    embed = discord.Embed(
        title="📞 VCが開店しました！",
        description=f"**{member.display_name}** さんが {channel.mention} で待っています。\n気軽に遊びに来てください！",
        color=discord.Color.green()
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    try:
        await notify_ch.send(
            content=f"<@&{role_id}>",
            embed=embed,
            allowed_mentions=discord.AllowedMentions(roles=[discord.Object(id=role_id)])
        )
        _vc_last_notified[channel.id] = now
    except discord.HTTPException as e:
        print(f"⚠️ VC開店通知の送信に失敗 (guild={member.guild.id}): {e}")


client.run(TOKEN)
