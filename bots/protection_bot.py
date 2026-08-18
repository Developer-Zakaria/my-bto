# -*- coding: utf-8 -*-
"""🛡️ بوت حماية — يُضاف كمشرف لمجموعة ويحميها: روابط، سبام، توجيه قنوات، تحذيرات."""

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatPermissions
from telegram.constants import ParseMode
from telegram.ext import (
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

import bot as core


def _group_conf(rec, chat_id):
    groups = rec.setdefault("groups", {})
    key = str(chat_id)
    conf = groups.setdefault(key, {})
    conf.setdefault("antilink", True)
    conf.setdefault("antiforward", True)
    conf.setdefault("welcome_enabled", True)
    conf.setdefault("welcome_msg", "")
    conf.setdefault("warn_limit", 3)
    conf.setdefault("warnings", {})
    return conf


async def _is_group_admin(bot, chat_id, user_id):
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in ("administrator", "creator")
    except Exception:
        return False


async def child_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    owner_id = context.bot_data["owner_id"]
    uid = update.effective_user.id
    text = (
        "🛡️ <b>بوت الحماية</b>\n"
        "━━━━━━━━━━━━━━━\n"
        "ضيفني كمشرف (Admin) بمجموعتك وفعّل صلاحيات حذف الرسائل والحظر.\n\n"
        "بعدها اكتب <code>/settings</code> جوا المجموعة (لازم تكون مشرف) لتشغيل/إيقاف كل ميزة.\n\n"
        "<b>أوامر المشرفين (رد على رسالة الشخص):</b>\n"
        "🚫 <code>/ban</code>  •  👢 <code>/kick</code>  •  🔇 <code>/mute</code>  •  ⚠️ <code>/warn</code>\n\n"
        f"٣ تحذيرات = طرد تلقائي (قابل للتعديل بـ /settings)."
    )
    if uid != owner_id:
        text += core.promo_line()
        await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=core.promo_kb())
    else:
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)


def settings_text(conf):
    return (
        "⚙️ <b>إعدادات الحماية لهاي المجموعة</b>\n"
        "━━━━━━━━━━━━━━━\n"
        f"🔢 حد التحذيرات قبل الطرد: <b>{conf['warn_limit']}</b>\n"
        "استعمل الأزرار للتشغيل/الإيقاف 👇"
    )


def settings_kb(chat_id, conf):
    al = "🟢" if conf["antilink"] else "🔴"
    af = "🟢" if conf["antiforward"] else "🔴"
    wl = "🟢" if conf["welcome_enabled"] else "🔴"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🔗 منع الروابط {al}", callback_data=f"gset:al:{chat_id}")],
        [InlineKeyboardButton(f"📢 منع توجيه القنوات {af}", callback_data=f"gset:af:{chat_id}")],
        [InlineKeyboardButton(f"👋 ترحيب الأعضاء {wl}", callback_data=f"gset:wl:{chat_id}")],
    ])


async def cmd_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    owner_id = context.bot_data["owner_id"]
    if not await _is_group_admin(context.bot, chat.id, user.id):
        await update.message.reply_text("⚠️ بس مشرفين المجموعة يقدروا يغيّروا الإعدادات.")
        return
    rec = core._bot_record(owner_id)
    conf = _group_conf(rec, chat.id)
    core.persist(owner_id)
    await update.message.reply_text(
        settings_text(conf), parse_mode=ParseMode.HTML, reply_markup=settings_kb(chat.id, conf)
    )


async def settings_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    owner_id = context.bot_data["owner_id"]
    parts = (q.data or "").split(":")
    if len(parts) != 3:
        await q.answer()
        return
    _, key, chat_id = parts
    if not await _is_group_admin(context.bot, int(chat_id), q.from_user.id):
        await q.answer("مش مسموح", show_alert=True)
        return
    rec = core._bot_record(owner_id)
    conf = _group_conf(rec, chat_id)
    field = {"al": "antilink", "af": "antiforward", "wl": "welcome_enabled"}.get(key)
    if field:
        conf[field] = not conf[field]
        core.persist(owner_id)
    await q.answer("تم التغيير ✅")
    await q.edit_message_text(settings_text(conf), parse_mode=ParseMode.HTML, reply_markup=settings_kb(chat_id, conf))


async def welcome_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    owner_id = context.bot_data["owner_id"]
    rec = core._bot_record(owner_id)
    chat = update.effective_chat
    conf = _group_conf(rec, chat.id)
    core.persist(owner_id)
    if not conf.get("welcome_enabled", True):
        return
    for member in update.message.new_chat_members:
        if member.is_bot:
            continue
        msg = conf.get("welcome_msg") or f"👋 أهلاً {member.full_name} بمجموعتنا!"
        try:
            await update.message.reply_text(msg)
        except Exception:
            pass


