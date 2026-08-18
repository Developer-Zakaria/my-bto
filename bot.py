# -*- coding: utf-8 -*-
"""
🤖 بوت أب PRO+ — منصة إنشاء بوتات تلغرام | تطوير: @zyh011

كل شي أزرار مدمجة (inline) — ما في أزرار سفلية بتبعت رسائل بالغلط.

المستخدم يختار نوع بوته عند الإنشاء (بوت رسائل، حماية، ألعاب، كازينو،
إذاعة، ترفيه، أدوات). كل نوع بملفه الخاص جوا مجلد bots/.

هذا الملف (bot.py) هو المنسّق: طبقة التخزين المشتركة، البوت الرئيسي
(المنصة)، وتشغيل/إيقاف بوتات الأطفال حسب نوعها.

تخزين دائم PostgreSQL.
"""

import os
import re
import json
import asyncio
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    CommandHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)

# ================== الإعدادات ==================
OWNER_BOT_TOKEN = os.environ.get("OWNER_BOT_TOKEN", "حط_توكن_البوت_الرئيسي_هون")
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
DATA_FILE = os.environ.get("DATA_FILE", "botup_data.json")

DEVELOPER = "@zyh011"
PLATFORM_BOT = os.environ.get("PLATFORM_BOT", "zyh011_bot")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "7584371298"))
# ===============================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("botup")

LINK_PATTERN = re.compile(
    r"(https?://|www\.|t\.me/|telegram\.me/|@\w{4,})", re.IGNORECASE
)
TOKEN_PATTERN = re.compile(r"^\d{6,}:[A-Za-z0-9_\-]{30,}$")

DEFAULT_WELCOME = "🌟 أهلاً وسهلاً!\nاكتب رسالتك هون ورح توصل وارُدّ عليك بأقرب وقت 💬"
DEFAULT_BUSY = "🕓 صاحب البوت مشغول حالياً، رسالتك وصلت ورح يرد عليك قريباً."

# ==================================================================
#            أنواع البوتات المتاحة بالمنصّة
# ==================================================================
BOT_TYPE_LABELS = {
    "messages": "💬 بوت رسائل",
    "protection": "🛡️ بوت حماية",
    "games": "🎮 بوت ألعاب",
    "casino": "🎲 بوت كازينو (نقاط)",
    "broadcast": "📢 بوت إذاعة",
    "fun": "🎉 بوت ترفيه",
    "tools": "🔧 بوت أدوات",
}
BOT_TYPE_ORDER = ["messages", "protection", "games", "casino", "broadcast", "fun", "tools"]
IMPLEMENTED_BOT_TYPES = set(BOT_TYPE_ORDER)


def type_select_kb():
    rows = []
    for key in BOT_TYPE_ORDER:
        label = BOT_TYPE_LABELS[key]
        if key not in IMPLEMENTED_BOT_TYPES:
            label += " 🔜"
        rows.append([InlineKeyboardButton(label, callback_data=f"type:{key}")])
    return InlineKeyboardMarkup(rows)


# owner_id -> توكن ينتظر اختيار نوع البوت
PENDING_TOKEN = {}


# ==================================================================
#          طبقة التخزين
# ==================================================================
USE_DB = bool(DATABASE_URL)
_lock = threading.Lock()

# القيم الافتراضية لأي سجل
def _default_rec(token):
    return {
        "token": token,
        "bot_type": None,      # نوع البوت (messages / protection / games / ...)
        # بوت رسائل
        "blocked": [],
        "muted": [],
        "welcome": "",
        "busy_msg": "",
        "users": {},          # {user_id(str): {"name": str, "count": int}}
        "antilink": True,      # منع الروابط مفعّل
        "paused": False,       # إيقاف الاستقبال
        "busy": False,         # وضع مشغول (يرد رسالة تلقائية)
        # بوت حماية — إعدادات لكل مجموعة أضيف لها البوت
        "groups": {},          # {chat_id(str): {...}}
        # بوت ألعاب
        "scores": {},          # {user_id(str): points(int)}
        # بوت كازينو (نقاط وهمية فقط)
        "casino": {"balances": {}, "last_daily": {}},
        # بوت إذاعة
        "broadcast_stats": {"last_sent": 0, "last_failed": 0, "last_at": ""},
    }


