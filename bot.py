# -*- coding: utf-8 -*-
"""
🤖 بوت أب PRO+ — منصة إنشاء بوتات "الناس تحكيني" | تطوير: @zyh011

كل شي أزرار مدمجة (inline) — ما في أزرار سفلية بتبعت رسائل بالغلط.

لوحة تحكم كاملة لصاحب البوت:
  ✏️ رسالة الترحيب
  🔗 منع الروابط (تشغيل/إيقاف)
  ⏸ إيقاف استقبال الرسائل مؤقتاً
  💤 رسالة "مشغول" التلقائية
  👥 قائمة المستخدمين (أسماء + عدد رسائل)
  🚫 المحظورين / المكتومين

للأدمن: 📊 إحصائيات + 📢 رسالة جماعية
تخزين دائم PostgreSQL.
"""

import os
import re
import json
import asyncio
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    BotCommand,
    BotCommandScopeDefault,
    BotCommandScopeChat,
)
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
#          طبقة التخزين
# ==================================================================
USE_DB = bool(DATABASE_URL)
_lock = threading.Lock()

# القيم الافتراضية لأي سجل
def _default_rec(token):
    return {
        "token": token,
        "blocked": [],
        "muted": [],
        "welcome": "",
        "busy_msg": "",
        "users": {},          # {user_id(str): {"name": str, "count": int}}
        "antilink": True,      # منع الروابط مفعّل
        "paused": False,       # إيقاف الاستقبال
        "busy": False,         # وضع مشغول (يرد رسالة تلقائية)
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
    # ترقية: لو users كانت list قديمة، نحولها dict
    if isinstance(rec.get("users"), list):
        rec["users"] = {str(u): {"name": "?", "count": 0} for u in rec["users"]}
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


# ==================================================================
#            لوحة تحكم صاحب البوت (كلها inline)
# ==================================================================
def panel_kb(rec):
    antilink = "🟢" if rec.get("antilink", True) else "🔴"
    paused = "🔴 موقوف" if rec.get("paused") else "🟢 يستقبل"
    busy = "🟢" if rec.get("busy") else "🔴"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ رسالة الترحيب", callback_data="p_welcome")],
        [InlineKeyboardButton(f"🔗 منع الروابط {antilink}", callback_data="p_antilink")],
        [InlineKeyboardButton(f"⏸ الاستقبال: {paused}", callback_data="p_pause")],
        [InlineKeyboardButton(f"💤 وضع مشغول {busy}", callback_data="p_busy"),
         InlineKeyboardButton("📝 نص المشغول", callback_data="p_busymsg")],
        [InlineKeyboardButton("👥 المستخدمين", callback_data="p_users"),
         InlineKeyboardButton("🚫 المحظورين", callback_data="p_blocked")],
        [InlineKeyboardButton("🔄 تحديث", callback_data="p_refresh")],
    ])


def panel_text(rec):
    total = len(rec.get("users", {}))
    return (
        "🎛 <b>لوحة تحكم بوتك</b>\n"
        "━━━━━━━━━━━━━━━\n"
        f"👥 المستخدمين: <b>{total}</b>\n"
        f"🚫 محظورين: <b>{len(rec['blocked'])}</b>  •  🔇 مكتومين: <b>{len(rec['muted'])}</b>\n\n"
        "• للرد على أي شخص: اعمل <b>reply</b> على رسالته.\n"
        "• استعمل الأزرار للتحكم بكل شي 👇"
    )


def back_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع للوحة", callback_data="p_refresh")]])


# ==================================================================
#                    بوت الطفل
# ==================================================================
async def child_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    owner_id = context.bot_data["owner_id"]
    uid = update.effective_user.id
    rec = _bot_record(owner_id)

    if uid == owner_id:
        await update.message.reply_text(
            panel_text(rec), parse_mode=ParseMode.HTML, reply_markup=panel_kb(rec)
        )
    else:
        _track_user(rec, uid, update.effective_user.full_name, owner_id, inc=False)
        welcome = (rec or {}).get("welcome") or DEFAULT_WELCOME
        await update.message.reply_text(
            welcome,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🤖 اعمل بوتك الخاص مجاناً", url=f"https://t.me/{PLATFORM_BOT}")]
            ]),
        )


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


