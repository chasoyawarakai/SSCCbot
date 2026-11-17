#SSCCbot Ver.4.0
import discord
from discord import app_commands
from discord.ext import tasks
import json
import os
import secrets
import random
import calendar
import shutil
import unicodedata
import asyncio
import threading
from datetime import time, date, datetime, timedelta, timezone

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
        "bot_notify_channel_id": 1234567891234567890, #Botからのお知らせ（起動通知・称号獲得のお知らせ）を送るチャンネルのIDを入力（使わない場合はこの行ごと削除）
        "ranking_channel_id": 1234567891234567890, #出席率ランキング通知を送るチャンネルのIDを入力
        "intro_channel_id": 1234567891234567890, #自己紹介チャンネルのIDを入力
        "birthday_notify_channel_id": 1234567891234567890, #誕生日通知を送るチャンネルのIDを入力
        "vc_notify_channel_id": 1234567891234567890, #VC開店通知を送るチャンネルのIDを入力（使わない場合はこの行ごと削除）
        "welcome_channel_id": 1234567891234567890, #新規参加者の歓迎メッセージを送るチャンネルのIDを入力（使わない場合はこの行ごと削除）
        "suggestion_forum_id": 1234567891234567890, #意見箱のフォーラムチャンネルのIDを入力（使わない場合はこの行ごと削除）
        "suggestion_notify_channel_id": 1234567891234567890, #意見箱に新しい投稿があったときに知らせる、管理者用チャンネルのIDを入力（使わない場合はこの行ごと削除）
        
        # 🏷️ ロールのID
        "admin_role_id": 1234567891234567890, #管理者ロールのIDを入力
        "vc_notify_role_id": 1234567891234567890, #VC開店通知を希望する人のロールのIDを入力（使わない場合はこの行ごと削除）
        "startup_notify_role_id": 1234567891234567890, #Botの起動通知を希望する人のロールのIDを入力（使わない場合はこの行ごと削除）
        
        # 📁 フォーラムID と 🏷️ メンションしたいロールID のペア
        "forum_role_map": {
            1234567891234567890: 1234567891234567890, #一つ目の分野のフォーラムのIDを入力: 一つ目の分野のロールのIDを入力
            1234567891234567890: 1234567891234567890, #二つ目の分野のフォーラムのIDを入力: 二つ目の分野のロールのIDを入力
            # 同様の形式で追加可能
        },

        # 👋 新規参加者への歓迎メッセージの文面（サーバーごとに変えられます。この項目ごと削除すると、標準の文面になります）
        # {intro} は、自己紹介チャンネルへのリンクに置き換わります
        "welcome_lines": [
            "サーバーへようこそ！🎉",
            "まずは {intro} で自己紹介をお願いします。",
            "Botの使い方は、`/commands` で確認できます。",
            "わからないことがあれば、気軽に質問してください！",
        ],

        # 🎖️ 称号ロール（条件を満たした人に、Botが自動でロールを付与します。使わない場合はこの項目ごと削除）
        # "type" の種類:
        #   "attend_total"        … 累計の出席回数が value 回以上
        #   "join_years"          … サーバーに参加してから value 年以上
        #   "birthday_registered" … 誕生日を登録済み（value は不要）
        # ロールは先に作っておき、Botのロールをそれより上に配置してください
        "title_roles": [
            {"role_id": 1234567891234567890, "type": "attend_total", "value": 1},  # 例: 初めての出席
            {"role_id": 1234567891234567890, "type": "attend_total", "value": 10},  # 例: 出席10回
            {"role_id": 1234567891234567890, "type": "join_years", "value": 1},  # 例: サーバー参加1周年
            {"role_id": 1234567891234567890, "type": "birthday_registered"},  # 例: 誕生日登録済み
        ],
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

# --- リアクションロールの同期用の記録（Bot停止中の付け外しを反映するため） ---
REACTION_STATE_FILE = "reaction_role_state.json"
# True にすると、起動時の同期で「パネルにリアクションしていないのに、そのロールを持っている人」からもロールを外します。
# 手動で付与したロールも外れるため、通常は False のままにしてください。
# （1つのロールを1つのパネルだけで管理している場合に、ずれを一括で整理したいときだけ一時的に True にします）
REACTION_ROLE_STRICT_SYNC = False

def rr_state_get(msg_id) -> dict:
    with file_lock:
        return _read_json(REACTION_STATE_FILE, {}).get(str(msg_id), {})

def rr_state_apply(msg_id, emoji=None, add=(), remove=(), **fields):
    """パネルの記録を更新する。add/remove は「Botがロールを付与した人」の増減、fields はチャンネルIDなど"""
    with file_lock:
        state = _read_json(REACTION_STATE_FILE, {})
        entry = state.setdefault(str(msg_id), {})
        entry.update(fields)
        if emoji is not None:
            applied = set(entry.setdefault("applied", {}).get(emoji, []))
            applied |= set(add)
            applied -= set(remove)
            entry["applied"][emoji] = sorted(applied)
        _write_json_atomic(REACTION_STATE_FILE, state)

# --- 予定の通知（/reminder）のデータ ---
REMINDERS_FILE = "reminders.json"
REMINDER_LATE_GRACE_MINUTES = 60   # Bot停止などで遅れた場合、予定の時刻からこの分数以内なら遅れて通知する
REMINDER_MAX_PENDING = 50          # 1サーバーで同時に登録できる予定の数

def load_reminders() -> dict:
    with file_lock:
        data = _read_json(REMINDERS_FILE, {"next_id": 1, "items": {}})
    data.setdefault("next_id", 1)
    data.setdefault("items", {})
    return data

def add_reminder(item: dict) -> int:
    with file_lock:
        data = _read_json(REMINDERS_FILE, {"next_id": 1, "items": {}})
        data.setdefault("items", {})
        rid = data.get("next_id", 1)
        data["next_id"] = rid + 1
        data["items"][str(rid)] = item
        _write_json_atomic(REMINDERS_FILE, data)
    return rid

def mark_reminder(rid, **fields):
    """最新のデータを読み直して更新する（通知中に削除された場合は何もしない）"""
    with file_lock:
        data = _read_json(REMINDERS_FILE, {"next_id": 1, "items": {}})
        item = data.get("items", {}).get(str(rid))
        if item is None:
            return
        item.update(fields)
        _write_json_atomic(REMINDERS_FILE, data)

def delete_reminder(rid, guild_id=None, scope=None, user_id=None):
    """削除できたら、その予定のデータを返す。無い/別サーバー/種類や持ち主が違う予定なら None
    scope は "guild"（管理者が登録した予定）か "personal"（個人用）"""
    with file_lock:
        data = _read_json(REMINDERS_FILE, {"next_id": 1, "items": {}})
        item = data.get("items", {}).get(str(rid))
        if item is None:
            return None
        if guild_id is not None and item.get("guild_id") != guild_id:
            return None
        if scope is not None and item.get("scope", "guild") != scope:
            return None
        if user_id is not None and item.get("user_id") != user_id:
            return None
        del data["items"][str(rid)]
        _write_json_atomic(REMINDERS_FILE, data)
        return item

WEEKDAYS_JA = ["月", "火", "水", "木", "金", "土", "日"]

def fmt_dt_ja(dt: datetime) -> str:
    return f"{dt.year}/{dt.month:02d}/{dt.day:02d}（{WEEKDAYS_JA[dt.weekday()]}） {dt.hour:02d}:{dt.minute:02d}"

def fmt_duration(total_minutes: int) -> str:
    days, rem = divmod(total_minutes, 1440)
    hours, minutes = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days}日")
    if hours:
        parts.append(f"{hours}時間")
    if minutes or not parts:
        parts.append(f"{minutes}分")
    return "".join(parts)

# --- 順位の付け方（同じ回数の人は同順位） ---
def rank_entries(user_counts: dict, users_dict: dict, limit_rank: int = 10, max_rows: int = 30) -> list:
    """(順位, user_id, 回数) のリストを返す。同じ回数なら同順位にする（1位が3人なら全員1位、次は4位）。
    limit_rank 位までを対象にし、同順位の人はまとめて含める（最大 max_rows 行）"""
    ordered = sorted(user_counts.items(), key=lambda x: (-x[1], users_dict.get(x[0], {}).get("name", ""), x[0]))
    result = []
    prev_count = None
    prev_rank = 0
    for i, (uid, count) in enumerate(ordered):
        rank = prev_rank if count == prev_count else i + 1
        if rank > limit_rank or len(result) >= max_rows:
            break
        result.append((rank, uid, count))
        prev_count, prev_rank = count, rank
    return result

def rank_label(rank: int) -> str:
    return {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, f"{rank}.")

# --- 次の誕生日（今日を含む）。うるう年以外の2/29生まれは、誕生日通知と同じく2/28として扱う ---
def next_birthday_date(month: int, day: int, today: date) -> date:
    for year in (today.year, today.year + 1):
        d = 28 if (month == 2 and day == 29 and not calendar.isleap(year)) else day
        candidate = date(year, month, d)
        if candidate >= today:
            return candidate

# --- Botのバージョン（起動通知に表示） ---
BOT_VERSION = "4.0"

# --- 称号ロールの記録（付与済みの記録を残し、手動で外されても再付与しない） ---
TITLES_FILE = "titles.json"
TITLE_TYPES = ("attend_total", "join_years", "birthday_registered")

def get_title_rules(config) -> list:
    """設定の title_roles を読み込む（形式が正しくないものは無視する）"""
    rules = []
    for raw in (config or {}).get("title_roles", []) or []:
        try:
            rtype = raw["type"]
            role_id = int(raw["role_id"])
            value = int(raw.get("value", 1))
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
        if rtype not in TITLE_TYPES:
            continue
        rules.append({"role_id": role_id, "type": rtype, "value": value})
    return rules

def title_entry(guild_id, role_id):
    with file_lock:
        return _read_json(TITLES_FILE, {}).get(str(guild_id), {}).get(str(role_id))

