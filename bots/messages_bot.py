# -*- coding: utf-8 -*-
"""بوت رسائل — الناس تحكيني بسرية. منطق مطابق تماماً لما كان بـ bot.py الأصلي."""

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
    rec = core._bot_record(owner_id)

    if uid == owner_id:
        await update.message.reply_text(
            panel_text(rec), parse_mode=ParseMode.HTML, reply_markup=panel_kb(rec)
        )
    else:
        core._track_user(rec, uid, update.effective_user.full_name, owner_id, inc=False)
        welcome = (rec or {}).get("welcome") or core.DEFAULT_WELCOME
        await update.message.reply_text(
            welcome + core.promo_line(),
            reply_markup=core.promo_kb(),
        )


async def child_panel_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """كل أزرار لوحة التحكم"""
    q = update.callback_query
    owner_id = context.bot_data["owner_id"]
    if q.from_user.id != owner_id:
        await q.answer("مش مسموح", show_alert=True)
        return
    rec = core._bot_record(owner_id)
    data = q.data

    if data == "p_refresh":
        core.AWAITING.pop(owner_id, None)
        await q.answer()
        try:
            await q.edit_message_text(panel_text(rec), parse_mode=ParseMode.HTML, reply_markup=panel_kb(rec))
        except Exception:
            await context.bot.send_message(owner_id, panel_text(rec), parse_mode=ParseMode.HTML, reply_markup=panel_kb(rec))
        return

    if data == "p_welcome":
        core.AWAITING[owner_id] = "welcome"
        await q.answer()
        cur = rec.get("welcome") or core.DEFAULT_WELCOME
        await q.edit_message_text(
            f"✏️ <b>رسالة الترحيب الحالية:</b>\n\n{core.esc(cur)}\n\n"
            "ابعتلي الرسالة الجديدة كنص عادي 👇",
            parse_mode=ParseMode.HTML, reply_markup=back_kb(),
        )
        return

    if data == "p_busymsg":
        core.AWAITING[owner_id] = "busy"
        await q.answer()
        cur = rec.get("busy_msg") or core.DEFAULT_BUSY
        await q.edit_message_text(
            f"📝 <b>رسالة المشغول الحالية:</b>\n\n{core.esc(cur)}\n\n"
            "ابعتلي النص الجديد 👇",
            parse_mode=ParseMode.HTML, reply_markup=back_kb(),
        )
        return

    if data == "p_antilink":
        rec["antilink"] = not rec.get("antilink", True)
        core.persist(owner_id)
        await q.answer("تم التغيير ✅")
        await q.edit_message_text(panel_text(rec), parse_mode=ParseMode.HTML, reply_markup=panel_kb(rec))
        return

    if data == "p_pause":
        rec["paused"] = not rec.get("paused", False)
        core.persist(owner_id)
        await q.answer("⏸ موقوف" if rec["paused"] else "▶️ يستقبل")
        await q.edit_message_text(panel_text(rec), parse_mode=ParseMode.HTML, reply_markup=panel_kb(rec))
        return

    if data == "p_busy":
        rec["busy"] = not rec.get("busy", False)
        core.persist(owner_id)
        await q.answer("💤 مشغول" if rec["busy"] else "✅ متاح")
        await q.edit_message_text(panel_text(rec), parse_mode=ParseMode.HTML, reply_markup=panel_kb(rec))
        return

    if data == "p_users":
        await q.answer()
        users = rec.get("users", {})
        if not users:
            body = "ما في مستخدمين بعد."
        else:
            items = sorted(users.items(), key=lambda x: x[1].get("count", 0), reverse=True)
            lines = []
            for i, (uid, info) in enumerate(items[:40], 1):
                lines.append(f"{i}. {core.esc(info.get('name','?'))} — <code>{uid}</code> ({info.get('count',0)} رسالة)")
            if len(items) > 40:
                lines.append(f"... و{len(items)-40} غيرهم")
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
    rec = core._bot_record(owner_id)
    data = q.data or ""

    if data.startswith("pic:"):
        file_id = core.PIC_STORE.get(data[4:])
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
            core.persist(owner_id)
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
            core.persist(owner_id)
        await q.answer("🔇 تم الكتم")
        return


async def child_unblock(update, context):
    owner_id = context.bot_data["owner_id"]
    if update.effective_user.id != owner_id:
        return
    rec = core._bot_record(owner_id)
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
        core.persist(owner_id)
    await update.message.reply_text(f"✅ تم فك الحظر عن {target}")


async def child_unmute(update, context):
    owner_id = context.bot_data["owner_id"]
    if update.effective_user.id != owner_id:
        return
    rec = core._bot_record(owner_id)
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
        core.persist(owner_id)
    await update.message.reply_text(f"🔊 تم فك الكتم عن {target}")


async def child_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if msg is None:
        return
    owner_id = context.bot_data["owner_id"]
    token = context.bot_data["token"]
    rec = core._bot_record(owner_id)
    if rec is None:
        return

    # ====== صاحب البوت ======
    if msg.from_user.id == owner_id:
        pending = core.AWAITING.get(owner_id)
        if pending and msg.text and not msg.reply_to_message:
            if pending == "welcome":
                rec["welcome"] = msg.text
            elif pending == "busy":
                rec["busy_msg"] = msg.text
            core.persist(owner_id)
            core.AWAITING.pop(owner_id, None)
            await msg.reply_text("✅ تم الحفظ.", reply_markup=back_kb())
            return

        if msg.reply_to_message:
            target = core.MSG_MAP.get(token, {}).get(msg.reply_to_message.message_id)
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
    core._track_user(rec, uid, msg.from_user.full_name, owner_id, inc=True)

    if uid in rec["blocked"]:
        return
    if uid in rec["muted"]:
        return

    if rec.get("paused"):
        return

    text = msg.text or msg.caption or ""
    if rec.get("antilink", True) and core.LINK_PATTERN.search(text):
        await msg.reply_text("🚫 ممنوع إرسال روابط.")
        return

    try:
        u = msg.from_user
        full_name = core.esc(u.full_name) or "بدون اسم"
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
            buttons.append(InlineKeyboardButton("🖼", callback_data=f"pic:{core._store_pic(pic_file_id)}"))
        buttons.append(InlineKeyboardButton("🚫 حظر", callback_data=f"blk:{u.id}"))
        buttons.append(InlineKeyboardButton("🔇 كتم", callback_data=f"mut:{u.id}"))

        await context.bot.send_message(
            chat_id=owner_id, text=header, parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([buttons]),
        )
        fwd = await context.bot.copy_message(
            chat_id=owner_id, from_chat_id=msg.chat_id, message_id=msg.message_id
        )
        core.MSG_MAP.setdefault(token, {})[fwd.message_id] = uid

        if rec.get("busy"):
            busy_msg = rec.get("busy_msg") or core.DEFAULT_BUSY
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
        core.log.error(f"خطأ بالتوصيل owner={owner_id}: {e}")


def register(app, owner_id, token):
    """يسجّل كل معالجات بوت الرسائل على الـ Application."""
    app.add_handler(CommandHandler("start", child_start))
    app.add_handler(CommandHandler("unblock", child_unblock))
    app.add_handler(CommandHandler("unmute", child_unmute))
    app.add_handler(CallbackQueryHandler(child_msg_buttons, pattern="^(pic|blk|mut):"))
    app.add_handler(CallbackQueryHandler(child_panel_cb, pattern="^p_"))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, child_message))
