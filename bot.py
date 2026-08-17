# -*- coding: utf-8 -*-
"""
🤖 بوت أب (Bot-Up) — منصة إنشاء بوتات "الناس تحكيني" | تطوير: @zyh011

الفكرة:
  • بوت رئيسي واحد (منصة). أي شخص بيفوت عليه بيحط توكن بوته.
  • بصير عندو بوت خاص "الناس تحكيني" كامل بكل الميزات.
  • الرسائل بتوصل مع اسم المرسِل + زر لفتح صورته + زر حظر/كتم سريع.
  • كلو مجاني. كل بوت مستقل.

التشغيل: يحتاج متغير OWNER_BOT_TOKEN (توكن البوت الرئيسي).
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
DATA_FILE = os.environ.get("DATA_FILE", "botup_data.json")

# صاحب المنصة (بيبين للناس)
DEVELOPER = "@zyh011"
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
    d.setdefault("bots", {})   # owner_id -> {token, blocked[], muted[], welcome}
    return d


def save_data(data):
    with _data_lock:
        tmp = DATA_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, DATA_FILE)


DATA = load_data()

RUNNING = {}        # token -> Application
MSG_MAP = {}        # token -> { admin_msg_id: sender_id }
MAIN_LOOP = None


def _bot_record(owner_id):
    return DATA["bots"].get(str(owner_id))


def esc(text):
    """تهريب رموز HTML عشان الأسماء ما تكسر التنسيق"""
    if not text:
        return ""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


# ==================================================================
#                    بوت الطفل (اللي بيشغله كل مستخدم)
# ==================================================================
DEFAULT_WELCOME = "أهلين! 🌟 ابعتلي رسالتك ورح ارد عليك."


async def child_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    owner_id = context.bot_data["owner_id"]
    uid = update.effective_user.id
    rec = _bot_record(owner_id)

    if uid == owner_id:
        text = (
            "🎛 <b>لوحة تحكم بوتك</b>\n\n"
            "بوتك شغّال تمام ✅\n"
            "لما حدا يبعتلك، بتوصلك رسالته مع اسمه، وبتلاقي أزرار سريعة "
            "لفتح صورته أو حظره أو كتمه.\n\n"
            "🔹 <b>للرد:</b> اعمل reply على رسالة الشخص.\n\n"
            "🔹 <b>الأوامر:</b>\n"
            "/setwelcome — تغيير رسالة الترحيب\n"
            "/list — المحظورين والمكتومين\n"
            "/unblock &lt;id&gt; — فك حظر\n"
            "/unmute &lt;id&gt; — فك كتم"
        )
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)
    else:
        welcome = (rec or {}).get("welcome") or DEFAULT_WELCOME
        await update.message.reply_text(welcome)


async def child_setwelcome(update, context):
    owner_id = context.bot_data["owner_id"]
    if update.effective_user.id != owner_id:
        return
    rec = _bot_record(owner_id)
    if not context.args:
        await update.message.reply_text(
            "اكتب رسالة الترحيب بعد الأمر، مثال:\n"
            "/setwelcome أهلا فيك، اكتب رسالتك وبرد عليك بأسرع وقت 💬"
        )
        return
    new_welcome = update.message.text.split(None, 1)[1]
    rec["welcome"] = new_welcome
    save_data(DATA)
    await update.message.reply_text("✅ تم تغيير رسالة الترحيب.")


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
        save_data(DATA)
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
        save_data(DATA)
    await update.message.reply_text(f"🔊 تم فك الكتم عن {target}")


async def child_list(update, context):
    owner_id = context.bot_data["owner_id"]
    if update.effective_user.id != owner_id:
        return
    rec = _bot_record(owner_id)
    blocked = ", ".join(map(str, rec["blocked"])) or "لا يوجد"
    muted = ", ".join(map(str, rec["muted"])) or "لا يوجد"
    await update.message.reply_text(
        f"🚫 <b>المحظورين:</b> {blocked}\n🔇 <b>المكتومين:</b> {muted}",
        parse_mode=ParseMode.HTML,
    )


async def child_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أزرار الرسالة: فتح الصورة / حظر / كتم"""
    q = update.callback_query
    owner_id = context.bot_data["owner_id"]
    if q.from_user.id != owner_id:
        await q.answer("مش مسموح", show_alert=True)
        return
    rec = _bot_record(owner_id)
    data = q.data or ""

    if data.startswith("pic:"):
        file_id = data[4:]
        try:
            await context.bot.send_photo(
                chat_id=owner_id, photo=file_id, caption="🖼 صورة المرسِل"
            )
            await q.answer()
        except Exception:
            await q.answer("ما قدرت أفتح الصورة", show_alert=True)
        return

    if data.startswith("blk:"):
        target = int(data[4:])
        if target not in rec["blocked"]:
            rec["blocked"].append(target)
            save_data(DATA)
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
            save_data(DATA)
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
                    await msg.set_reaction("👍")
                except Exception as e:
                    await msg.reply_text(f"ما قدرت ابعت الرد: {e}")
            else:
                await msg.reply_text("↩️ رد على رسالة الشخص نفسها عشان يوصله ردك.")
        return

    # ====== شخص عادي عم يبعت ======
    uid = msg.from_user.id
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

        # نجيب صورة البروفايل (لو موجودة) — للزر المصغّر
        pic_file_id = None
        try:
            photos = await context.bot.get_user_profile_photos(u.id, limit=1)
            if photos.total_count > 0:
                # نستعمل أصغر حجم للزر (thumbnail)
                pic_file_id = photos.photos[0][0].file_id
        except Exception:
            pass

        # سطر معلومات أنيق
        header = (
            f"📨 <b>رسالة جديدة</b>\n"
            f"━━━━━━━━━━━━━\n"
            f"👤 <b>{full_name}</b>\n"
            f"🔗 {username}\n"
            f"🆔 <code>{u.id}</code>"
        )

        # أزرار سريعة
        buttons = []
        if pic_file_id:
            buttons.append(
                InlineKeyboardButton("🖼 الصورة", callback_data=f"pic:{pic_file_id}")
            )
        buttons.append(
            InlineKeyboardButton("🚫 حظر", callback_data=f"blk:{u.id}")
        )
        buttons.append(
            InlineKeyboardButton("🔇 كتم", callback_data=f"mut:{u.id}")
        )
        kb = InlineKeyboardMarkup([buttons])

        await context.bot.send_message(
            chat_id=owner_id,
            text=header,
            parse_mode=ParseMode.HTML,
            reply_markup=kb,
        )

        # الرسالة نفسها (اللي بيرد عليها)
        fwd = await context.bot.copy_message(
            chat_id=owner_id,
            from_chat_id=msg.chat_id,
            message_id=msg.message_id,
        )
        MSG_MAP.setdefault(token, {})[fwd.message_id] = uid

        # نعلم الشخص إنه رسالته وصلت
        try:
            await msg.set_reaction("✅")
        except Exception:
            pass
    except Exception as e:
        log.error(f"خطأ بالتوصيل (child): {e}")