def title_ensure_entry(guild_id, role_id):
    with file_lock:
        data = _read_json(TITLES_FILE, {})
        g = data.setdefault(str(guild_id), {})
        if str(role_id) not in g:
            g[str(role_id)] = {"first_user": None, "first_at": None, "awarded": {}}
            _write_json_atomic(TITLES_FILE, data)

def title_record(guild_id, role_id, user_id, first_candidate=False) -> bool:
    """付与を記録する。このサーバーで初めての獲得者になったら True を返す"""
    with file_lock:
        data = _read_json(TITLES_FILE, {})
        entry = data.setdefault(str(guild_id), {}).setdefault(
            str(role_id), {"first_user": None, "first_at": None, "awarded": {}})
        is_first = bool(first_candidate and not entry["awarded"] and entry.get("first_user") is None)
        now_iso = datetime.now(JST).isoformat()
        entry["awarded"][str(user_id)] = now_iso
        if is_first:
            entry["first_user"] = user_id
            entry["first_at"] = now_iso
        _write_json_atomic(TITLES_FILE, data)
    return is_first

def attend_totals(guild_id) -> dict:
    """サーバーの出席データから、ユーザーごとの累計出席回数を集計する"""
    server = load_attendance_data().get(str(guild_id), {})
    counts = {}
    for uids in server.get("dates", {}).values():
        for uid in uids:
            counts[uid] = counts.get(uid, 0) + 1
    return counts

# --- 繰り返し予定の日付計算 ---
REPEAT_LABELS = {"none": "繰り返しなし", "daily": "毎日", "weekly": "毎週", "monthly": "毎月", "yearly": "毎年"}
PERSONAL_REMINDER_MAX = 10   # 1人が同時に登録できる個人用リマインダーの数
PERSONAL_NOTICE_KEEP_DAYS = 7   # 個人用リマインダーの内容を、ボタンで確認できる期間（日）

def add_delivered(msg_id, user_id, title: str, event_dt_iso: str):
    """個人用リマインダーの通知メッセージと内容を紐付けて保存する（ボタンを押した本人にだけ内容を見せるため）"""
    with file_lock:
        data = _read_json(REMINDERS_FILE, {"next_id": 1, "items": {}})
        data.setdefault("delivered", {})[str(msg_id)] = {
            "user_id": user_id, "title": title, "event_dt": event_dt_iso, "sent_at": datetime.now(JST).isoformat()}
        _write_json_atomic(REMINDERS_FILE, data)

def get_delivered(msg_id):
    with file_lock:
        return _read_json(REMINDERS_FILE, {}).get("delivered", {}).get(str(msg_id))

def purge_delivered():
    """保存期間を過ぎた、個人用リマインダーの内容を削除する"""
    with file_lock:
        data = _read_json(REMINDERS_FILE, {"next_id": 1, "items": {}})
        delivered = data.get("delivered", {})
        cutoff = datetime.now(JST) - timedelta(days=PERSONAL_NOTICE_KEEP_DAYS)
        old = []
        for key, rec in delivered.items():
            try:
                if datetime.fromisoformat(rec.get("sent_at", "")) < cutoff:
                    old.append(key)
            except ValueError:
                old.append(key)
        if old:
            for key in old:
                del delivered[key]
            _write_json_atomic(REMINDERS_FILE, data)

def _add_months(dt: datetime, months: int, anchor_day: int) -> datetime:
    """月を足す。存在しない日（31日→2月など）は、その月の末日にする"""
    year, month0 = divmod(dt.year * 12 + (dt.month - 1) + months, 12)
    month = month0 + 1
    day = min(anchor_day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)

def add_years(dt: datetime, years: int) -> datetime:
    return _add_months(dt, 12 * years, dt.day)

def occurrence_at(anchor: datetime, repeat: str, n: int) -> datetime:
    """最初の予定日時（anchor）から数えて、n回目の繰り返しの日時"""
    if repeat == "daily":
        return anchor + timedelta(days=n)
    if repeat == "weekly":
        return anchor + timedelta(weeks=n)
    if repeat == "monthly":
        return _add_months(anchor, n, anchor.day)
    if repeat == "yearly":
        return _add_months(anchor, 12 * n, anchor.day)
    raise ValueError(f"unknown repeat: {repeat}")

def next_occurrence(anchor: datetime, repeat: str, after: datetime) -> datetime:
    """after より後で、最初の繰り返し日時を返す"""
    if repeat in ("daily", "weekly"):
        step = 86400 if repeat == "daily" else 7 * 86400
        n = int((after - anchor).total_seconds() // step) - 1
    else:
        step_m = 1 if repeat == "monthly" else 12
        n = ((after.year - anchor.year) * 12 + after.month - anchor.month) // step_m - 1
    n = max(0, n)
    while True:
        occ = occurrence_at(anchor, repeat, n)
        if occ > after:
            return occ
        n += 1

def parse_event_dt(text: str):
    """「YYYY-MM-DD HH:MM」（日本時間）を読み取る。全角数字も可。形式が違えば None"""
    try:
        return datetime.strptime(unicodedata.normalize("NFKC", text).strip(), "%Y-%m-%d %H:%M").replace(tzinfo=JST)
    except ValueError:
        return None

def check_repeat_before(repeat: str, before_minutes: int):
    """「繰り返し」と「何分前」の組み合わせに問題があれば、エラーメッセージを返す"""
    if repeat not in REPEAT_LABELS:
        return "❌ 繰り返しの指定が正しくありません。"
    if not 0 <= before_minutes <= 10080:
        return "❌ 「何分前」は0〜10080（1週間）の範囲で指定してください。"
    limit = {"daily": 1439, "weekly": 10079}.get(repeat)
    if limit is not None and before_minutes > limit:
        return f"❌ {REPEAT_LABELS[repeat]}の繰り返しでは、「何分前」は{limit}分以内にしてください（次の予定より前になってしまうため）。"
    return None

def build_reminder_item(event_dt: datetime, content: str, before_minutes: int, repeat: str, **extra) -> dict:
    return {
        "title": content,
        "event_dt": event_dt.isoformat(),
        "anchor_dt": event_dt.isoformat(),   # 繰り返しの基準（最初の予定日時）
        "notify_dt": (event_dt - timedelta(minutes=before_minutes)).isoformat(),
        "before_minutes": before_minutes,
        "repeat": repeat,
        "done": False,
        **extra,
    }

def check_vote_reminder_args(deadline_dt, target_role, remind_before_minutes):
    """/schedule・/poll の「未回答者リマインド」の指定に問題があれば、エラーメッセージを返す"""
    if not 0 <= remind_before_minutes <= 10080:
        return "❌ 「何分前」は0〜10080（1週間）の範囲で指定してください。"
    if remind_before_minutes > 0 and (deadline_dt is None or target_role is None):
        return "❌ 未回答者へのリマインドを設定するには、「期限」と「対象ロール」の両方を指定してください。"
    return None

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
        self.add_view(SuggestionView())  # 意見箱のボタン（再起動後も使えるように登録）
        self.add_view(MyReminderView())  # 個人用リマインダーのボタン（同上）
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
    if not reminder_task.is_running(): reminder_task.start()
    spawn(_safe_notify(sync_reaction_roles))  # Bot停止中に付け外しされたリアクションをロールへ反映
    spawn(_safe_notify(send_startup_notice))  # 起動したことを通知チャンネルへ知らせる

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
@app_commands.describe(
    title="日程調整のタイトル",
    dates="候補日（例: 5/1, 5/2, 5/3）",
    deadline="期限（例: YYYY-MM-DD HH:MM あるいは なし）",
    target_role="回答してほしい人のロール（未回答者へのリマインド用・省略可）",
    remind_before_minutes="期限の何分前に、未回答者へリマインドするか（省略時はリマインドなし。例: 1440 で1日前）"
)
@app_commands.guild_only()
async def schedule_command(interaction: discord.Interaction, title: str, dates: str, deadline: str = "なし",
                           target_role: discord.Role = None, remind_before_minutes: int = 0):
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

    remind_error = check_vote_reminder_args(deadline_dt, target_role, remind_before_minutes)
    if remind_error:
        await interaction.response.send_message(remind_error, ephemeral=True)
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
        "votes": {str(i): [] for i in range(len(date_list))},
        "target_role_id": target_role.id if (target_role and remind_before_minutes > 0) else None,
        "remind_before": remind_before_minutes,
        "reminded": False
    }
    
    embed = view.build_embed(s_data, closed=False)
    msg = await interaction.channel.send(embed=embed, view=view)
    
    data_all = load_votes_data()
    data_all.setdefault("schedules", {})[str(msg.id)] = s_data
    save_votes_data(data_all)

    client.add_view(view, message_id=msg.id)
    if deadline_dt:
        spawn(deadline_timer(client, "schedule", str(msg.id), deadline_dt))
    if remind_before_minutes > 0:
        await interaction.followup.send(
            f"⏰ 期限の{fmt_duration(remind_before_minutes)}前に、「{target_role.name}」のうち、まだ回答していない人へリマインドします。", ephemeral=True)


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
    try:
        await check_member_titles(interaction.guild, interaction.user)  # 称号の判定（失敗しても出席登録には影響しない）
    except Exception as e:
        print(f"⚠️ 称号の判定でエラー: {e}")

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

    ranking_lines = []
    period_title = "今月" if period == "month" else "今年度" if period == "year" else "総合"

    for rank, uid, count in rank_entries(user_counts, users_dict):
        u_name = users_dict.get(uid, {}).get("name", "メンバー")
        rate = (count / total_days) * 100 if total_days > 0 else 0
        ranking_lines.append(f"{rank_label(rank)} **{u_name}** : {count}回 出席 ({rate:.1f}%)")

    if not ranking_lines:
        ranking_lines.append("まだ出席データがありません。")

    description = "\n".join(ranking_lines)
    description = clamp_description(description)

    embed = discord.Embed(title=f"🏆 出席ランキング 【{period_title}】 (全 {total_days} 回開催)", description=description, color=discord.Color.orange())
    my_count = user_counts.get(str(interaction.user.id), 0)
    my_rate = (my_count / total_days) * 100 if total_days > 0 else 0
    my_rank_text = f" ／ {1 + sum(1 for c in user_counts.values() if c > my_count)}位" if my_count > 0 else ""
    embed.set_footer(text=f"あなたの記録: {my_count}回出席 ({my_rate:.1f}%){my_rank_text}")
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
    lines = []
    for rank, uid, count in rank_entries(user_counts, users_dict):
        u_name = users_dict.get(uid, {}).get("name", "メンバー")
        rate = (count / total_days) * 100
        lines.append(f"{rank_label(rank)} **{u_name}** : {count}回 出席 ({rate:.1f}%)")
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
    await _safe_notify(run_daily_backup)  # その日の最初の1回だけバックアップ（起動直後にも実行）
    await _safe_notify(scan_titles)       # 称号の確認（参加1周年など、時間の経過で条件を満たすものを含む）
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
    rr_state_apply(msg.id, channel_id=interaction.channel.id)  # 起動時の同期でパネルを見つけるための記録
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
                else:
                    rr_state_apply(payload.message_id, emoji_str, add=[member.id])

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
                else:
                    rr_state_apply(payload.message_id, emoji_str, remove=[member.id])