async def _add_warning(bot, owner_id, conf, chat_id, user):
    warnings = conf.setdefault("warnings", {})
    key = str(user.id)
    warnings[key] = warnings.get(key, 0) + 1
    count = warnings[key]
    limit = conf.get("warn_limit", 3)
    core.persist(owner_id)
    if count >= limit:
        warnings[key] = 0
        core.persist(owner_id)
        try:
            await bot.ban_chat_member(chat_id, user.id)
            await bot.unban_chat_member(chat_id, user.id)
            await bot.send_message(chat_id, f"👢 تم طرد {user.full_name} بعد {limit} تحذيرات.")
        except Exception:
            pass
    else:
        try:
            await bot.send_message(chat_id, f"⚠️ تحذير {count}/{limit} لـ {user.full_name}")
        except Exception:
            pass


async def moderate_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if msg is None or msg.from_user is None or msg.from_user.is_bot:
        return
    owner_id = context.bot_data["owner_id"]
    rec = core._bot_record(owner_id)
    chat = update.effective_chat
    conf = _group_conf(rec, chat.id)

    if await _is_group_admin(context.bot, chat.id, msg.from_user.id):
        core.persist(owner_id)
        return

    text = msg.text or msg.caption or ""
    violated = False
    if conf.get("antilink", True) and core.LINK_PATTERN.search(text):
        violated = True
    if not violated and conf.get("antiforward", True) and msg.forward_from_chat is not None \
            and msg.forward_from_chat.type == "channel":
        violated = True

    if violated:
        try:
            await msg.delete()
        except Exception:
            pass
        await _add_warning(context.bot, owner_id, conf, chat.id, msg.from_user)
    else:
        core.persist(owner_id)


async def _require_reply_admin(update, context):
    chat = update.effective_chat
    user = update.effective_user
    if not await _is_group_admin(context.bot, chat.id, user.id):
        await update.message.reply_text("⚠️ بس مشرفين المجموعة يقدروا يستخدموا هالأمر.")
        return None
    if not update.message.reply_to_message:
        await update.message.reply_text("رد على رسالة الشخص المطلوب أولاً.")
        return None
    return update.message.reply_to_message.from_user


async def cmd_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target = await _require_reply_admin(update, context)
    if not target:
        return
    try:
        await context.bot.ban_chat_member(update.effective_chat.id, target.id)
        await update.message.reply_text(f"🚫 تم حظر {target.full_name}")
    except Exception as e:
        await update.message.reply_text(f"ما قدرت أحظر: {e}")


async def cmd_kick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target = await _require_reply_admin(update, context)
    if not target:
        return
    try:
        chat_id = update.effective_chat.id
        await context.bot.ban_chat_member(chat_id, target.id)
        await context.bot.unban_chat_member(chat_id, target.id)
        await update.message.reply_text(f"👢 تم طرد {target.full_name}")
    except Exception as e:
        await update.message.reply_text(f"ما قدرت أطرد: {e}")


async def cmd_mute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target = await _require_reply_admin(update, context)
    if not target:
        return
    try:
        await context.bot.restrict_chat_member(
            update.effective_chat.id, target.id, permissions=ChatPermissions(can_send_messages=False)
        )
        await update.message.reply_text(f"🔇 تم كتم {target.full_name}")
    except Exception as e:
        await update.message.reply_text(f"ما قدرت أكتم: {e}")


async def cmd_warn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target = await _require_reply_admin(update, context)
    if not target:
        return
    owner_id = context.bot_data["owner_id"]
    rec = core._bot_record(owner_id)
    conf = _group_conf(rec, update.effective_chat.id)
    await _add_warning(context.bot, owner_id, conf, update.effective_chat.id, target)


def register(app, owner_id, token):
    app.add_handler(CommandHandler("start", child_start, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("settings", cmd_settings, filters=filters.ChatType.GROUPS))
    app.add_handler(CommandHandler("ban", cmd_ban, filters=filters.ChatType.GROUPS))
    app.add_handler(CommandHandler("kick", cmd_kick, filters=filters.ChatType.GROUPS))
    app.add_handler(CommandHandler("mute", cmd_mute, filters=filters.ChatType.GROUPS))
    app.add_handler(CommandHandler("warn", cmd_warn, filters=filters.ChatType.GROUPS))
    app.add_handler(CallbackQueryHandler(settings_cb, pattern="^gset:"))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_new_member))
    app.add_handler(MessageHandler(
        filters.ChatType.GROUPS & filters.ALL & ~filters.COMMAND & ~filters.StatusUpdate.ALL,
        moderate_message,
    ))