def build_child_app(token, owner_id):
    app = ApplicationBuilder().token(token).build()
    app.bot_data["owner_id"] = owner_id
    app.bot_data["token"] = token
    app.add_handler(CommandHandler("start", child_start))
    app.add_handler(CommandHandler("setwelcome", child_setwelcome))
    app.add_handler(CommandHandler("unblock", child_unblock))
    app.add_handler(CommandHandler("unmute", child_unmute))
    app.add_handler(CommandHandler("list", child_list))
    app.add_handler(CallbackQueryHandler(child_buttons, pattern="^(pic|blk|mut):"))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, child_message))
    return app


async def start_child_bot(token, owner_id):
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
#                        البوت الرئيسي (المنصة)
# ==================================================================
def _owner_menu(has_bot, bot_username=None):
    rows = []
    if has_bot:
        rows.append(
            [InlineKeyboardButton(f"🤖 بوتي: @{bot_username}", url=f"https://t.me/{bot_username}")]
        )
        rows.append(
            [InlineKeyboardButton("🗑 حذف بوتي", callback_data="delete_bot")]
        )
    rows.append(
        [InlineKeyboardButton("👨‍💻 المطوّر", url=f"https://t.me/{DEVELOPER.lstrip('@')}")]
    )
    return InlineKeyboardMarkup(rows)