if USE_DB:
    import psycopg

    def _db():
        return psycopg.connect(DATABASE_URL, autocommit=True)

    def _columns(conn):
        rows = conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name='bots'"
        ).fetchall()
        return {r[0] for r in rows}

    def db_init():
        with _db() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS bots (
                    owner_id TEXT PRIMARY KEY
                )
                """
            )
            cols = _columns(conn)
            # نتأكد إنو عمود data موجود
            if "data" not in cols:
                conn.execute("ALTER TABLE bots ADD COLUMN data TEXT DEFAULT ''")
                cols = _columns(conn)
            # ترقية من الشكل القديم (أعمدة منفصلة) للشكل الجديد
            if "token" in cols:
                try:
                    rows = conn.execute(
                        "SELECT owner_id, token, blocked, muted, welcome FROM bots "
                        "WHERE data IS NULL OR data=''"
                    ).fetchall()
                    for row in rows:
                        rec = _default_rec(row[1])
                        try:
                            rec["blocked"] = json.loads(row[2] or "[]")
                            rec["muted"] = json.loads(row[3] or "[]")
                            rec["welcome"] = row[4] or ""
                        except Exception:
                            pass
                        conn.execute(
                            "UPDATE bots SET data=%s WHERE owner_id=%s",
                            (json.dumps(rec, ensure_ascii=False), row[0]),
                        )
                    if rows:
                        log.info(f"↗️ رقّيت {len(rows)} سجل قديم للشكل الجديد")
                except Exception as e:
                    log.warning(f"تخطّي الترقية: {e}")
                # نشيل قيود NOT NULL عن الأعمدة القديمة عشان الإدخال الجديد يشتغل
                for col in ("token", "blocked", "muted", "welcome", "users"):
                    try:
                        conn.execute(f"ALTER TABLE bots ALTER COLUMN {col} DROP NOT NULL")
                    except Exception:
                        pass
        log.info("✅ قاعدة البيانات جاهزة")

    def db_all_bots():
        out = {}
        with _db() as conn:
            # نتأكد إنو عمود data موجود (حماية إضافية)
            if "data" not in _columns(conn):
                return out
            for row in conn.execute("SELECT owner_id, data FROM bots WHERE data IS NOT NULL AND data<>''"):
                try:
                    out[row[0]] = json.loads(row[1])
                except Exception:
                    pass
        return out

    def db_upsert(owner_id, rec):
        with _db() as conn:
            conn.execute(
                """
                INSERT INTO bots (owner_id, data) VALUES (%s,%s)
                ON CONFLICT (owner_id) DO UPDATE SET data=EXCLUDED.data
                """,
                (str(owner_id), json.dumps(rec, ensure_ascii=False)),
            )

    def db_delete(owner_id):
        with _db() as conn:
            conn.execute("DELETE FROM bots WHERE owner_id=%s", (str(owner_id),))


DATA = {"bots": {}}


def _normalize(rec):
    """يتأكد إنو السجل فيه كل المفاتيح الجديدة"""
    base = _default_rec(rec.get("token", ""))
    for k, v in base.items():
        rec.setdefault(k, v)
    # سجلات قديمة بلا bot_type كانت كلها بوت رسائل قبل ما ينضاف اختيار النوع
    if not rec.get("bot_type"):
        rec["bot_type"] = "messages"
    # ترقية: لو users كانت list قديمة، نحولها dict
    if isinstance(rec.get("users"), list):
        rec["users"] = {str(u): {"name": "?", "count": 0} for u in rec["users"]}
    # تعميق الترقية للمفاتيح المتداخلة (لسجلات كتبت قبل إضافة نوع بوت جديد)
    rec.setdefault("casino", {})
    rec["casino"].setdefault("balances", {})
    rec["casino"].setdefault("last_daily", {})
    rec.setdefault("broadcast_stats", {})
    rec["broadcast_stats"].setdefault("last_sent", 0)
    rec["broadcast_stats"].setdefault("last_failed", 0)
    rec["broadcast_stats"].setdefault("last_at", "")
    return rec


def load_all():
    global DATA
    if USE_DB:
        DATA["bots"] = db_all_bots()
    else:
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, "r", encoding="utf-8") as f:
                    DATA = json.load(f)
            except Exception:
                DATA = {"bots": {}}
        DATA.setdefault("bots", {})
    for r in DATA["bots"].values():
        _normalize(r)
    return DATA


def persist(owner_id=None):
    with _lock:
        if USE_DB:
            if owner_id is not None and str(owner_id) in DATA["bots"]:
                db_upsert(owner_id, DATA["bots"][str(owner_id)])
        else:
            tmp = DATA_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(DATA, f, ensure_ascii=False, indent=2)
            os.replace(tmp, DATA_FILE)


def remove_record(owner_id):
    with _lock:
        DATA["bots"].pop(str(owner_id), None)
        if USE_DB:
            db_delete(owner_id)
        else:
            tmp = DATA_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(DATA, f, ensure_ascii=False, indent=2)
            os.replace(tmp, DATA_FILE)


def _bot_record(owner_id):
    return DATA["bots"].get(str(owner_id))


RUNNING = {}
MSG_MAP = {}
PIC_STORE = {}
_pic_counter = [0]
MAIN_LOOP = None
# صاحب بوت ينتظر إدخال (welcome / busy)
AWAITING = {}   # owner_id -> "welcome" | "busy"


def _store_pic(file_id):
    _pic_counter[0] += 1
    key = str(_pic_counter[0])
    PIC_STORE[key] = file_id
    if len(PIC_STORE) > 5000:
        for k in list(PIC_STORE.keys())[:1000]:
            PIC_STORE.pop(k, None)
    return key


def esc(text):
    if not text:
        return ""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _track_user(rec, uid, name, owner_id, inc=True):
    if rec is None:
        return
    users = rec.setdefault("users", {})
    key = str(uid)
    if key not in users:
        users[key] = {"name": name or "?", "count": 0}
    else:
        users[key]["name"] = name or users[key].get("name", "?")
    if inc:
        users[key]["count"] = users[key].get("count", 0) + 1
    persist(owner_id)


# ==================================================================
#     الإعلان التلقائي الثابت — بيظهر بكل بوت متصنّع، أي نوع كان
#     (مو قابل للتعطيل من صاحب البوت)
# ==================================================================
def promo_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🤖 اصنع بوتك الخاص", url=f"https://t.me/{PLATFORM_BOT}")],
        [InlineKeyboardButton("👨‍💻 صانع البوتات", url=f"https://t.me/{DEVELOPER.lstrip('@')}")],
    ])


def promo_line():
    return f"\n\n⚡ هذا البوت صُنع عبر @{PLATFORM_BOT}"


# ==================================================================
#              تشغيل/إيقاف بوتات الأطفال حسب نوعها
# ==================================================================
def build_child_app(token, owner_id, bot_type):
    app = ApplicationBuilder().token(token).build()
    app.bot_data["owner_id"] = int(owner_id)
    app.bot_data["token"] = token
    app.bot_data["bot_type"] = bot_type

    if bot_type == "messages":
        from bots import messages_bot as mod
    elif bot_type == "protection":
        from bots import protection_bot as mod
    elif bot_type == "games":
        from bots import games_bot as mod
    elif bot_type == "casino":
        from bots import casino_bot as mod
    elif bot_type == "broadcast":
        from bots import broadcast_bot as mod
    elif bot_type == "fun":
        from bots import fun_bot as mod
    elif bot_type == "tools":
        from bots import tools_bot as mod
    else:
        raise ValueError(f"نوع البوت غير مدعوم بعد: {bot_type}")

    mod.register(app, owner_id, token)
    return app


async def start_child_bot(token, owner_id, bot_type):
    if token in RUNNING:
        return True, "شغّال أصلاً"
    app = build_child_app(token, int(owner_id), bot_type)
    try:
        await app.initialize()
        me = await app.bot.get_me()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
    except Exception as e:
        try:
            await app.shutdown()
        except Exception:
            pass
        return False, str(e)
    RUNNING[token] = app
    return True, me.username


async def stop_child_bot(token):
    app = RUNNING.pop(token, None)
    if not app:
        return
    try:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()
    except Exception as e:
        log.error(f"خطأ بإيقاف بوت: {e}")


# ==================================================================
#                        البوت الرئيسي (المنصة)
# ==================================================================
def platform_kb(has_bot, bot_username=None, is_admin=False):
    rows = []
    if has_bot and bot_username:
        rows.append([InlineKeyboardButton(f"🚀 افتح بوتي @{bot_username}", url=f"https://t.me/{bot_username}")])
        rows.append([InlineKeyboardButton("🗑 حذف بوتي", callback_data="delete_bot")])
    rows.append([InlineKeyboardButton("👨‍💻 المطوّر", url=f"https://t.me/{DEVELOPER.lstrip('@')}")])
    if is_admin:
        rows.append([
            InlineKeyboardButton("📊 إحصائيات", callback_data="admin_stats"),
            InlineKeyboardButton("📢 رسالة جماعية", callback_data="admin_bc_hint"),
        ])
    return InlineKeyboardMarkup(rows)


async def owner_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    rec = DATA["bots"].get(str(uid))
    is_admin = uid == ADMIN_ID

    if rec and rec["token"] in RUNNING:
        try:
            me = await RUNNING[rec["token"]].bot.get_me()
            uname = me.username
        except Exception:
            uname = None
        await update.message.reply_text(
            "✨ <b>عندك بوت شغّال!</b>\n"
            "━━━━━━━━━━━━━━━\n"
            "افتح بوتك واكتب /start عشان تفتح لوحة التحكم الكاملة 👇",
            parse_mode=ParseMode.HTML,
            reply_markup=platform_kb(True, uname, is_admin),
        )
        return

    await update.message.reply_text(
        "🤖 <b>منصّة إنشاء بوتات تلغرام</b>\n"
        "━━━━━━━━━━━━━━━\n\n"
        "اعمل بوتك الخاص بخطوة وحدة، تختار نوعه، وبيشتغل فوراً 🚀\n\n"
        "<b>📝 كيف تبدأ:</b>\n"
        "1️⃣ افتح @BotFather واكتب /newbot\n"
        "2️⃣ خد التوكن اللي بيعطيك ياه\n"
        "3️⃣ ابعتلي التوكن هون\n\n"
        f"━━━━━━━━━━━━━━━\n👨‍💻 تطوير: {DEVELOPER}",
        parse_mode=ParseMode.HTML,
        reply_markup=platform_kb(False, None, is_admin),
    )


async def owner_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    data = q.data

    if data == "delete_bot":
        await q.answer()
        rec = DATA["bots"].get(str(uid))
        if not rec:
            await q.edit_message_text("ما عندك بوت لحذفه.")
            return
        token = rec["token"]
        await stop_child_bot(token)
        MSG_MAP.pop(token, None)
        remove_record(uid)
        await q.edit_message_text("🗑 تم حذف بوتك.\nابعتلي توكن جديد وقت ما بدك.")
        return

    if data == "admin_stats":
        if uid != ADMIN_ID:
            await q.answer("مش مسموح", show_alert=True)
            return
        await q.answer()
        await _send_admin_stats(context.bot, uid)
        return

    if data == "admin_bc_hint":
        if uid != ADMIN_ID:
            await q.answer("مش مسموح", show_alert=True)
            return
        await q.answer()
        await context.bot.send_message(
            chat_id=uid,
            text="📢 <b>رسالة جماعية</b>\n\nاكتب:\n<code>/broadcast نص الرسالة</code>\n"
            "أو رد بـ /broadcast على أي رسالة.",
            parse_mode=ParseMode.HTML,
        )
        return


async def owner_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text:
        return
    uid = msg.from_user.id
    text = msg.text.strip()

    if not TOKEN_PATTERN.match(text):
        await msg.reply_text(
            "🔑 ابعتلي <b>توكن بوت</b> صحيح.\n\n"
            "شكله:\n<code>123456789:AAExxxxxxxxxxxxxxxxxxxxx</code>\n\n"
            "خده من @BotFather بعد /newbot",
            parse_mode=ParseMode.HTML,
        )
        return

    own_current_token = DATA["bots"].get(str(uid), {}).get("token")
    if text in RUNNING and text != own_current_token:
        await msg.reply_text("⚠️ هالتوكن مستعمل بحساب تاني.")
        return

    PENDING_TOKEN[uid] = text
    await msg.reply_text(
        "🤖 <b>اختر نوع بوتك:</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=type_select_kb(),
    )


async def type_select_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    key = (q.data or "").split(":", 1)[-1]

    if key not in BOT_TYPE_LABELS:
        await q.answer()
        return

    if key not in IMPLEMENTED_BOT_TYPES:
        await q.answer("🔜 هالنوع لسه قيد التطوير، جرّب 💬 بوت رسائل حالياً.", show_alert=True)
        return

    token = PENDING_TOKEN.pop(uid, None)
    if not token:
        await q.answer("⌛ انتهت صلاحية هالطلب، ابعت التوكن من جديد.", show_alert=True)
        return

    await q.answer()

    old = DATA["bots"].get(str(uid))
    if old and old.get("token") != token:
        await stop_child_bot(old["token"])
        MSG_MAP.pop(old["token"], None)

    await q.edit_message_text("⏳ عم شغّل بوتك...")

    rec = _default_rec(token)
    rec["bot_type"] = key
    DATA["bots"][str(uid)] = rec
    ok, info = await start_child_bot(token, uid, key)

    if ok:
        persist(uid)
        await q.edit_message_text(
            "✅ <b>تم بنجاح!</b>\n"
            "━━━━━━━━━━━━━━━\n"
            f"بوتك @{info} صار شغّال 🎉\n\n"
            "افتحه واكتب /start عشان تفتح لوحة التحكم الكاملة.\n\n"
            f"👨‍💻 {DEVELOPER}",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton(f"🚀 افتح @{info}", url=f"https://t.me/{info}")]]
            ),
        )
    else:
        remove_record(uid)
        await q.edit_message_text(
            "❌ ما قدرت شغّل البوت.\n"
            f"<b>السبب:</b> {esc(info)}\n\n"
            "تأكد إنك ناسخ التوكن كامل من @BotFather.",
            parse_mode=ParseMode.HTML,
        )


async def _send_admin_stats(bot, to_id):
    bots = DATA["bots"]
    total = len(bots)
    running = sum(1 for r in bots.values() if r["token"] in RUNNING)
    total_users = sum(len(r.get("users", {})) for r in bots.values())

    lines = [
        "📊 <b>إحصائيات المنصّة</b>",
        "━━━━━━━━━━━━━━━",
        f"👤 أصحاب البوتات: <b>{total}</b>",
        f"🟢 بوتات شغّالة: <b>{running}</b>",
        f"👥 إجمالي المستخدمين: <b>{total_users}</b>",
        "",
        "<b>الحسابات:</b>",
    ]
    shown = 0
    for owner_id, rec in bots.items():
        if shown >= 40:
            lines.append(f"... و{total - 40} غيرهم")
            break
        uname = "متوقف"
        app = RUNNING.get(rec["token"])
        if app:
            try:
                me = await app.bot.get_me()
                uname = f"@{me.username}"
            except Exception:
                pass
        ucount = len(rec.get("users", {}))
        btype = BOT_TYPE_LABELS.get(rec.get("bot_type"), rec.get("bot_type") or "؟")
        lines.append(f"• <code>{owner_id}</code> — {uname} ({btype}, {ucount} مستخدم)")
        shown += 1

    await bot.send_message(chat_id=to_id, text="\n".join(lines), parse_mode=ParseMode.HTML)


async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    await _send_admin_stats(context.bot, update.effective_user.id)


async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    if not context.args and not update.message.reply_to_message:
        await update.message.reply_text(
            "📢 <b>رسالة جماعية</b>\n\nاكتب:\n<code>/broadcast نص الرسالة</code>\n"
            "أو رد بـ /broadcast على رسالة.",
            parse_mode=ParseMode.HTML,
        )
        return
    if update.message.reply_to_message:
        text = update.message.reply_to_message.text or update.message.reply_to_message.caption or ""
    else:
        text = update.message.text.split(None, 1)[1]
    if not text.strip():
        await update.message.reply_text("الرسالة فاضية.")
        return

    bots = DATA["bots"]
    status = await update.message.reply_text(f"⏳ عم ابعت لـ {len(bots)} مستخدم...")
    sent, failed = 0, 0
    for owner_id in list(bots.keys()):
        try:
            await context.bot.send_message(
                chat_id=int(owner_id),
                text=f"📢 <b>رسالة من إدارة المنصّة</b>\n━━━━━━━━━━━━━━━\n{esc(text)}",
                parse_mode=ParseMode.HTML,
            )
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)
    await status.edit_text(f"✅ تم.\n📨 وصلت: {sent}\n❌ فشلت: {failed}")


def build_owner_app():
    app = ApplicationBuilder().token(OWNER_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", owner_start))
    app.add_handler(CommandHandler("stats", admin_stats))
    app.add_handler(CommandHandler("broadcast", admin_broadcast))
    app.add_handler(CallbackQueryHandler(owner_callbacks, pattern="^(delete_bot|admin_stats|admin_bc_hint)$"))
    app.add_handler(CallbackQueryHandler(type_select_cb, pattern="^type:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, owner_message))
    return app


# ==================================================================
#            سيرفر ويب صغير
# ==================================================================
class _PingHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"BotUp is running")

    def log_message(self, *args):
        pass


def start_web_server():
    port = int(os.environ.get("PORT", "10000"))
    HTTPServer(("0.0.0.0", port), _PingHandler).serve_forever()


# ==================================================================
#                            التشغيل
# ==================================================================
async def restore_bots():
    for owner_id, rec in list(DATA["bots"].items()):
        bot_type = rec.get("bot_type") or "messages"
        ok, info = await start_child_bot(rec["token"], int(owner_id), bot_type)
        if ok:
            log.info(f"↻ رجّعت بوت {owner_id} ({bot_type}) (@{info})")
        else:
            log.warning(f"⚠️ ما قدرت أرجّع بوت {owner_id}: {info}")


async def run():
    global MAIN_LOOP
    MAIN_LOOP = asyncio.get_running_loop()

    if USE_DB:
        db_init()
    load_all()
    log.info(f"📦 التخزين: {'PostgreSQL' if USE_DB else 'ملف محلي'} | بوتات: {len(DATA['bots'])}")

    owner_app = build_owner_app()
    await owner_app.initialize()
    await owner_app.start()
    await owner_app.updater.start_polling(drop_pending_updates=True)
    log.info("✅ البوت الرئيسي شغّال")

    await restore_bots()

    stop_event = asyncio.Event()
    try:
        await stop_event.wait()
    finally:
        for token in list(RUNNING.keys()):
            await stop_child_bot(token)
        await owner_app.updater.stop()
        await owner_app.stop()
        await owner_app.shutdown()


def main():
    if not OWNER_BOT_TOKEN or "حط_توكن" in OWNER_BOT_TOKEN:
        raise SystemExit("⚠️ لازم تحط توكن البوت الرئيسي بمتغير OWNER_BOT_TOKEN")
    threading.Thread(target=start_web_server, daemon=True).start()
    try:
        asyncio.run(run())
    except (KeyboardInterrupt, SystemExit):
        pass


if __name__ == "__main__":
    main()
