# -*- coding: utf-8 -*-
"""
بوت رسائل خاص — الناس بتبعتلك، الرسائل بتوصلك عالبوت وأنت بترد عليها مباشرة.
مع: حظر (block/unblock)، كتم (mute/unmute)، منع الروابط/السبام.

طريقة التشغيل مكتوبة بملف README.txt المرفق.
"""

import json
import os
import re
import logging

from telegram import Update
from telegram.ext import (
    Application,
    MessageHandler,
    CommandHandler,
    filters,
    ContextTypes,
)

# ================== الإعدادات ==================
TOKEN = os.environ.get("BOT_TOKEN", "8976312381:AAGi1hsCQZEwCPPWqcq1kQ-86AFYgfYi8LY")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "7584371298"))  # ايدي حسابك (رقم)

DATA_FILE = "bot_data.json"
# ===============================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

# رابط / يوزرنيم / سبام — regex بسيط
LINK_PATTERN = re.compile(
    r"(https?://|www\.|t\.me/|telegram\.me/|@\w{4,})",
    re.IGNORECASE,
)


# ---------- حفظ وتحميل البيانات ----------
def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
            d["blocked"] = set(d.get("blocked", []))
            d["muted"] = set(d.get("muted", []))
            # المفاتيح لازم تكون int
            d["map"] = {int(k): v for k, v in d.get("map", {}).items()}
            return d
    return {"blocked": set(), "muted": set(), "map": {}}


def save_data(data):
    out = {
        "blocked": list(data["blocked"]),
        "muted": list(data["muted"]),
        "map": data["map"],
    }
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)


# ---------- أوامر الأدمن ----------
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id == ADMIN_ID:
        await update.message.reply_text(
            "أهلين 👋 هدا بوت الرسائل تبعك.\n\n"
            "الأوامر:\n"
            "رد على أي رسالة موصولة = بيوصل ردك للشخص.\n"
            "/block  (بالرد على رسالة) = حظر الشخص\n"
            "/unblock <id> = فك الحظر\n"
            "/mute   (بالرد على رسالة) = كتم الشخص\n"
            "/unmute <id> = فك الكتم\n"
            "/list = عرض المحظورين والمكتومين"
        )
    else:
        await update.message.reply_text("أهلين! ابعتلي رسالتك ورح ارد عليك 🌟")


def _target_from_reply(update, context):
    """يرجّع ايدي الشخص الأصلي من الرسالة الموصولة اللي عم يرد عليها الأدمن"""
    reply = update.message.reply_to_message
    if not reply:
        return None
    return context.bot_data["store"]["map"].get(reply.message_id)


async def block_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        return
    store = context.bot_data["store"]
    target = _target_from_reply(update, context)
    if not target and context.args:
        target = int(context.args[0])
    if not target:
        await update.message.reply_text("رد على رسالة الشخص أو اكتب /block <id>")
        return
    store["blocked"].add(target)
    save_data(store)
    await update.message.reply_text(f"تم حظر {target} 🚫")


async def unblock_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        return
    store = context.bot_data["store"]
    if not context.args:
        await update.message.reply_text("اكتب /unblock <id>")
        return
    target = int(context.args[0])
    store["blocked"].discard(target)
    save_data(store)
    await update.message.reply_text(f"تم فك الحظر عن {target} ✅")


async def mute_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        return
    store = context.bot_data["store"]
    target = _target_from_reply(update, context)
    if not target and context.args:
        target = int(context.args[0])
    if not target:
        await update.message.reply_text("رد على رسالة الشخص أو اكتب /mute <id>")
        return
    store["muted"].add(target)
    save_data(store)
    await update.message.reply_text(f"تم كتم {target} 🔇")


async def unmute_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        return
    store = context.bot_data["store"]
    if not context.args:
        await update.message.reply_text("اكتب /unmute <id>")
        return
    target = int(context.args[0])
    store["muted"].discard(target)
    save_data(store)
    await update.message.reply_text(f"تم فك الكتم عن {target} 🔊")


async def list_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        return
    store = context.bot_data["store"]
    blocked = ", ".join(map(str, store["blocked"])) or "لا يوجد"
    muted = ", ".join(map(str, store["muted"])) or "لا يوجد"
    await update.message.reply_text(
        f"🚫 المحظورين: {blocked}\n🔇 المكتومين: {muted}"
    )


# ---------- معالجة الرسائل ----------
async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if msg is None:
        return
    store = context.bot_data["store"]

    # ====== حالة (1): الأدمن عم يرد ======
    if msg.from_user.id == ADMIN_ID:
        if msg.reply_to_message:
            target = store["map"].get(msg.reply_to_message.message_id)
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

    # ====== حالة (2): شخص عادي عم يبعت ======
    uid = msg.from_user.id

    if uid in store["blocked"]:
        return  # محظور: ما بيوصلك ولا بيرد عليه

    if uid in store["muted"]:
        # مكتوم: البوت بيتجاهل بصمت (الرسالة ما بتوصلك)
        return

    # منع الروابط/السبام
    text = msg.text or msg.caption or ""
    if LINK_PATTERN.search(text):
        await msg.reply_text("ممنوع إرسال روابط 🚫")
        return

    # وصّل الرسالة للأدمن
    try:
        fwd = await context.bot.copy_message(
            chat_id=ADMIN_ID,
            from_chat_id=msg.chat_id,
            message_id=msg.message_id,
        )
        # اربط الرسالة الموصولة بصاحبها الأصلي
        store["map"][fwd.message_id] = uid
        save_data(store)
    except Exception as e:
        logging.error(f"خطأ بالتوصيل: {e}")


def main():
    if not TOKEN or "حط_توكن" in TOKEN:
        raise SystemExit("⚠️ لازم تحط توكن البوت بمتغير BOT_TOKEN أو داخل الكود.")
    if ADMIN_ID == 0:
        raise SystemExit("⚠️ لازم تحط ايدي حسابك بمتغير ADMIN_ID.")

    app = Application.builder().token(TOKEN).build()
    app.bot_data["store"] = load_data()

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("block", block_cmd))
    app.add_handler(CommandHandler("unblock", unblock_cmd))
    app.add_handler(CommandHandler("mute", mute_cmd))
    app.add_handler(CommandHandler("unmute", unmute_cmd))
    app.add_handler(CommandHandler("list", list_cmd))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, on_message))

    print("✅ البوت شغال...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