async def owner_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    rec = DATA["bots"].get(str(uid))

    if rec and rec["token"] in RUNNING:
        try:
            me = await RUNNING[rec["token"]].bot.get_me()
            uname = me.username
        except Exception:
            uname = None
        await update.message.reply_text(
            "✨ <b>عندك بوت شغّال!</b>\n\n"
            "الناس اللي بتبعتله رح توصلك رسائلهم فيه، وبترد عليهم "
            "من دون ما يعرفوا مين أنت.\n\n"
            "بتقدر تفتح بوتك من الزر تحت 👇",
            parse_mode=ParseMode.HTML,
            reply_markup=_owner_menu(True, uname),
        )
        return

    await update.message.reply_text(
        "🤖 <b>أهلين فيك بمنصة إنشاء بوتات الرسائل!</b>\n\n"
        "بخطوة وحدة بيصير عندك بوت خاص، الناس بتبعتله رسائل "
        "وبتوصلك، وبترد عليهم بسرية تامة 🔒\n\n"
        "📝 <b>كيف تبدأ:</b>\n"
        "1️⃣ روح عند @BotFather واكتب /newbot\n"
        "2️⃣ خد التوكن اللي بيعطيك ياه\n"
        "3️⃣ ابعتلي التوكن هون\n\n"
        "وأنا بشغّلك بوتك فوراً 🚀\n\n"
        f"━━━━━━━━━━━━━\n👨‍💻 تطوير: {DEVELOPER}",
        parse_mode=ParseMode.HTML,
        reply_markup=_owner_menu(False),
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
    await q.edit_message_text(
        "🗑 تم حذف بوتك.\nابعتلي توكن جديد وقت ما بدك عشان تعمل بوت جديد."
    )


async def owner_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text:
        return
    uid = msg.from_user.id
    text = msg.text.strip()

    if not TOKEN_PATTERN.match(text):
        await msg.reply_text(
            "🔑 ابعتلي <b>توكن بوت</b> صحيح.\n\n"
            "شكله هيك تقريباً:\n"
            "<code>123456789:AAExxxxxxxxxxxxxxxxxxxxxxxxx</code>\n\n"
            "خده من @BotFather بعد أمر /newbot",
            parse_mode=ParseMode.HTML,
        )
        return

    old = DATA["bots"].get(str(uid))
    if old:
        await stop_child_bot(old["token"])
        MSG_MAP.pop(old["token"], None)

    if text in RUNNING:
        await msg.reply_text("⚠️ هالتوكن مستعمل بحساب تاني. استعمل توكن غيره.")
        return

    status = await msg.reply_text("⏳ عم شغّل بوتك...")

    DATA["bots"][str(uid)] = {"token": text, "blocked": [], "muted": [], "welcome": ""}
    ok, info = await start_child_bot(text, uid)

    if ok:
        save_data(DATA)
        await status.edit_text(
            f"✅ <b>تم بنجاح!</b>\n\n"
            f"بوتك @{info} صار شغّال 🎉\n\n"
            "افتحه واكتب /start، وخلي الناس يبعتولك — رح توصلك الرسائل هون بالبوت اللي عملته.\n\n"
            f"👨‍💻 تطوير المنصة: {DEVELOPER}",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton(f"🚀 افتح @{info}", url=f"https://t.me/{info}")]]
            ),
        )
    else:
        DATA["bots"].pop(str(uid), None)
        save_data(DATA)
        await status.edit_text(
            "❌ ما قدرت شغّل البوت بهالتوكن.\n"
            f"<b>السبب:</b> {esc(info)}\n\n"
            "تأكد إنك ناسخ التوكن كامل وصحيح من @BotFather.",
            parse_mode=ParseMode.HTML,
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