async def child_panel_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """كل أزرار لوحة التحكم"""
    q = update.callback_query
    owner_id = context.bot_data["owner_id"]
    if q.from_user.id != owner_id:
        await q.answer("مش مسموح", show_alert=True)
        return
    rec = _bot_record(owner_id)
    data = q.data

    if data == "p_refresh":
        AWAITING.pop(owner_id, None)
        await q.answer()
        try:
            await q.edit_message_text(panel_text(rec), parse_mode=ParseMode.HTML, reply_markup=panel_kb(rec))
        except Exception:
            await context.bot.send_message(owner_id, panel_text(rec), parse_mode=ParseMode.HTML, reply_markup=panel_kb(rec))
        return

    if data == "p_welcome":
        AWAITING[owner_id] = "welcome"
        await q.answer()
        cur = rec.get("welcome") or DEFAULT_WELCOME
        await q.edit_message_text(
            f"✏️ <b>رسالة الترحيب الحالية:</b>\n\n{esc(cur)}\n\n"
            "ابعتلي الرسالة الجديدة كنص عادي 👇",
            parse_mode=ParseMode.HTML, reply_markup=back_kb(),
        )
        return

    if data == "p_busymsg":
        AWAITING[owner_id] = "busy"
        await q.answer()
        cur = rec.get("busy_msg") or DEFAULT_BUSY
        await q.edit_message_text(
            f"📝 <b>رسالة المشغول الحالية:</b>\n\n{esc(cur)}\n\n"
            "ابعتلي النص الجديد 👇",
            parse_mode=ParseMode.HTML, reply_markup=back_kb(),
        )
        return

    if data == "p_antilink":
        rec["antilink"] = not rec.get("antilink", True)
        persist(owner_id)
        await q.answer("تم التغيير ✅")
        await q.edit_message_text(panel_text(rec), parse_mode=ParseMode.HTML, reply_markup=panel_kb(rec))
        return

    if data == "p_pause":
        rec["paused"] = not rec.get("paused", False)
        persist(owner_id)
        await q.answer("⏸ موقوف" if rec["paused"] else "▶️ يستقبل")
        await q.edit_message_text(panel_text(rec), parse_mode=ParseMode.HTML, reply_markup=panel_kb(rec))
        return

    if data == "p_busy":
        rec["busy"] = not rec.get("busy", False)
        persist(owner_id)
        await q.answer("💤 مشغول" if rec["busy"] else "✅ متاح")
        await q.edit_message_text(panel_text(rec), parse_mode=ParseMode.HTML, reply_markup=panel_kb(rec))
        return

    if data == "p_users":
        await q.answer()
        users = rec.get("users", {})
        if not users:
            body = "ما في مستخدمين بعد."
        else:
            # نرتّب حسب عدد الرسائل
            items = sorted(users.items(), key=lambda x: x[1].get("count", 0), reverse=True)
            lines = []
            for i, (uid, info) in enumerate(items[:30], 1):
                # نحاول نجيب اليوزر مباشرة
                handle = None
                try:
                    chat = await context.bot.get_chat(int(uid))
                    if chat.username:
                        handle = f"@{chat.username}"
                    elif chat.full_name:
                        handle = esc(chat.full_name)
                except Exception:
                    pass
                if not handle:
                    handle = esc(info.get("name", "?"))
                lines.append(f"{i}. {handle} ({info.get('count',0)} رسالة)")
            if len(items) > 30:
                lines.append(f"... و{len(items)-30} غيرهم")
            body = "\n".join(lines)
        await q.edit_message_text(
            f"👥 <b>مستخدمين بوتك ({len(users)})</b>\n━━━━━━━━━━━━━━━\n{body}",
            parse_mode=ParseMode.HTML, reply_markup=back_kb(),
        )
        return

    if data == "p_blocked":
        await q.answer()
        blocked = ", ".join(map(str, rec["blocked"])) or "لا يوجد"
        muted = ", ".join(map(str, rec["muted"])) or "لا يوجد"
        await q.edit_message_text(
            f"🚫 <b>المحظورين:</b>\n{blocked}\n\n🔇 <b>المكتومين:</b>\n{muted}\n\n"
            "لفك الحظر: <code>/unblock الايدي</code>\n"
            "لفك الكتم: <code>/unmute الايدي</code>",
            parse_mode=ParseMode.HTML, reply_markup=back_kb(),
        )
        return


