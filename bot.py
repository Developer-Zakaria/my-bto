# -*- coding: utf-8 -*-
"""
🤖 بوت أب (Bot-Up) — منصة استضافة بوتات "الناس تحكيني"

الفكرة:
  • في بوت رئيسي واحد (تبعك أنت).
  • أي شخص بيفوت عليه بيحط توكن بوته (من @BotFather).
  • البوت الرئيسي بيشغّل بوت خاص لهالشخص تلقائياً بكل الميزات:
      - الناس بتبعتله، الرسائل بتوصله مع اسم وصورة المرسِل.
      - بيرد عليهم مباشرة (رد/reply).
      - حظر / كتم / منع الروابط.
  • كلو مجاني. كل بوت مستقل عن التاني.

التشغيل: يحتاج متغير OWNER_BOT_TOKEN (توكن البوت الرئيسي).
"""

import os
import re
import json
import asyncio
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    ApplicationBuilder,
    MessageHandler,
    CommandHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)

# ================== الإعدادات ==================
OWNER_BOT_TOKEN = os.environ.get("OWNER_BOT_TOKEN", "حط_توكن_البوت_الرئيسي_هون")
DATA_FILE = os.environ.get("DATA_FILE", "botup_data.json")
# ===============================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("botup")

LINK_PATTERN = re.compile(
    r"(https?://|www\.|t\.me/|telegram\.me/|@\w{4,})",
    re.IGNORECASE,
)

# التوكن: أرقام : حروف/رموز
TOKEN_PATTERN = re.compile(r"^\d{6,}:[A-Za-z0-9_\-]{30,}$")


# ==================================================================
#                         تخزين البيانات
# ==================================================================
_data_lock = threading.Lock()


def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
        except Exception:
            d = {}
    else:
        d = {}
    d.setdefault("bots", {})       # owner_id -> {token, blocked[], muted[]}
    return d


def save_data(data):
    with _data_lock:
        tmp = DATA_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, DATA_FILE)


DATA = load_data()

# ذاكرة وقت التشغيل: token -> Application (البوتات الشغالة)
RUNNING = {}
# ذاكرة ربط الرسائل لكل بوت: token -> { admin_msg_id: sender_id }
MSG_MAP = {}

MAIN_LOOP = None  # الـ event loop الرئيسي


# ==================================================================
#              منطق بوت الطفل (اللي بيشغله كل مستخدم)
# ==================================================================
def _bot_record(owner_id):
    return DATA["bots"].get(str(owner_id))


