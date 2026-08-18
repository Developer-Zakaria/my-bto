# -*- coding: utf-8 -*-
"""📢 بوت إذاعة — يجمع مشتركين ويبعتلهم رسائل جماعية."""

import asyncio
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

import bot as core


def panel_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 إرسال رسالة جماعية", callback_data="bc_send")],
        [InlineKeyboardButton("📊 إحصائيات", callback_data="bc_stats")],
        [InlineKeyboardButton("🔄 تحديث", callback_data="bc_refresh")],
    ])


def back_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="bc_refresh")]])


def panel_text(rec):
    total = len(rec.get("users", {}))
    stats = rec.get("broadcast_stats", {})
    last_at = stats.get("last_at") or "—"
    return (
        "📢 <b>لوحة بوت الإذاعة</b>\n"
        "━━━━━━━━━━━━━━━\n"
        f"👥 المشتركين: <b>{total}</b>\n"
        f"📨 آخر إرسال: {last_at}\n"
        f"✅ وصلت: {stats.get('last_sent', 0)}  •  ❌ فشلت: {stats.get('last_failed', 0)}\n\n"
        "استعمل الأزرار تحت 👇"
    )


async def child_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    owner_id = context.bot_data["owner_id"]
    uid = update.effective_user.id
    rec = core._bot_record(owner_id)

    if uid == owner_id:
        await update.message.reply_text(panel_text(rec), parse_mode=ParseMode.HTML, reply_markup=panel_kb())
    else:
        core._track_user(rec, uid, update.effective_user.full_name, owner_id, inc=False)
        await update.message.reply_text(
            "🔔 أهلاً! صرت مشترك بقناة التحديثات هاي، رح توصلك الرسائل هون أول ما تنبعت."
            + core.promo_line(),
            reply_markup=core.promo_kb(),
        )


async def panel_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    owner_id = context.bot_data["owner_id"]
    if q.from_user.id != owner_id:
        await q.answer("مش مسموح", show_alert=True)
        return
    rec = core._bot_record(owner_id)
    data = q.data

    if data == "bc_refresh":
        core.AWAITING.pop(owner_id, None)
        await q.answer()
        await q.edit_message_text(panel_text(rec), parse_mode=ParseMode.HTML, reply_markup=panel_kb())
        return

    if data == "bc_stats":
        await q.answer()
        await q.edit_message_text(panel_text(rec), parse_mode=ParseMode.HTML, reply_markup=back_kb())
        return

    if data == "bc_send":
        core.AWAITING[owner_id] = "broadcast"
        await q.answer()
        await q.edit_message_text(
            "📢 ابعتلي الرسالة يلي بدك تذيعها (نص/صورة/فيديو) وبتنبعت لكل المشتركين فوراً.",
            reply_markup=back_kb(),
        )
        return


async def _do_broadcast(bot, owner_id, rec, source_msg):
    users = rec.get("users", {})
    status = await source_msg.reply_text(f"⏳ عم ابعت لـ {len(users)} مشترك...")
    sent, failed = 0, 0
    for uid in list(users.keys()):
        try:
            await bot.copy_message(
                chat_id=int(uid), from_chat_id=source_msg.chat_id, message_id=source_msg.message_id
            )
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)

    rec["broadcast_stats"] = {
        "last_sent": sent,
        "last_failed": failed,
        "last_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    core.persist(owner_id)
    await status.edit_text(f"✅ تم الإرسال.\n📨 وصلت: {sent}\n❌ فشلت: {failed}")


async def child_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if msg is None:
        return
    owner_id = context.bot_data["owner_id"]
    rec = core._bot_record(owner_id)
    if rec is None:
        return

    if msg.from_user.id == owner_id:
        if core.AWAITING.get(owner_id) == "broadcast":
            core.AWAITING.pop(owner_id, None)
            await _do_broadcast(context.bot, owner_id, rec, msg)
        return

    uid = msg.from_user.id
    core._track_user(rec, uid, msg.from_user.full_name, owner_id, inc=True)


def register(app, owner_id, token):
    app.add_handler(CommandHandler("start", child_start))
    app.add_handler(CallbackQueryHandler(panel_cb, pattern="^bc_"))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, child_message))