# --- 起動時の同期: Bot停止中に付け外しされたリアクションを、ロールに反映する ---
async def _find_member(guild: discord.Guild, user_id: int):
    """(メンバー, サーバーから退出済みか) を返す"""
    member = guild.get_member(user_id)
    if member is not None:
        return member, False
    try:
        return await guild.fetch_member(user_id), False
    except discord.NotFound:
        return None, True
    except discord.HTTPException:
        return None, False

async def locate_panel_message(msg_id: int):
    """チャンネルが記録されていない旧パネルを、設定済みサーバーのチャンネルから探す。(メッセージ, 確認できないチャンネルがあったか)"""
    had_errors = False
    for gid in SERVER_CONFIGS:
        guild = client.get_guild(gid)
        if guild is None:
            continue
        for ch in list(guild.text_channels) + list(guild.threads):
            try:
                return await ch.fetch_message(msg_id), had_errors
            except discord.NotFound:
                continue
            except discord.HTTPException:
                had_errors = True  # 権限が無いチャンネルなど
                continue
    return None, had_errors

async def _sync_reaction_panel(msg_id: int, role_map: dict):
    entry = rr_state_get(msg_id)
    if entry.get("missing"):
        return  # 削除済みと分かっているパネル

    channel_id = entry.get("channel_id")
    if channel_id:
        channel = await resolve_channel(client, channel_id)
        if channel is None:
            print(f"⚠️ リアクションロールのパネルのチャンネルが見つかりません (message_id={msg_id})")
            return
        try:
            message = await channel.fetch_message(msg_id)
        except discord.NotFound:
            rr_state_apply(msg_id, missing=True)
            print(f"⚠️ リアクションロールのパネルが削除されていました (message_id={msg_id})。以降の同期は省略します")
            return
        except discord.HTTPException as e:
            print(f"⚠️ リアクションロールのパネルを取得できません (message_id={msg_id}): {e}")
            return
    else:
        message, had_errors = await locate_panel_message(msg_id)
        if message is None:
            if not had_errors:
                rr_state_apply(msg_id, missing=True)
                print(f"⚠️ リアクションロールのパネルが見つかりませんでした (message_id={msg_id})。以降の同期は省略します")
            return
        rr_state_apply(msg_id, channel_id=message.channel.id)

    guild = message.guild
    if guild is None:
        return

    for emoji_str, role_id in role_map.items():
        role = guild.get_role(role_id)
        if role is None:
            print(f"⚠️ ロールが見つかりません (role_id={role_id}, message_id={msg_id})")
            continue

        # 現在このリアクションをしている人
        reactors = set()
        for reaction in message.reactions:
            if str(reaction.emoji) == emoji_str:
                async for user in reaction.users():
                    if not user.bot:
                        reactors.add(user.id)
                break

        applied = set(rr_state_get(msg_id).get("applied", {}).get(emoji_str, []))
        newly_applied, newly_removed = [], []

        # ① リアクションしているのにロールが無い人 → 付与
        for uid in reactors:
            member, _gone = await _find_member(guild, uid)
            if member is None:
                continue
            if role not in member.roles:
                try:
                    await member.add_roles(role)
                except discord.HTTPException as e:
                    print(f"⚠️ ロール付与に失敗 (role={role.name}): {e}")
                    continue
            if uid not in applied:
                newly_applied.append(uid)

        # ② 以前Botが付与したのに、リアクションが外れている人 → 解除
        remove_ids = applied - reactors
        if REACTION_ROLE_STRICT_SYNC:
            remove_ids |= {m.id for m in role.members if not m.bot} - reactors
        for uid in remove_ids:
            member, gone = await _find_member(guild, uid)
            if member is None:
                if gone:
                    newly_removed.append(uid)  # 退出済みなら記録だけ消す
                continue
            if role in member.roles:
                try:
                    await member.remove_roles(role)
                except discord.HTTPException as e:
                    print(f"⚠️ ロール解除に失敗 (role={role.name}): {e}")
                    continue
            newly_removed.append(uid)

        if newly_applied or newly_removed:
            rr_state_apply(msg_id, emoji_str, add=newly_applied, remove=newly_removed)
            print(f"🔄 リアクションロールを同期しました (message_id={msg_id}, {emoji_str}: 付与{len(newly_applied)}件 / 解除{len(newly_removed)}件)")

async def sync_reaction_roles():
    """全パネルについて、現在のリアクションとロールの状態を突き合わせる"""
    async with _get_notify_lock("reaction_sync"):
        for msg_id, role_map in dict(load_reaction_roles()).items():
            try:
                await _sync_reaction_panel(msg_id, role_map)
            except Exception as e:
                print(f"⚠️ リアクションロールの同期でエラー (message_id={msg_id}): {e}")


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
@app_commands.describe(
    question="投票の質問",
    options="選択肢（カンマ区切り 例: はい, いいえ）",
    deadline="期限（例: YYYY-MM-DD HH:MM あるいは なし）",
    target_role="回答してほしい人のロール（未回答者へのリマインド用・省略可）",
    remind_before_minutes="期限の何分前に、未回答者へリマインドするか（省略時はリマインドなし。例: 1440 で1日前）"
)
@app_commands.guild_only()
async def poll_command(interaction: discord.Interaction, question: str, options: str, deadline: str = "なし",
                       target_role: discord.Role = None, remind_before_minutes: int = 0):
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

    remind_error = check_vote_reminder_args(deadline_dt, target_role, remind_before_minutes)
    if remind_error:
        await interaction.response.send_message(remind_error, ephemeral=True)
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
        "votes": {str(i): [] for i in range(len(opt_list))},
        "target_role_id": target_role.id if (target_role and remind_before_minutes > 0) else None,
        "remind_before": remind_before_minutes,
        "reminded": False
    }

    embed = view.build_embed(p_data, closed=False)
    msg = await interaction.channel.send(embed=embed, view=view)

    data_all = load_votes_data()
    data_all.setdefault("polls", {})[str(msg.id)] = p_data
    save_votes_data(data_all)

    client.add_view(view, message_id=msg.id)
    if deadline_dt:
        spawn(deadline_timer(client, "poll", str(msg.id), deadline_dt))
    if remind_before_minutes > 0:
        await interaction.followup.send(
            f"⏰ 期限の{fmt_duration(remind_before_minutes)}前に、「{target_role.name}」のうち、まだ回答していない人へリマインドします。", ephemeral=True)


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
    try:
        await check_member_titles(interaction.guild, interaction.user)
    except Exception as e:
        print(f"⚠️ 称号の判定でエラー: {e}")