async def child_msg_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أزرار الصورة/الحظر/الكتم تحت كل رسالة"""
    q = update.callback_query
    owner_id = context.bot_data["owner_id"]
    if q.from_user.id != owner_id:
        await q.answer("مش مسموح", show_alert=True)
        return
    rec = _bot_record(owner_id)
    data = q.data or ""

    if data.startswith("pic:"):
        file_id = PIC_STORE.get(data[4:])
        if not file_id:
            await q.answer("الصورة مش متوفرة", show_alert=True)
            return
        try:
            await context.bot.send_photo(chat_id=owner_id, photo=file_id, caption="🖼 صورة المرسِل")
            await q.answer()
        except Exception:
            await q.answer("ما قدرت أفتح الصورة", show_alert=True)
        return

    if data.startswith("blk:"):
        target = int(data[4:])
        if target not in rec["blocked"]:
            rec["blocked"].append(target)
            persist(owner_id)
        await q.answer("🚫 تم الحظر")
        try:
            await q.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        return

    if data.startswith("mut:"):
        target = int(data[4:])
        if target not in rec["muted"]:
            rec["muted"].append(target)
            persist(owner_id)
        await q.answer("🔇 تم الكتم")
        return


async def child_unblock(update, context):
    owner_id = context.bot_data["owner_id"]
    if update.effective_user.id != owner_id:
        return
    rec = _bot_record(owner_id)
    if not context.args:
        await update.message.reply_text("اكتب /unblock <id>")
        return
    try:
        target = int(context.args[0])
    except ValueError:
        await update.message.reply_text("الايدي لازم يكون رقم")
        return
    if target in rec["blocked"]:
        rec["blocked"].remove(target)
        persist(owner_id)
    await update.message.reply_text(f"✅ تم فك الحظر عن {target}")


async def child_unmute(update, context):
    owner_id = context.bot_data["owner_id"]
    if update.effective_user.id != owner_id:
        return
    rec = _bot_record(owner_id)
    if not context.args:
        await update.message.reply_text("اكتب /unmute <id>")
        return
    try:
        target = int(context.args[0])
    except ValueError:
        await update.message.reply_text("الايدي لازم يكون رقم")
        return
    if target in rec["muted"]:
        rec["muted"].remove(target)
        persist(owner_id)
    await update.message.reply_text(f"🔊 تم فك الكتم عن {target}")


async def child_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if msg is None:
        return
    owner_id = context.bot_data["owner_id"]
    token = context.bot_data["token"]
    rec = _bot_record(owner_id)
    if rec is None:
        return

    # ====== صاحب البوت ======
    if msg.from_user.id == owner_id:
        # ينتظر إدخال؟
        pending = AWAITING.get(owner_id)
        if pending and msg.text and not msg.reply_to_message:
            if pending == "welcome":
                rec["welcome"] = msg.text
            elif pending == "busy":
                rec["busy_msg"] = msg.text
            persist(owner_id)
            AWAITING.pop(owner_id, None)
            await msg.reply_text("✅ تم الحفظ.", reply_markup=back_kb())
            return

        # رد على رسالة زائر
        if msg.reply_to_message:
            target = MSG_MAP.get(token, {}).get(msg.reply_to_message.message_id)
            if target:
                try:
                    await context.bot.copy_message(
                        chat_id=target, from_chat_id=msg.chat_id, message_id=msg.message_id
                    )
                    await msg.set_reaction("👍")
                except Exception as e:
                    await msg.reply_text(f"ما قدرت ابعت الرد: {e}")
            else:
                await msg.reply_text("↩️ رد على رسالة الشخص نفسها عشان يوصله ردك.")
        return

    # ====== زائر ======
    uid = msg.from_user.id
    _track_user(rec, uid, msg.from_user.full_name, owner_id, inc=True)

    if uid in rec["blocked"]:
        return
    if uid in rec["muted"]:
        return

    # إيقاف مؤقت
    if rec.get("paused"):
        return

    text = msg.text or msg.caption or ""
    if rec.get("antilink", True) and LINK_PATTERN.search(text):
        await msg.reply_text("🚫 ممنوع إرسال روابط.")
        return

    try:
        u = msg.from_user
        full_name = esc(u.full_name) or "بدون اسم"
        username = f"@{u.username}" if u.username else "—"

        pic_file_id = None
        try:
            photos = await context.bot.get_user_profile_photos(u.id, limit=1)
            if photos.total_count > 0:
                pic_file_id = photos.photos[0][0].file_id
        except Exception:
            pass

        ucount = rec["users"].get(str(uid), {}).get("count", 0)
        header = (
            "📨 <b>رسالة جديدة</b>\n"
            "━━━━━━━━━━━━━━━\n"
            f"👤 <b>{full_name}</b>\n"
            f"🔗 {username}\n"
            f"🆔 <code>{u.id}</code>\n"
            f"💬 رسائله: {ucount}"
        )

        buttons = []
        if pic_file_id:
            buttons.append(InlineKeyboardButton("🖼", callback_data=f"pic:{_store_pic(pic_file_id)}"))
        buttons.append(InlineKeyboardButton("🚫 حظر", callback_data=f"blk:{u.id}"))
        buttons.append(InlineKeyboardButton("🔇 كتم", callback_data=f"mut:{u.id}"))

        await context.bot.send_message(
            chat_id=owner_id, text=header, parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([buttons]),
        )
        fwd = await context.bot.copy_message(
            chat_id=owner_id, from_chat_id=msg.chat_id, message_id=msg.message_id
        )
        MSG_MAP.setdefault(token, {})[fwd.message_id] = uid

        # وضع مشغول: رد تلقائي
        if rec.get("busy"):
            busy_msg = rec.get("busy_msg") or DEFAULT_BUSY
            try:
                await msg.reply_text(busy_msg)
            except Exception:
                pass
        else:
            try:
                await msg.set_reaction("✅")
            except Exception:
                pass
    except Exception as e:
        log.error(f"خطأ بالتوصيل owner={owner_id}: {e}")


def build_child_app(token, owner_id):
    app = ApplicationBuilder().token(token).build()
    app.bot_data["owner_id"] = int(owner_id)
    app.bot_data["token"] = token
    app.add_handler(CommandHandler("start", child_start))
    app.add_handler(CommandHandler("unblock", child_unblock))
    app.add_handler(CommandHandler("unmute", child_unmute))
    app.add_handler(CallbackQueryHandler(child_msg_buttons, pattern="^(pic|blk|mut):"))
    app.add_handler(CallbackQueryHandler(child_panel_cb, pattern="^p_"))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, child_message))
    return app


async def start_child_bot(token, owner_id):
    if token in RUNNING:
        return True, "شغّال أصلاً"
    app = build_child_app(token, int(owner_id))
    try:
        await app.initialize()
        me = await app.bot.get_me()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        # الأوامر الإدارية تظهر لصاحب البوت فقط، والزوار ما يشوفوا شي
        try:
            await app.bot.set_my_commands([], scope=BotCommandScopeDefault())
            await app.bot.set_my_commands(
                [
                    BotCommand("start", "لوحة التحكم"),
                    BotCommand("unblock", "فك حظر شخص"),
                    BotCommand("unmute", "فك كتم شخص"),
                ],
                scope=BotCommandScopeChat(chat_id=int(owner_id)),
            )
        except Exception:
            pass
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
            "الناس بتبعتله رسائل بتوصلك، وبترد عليهم بسرية.\n"
            "افتح بوتك واكتب /start عشان تفتح لوحة التحكم الكاملة 👇",
            parse_mode=ParseMode.HTML,
            reply_markup=platform_kb(True, uname, is_admin),
        )
        return

    await update.message.reply_text(
        "🤖 <b>منصّة إنشاء بوتات الرسائل</b>\n"
        "━━━━━━━━━━━━━━━\n\n"
        "اعمل بوتك الخاص بخطوة وحدة، والناس بتبعتلك رسائل "
        "بتوصلك وبترد عليهم مباشرة 🔒\n\n"
        "<b>📝 كيف تبدأ:</b>\n"
        "1️⃣ افتح @BotFather واكتب /newbot\n"
        "2️⃣ خد التوكن اللي بيعطيك ياه\n"
        "3️⃣ ابعتلي التوكن هون\n\n"
        "وبوتك بيشتغل فوراً 🚀\n\n"
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

    old = DATA["bots"].get(str(uid))
    if old:
        await stop_child_bot(old["token"])
        MSG_MAP.pop(old["token"], None)

    if text in RUNNING:
        await msg.reply_text("⚠️ هالتوكن مستعمل بحساب تاني.")
        return

    status = await msg.reply_text("⏳ عم شغّل بوتك...")
    DATA["bots"][str(uid)] = _default_rec(text)
    ok, info = await start_child_bot(text, uid)

    if ok:
        persist(uid)
        await status.edit_text(
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
        await status.edit_text(
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
        bot_uname = "متوقف"
        app = RUNNING.get(rec["token"])
        owner_handle = None
        if app:
            try:
                me = await app.bot.get_me()
                bot_uname = f"@{me.username}"
            except Exception:
                pass
            # نحاول نجيب يوزر صاحب البوت
            try:
                chat = await app.bot.get_chat(int(owner_id))
                if chat.username:
                    owner_handle = f"@{chat.username}"
                elif chat.full_name:
                    owner_handle = esc(chat.full_name)
            except Exception:
                pass
        # لو ما قدرنا نجيب اليوزر، نستعمل الايدي كبديل
        who = owner_handle or f"<code>{owner_id}</code>"
        ucount = len(rec.get("users", {}))
        lines.append(f"• {who} — {bot_uname} ({ucount} مستخدم)")
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
        ok, info = await start_child_bot(rec["token"], int(owner_id))
        if ok:
            log.info(f"↻ رجّعت بوت {owner_id} (@{info})")
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
    # أوامر الأدمن تظهر للأدمن فقط
    try:
        await owner_app.bot.set_my_commands([BotCommand("start", "ابدأ")], scope=BotCommandScopeDefault())
        await owner_app.bot.set_my_commands(
            [
                BotCommand("start", "ابدأ"),
                BotCommand("stats", "إحصائيات المنصة"),
                BotCommand("broadcast", "رسالة جماعية"),
            ],
            scope=BotCommandScopeChat(chat_id=ADMIN_ID),
        )
    except Exception:
        pass
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
