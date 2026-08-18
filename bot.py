# -*- coding: utf-8 -*-
"""
🤖 بوت أب PRO — منصة إنشاء بوتات "الناس تحكيني" | تطوير: @zyh011

تصميم احترافي 2026:
  • قائمة أزرار سفلية دائمة (Reply Keyboard) سهلة الوصول
  • لوحات تنقّل بأزرار مدمجة (Inline) للإعدادات
  • تجربة سلسة: تعديل الرسائل بدل إرسالها من جديد
  • تخزين دائم PostgreSQL
  • رسائل توصل مع اسم/صورة المرسِل + أزرار سريعة
  • رسالة ترويج ثابتة للزوار + زر المطوّر
  • أوامر إدارة: إحصائيات + رسالة جماعية

متغيرات: OWNER_BOT_TOKEN (إجباري), DATABASE_URL, ADMIN_ID, PLATFORM_BOT
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
    ReplyKeyboardMarkup,
    KeyboardButton,
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

DEFAULT_WELCOME = "🌟 أهلاً وسهلاً!\nاكتب رسالتك هون ورح توصل واردّ عليك بأقرب وقت 💬"

# نصوص أزرار القائمة السفلية (للزوار داخل بوت الطفل)
BTN_MAKE_BOT = "🤖 اعمل بوتك"
BTN_DEV = "👨‍💻 المطوّر"


# ==================================================================
#          طبقة التخزين: PostgreSQL أو ملف
# ==================================================================
USE_DB = bool(DATABASE_URL)
_lock = threading.Lock()

if USE_DB:
    import psycopg

    def _db():
        return psycopg.connect(DATABASE_URL, autocommit=True)

    def db_init():
        with _db() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS bots (
                    owner_id  TEXT PRIMARY KEY,
                    token     TEXT NOT NULL,
                    blocked   TEXT DEFAULT '[]',
                    muted     TEXT DEFAULT '[]',
                    welcome   TEXT DEFAULT '',
                    users     TEXT DEFAULT '[]'
                )
                """
            )
            # ترقية: نضيف عمود users لو الجدول قديم
            try:
                conn.execute("ALTER TABLE bots ADD COLUMN IF NOT EXISTS users TEXT DEFAULT '[]'")
            except Exception:
                pass
        log.info("✅ قاعدة البيانات جاهزة")

    def db_all_bots():
        out = {}
        with _db() as conn:
            for row in conn.execute("SELECT owner_id, token, blocked, muted, welcome, users FROM bots"):
                out[row[0]] = {
                    "token": row[1],
                    "blocked": json.loads(row[2] or "[]"),
                    "muted": json.loads(row[3] or "[]"),
                    "welcome": row[4] or "",
                    "users": json.loads(row[5] or "[]"),
                }
        return out

    def db_upsert(owner_id, rec):
        with _db() as conn:
            conn.execute(
                """
                INSERT INTO bots (owner_id, token, blocked, muted, welcome, users)
                VALUES (%s,%s,%s,%s,%s,%s)
                ON CONFLICT (owner_id) DO UPDATE SET
                    token=EXCLUDED.token, blocked=EXCLUDED.blocked,
                    muted=EXCLUDED.muted, welcome=EXCLUDED.welcome, users=EXCLUDED.users
                """,
                (
                    str(owner_id), rec["token"],
                    json.dumps(rec["blocked"]), json.dumps(rec["muted"]),
                    rec.get("welcome", ""), json.dumps(rec.get("users", [])),
                ),
            )

    def db_delete(owner_id):
        with _db() as conn:
            conn.execute("DELETE FROM bots WHERE owner_id=%s", (str(owner_id),))


DATA = {"bots": {}}


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
    # نتأكد إنو كل سجل فيه المفاتيح المطلوبة
    for r in DATA["bots"].values():
        r.setdefault("blocked", [])
        r.setdefault("muted", [])
        r.setdefault("welcome", "")
        r.setdefault("users", [])
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
#            لوحات المفاتيح (Keyboards)
# ==================================================================
def visitor_reply_kb():
    """قائمة سفلية دائمة للزوار داخل بوت الطفل"""
    return ReplyKeyboardMarkup(
        [[KeyboardButton(BTN_MAKE_BOT), KeyboardButton(BTN_DEV)]],
        resize_keyboard=True,
        input_field_placeholder="اكتب رسالتك هون...",
    )