@birthday_group.command(name="show", description="誕生日を確認します")
@app_commands.describe(member="確認したいメンバー（省略した場合は自分）")
async def birthday_show(interaction: discord.Interaction, member: discord.Member = None):
    guild_id_str = str(interaction.guild.id)
    target = member or interaction.user
    data = load_birthdays()
    server_birthdays = data.get(guild_id_str, {})
    b = server_birthdays.get(str(target.id))
    if b:
        today = datetime.now(JST).date()
        days = (next_birthday_date(b['month'], b['day'], today) - today).days
        countdown = "🎉 今日が誕生日です！おめでとうございます！" if days == 0 else f"⏳ 次の誕生日まで あと **{days}日** です！"
        await interaction.response.send_message(f"👤 **{target.display_name}** さんの誕生日は **{b['month']}月{b['day']}日** です！\n{countdown}", ephemeral=True)
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
            "└ 誕生日を確認（次の誕生日までの日数つき・自動お祝い通知付き）\n"
            "**/birthday everyone**\n"
            "└ 全員分の誕生日一覧を表示"
        ),
        inline=False
    )
    embed.add_field(
        name="📅 日程調整・投票",
        value=(
            "**/schedule** `[タイトル]` `[候補日]` `[期限]` `[対象ロール]` `[何分前]`\n"
            "└ 【管理者用】日程調整（自動締め切り・永続化・管理者優先集計）\n"
            "**/poll** `[質問]` `[選択肢]` `[期限]` `[対象ロール]` `[何分前]`\n"
            "└ 簡易投票パネル（自動締め切り対応）\n"
            "※ 対象ロールと「何分前」を指定すると、期限の前に、未回答の人へリマインドします"
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
            "**/attend stats**\n"
            "└ 出席の統計（平均出席者数・月別の推移など）\n"
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
            "└ 誰もいないVCに最初の人が入ると、希望者にメンション通知\n"
            "👋 **新規参加者の歓迎**\n"
            "└ サーバー参加時に、歓迎メッセージを自動で投稿"
        ),
        inline=False
    )
    embed.add_field(
        name="🗓️ 予定の通知",
        value=(
            "**/reminder add** `[日時]` `[内容]` `[何分前]` `[繰り返し]` `[ロール]` `[チャンネル]`\n"
            "└ 【管理者用】予定の通知を登録（日時は日本時間・繰り返し可）\n"
            "**/reminder list** / **/reminder delete** `[ID]`\n"
            "└ 登録中の予定の確認 / 【管理者用】削除\n"
            "**/myreminder add** `[日時]` `[内容]` `[何分前]` `[繰り返し]`\n"
            "└ 自分専用の予定を登録（このチャンネルで、あなたにメンション。内容はボタンを押したあなただけに表示）\n"
            "**/myreminder list** / **/myreminder delete** `[ID]`\n"
            "└ 自分の予定の確認 / 削除"
        ),
        inline=False
    )
    embed.add_field(
        name="🎖️ 称号・🗳️ 意見箱",
        value=(
            "**/title list**\n"
            "└ 称号の一覧と、自分の獲得状況を確認\n"
            "**/suggest**\n"
            "└ 匿名で意見・要望を投稿（意見箱のフォーラムに投稿されます。投稿者は誰にも分かりません）"
        ),
        inline=False
    )
    embed.add_field(
        name="🎲 お楽しみ",
        value=(
            "**/omikuji**\n"
            "└ 今日のおみくじ（1日1回・自分だけに表示）\n"
            "**/random member** `[人数]` `[ロール]`\n"
            "└ メンバーからランダムに抽選（重複なし）"
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


# ==========================================
# 11. 予定の通知 (/reminder, /myreminder)・投票の未回答者リマインド
# ==========================================
async def require_admin(interaction: discord.Interaction) -> bool:
    config = SERVER_CONFIGS.get(interaction.guild.id)
    if config is None:
        await interaction.response.send_message("このサーバーはまだBotの設定がされていません。", ephemeral=True)
        return False
    if not any(role.id == config.get("admin_role_id") for role in interaction.user.roles):
        await interaction.response.send_message("❌ このコマンドは管理者ロールを持つ人のみ実行できます。", ephemeral=True)
        return False
    return True

REPEAT_CHOICES = [
    app_commands.Choice(name="繰り返しなし", value="none"),
    app_commands.Choice(name="毎日", value="daily"),
    app_commands.Choice(name="毎週", value="weekly"),
    app_commands.Choice(name="毎月", value="monthly"),
    app_commands.Choice(name="毎年", value="yearly"),
]

def reminder_notice_text(item: dict) -> str:
    before = item.get("before_minutes", 0)
    return f"{fmt_duration(before)}前" if before else "予定の時刻ちょうど"

reminder_group = app_commands.Group(name="reminder", description="予定の通知に関するコマンド", guild_only=True)

@reminder_group.command(name="add", description="【管理者用】予定の通知を登録します")
@app_commands.describe(
    when="予定の日時（日本時間 例: 2026-12-01 19:00）",
    content="予定の内容（例: 定例会）",
    before_minutes="何分前に通知するか（省略時は予定の時刻ちょうど。例: 60 で1時間前）",
    repeat="繰り返し（省略時は1回だけ。毎月・毎年は、日付が同じ日になります）",
    role="通知でメンションするロール（省略可）",
    channel="通知を送るチャンネル（省略時は、このコマンドを実行したチャンネル）"
)
@app_commands.choices(repeat=REPEAT_CHOICES)
async def reminder_add(interaction: discord.Interaction, when: str, content: str, before_minutes: int = 0,
                       repeat: str = "none", role: discord.Role = None, channel: discord.TextChannel = None):
    if not await require_admin(interaction):
        return

    event_dt = parse_event_dt(when)
    if event_dt is None:
        await interaction.response.send_message("❌ 日時の形式が違います。`YYYY-MM-DD HH:MM`（日本時間）で指定してください。", ephemeral=True)
        return
    now = datetime.now(JST)
    if event_dt <= now:
        await interaction.response.send_message("❌ 未来の日時を指定してください。", ephemeral=True)
        return

    content = content.strip()
    if not content or len(content) > 200:
        await interaction.response.send_message("❌ 予定の内容は1〜200文字で指定してください。", ephemeral=True)
        return
    error = check_repeat_before(repeat, before_minutes)
    if error:
        await interaction.response.send_message(error, ephemeral=True)
        return

    target = channel or interaction.channel
    if not isinstance(target, (discord.TextChannel, discord.Thread)):
        await interaction.response.send_message("❌ 通知を送れるチャンネルで実行するか、チャンネルを指定してください。", ephemeral=True)
        return

    pending = sum(1 for it in load_reminders()["items"].values()
                  if it.get("guild_id") == interaction.guild.id and it.get("scope", "guild") == "guild" and not it.get("done"))
    if pending >= REMINDER_MAX_PENDING:
        await interaction.response.send_message(f"❌ 登録できる予定は最大{REMINDER_MAX_PENDING}件までです。不要な予定を削除してください。", ephemeral=True)
        return

    item = build_reminder_item(event_dt, content, before_minutes, repeat,
                               guild_id=interaction.guild.id, channel_id=target.id,
                               role_id=role.id if role else None, author_id=interaction.user.id, scope="guild")
    rid = add_reminder(item)

    lines = [
        f"✅ 予定を登録しました（ID: {rid}）",
        f"🗓️ {fmt_dt_ja(event_dt)}",
        f"📝 {content}",
        f"📣 通知: {reminder_notice_text(item)} → {target.mention}" + (f"（{role.name} をメンション）" if role else ""),
    ]
    if repeat != "none":
        lines.append(f"🔁 {REPEAT_LABELS[repeat]}（削除するまで続きます）")
    if event_dt - timedelta(minutes=before_minutes) <= now:
        lines.append("※ 通知の時刻をすでに過ぎているため、まもなく通知されます。")
    await interaction.response.send_message("\n".join(lines), ephemeral=True)

@reminder_group.command(name="list", description="登録されている予定の通知を一覧表示します")
async def reminder_list(interaction: discord.Interaction):
    items = [(rid, it) for rid, it in load_reminders()["items"].items()
             if it.get("guild_id") == interaction.guild.id and it.get("scope", "guild") == "guild" and not it.get("done")]
    if not items:
        await interaction.response.send_message("登録されている予定はありません。", ephemeral=True)
        return
    items.sort(key=lambda x: x[1]["event_dt"])

    lines = []
    for rid, it in items[:25]:
        repeat_text = f" ／ 🔁 {REPEAT_LABELS.get(it.get('repeat', 'none'), '')}" if it.get("repeat", "none") != "none" else ""
        lines.append(f"**ID {rid}**｜{fmt_dt_ja(datetime.fromisoformat(it['event_dt']))}\n{it['title']}\n"
                     f"└ <#{it['channel_id']}> ／ 通知: {reminder_notice_text(it)}{repeat_text}")
    embed = discord.Embed(title="🗓️ 登録中の予定の通知", description=clamp_description("\n\n".join(lines)), color=discord.Color.orange())
    if len(items) > 25:
        embed.set_footer(text=f"※ 全{len(items)}件のうち、直近の25件のみ表示しています")
    await interaction.response.send_message(embed=embed, ephemeral=True)

@reminder_group.command(name="delete", description="【管理者用】登録した予定の通知を削除します（繰り返しの予定は、以降の分もすべて削除されます）")
@app_commands.describe(reminder_id="削除する予定のID（/reminder list で確認できます）")
async def reminder_delete(interaction: discord.Interaction, reminder_id: int):
    if not await require_admin(interaction):
        return
    removed = delete_reminder(reminder_id, interaction.guild.id, scope="guild")
    if removed is None:
        await interaction.response.send_message(f"❌ ID {reminder_id} の予定は見つかりませんでした。", ephemeral=True)
        return
    await interaction.response.send_message(f"🗑️ 予定を削除しました（ID: {reminder_id}／{removed['title']}）", ephemeral=True)

client.tree.add_command(reminder_group)

# --- 個人用リマインダー（通知は、Botの通知チャンネルで、本人にメンションして送る） ---
myreminder_group = app_commands.Group(name="myreminder", description="自分専用の予定の通知に関するコマンド", guild_only=True)

@myreminder_group.command(name="add", description="自分専用の予定を登録します（このチャンネルで通知。内容はボタンを押したあなただけに表示）")
@app_commands.describe(
    when="予定の日時（日本時間 例: 2026-12-01 19:00）",
    content="予定の内容（例: レポートの提出）",
    before_minutes="何分前に通知するか（省略時は予定の時刻ちょうど）",
    repeat="繰り返し（省略時は1回だけ）"
)
@app_commands.choices(repeat=REPEAT_CHOICES)
async def myreminder_add(interaction: discord.Interaction, when: str, content: str, before_minutes: int = 0, repeat: str = "none"):
    config = SERVER_CONFIGS.get(interaction.guild.id)
    if config is None:
        await interaction.response.send_message("このサーバーはまだBotの設定がされていません。", ephemeral=True)
        return
    target = interaction.channel   # 通知は、このコマンドを実行したチャンネルに送る
    if not isinstance(target, (discord.TextChannel, discord.Thread)):
        await interaction.response.send_message("❌ 通知を送れるチャンネルで実行してください。", ephemeral=True)
        return

    event_dt = parse_event_dt(when)
    if event_dt is None:
        await interaction.response.send_message("❌ 日時の形式が違います。`YYYY-MM-DD HH:MM`（日本時間）で指定してください。", ephemeral=True)
        return
    now = datetime.now(JST)
    if event_dt <= now:
        await interaction.response.send_message("❌ 未来の日時を指定してください。", ephemeral=True)
        return
    content = content.strip()
    if not content or len(content) > 200:
        await interaction.response.send_message("❌ 予定の内容は1〜200文字で指定してください。", ephemeral=True)
        return
    error = check_repeat_before(repeat, before_minutes)
    if error:
        await interaction.response.send_message(error, ephemeral=True)
        return

    mine = sum(1 for it in load_reminders()["items"].values()
               if it.get("scope") == "personal" and it.get("user_id") == interaction.user.id and not it.get("done"))
    if mine >= PERSONAL_REMINDER_MAX:
        await interaction.response.send_message(f"❌ 登録できる個人用の予定は最大{PERSONAL_REMINDER_MAX}件までです。不要な予定を削除してください。", ephemeral=True)
        return

    item = build_reminder_item(event_dt, content, before_minutes, repeat,
                               guild_id=interaction.guild.id, channel_id=target.id,
                               user_id=interaction.user.id, author_id=interaction.user.id, scope="personal")
    rid = add_reminder(item)

    lines = [
        f"✅ 個人用の予定を登録しました（ID: {rid}）",
        f"🗓️ {fmt_dt_ja(event_dt)}",
        f"📝 {content}",
        f"📣 通知: {reminder_notice_text(item)} → このチャンネル（{target.mention}）で、あなたにメンションします",
    ]
    if repeat != "none":
        lines.append(f"🔁 {REPEAT_LABELS[repeat]}（削除するまで続きます）")
    lines.append("🔒 通知の本文に、予定の内容は載りません。ボタンを押した本人（あなた）にだけ、内容が表示されます（他の人には、あなた宛てのリマインドがあることだけが見えます）。")
    await interaction.response.send_message("\n".join(lines), ephemeral=True)

@myreminder_group.command(name="list", description="自分専用に登録している予定の通知を一覧表示します")
async def myreminder_list(interaction: discord.Interaction):
    items = [(rid, it) for rid, it in load_reminders()["items"].items()
             if it.get("scope") == "personal" and it.get("user_id") == interaction.user.id
             and it.get("guild_id") == interaction.guild.id and not it.get("done")]
    if not items:
        await interaction.response.send_message("登録している個人用の予定はありません。", ephemeral=True)
        return
    items.sort(key=lambda x: x[1]["event_dt"])
    lines = []
    for rid, it in items:
        repeat_text = f" ／ 🔁 {REPEAT_LABELS.get(it.get('repeat', 'none'), '')}" if it.get("repeat", "none") != "none" else ""
        lines.append(f"**ID {rid}**｜{fmt_dt_ja(datetime.fromisoformat(it['event_dt']))}\n{it['title']}\n└ 通知: {reminder_notice_text(it)}{repeat_text}")
    embed = discord.Embed(title="📝 あなたの個人用の予定", description=clamp_description("\n\n".join(lines)), color=discord.Color.orange())
    await interaction.response.send_message(embed=embed, ephemeral=True)

@myreminder_group.command(name="delete", description="自分専用に登録した予定の通知を削除します")
@app_commands.describe(reminder_id="削除する予定のID（/myreminder list で確認できます）")
async def myreminder_delete(interaction: discord.Interaction, reminder_id: int):
    removed = delete_reminder(reminder_id, interaction.guild.id, scope="personal", user_id=interaction.user.id)
    if removed is None:
        await interaction.response.send_message(f"❌ ID {reminder_id} の個人用の予定は見つかりませんでした。", ephemeral=True)
        return
    await interaction.response.send_message(f"🗑️ 予定を削除しました（ID: {reminder_id}／{removed['title']}）", ephemeral=True)

client.tree.add_command(myreminder_group)

class MyReminderView(discord.ui.View):
    """個人用リマインダーの通知に付くボタン（押した本人にだけ、内容を表示する）。Botを再起動しても使えるように、固定のIDで登録します"""
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="内容を確認する", emoji="📝", style=discord.ButtonStyle.primary, custom_id="myreminder:show")
    async def show(self, interaction: discord.Interaction, button: discord.ui.Button):
        record = get_delivered(interaction.message.id)
        if record is None:
            await interaction.response.send_message(
                f"❌ このリマインドの内容は、保存期間（{PERSONAL_NOTICE_KEEP_DAYS}日）が過ぎたため表示できません。", ephemeral=True)
            return
        if record["user_id"] != interaction.user.id:
            await interaction.response.send_message("❌ このリマインドは、あなた宛てではありません。", ephemeral=True)
            return
        embed = discord.Embed(
            title="📝 あなたのリマインド",
            description=f"**{record['title']}**\n\n🗓️ {fmt_dt_ja(datetime.fromisoformat(record['event_dt']))}",
            color=discord.Color.orange()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

async def send_reminder(item: dict, event_dt: datetime, now: datetime) -> bool:
    channel = await resolve_channel(client, item["channel_id"])
    if channel is None:
        print(f"⚠️ 予定の通知先チャンネルが見つかりません (channel_id={item['channel_id']})")
        return False
    remaining = int((event_dt - now).total_seconds() + 30) // 60   # 四捨五入して分に
    when_text = f"⏰ あと{fmt_duration(remaining)}" if remaining > 0 else "⏰ 予定の時刻です"

    # 個人用: 本文に内容は載せず、本人にだけメンション。内容は、ボタンを押した本人にだけ表示する
    if item.get("scope") == "personal" and item.get("user_id"):
        user_id = item["user_id"]
        embed = discord.Embed(
            title="📝 マイリマインド",
            description=f"{when_text}\n内容は、下のボタンを押すと、あなただけに表示されます。",
            color=discord.Color.orange()
        )
        try:
            msg = await channel.send(
                content=f"<@{user_id}>", embed=embed, view=MyReminderView(),
                allowed_mentions=discord.AllowedMentions(users=[discord.Object(id=user_id)])
            )
        except discord.HTTPException as e:
            print(f"⚠️ 個人用の予定の通知に失敗 (channel_id={item['channel_id']}): {e}")
            return False
        try:
            add_delivered(msg.id, user_id, item["title"], event_dt.isoformat())
        except Exception as e:
            print(f"⚠️ 個人用の予定の内容の保存に失敗: {e}")   # 通知は送れているので、二重に送らないよう成功扱いにする
        return True

    repeat = item.get("repeat", "none")
    embed = discord.Embed(
        title="📣 予定のお知らせ",
        description=f"**{item['title']}**\n\n🗓️ {fmt_dt_ja(event_dt)}\n{when_text}",
        color=discord.Color.orange()
    )
    if repeat != "none":
        embed.set_footer(text=f"🔁 {REPEAT_LABELS.get(repeat, '')}の予定です")
    content = None
    allowed = discord.AllowedMentions.none()
    if item.get("role_id"):
        content = f"<@&{item['role_id']}>"
        allowed = discord.AllowedMentions(roles=[discord.Object(id=item["role_id"])])
    try:
        await channel.send(content=content, embed=embed, allowed_mentions=allowed)
        return True
    except discord.HTTPException as e:
        print(f"⚠️ 予定の通知に失敗 (channel_id={item['channel_id']}): {e}")
        return False

def roll_reminder(rid, item: dict, after: datetime, now=None):
    """繰り返しの予定を、after より後の次の日時へ進める。
    now を渡すと、通知の時刻がすでに過ぎている回は飛ばす（連続して通知されるのを防ぐ）"""
    anchor = datetime.fromisoformat(item.get("anchor_dt") or item["event_dt"])
    repeat = item.get("repeat", "none")
    before = timedelta(minutes=item.get("before_minutes", 0))
    next_event = next_occurrence(anchor, repeat, after)
    if now is not None:
        for _ in range(1000):
            if next_event - before > now:
                break
            next_event = next_occurrence(anchor, repeat, next_event)
    mark_reminder(rid, event_dt=next_event.isoformat(), notify_dt=(next_event - before).isoformat())

async def process_reminders():
    """通知時刻になった予定を送る。Botが止まっていた間の分も、予定の時刻から一定時間内なら遅れて送る。
    繰り返しの予定は、送ったあとに次の日時へ進める"""
    async with _get_notify_lock("reminders"):
        now = datetime.now(JST)
        grace = timedelta(minutes=REMINDER_LATE_GRACE_MINUTES)
        purge_delivered()  # 保存期間を過ぎた、個人用リマインダーの内容を削除
        for rid, item in list(load_reminders()["items"].items()):
            try:
                event_dt = datetime.fromisoformat(item["event_dt"])
                notify_dt = datetime.fromisoformat(item["notify_dt"])
            except (KeyError, ValueError):
                print(f"⚠️ 予定のデータが不正なため無効にしました (ID={rid})")
                mark_reminder(rid, done=True, expired=True)
                continue

            repeat = item.get("repeat", "none")
            if item.get("done"):
                if event_dt < now - timedelta(days=7):
                    delete_reminder(rid)  # 完了から時間が経った予定を整理
                continue
            if now < notify_dt:
                continue
            if now > event_dt + grace:
                if repeat != "none":
                    # 止まっていた間に過ぎた回は飛ばして、次の回へ進める
                    print(f"⚠️ 予定の時刻を大きく過ぎた回の通知を見送りました (ID={rid}: {item.get('title')})")
                    roll_reminder(rid, item, max(event_dt, now - grace - timedelta(seconds=1)))
                else:
                    print(f"⚠️ 予定の時刻を大きく過ぎたため通知を見送りました (ID={rid}: {item.get('title')})")
                    mark_reminder(rid, done=True, expired=True)
                continue
            if await send_reminder(item, event_dt, now):
                if repeat != "none":
                    roll_reminder(rid, item, event_dt, now)
                else:
                    mark_reminder(rid, done=True)
            # 失敗した場合は記録せず、次回（1分後）に再試行（予定の時刻から一定時間を過ぎるまで）

# --- 投票・日程調整の「未回答者リマインド」 ---
def mark_vote_reminded(key: str, msg_id_str: str):
    data_all = load_votes_data()
    item = data_all.get(key, {}).get(msg_id_str)
    if item is not None:
        item["reminded"] = True
        save_votes_data(data_all)

async def send_vote_reminder(msg_id_str: str, item: dict, deadline: datetime, now: datetime) -> bool:
    """未回答の人にメンションを送る。送れた（または送る必要がない）なら True、失敗なら False（次回再試行）"""
    channel = await resolve_channel(client, item["channel_id"])
    if channel is None:
        print(f"⚠️ 未回答者リマインドの送信先が見つかりません (message_id={msg_id_str})")
        return False
    guild = getattr(channel, "guild", None)
    role = guild.get_role(item["target_role_id"]) if guild else None
    if role is None:
        print(f"⚠️ 未回答者リマインドの対象ロールが見つかりません (message_id={msg_id_str})")
        return True

    answered = {int(uid) for uids in item.get("votes", {}).values() for uid in uids}
    pending = [m for m in role.members if not m.bot and m.id not in answered]
    if not pending:
        return True  # 全員回答済み

    title = item.get("title") or item.get("question") or "投票"
    remaining = int((deadline - now).total_seconds() + 30) // 60
    link = f"https://discord.com/channels/{guild.id}/{channel.id}/{msg_id_str}"
    header = f"⏰ **{title}** の回答期限まで あと{fmt_duration(max(remaining, 1))}です。\nまだ回答していない方は、回答をお願いします！\n{link}"

    sent_any = False
    for i in range(0, len(pending), 50):   # メンションが多いときは、50人ずつに分けて送る
        chunk = pending[i:i + 50]
        content = (header + "\n" if i == 0 else "") + " ".join(m.mention for m in chunk)
        try:
            await channel.send(content=content, allowed_mentions=discord.AllowedMentions(users=chunk))
            sent_any = True
        except discord.HTTPException as e:
            print(f"⚠️ 未回答者リマインドの送信に失敗 (message_id={msg_id_str}): {e}")
            return sent_any  # 一部でも送れていたら、重複を避けるため完了扱いにする
    return True

async def process_vote_reminders():
    """期限の少し前に、対象ロールのうち、まだ回答していない人へリマインドを送る"""
    async with _get_notify_lock("vote_reminders"):
        now = datetime.now(JST)
        data = load_votes_data()
        for key in ("schedules", "polls"):
            for msg_id_str, item in list(data.get(key, {}).items()):
                if (item.get("is_closed") or item.get("reminded") or not item.get("target_role_id")
                        or not item.get("remind_before") or not item.get("deadline_dt")):
                    continue
                try:
                    deadline = datetime.fromisoformat(item["deadline_dt"])
                except ValueError:
                    continue
                if now < deadline - timedelta(minutes=item["remind_before"]):
                    continue
                if now >= deadline:
                    mark_vote_reminded(key, msg_id_str)  # もう締め切りの時刻なので、送らない
                    continue
                if await send_vote_reminder(msg_id_str, item, deadline, now):
                    mark_vote_reminded(key, msg_id_str)

@tasks.loop(minutes=1)
async def reminder_task():
    await client.wait_until_ready()
    await _safe_notify(process_reminders)
    await _safe_notify(process_vote_reminders)


# ==========================================
# 12. 新規参加者の歓迎メッセージ
# ==========================================
# 設定エリアの welcome_lines が無いサーバーで使う、標準の文面です（サーバーごとの文面は設定エリアで指定できます）
DEFAULT_WELCOME_LINES = [
    "SSCCへようこそ！🎉",
    "まずは {intro} で自己紹介をお願いします。",
    "Botの使い方は、`/commands` で確認できます。",
    "わからないことがあれば、気軽に質問してください！",
]

@client.event
async def on_member_join(member: discord.Member):
    if member.bot:
        return
    config = SERVER_CONFIGS.get(member.guild.id)
    if not config:
        return
    ch_id = config.get("welcome_channel_id")
    if not ch_id:
        return  # 設定されていないサーバーでは何もしない

    channel = await resolve_channel(client, ch_id)
    if channel is None:
        print(f"⚠️ 歓迎メッセージの送信先チャンネルが見つかりません (guild={member.guild.id})")
        return

    intro_id = config.get("intro_channel_id")
    intro = f"<#{intro_id}>" if intro_id else "自己紹介チャンネル"
    lines = config.get("welcome_lines") or DEFAULT_WELCOME_LINES
    if isinstance(lines, str):
        lines = [lines]
    text = clamp_description("\n".join(str(line) for line in lines).replace("{intro}", intro))
    embed = discord.Embed(title=f"👋 ようこそ、{member.display_name} さん！", description=text, color=discord.Color.green())
    embed.set_thumbnail(url=member.display_avatar.url)
    try:
        await channel.send(content=member.mention, embed=embed, allowed_mentions=discord.AllowedMentions(users=[member]))
    except discord.HTTPException as e:
        print(f"⚠️ 歓迎メッセージの送信に失敗 (guild={member.guild.id}): {e}")

# ==========================================
# 13. おみくじ (/omikuji)・メンバー抽選 (/random member)
# ==========================================
# (運勢, 出やすさ, ひとこと) ※ 出やすさは数字が大きいほど出やすい
OMIKUJI_RESULTS = [
    ("大吉", 10, "今日は何をやってもうまくいく予感！思い切って挑戦してみよう。"),
    ("中吉", 20, "いい流れが来ています。前から気になっていたことを始めるチャンス。"),
    ("吉",   25, "穏やかで順調な一日。いつもどおりに過ごせば大丈夫。"),
    ("小吉", 20, "小さな幸せが見つかりそう。身の回りを整えると運気アップ。"),
    ("末吉", 15, "焦らずゆっくりが吉。今日の努力は後から効いてきます。"),
    ("凶",   10, "今日は慎重に。こまめな保存とバックアップを忘れずに。"),
]
OMIKUJI_COLORS = ["赤", "青", "緑", "黄色", "紫", "オレンジ", "ピンク", "水色", "白", "黒", "金色", "銀色"]
OMIKUJI_ITEMS = ["キーボード", "マウス", "USBメモリ", "ノートPC", "イヤホン", "付箋", "コーヒー", "お菓子",
                 "ステッカー", "モバイルバッテリー", "ホワイトボード", "ダークモード"]
OMIKUJI_EMBED_COLORS = {"大吉": "gold", "中吉": "orange", "吉": "green", "小吉": "teal", "末吉": "blue", "凶": "dark_grey"}

def draw_omikuji(user_id: int, today_str: str):
    """同じ人・同じ日なら、何度引いても同じ結果になる（日付が変わると引き直せる）"""
    rng = random.Random(f"omikuji-{user_id}-{today_str}")
    result = rng.choices(OMIKUJI_RESULTS, weights=[r[1] for r in OMIKUJI_RESULTS], k=1)[0]
    return result, rng.choice(OMIKUJI_COLORS), rng.choice(OMIKUJI_ITEMS)

@client.tree.command(name="omikuji", description="今日のおみくじを引きます（1日1回・同じ日は同じ結果）")
@app_commands.guild_only()
async def omikuji_command(interaction: discord.Interaction):
    today_str = datetime.now(JST).strftime("%Y-%m-%d")
    (name, _weight, message), color, item = draw_omikuji(interaction.user.id, today_str)
    color_factory = getattr(discord.Color, OMIKUJI_EMBED_COLORS.get(name, "blurple"), discord.Color.blurple)
    embed = discord.Embed(
        title=f"🎴 {interaction.user.display_name} さんの今日の運勢",
        description=f"**【{name}】**\n{message}",
        color=color_factory()
    )
    embed.add_field(name="🎨 ラッキーカラー", value=color, inline=True)
    embed.add_field(name="🍀 ラッキーアイテム", value=item, inline=True)
    embed.set_footer(text="おみくじは1日1回。日本時間の0時を過ぎると、また引けます。")
    await interaction.response.send_message(embed=embed, ephemeral=True)

random_group = app_commands.Group(name="random", description="ランダム抽選に関するコマンド", guild_only=True)

@random_group.command(name="member", description="サーバーのメンバーからランダムに抽選します（重複なし）")
@app_commands.describe(count="選ぶ人数（省略時は1人。最大20人）", role="抽選の対象にしたいロール（省略時はサーバーの全員）")
async def random_member(interaction: discord.Interaction, count: int = 1, role: discord.Role = None):
    if count < 1 or count > 20:
        await interaction.response.send_message("❌ 人数は1〜20人の範囲で指定してください。", ephemeral=True)
        return
    pool = [m for m in interaction.guild.members if not m.bot and (role is None or role in m.roles)]
    if not pool:
        await interaction.response.send_message("❌ 抽選の対象になるメンバーがいません。", ephemeral=True)
        return
    if count > len(pool):
        await interaction.response.send_message(f"❌ 抽選の対象は{len(pool)}人しかいません。人数を減らしてください。", ephemeral=True)
        return

    winners = secrets.SystemRandom().sample(pool, count)
    embed = discord.Embed(
        title="🎲 抽選結果",
        description="\n".join(f"{i}. {m.mention}" for i, m in enumerate(winners, start=1)),
        color=discord.Color.purple()
    )
    scope = f"ロール「{role.name}」の" if role else "サーバーの"
    embed.set_footer(text=f"{scope}{len(pool)}人から{count}人を抽選しました（重複なし）")
    await interaction.response.send_message(embed=embed)

client.tree.add_command(random_group)

# ==========================================
# 14. データの自動バックアップ
# ==========================================
BACKUP_DIR = "backups"
BACKUP_KEEP_DAYS = 14   # 何日分のバックアップを残すか（これより古いものは自動で削除）

def backup_target_files() -> list:
    return [ATTENDANCE_FILE, VOTES_FILE, BIRTHDAYS_FILE, REACTION_ROLES_FILE,
            NOTIFY_STATE_FILE, REACTION_STATE_FILE, REMINDERS_FILE, TITLES_FILE]

async def run_daily_backup():
    """その日の最初の1回だけ、データファイルを backups/日付/ にコピーする。古い分は自動で削除する。
    復元するときは、Botを止めて、日付フォルダの中身を bot.py と同じフォルダへコピーしてください。"""
    now = datetime.now(JST)
    dest = os.path.join(BACKUP_DIR, now.strftime("%Y-%m-%d"))
    if not os.path.isdir(dest):
        with file_lock:
            existing = [f for f in backup_target_files() if os.path.exists(f)]
            if existing:
                tmp = dest + ".tmp"
                shutil.rmtree(tmp, ignore_errors=True)
                os.makedirs(tmp)
                for f in existing:
                    shutil.copy2(f, os.path.join(tmp, os.path.basename(f)))
                os.replace(tmp, dest)  # コピーがすべて終わってから、日付フォルダとして確定させる
                print(f"💾 バックアップを作成しました: {dest}（{len(existing)}ファイル）")

    cutoff = now.date() - timedelta(days=BACKUP_KEEP_DAYS)
    if os.path.isdir(BACKUP_DIR):
        for name in os.listdir(BACKUP_DIR):
            try:
                folder_date = datetime.strptime(name, "%Y-%m-%d").date()
            except ValueError:
                continue  # 日付の形式でないフォルダには触らない
            if folder_date < cutoff:
                shutil.rmtree(os.path.join(BACKUP_DIR, name), ignore_errors=True)


# ==========================================
# 15. 出席統計 (/attend stats)
# ==========================================
def compute_attendance_stats(dates_dict: dict, user_id: str, now: datetime) -> dict:
    """出席データから、期間ごとの開催回数・延べ出席者数・平均出席者数などを計算する"""
    valid = {}
    for d, uids in dates_dict.items():
        try:
            dt = datetime.strptime(d, "%Y-%m-%d")
        except ValueError:
            continue
        valid[d] = (dt, len(uids), user_id in uids)

    def summarize(pred):
        items = [(n, me) for d, (dt, n, me) in valid.items() if pred(d, dt)]
        days = len(items)
        total = sum(n for n, _ in items)
        return {"days": days, "total": total, "avg": (total / days) if days else 0.0, "mine": sum(1 for _, me in items if me)}

    month_key = now.strftime("%Y-%m")
    prev_key = (now.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    fy = get_fiscal_year(now)
    monthly = []
    for i in range(5, -1, -1):   # 直近6か月（古い順）
        year, month0 = divmod(now.year * 12 + (now.month - 1) - i, 12)
        key = f"{year:04d}-{month0 + 1:02d}"
        s = summarize(lambda d, dt, key=key: d.startswith(key))
        monthly.append((key, s["days"], s["avg"]))
    peak = max(((d, n) for d, (dt, n, me) in valid.items()), key=lambda x: (x[1], x[0]), default=None)
    return {
        "month_key": month_key, "prev_key": prev_key, "fy": fy,
        "month": summarize(lambda d, dt: d.startswith(month_key)),
        "prev": summarize(lambda d, dt: d.startswith(prev_key)),
        "year": summarize(lambda d, dt: get_fiscal_year(dt) == fy),
        "total": summarize(lambda d, dt: True),
        "peak": peak,
        "monthly": monthly,
    }

def format_trend_lines(monthly: list) -> str:
    """月ごとの平均出席者数を、文字の棒グラフにする"""
    max_avg = max((avg for _, _, avg in monthly), default=0)
    lines = []
    for key, days, avg in monthly:
        width = 0 if max_avg <= 0 else max(1 if avg > 0 else 0, round(avg / max_avg * 10))
        lines.append(f"{key} {'█' * width:<10} {avg:.1f}人（{days}回）")
    return "\n".join(lines)

def _rate_text(mine: int, days: int) -> str:
    return f"{mine}/{days}回（{(mine / days) * 100:.1f}%）" if days else "開催なし"

@attend_group.command(name="stats", description="出席の統計（平均出席者数・月別の推移など）を表示します")
async def attend_stats(interaction: discord.Interaction):
    data = load_attendance_data()
    dates_dict = data.get(str(interaction.guild.id), {}).get("dates", {})
    now = datetime.now(JST)
    st = compute_attendance_stats(dates_dict, str(interaction.user.id), now)
    if st["total"]["days"] == 0:
        await interaction.response.send_message("まだ出席データがありません。", ephemeral=True)
        return

    m, p, y, a = st["month"], st["prev"], st["year"], st["total"]
    if m["days"] == 0:
        month_text = "今月はまだ開催がありません。"
    else:
        month_text = f"開催 {m['days']}回 ／ 延べ {m['total']}人 ／ 平均 {m['avg']:.1f}人"
    if p["days"] > 0 and m["days"] > 0:
        month_text += f"\n前月比: 開催 {m['days'] - p['days']:+d}回 ／ 平均 {m['avg'] - p['avg']:+.1f}人（前月: {p['days']}回・平均{p['avg']:.1f}人）"
    elif p["days"] == 0:
        month_text += "\n前月は開催がありませんでした。"

    embed = discord.Embed(title="📊 出席統計", color=discord.Color.teal())
    embed.add_field(name=f"📅 今月（{st['month_key']}）", value=month_text, inline=False)
    embed.add_field(name=f"📆 今年度（{st['fy']}年度）", value=f"開催 {y['days']}回 ／ 延べ {y['total']}人 ／ 平均 {y['avg']:.1f}人", inline=False)
    all_text = f"開催 {a['days']}回 ／ 延べ {a['total']}人 ／ 平均 {a['avg']:.1f}人"
    if st["peak"]:
        all_text += f"\n🔥 最多出席: {st['peak'][0]}（{st['peak'][1]}人）"
    embed.add_field(name="🗂️ 全期間", value=all_text, inline=False)
    embed.add_field(name="📈 月別の推移（直近6か月・1回あたりの平均出席者数）", value="```\n" + format_trend_lines(st["monthly"]) + "\n```", inline=False)
    embed.add_field(
        name="🙋 あなたの出席",
        value=f"今月 {_rate_text(m['mine'], m['days'])}\n今年度 {_rate_text(y['mine'], y['days'])}\n全期間 {_rate_text(a['mine'], a['days'])}",
        inline=False
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ==========================================
# 16. 称号ロール (/title list)
# ==========================================
def title_condition_met(rule: dict, member, attend_counts: dict, birthdays: dict, now: datetime) -> bool:
    kind = rule["type"]
    if kind == "attend_total":
        return attend_counts.get(str(member.id), 0) >= rule["value"]
    if kind == "join_years":
        joined = getattr(member, "joined_at", None)
        return bool(joined) and now >= add_years(joined, rule["value"])
    if kind == "birthday_registered":
        return str(member.id) in birthdays
    return False

def describe_title_rule(rule: dict) -> str:
    if rule["type"] == "attend_total":
        return f"累計{rule['value']}回出席"
    if rule["type"] == "join_years":
        return f"サーバーに参加して{rule['value']}年"
    return "誕生日を登録"

def title_progress_text(rule: dict, member, attend_counts: dict, now: datetime) -> str:
    if rule["type"] == "attend_total":
        return f"現在 {attend_counts.get(str(member.id), 0)}/{rule['value']}回"
    if rule["type"] == "join_years":
        joined = getattr(member, "joined_at", None)
        if joined:
            days = (add_years(joined, rule["value"]) - now).days
            if days > 0:
                return f"あと{days}日"
    return ""

async def announce_title(guild: discord.Guild, member: discord.Member, role: discord.Role, is_first: bool):
    config = SERVER_CONFIGS.get(guild.id) or {}
    ch_id = config.get("bot_notify_channel_id")
    if not ch_id:
        return
    channel = await resolve_channel(client, ch_id)
    if channel is None:
        print(f"⚠️ 称号のお知らせの送信先が見つかりません (guild={guild.id})")
        return
    if is_first:
        embed = discord.Embed(
            title="🏆 サーバー初の称号獲得！",
            description=f"{member.mention} さんが、このサーバーで**初めて**称号「{role.name}」を獲得しました！\n✨ おめでとうございます！",
            color=discord.Color.gold()
        )
    else:
        embed = discord.Embed(
            title="🎖️ 称号を獲得しました！",
            description=f"{member.mention} さんが称号「{role.name}」を獲得しました！",
            color=discord.Color.green()
        )
    try:
        await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions(users=[member]))
    except discord.HTTPException as e:
        print(f"⚠️ 称号のお知らせの送信に失敗 (guild={guild.id}): {e}")

async def evaluate_member_titles(guild, member, rules, attend_counts, birthdays, now, bootstrap_roles=frozenset()):
    """bootstrap_roles: 初回の整理の対象になっているロールID（お知らせなしで付与し、「初獲得」の扱いにもしない）"""
    for rule in rules:
        role_id = rule["role_id"]
        entry = title_entry(guild.id, role_id)
        if entry is None:
            continue  # まだ初回の整理が済んでいない称号は、整理を待つ
        if str(member.id) in entry.get("awarded", {}):
            continue  # 付与済み（手動で外されても、再付与しない）
        if not title_condition_met(rule, member, attend_counts, birthdays, now):
            continue
        role = guild.get_role(role_id)
        if role is None:
            print(f"⚠️ 称号のロールが見つかりません (role_id={role_id})")
            continue
        silent = role_id in bootstrap_roles
        if role in member.roles:
            title_record(guild.id, role_id, member.id)  # すでに持っている（手動付与など）→ 記録だけ残す
            continue
        first_candidate = (not silent) and not any(m.id != member.id and not m.bot for m in role.members)
        try:
            await member.add_roles(role)
        except discord.HTTPException as e:
            print(f"⚠️ 称号ロールの付与に失敗 (role={role.name}): {e}")
            continue
        is_first = title_record(guild.id, role_id, member.id, first_candidate)
        if not silent:
            await announce_title(guild, member, role, is_first)

async def check_member_titles(guild: discord.Guild, member: discord.Member):
    """出席登録・誕生日登録のあとに、その人の称号を確認する"""
    rules = get_title_rules(SERVER_CONFIGS.get(guild.id))
    if not rules or member.bot:
        return
    async with _get_notify_lock("titles"):
        await evaluate_member_titles(guild, member, rules, attend_totals(guild.id),
                                     load_birthdays().get(str(guild.id), {}), datetime.now(JST))

async def scan_titles():
    """全メンバーの称号を確認する（1日1回）。設定に新しく追加された称号は、初回だけお知らせなしで整理する"""
    async with _get_notify_lock("titles"):
        now = datetime.now(JST)
        today = now.strftime("%Y-%m-%d")
        for guild_id, config in SERVER_CONFIGS.items():
            rules = get_title_rules(config)
            guild = client.get_guild(guild_id)
            if not rules or guild is None:
                continue
            bootstrap = {r["role_id"] for r in rules if title_entry(guild_id, r["role_id"]) is None}
            if not bootstrap and get_notified("title_scan", str(guild_id)) == today:
                continue
            for role_id in bootstrap:
                title_ensure_entry(guild_id, role_id)
            counts = attend_totals(guild_id)
            birthdays = load_birthdays().get(str(guild_id), {})
            for member in list(guild.members):
                if member.bot:
                    continue
                await evaluate_member_titles(guild, member, rules, counts, birthdays, now, bootstrap)
            mark_notified("title_scan", str(guild_id), today)

title_group = app_commands.Group(name="title", description="称号に関するコマンド", guild_only=True)

@title_group.command(name="list", description="称号の一覧と、自分の獲得状況を表示します")
async def title_list(interaction: discord.Interaction):
    guild = interaction.guild
    rules = get_title_rules(SERVER_CONFIGS.get(guild.id))
    if not rules:
        await interaction.response.send_message("このサーバーでは、称号がまだ設定されていません。", ephemeral=True)
        return
    member = interaction.user
    counts = attend_totals(guild.id)
    now = datetime.now(JST)
    blocks = []
    for rule in rules:
        role = guild.get_role(rule["role_id"])
        entry = title_entry(guild.id, rule["role_id"]) or {}
        earned = str(member.id) in entry.get("awarded", {}) or (role is not None and role in member.roles)
        text = f"{'✅' if earned else '🔒'} **{role.name if role else '（ロールが見つかりません）'}**\n└ 条件: {describe_title_rule(rule)}"
        if not earned:
            progress = title_progress_text(rule, member, counts, now)
            if progress:
                text += f"（{progress}）"
        if entry.get("first_user"):
            text += f"\n└ 🏆 サーバー初の獲得者: <@{entry['first_user']}>"
        blocks.append(text)
    embed = discord.Embed(title="🎖️ 称号一覧", description=clamp_description("\n\n".join(blocks)), color=discord.Color.gold())
    embed.set_footer(text="✅ 獲得済み ／ 🔒 未獲得")
    await interaction.response.send_message(embed=embed, ephemeral=True)

client.tree.add_command(title_group)

# ==========================================
# 17. 匿名意見箱 (/suggest)
# ==========================================
# 完全匿名です。投稿者のIDは、記録もログ出力もしません（Botが代わりにフォーラムへ投稿します）。
CLOSED_PREFIX = "【解決済み】"

class SuggestionModal(discord.ui.Modal, title="🗳️ 匿名で意見を投稿"):
    subject = discord.ui.TextInput(label="題名", placeholder="例: 活動日を増やしてほしい", max_length=100)
    body = discord.ui.TextInput(label="内容", style=discord.TextStyle.paragraph,
                                placeholder="意見・要望・質問など、自由に書いてください（匿名で投稿されます）", max_length=3000)

    async def on_submit(self, interaction: discord.Interaction):
        config = SERVER_CONFIGS.get(interaction.guild.id) or {}
        await interaction.response.defer(ephemeral=True)
        forum = await resolve_channel(client, config.get("suggestion_forum_id"))
        if not isinstance(forum, discord.ForumChannel):
            await interaction.followup.send("❌ 意見箱のフォーラムが見つかりませんでした。管理者に連絡してください。", ephemeral=True)
            return

        subject = self.subject.value.strip()[:100] or "（題名なし）"
        embed = discord.Embed(title="🗳️ 匿名の意見", description=self.body.value, color=discord.Color.blurple())
        embed.set_footer(text="この投稿は匿名です。投稿者は、管理者にもBotにも分かりません。")
        try:
            created = await forum.create_thread(name=subject, embed=embed, view=SuggestionView())
        except discord.HTTPException as e:
            print(f"⚠️ 意見箱への投稿に失敗: {e}")   # 投稿者の情報は出力しない
            await interaction.followup.send("❌ 投稿に失敗しました。時間をおいて、もう一度お試しください。", ephemeral=True)
            return
        thread = created.thread

        # 管理者用チャンネルへ通知
        notify_ch = await resolve_channel(client, config.get("suggestion_notify_channel_id"))
        if notify_ch is not None:
            role_id = config.get("admin_role_id")
            snippet = self.body.value if len(self.body.value) <= 200 else self.body.value[:200] + "…"
            notice = discord.Embed(
                title="📮 意見箱に新しい投稿がありました",
                description=f"**{subject}**\n{snippet}\n\n👉 {thread.mention}",
                color=discord.Color.orange()
            )
            try:
                await notify_ch.send(
                    content=f"<@&{role_id}>" if role_id else None,
                    embed=notice,
                    allowed_mentions=discord.AllowedMentions(roles=[discord.Object(id=role_id)]) if role_id else discord.AllowedMentions.none()
                )
            except discord.HTTPException as e:
                print(f"⚠️ 意見箱の管理者通知に失敗: {e}")
        await interaction.followup.send("✅ 匿名で投稿しました。ご意見ありがとうございます！", ephemeral=True)

class SuggestionAddModal(discord.ui.Modal, title="💬 匿名で意見を追加"):
    body = discord.ui.TextInput(label="内容", style=discord.TextStyle.paragraph,
                                placeholder="この投稿への追加の意見（匿名で投稿されます）", max_length=1500)

    async def on_submit(self, interaction: discord.Interaction):
        thread = interaction.channel
        if not isinstance(thread, discord.Thread) or thread.archived or thread.locked:
            await interaction.response.send_message("❌ この投稿はクローズされているため、意見を追加できません。", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        embed = discord.Embed(title="💬 匿名の追加意見", description=self.body.value, color=discord.Color.light_grey())
        try:
            await thread.send(embed=embed)
        except discord.HTTPException as e:
            print(f"⚠️ 意見の追加に失敗: {e}")
            await interaction.followup.send("❌ 投稿に失敗しました。", ephemeral=True)
            return
        await interaction.followup.send("✅ 匿名で投稿しました。", ephemeral=True)

class SuggestionView(discord.ui.View):
    """意見箱の投稿に付くボタン（Botを再起動しても使えるように、固定のIDで登録します）"""
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="匿名で意見を追加", emoji="💬", style=discord.ButtonStyle.primary, custom_id="suggestion:add")
    async def add_opinion(self, interaction: discord.Interaction, button: discord.ui.Button):
        thread = interaction.channel
        if not isinstance(thread, discord.Thread) or thread.archived or thread.locked:
            await interaction.response.send_message("❌ この投稿はクローズされているため、意見を追加できません。", ephemeral=True)
            return
        await interaction.response.send_modal(SuggestionAddModal())

    @discord.ui.button(label="解決してクローズ（管理者）", emoji="✅", style=discord.ButtonStyle.success, custom_id="suggestion:close")
    async def close_thread(self, interaction: discord.Interaction, button: discord.ui.Button):
        config = SERVER_CONFIGS.get(interaction.guild.id) or {}
        if not any(role.id == config.get("admin_role_id") for role in interaction.user.roles):
            await interaction.response.send_message("❌ クローズできるのは、管理者ロールを持つ人のみです。", ephemeral=True)
            return
        thread = interaction.channel
        if not isinstance(thread, discord.Thread):
            await interaction.response.send_message("❌ この操作は、意見箱の投稿の中でのみ使えます。", ephemeral=True)
            return
        await interaction.response.send_message(f"✅ {interaction.user.display_name} さんが、解決済みとしてクローズしました。")
        new_name = thread.name if thread.name.startswith(CLOSED_PREFIX) else (CLOSED_PREFIX + thread.name)[:100]
        try:
            await thread.edit(name=new_name, archived=True, locked=True)
        except discord.HTTPException as e:
            print(f"⚠️ 意見箱の投稿のクローズに失敗: {e}")
            await interaction.followup.send("⚠️ クローズに失敗しました。Botに「スレッドの管理」の権限があるか確認してください。", ephemeral=True)

@client.tree.command(name="suggest", description="匿名で意見・要望を投稿します（意見箱のフォーラムに投稿されます）")
@app_commands.guild_only()
async def suggest_command(interaction: discord.Interaction):
    config = SERVER_CONFIGS.get(interaction.guild.id)
    if not config or not config.get("suggestion_forum_id"):
        await interaction.response.send_message("このサーバーでは、意見箱がまだ設定されていません。", ephemeral=True)
        return
    await interaction.response.send_modal(SuggestionModal())

# ==========================================
# 18. Bot起動通知
# ==========================================
_startup_notified = False

async def send_startup_notice():
    """Botが起動（接続）したことを、通知チャンネルへ知らせる（起動ごとに1回）"""
    global _startup_notified
    if _startup_notified:
        return
    _startup_notified = True
    now = datetime.now(JST)
    for guild_id, config in SERVER_CONFIGS.items():
        ch_id = config.get("bot_notify_channel_id")
        if not ch_id:
            continue
        channel = await resolve_channel(client, ch_id)
        if channel is None:
            print(f"⚠️ 起動通知の送信先チャンネルが見つかりません (guild={guild_id})")
            continue
        role_id = config.get("startup_notify_role_id")
        embed = discord.Embed(
            title="🟢 SSCCbotが起動しました",
            description=f"バージョン: Ver.{BOT_VERSION}\n起動時刻: {fmt_dt_ja(now)}",
            color=discord.Color.green()
        )
        try:
            await channel.send(
                content=f"<@&{role_id}>" if role_id else None,
                embed=embed,
                allowed_mentions=discord.AllowedMentions(roles=[discord.Object(id=role_id)]) if role_id else discord.AllowedMentions.none()
            )
        except discord.HTTPException as e:
            print(f"⚠️ 起動通知の送信に失敗 (guild={guild_id}): {e}")


client.run(TOKEN)