async def child_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /start داخل بوت الطفل"""
    owner_id = context.bot_data["owner_id"]
    uid = update.effective_user.id
    if uid == owner_id:
        await update.message.reply_text(
            "أهلين 👋 هدا بوتك الخاص، شغّال تمام.\n\n"
            "لما حدا يبعتلك، رح توصلك رسالته مع اسمه وصورته.\n"
            "رد (reply) على رسالته عشان يوصله ردك.\n\n"
            "الأوامر:\n"
            "/block  (بالرد على رسالة) — حظر\n"
            "/unblock <id> — فك الحظر\n"
            "/mute   (بالرد على رسالة) — كتم\n"
            "/unmute <id> — فك الكتم\n"
            "/list — عرض المحظورين والمكتومين"
        )
    else:
        await update.message.reply_text("أهلين! ابعتلي رسالتك ورح ارد عليك 🌟")


def _child_target_from_reply(update, token):
    reply = update.message.reply_to_message
    if not reply:
        return None
    return MSG_MAP.get(token, {}).get(reply.message_id)


async def child_block(update, context):
    owner_id = context.bot_data["owner_id"]
    token = context.bot_data["token"]
    if update.effective_user.id != owner_id:
        return
    rec = _bot_record(owner_id)
    target = _child_target_from_reply(update, token)
    if not target and context.args:
        try:
            target = int(context.args[0])
        except ValueError:
            target = None
    if not target:
        await update.message.reply_text("رد على رسالة الشخص أو اكتب /block <id>")
        return
    if target not in rec["blocked"]:
        rec["blocked"].append(target)
        save_data(DATA)
    await update.message.reply_text(f"تم حظر {target} 🚫")


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
        save_data(DATA)
    await update.message.reply_text(f"تم فك الحظر عن {target} ✅")


async def child_mute(update, context):
    owner_id = context.bot_data["owner_id"]
    token = context.bot_data["token"]
    if update.effective_user.id != owner_id:
        return
    rec = _bot_record(owner_id)
    target = _child_target_from_reply(update, token)
    if not target and context.args:
        try:
            target = int(context.args[0])
        except ValueError:
            target = None
    if not target:
        await update.message.reply_text("رد على رسالة الشخص أو اكتب /mute <id>")
        return
    if target not in rec["muted"]:
        rec["muted"].append(target)
        save_data(DATA)
    await update.message.reply_text(f"تم كتم {target} 🔇")


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
        save_data(DATA)
    await update.message.reply_text(f"تم فك الكتم عن {target} 🔊")


async def child_list(update, context):
    owner_id = context.bot_data["owner_id"]
    if update.effective_user.id != owner_id:
        return
    rec = _bot_record(owner_id)
    blocked = ", ".join(map(str, rec["blocked"])) or "لا يوجد"
    muted = ", ".join(map(str, rec["muted"])) or "لا يوجد"
    await update.message.reply_text(f"🚫 المحظورين: {blocked}\n🔇 المكتومين: {muted}")


async def child_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if msg is None:
        return
    owner_id = context.bot_data["owner_id"]
    token = context.bot_data["token"]
    rec = _bot_record(owner_id)
    if rec is None:
        return

    # ====== صاحب البوت عم يرد ======
    if msg.from_user.id == owner_id:
        if msg.reply_to_message:
            target = MSG_MAP.get(token, {}).get(msg.reply_to_message.message_id)
            if target:
                try:
                    await context.bot.copy_message(
                        chat_id=target,
                        from_chat_id=msg.chat_id,
                        message_id=msg.message_id,
                    )
                except Exception as e:
                    await msg.reply_text(f"ما قدرت ابعت الرد: {e}")
            else:
                await msg.reply_text("ما لقيت لمين ابعت الرد. رد على الرسالة الموصولة.")
        return

    # ====== شخص عادي عم يبعت ======
    uid = msg.from_user.id
    if uid in rec["blocked"]:
        return
    if uid in rec["muted"]:
        return

    text = msg.text or msg.caption or ""
    if LINK_PATTERN.search(text):
        await msg.reply_text("ممنوع إرسال روابط 🚫")
        return

    try:
        u = msg.from_user
        full_name = u.full_name or "بدون اسم"
        username = f"@{u.username}" if u.username else "بدون يوزر"
        header = f"👤 {full_name}\n🔗 {username}\n🆔 {u.id}"

        sent_header = False
        try:
            photos = await context.bot.get_user_profile_photos(u.id, limit=1)
            if photos.total_count > 0:
                file_id = photos.photos[0][-1].file_id
                await context.bot.send_photo(
                    chat_id=owner_id, photo=file_id, caption=header
                )
                sent_header = True
        except Exception:
            pass
        if not sent_header:
            await context.bot.send_message(chat_id=owner_id, text=header)

        fwd = await context.bot.copy_message(
            chat_id=owner_id,
            from_chat_id=msg.chat_id,
            message_id=msg.message_id,
        )
        MSG_MAP.setdefault(token, {})[fwd.message_id] = uid
    except Exception as e:
        log.error(f"خطأ بالتوصيل (child): {e}")


def build_child_app(token, owner_id):
    """يبني Application لبوت طفل"""
    app = ApplicationBuilder().token(token).build()
    app.bot_data["owner_id"] = owner_id
    app.bot_data["token"] = token
    app.add_handler(CommandHandler("start", child_start))
    app.add_handler(CommandHandler("block", child_block))
    app.add_handler(CommandHandler("unblock", child_unblock))
    app.add_handler(CommandHandler("mute", child_mute))
    app.add_handler(CommandHandler("unmute", child_unmute))
    app.add_handler(CommandHandler("list", child_list))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, child_message))
    return app


async def start_child_bot(token, owner_id):
    """يشغّل بوت طفل على نفس الـ loop"""
    if token in RUNNING:
        return True, "شغّال أصلاً"
    app = build_child_app(token, owner_id)
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
#                        البوت الرئيسي (Owner)
# ==================================================================
async def owner_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    rec = DATA["bots"].get(str(uid))
    if rec and rec["token"] in RUNNING:
        try:
            me = await RUNNING[rec["token"]].bot.get_me()
            uname = f"@{me.username}"
        except Exception:
            uname = "بوتك"
        kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton("🗑 حذف بوتي", callback_data="delete_bot")]]
        )
        await update.message.reply_text(
            f"عندك بوت شغّال: {uname} ✅\n\n"
            "الناس اللي بتبعتله رح توصلك رسائلهم فيه.\n"
            "إذا بدك تبدّل التوكن، احذف بوتك الحالي وابعت توكن جديد.",
            reply_markup=kb,
        )
        return

    await update.message.reply_text(
        "🤖 أهلين فيك بمنصة إنشاء بوت \"الناس تحكيني\"!\n\n"
        "بخطوة وحدة بيصير عندك بوت خاص، الناس بتبعتله رسائل مجهولة "
        "وبتوصلك، وبترد عليهم من دون ما يعرفوا مين أنت.\n\n"
        "🔹 كيف تبدأ:\n"
        "1) روح عند @BotFather واعمل /newbot\n"
        "2) خد التوكن اللي بيعطيك ياه\n"
        "3) ابعتلي التوكن هون مباشرة\n\n"
        "وأنا بشغّلك بوتك فوراً 🚀"
    )


async def owner_delete_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    rec = DATA["bots"].get(str(uid))
    if not rec:
        await q.edit_message_text("ما عندك بوت لحذفه.")
        return
    token = rec["token"]
    await stop_child_bot(token)
    MSG_MAP.pop(token, None)
    DATA["bots"].pop(str(uid), None)
    save_data(DATA)
    await q.edit_message_text("تم حذف بوتك 🗑\nابعتلي توكن جديد وقت ما بدك.")


async def owner_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أي رسالة نصية للبوت الرئيسي: نتعامل معها كتوكن محتمل"""
    msg = update.message
    if not msg or not msg.text:
        return
    uid = msg.from_user.id
    text = msg.text.strip()

    if not TOKEN_PATTERN.match(text):
        await msg.reply_text(
            "ابعتلي توكن بوت صحيح 🔑\n"
            "شكله هيك تقريباً:\n"
            "123456789:AAExxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx\n\n"
            "خده من @BotFather بعد أمر /newbot"
        )
        return

    # عنده بوت أصلاً؟
    old = DATA["bots"].get(str(uid))
    if old:
        await stop_child_bot(old["token"])
        MSG_MAP.pop(old["token"], None)

    if text in RUNNING:
        await msg.reply_text("هالتوكن مستعمل بحساب تاني. استعمل توكن غيره.")
        return

    status = await msg.reply_text("⏳ عم شغّل بوتك...")

    # نجهّز السجل
    DATA["bots"][str(uid)] = {"token": text, "blocked": [], "muted": []}
    ok, info = await start_child_bot(text, uid)

    if ok:
        save_data(DATA)
        await status.edit_text(
            f"✅ تم! بوتك @{info} صار شغّال.\n\n"
            "جرّبه: افتحه وابعتله /start، وخلي حدا تاني يبعتله رسالة — رح توصلك هون بالبوت اللي فتحته."
        )
    else:
        DATA["bots"].pop(str(uid), None)
        save_data(DATA)
        await status.edit_text(
            "❌ ما قدرت شغّل البوت بهالتوكن.\n"
            f"السبب: {info}\n\n"
            "تأكد إنك ناسخ التوكن كامل وصحيح من @BotFather."
        )


def build_owner_app():
    app = ApplicationBuilder().token(OWNER_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", owner_start))
    app.add_handler(CallbackQueryHandler(owner_delete_cb, pattern="^delete_bot$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, owner_message))
    return app


# ==================================================================
#            سيرفر ويب صغير (عشان Render المجاني يرضى)
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
    """يرجّع تشغيل كل البوتات المحفوظة بعد إعادة التشغيل"""
    for owner_id, rec in list(DATA["bots"].items()):
        ok, info = await start_child_bot(rec["token"], int(owner_id))
        if ok:
            log.info(f"↻ رجّعت بوت المستخدم {owner_id} (@{info})")
        else:
            log.warning(f"⚠️ ما قدرت أرجّع بوت {owner_id}: {info}")


async def run():
    global MAIN_LOOP
    MAIN_LOOP = asyncio.get_running_loop()

    owner_app = build_owner_app()
    await owner_app.initialize()
    await owner_app.start()
    await owner_app.updater.start_polling(drop_pending_updates=True)
    log.info("✅ البوت الرئيسي شغّال")

    # نرجّع البوتات المحفوظة
    await restore_bots()

    # نضل شغالين
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