def owner_panel_reply_kb():
    """قائمة سفلية دائمة لصاحب البوت"""
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("📊 إحصائياتي"), KeyboardButton("⚙️ الإعدادات")],
            [KeyboardButton("📋 المحظورين")],
        ],
        resize_keyboard=True,
        input_field_placeholder="ردّ على رسالة لتوصل للشخص...",
    )


def settings_inline_kb():
    """لوحة إعدادات مدمجة لصاحب البوت"""
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✏️ رسالة الترحيب", callback_data="set_welcome")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="close_panel")],
        ]
    )


def branding_url_kb():
    """أزرار مدمجة للترويج (بتنحط مع رسالة الزائر)"""
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("🤖 اعمل بوتك الخاص مجاناً", url=f"https://t.me/{PLATFORM_BOT}")]]
    )


# ==================================================================
#                    بوت الطفل
# ==================================================================
async def child_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    owner_id = context.bot_data["owner_id"]
    uid = update.effective_user.id
    rec = _bot_record(owner_id)

    if uid == owner_id:
        await update.message.reply_text(
            "🎛 <b>لوحة تحكم بوتك</b>\n"
            "━━━━━━━━━━━━━━━\n"
            "بوتك جاهز وشغّال ✅\n\n"
            "• لما يبعتلك حدا، بتوصلك رسالته مع اسمه وأزرار سريعة.\n"
            "• للرد: اعمل <b>reply</b> على رسالته.\n\n"
            "استعمل القائمة تحت للتحكم السريع 👇",
            parse_mode=ParseMode.HTML,
            reply_markup=owner_panel_reply_kb(),
        )
    else:
        # نسجّل الزائر (للإحصائيات) بدون تكرار
        if rec is not None and uid not in rec["users"]:
            rec["users"].append(uid)
            persist(owner_id)
        welcome = (rec or {}).get("welcome") or DEFAULT_WELCOME
        await update.message.reply_text(
            welcome,
            reply_markup=visitor_reply_kb(),
        )


async def child_owner_panel_text(update, context):
    """أزرار القائمة السفلية لصاحب البوت"""
    owner_id = context.bot_data["owner_id"]
    if update.effective_user.id != owner_id:
        return False
    rec = _bot_record(owner_id)
    txt = update.message.text

    if txt == "📊 إحصائياتي":
        total = len(rec.get("users", []))
        blocked = len(rec["blocked"])
        muted = len(rec["muted"])
        await update.message.reply_text(
            "📊 <b>إحصائيات بوتك</b>\n"
            "━━━━━━━━━━━━━━━\n"
            f"👥 عدد الأشخاص: <b>{total}</b>\n"
            f"🚫 محظورين: <b>{blocked}</b>\n"
            f"🔇 مكتومين: <b>{muted}</b>",
            parse_mode=ParseMode.HTML,
        )
        return True

    if txt == "⚙️ الإعدادات":
        await update.message.reply_text(
            "⚙️ <b>الإعدادات</b>\nاختر شو بدك تعدّل:",
            parse_mode=ParseMode.HTML,
            reply_markup=settings_inline_kb(),
        )
        return True

    if txt == "📋 المحظورين":
        blocked = ", ".join(map(str, rec["blocked"])) or "لا يوجد"
        muted = ", ".join(map(str, rec["muted"])) or "لا يوجد"
        await update.message.reply_text(
            f"🚫 <b>المحظورين:</b>\n{blocked}\n\n🔇 <b>المكتومين:</b>\n{muted}\n\n"
            "لفك الحظر: <code>/unblock الايدي</code>\n"
            "لفك الكتم: <code>/unmute الايدي</code>",
            parse_mode=ParseMode.HTML,
        )
        return True

    return False


async def child_settings_cb(update, context):
    q = update.callback_query
    owner_id = context.bot_data["owner_id"]
    if q.from_user.id != owner_id:
        await q.answer("مش مسموح", show_alert=True)
        return
    data = q.data

    if data == "set_welcome":
        context.bot_data.setdefault("awaiting_welcome", set()).add(owner_id)
        await q.answer()
        await q.edit_message_text(
            "✏️ ابعتلي رسالة الترحيب الجديدة اللي بدك الزوار يشوفوها.\n\n"
            "(ابعتها كرسالة عادية هلق)",
        )
        return

    if data == "close_panel":
        await q.answer()
        await q.edit_message_text("✅ تمام.")
        return


def _child_target_from_reply(update, token):
    reply = update.message.reply_to_message
    if not reply:
        return None
    return MSG_MAP.get(token, {}).get(reply.message_id)


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


async def child_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        # هل ينتظر رسالة ترحيب جديدة؟
        awaiting = context.bot_data.get("awaiting_welcome", set())
        if owner_id in awaiting and msg.text and not msg.reply_to_message:
            rec["welcome"] = msg.text
            persist(owner_id)
            awaiting.discard(owner_id)
            await msg.reply_text("✅ تم تحديث رسالة الترحيب.")
            return

        # أزرار القائمة السفلية
        if msg.text and await child_owner_panel_text(update, context):
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
    if rec is not None and uid not in rec["users"]:
        rec["users"].append(uid)
        persist(owner_id)

    log.info(f"📩 رسالة لبوت owner={owner_id} من زائر={uid}")
    if uid in rec["blocked"]:
        return
    if uid in rec["muted"]:
        return

    text = msg.text or msg.caption or ""
    if LINK_PATTERN.search(text):
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

        header = (
            "📨 <b>رسالة جديدة</b>\n"
            "━━━━━━━━━━━━━━━\n"
            f"👤 <b>{full_name}</b>\n"
            f"🔗 {username}\n"
            f"🆔 <code>{u.id}</code>"
        )

        buttons = []
        if pic_file_id:
            buttons.append(InlineKeyboardButton("🖼", callback_data=f"pic:{_store_pic(pic_file_id)}"))
        buttons.append(InlineKeyboardButton("🚫 حظر", callback_data=f"blk:{u.id}"))
        buttons.append(InlineKeyboardButton("🔇 كتم", callback_data=f"mut:{u.id}"))

        await context.bot.send_message(
            chat_id=owner_id, text=header,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([buttons]),
        )

        fwd = await context.bot.copy_message(
            chat_id=owner_id, from_chat_id=msg.chat_id, message_id=msg.message_id
        )
        MSG_MAP.setdefault(token, {})[fwd.message_id] = uid
        log.info(f"   ✅ وصلت لصاحب البوت {owner_id}")

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
    app.add_handler(CallbackQueryHandler(child_buttons, pattern="^(pic|blk|mut):"))
    app.add_handler(CallbackQueryHandler(child_settings_cb, pattern="^(set_welcome|close_panel)$"))
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
def platform_main_kb(has_bot, bot_username=None, is_admin=False):
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
            "افتح بوتك من الزر تحت 👇",
            parse_mode=ParseMode.HTML,
            reply_markup=platform_main_kb(True, uname, is_admin),
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
        reply_markup=platform_main_kb(False, None, is_admin),
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
    DATA["bots"][str(uid)] = {"token": text, "blocked": [], "muted": [], "welcome": "", "users": []}
    ok, info = await start_child_bot(text, uid)

    if ok:
        persist(uid)
        await status.edit_text(
            "✅ <b>تم بنجاح!</b>\n"
            "━━━━━━━━━━━━━━━\n"
            f"بوتك @{info} صار شغّال 🎉\n\n"
            "افتحه واكتب /start، وخلي الناس يبعتولك — رح توصلك الرسائل.\n\n"
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


# ---------- أوامر الإدارة ----------
async def _send_admin_stats(bot, to_id):
    bots = DATA["bots"]
    total = len(bots)
    running = sum(1 for r in bots.values() if r["token"] in RUNNING)
    total_users = sum(len(r.get("users", [])) for r in bots.values())

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
        ucount = len(rec.get("users", []))
        lines.append(f"• <code>{owner_id}</code> — {uname} ({ucount} مستخدم)")
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
            "📢 <b>رسالة جماعية</b>\n\n"
            "اكتب:\n<code>/broadcast نص الرسالة</code>\n"
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
