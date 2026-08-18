# -*- coding: utf-8 -*-
"""🔧 بوت أدوات — مختصر روابط، كلمة سر، حاسبة، تحويل عملات، QR، الوقت بالمناطق."""

import ast
import asyncio
import operator
import re
import secrets
import string
import urllib.parse
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

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

# (owner_id, uid) -> "calc" | "curr" | "short" | "qr"
TOOL_AWAITING = {}

CURRENCY_RATES = {  # تقريبية وثابتة، مقابل الدولار
    "USD": 1.0, "EUR": 0.92, "GBP": 0.79, "TRY": 34.0,
    "SAR": 3.75, "AED": 3.67, "EGP": 49.0, "JOD": 0.71,
}

TIMEZONES = [
    ("🇯🇴 عمّان", "Asia/Amman"),
    ("🇸🇦 الرياض", "Asia/Riyadh"),
    ("🇪🇬 القاهرة", "Africa/Cairo"),
    ("🇦🇪 دبي", "Asia/Dubai"),
    ("🇬🇧 لندن", "Europe/London"),
    ("🇺🇸 نيويورك", "America/New_York"),
    ("🇯🇵 طوكيو", "Asia/Tokyo"),
]

_ALLOWED_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod,
    ast.USub: operator.neg, ast.UAdd: operator.pos,
}


def _safe_eval(expr):
    def _eval(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_OPS:
            return _ALLOWED_OPS[type(node.op)](_eval(node.left), _eval(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_OPS:
            return _ALLOWED_OPS[type(node.op)](_eval(node.operand))
        raise ValueError("تعبير غير مسموح")

    tree = ast.parse(expr, mode="eval")
    return _eval(tree.body)


def main_menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔑 مولّد كلمة سر", callback_data="tl_pass"),
         InlineKeyboardButton("🧮 حاسبة", callback_data="tl_calc")],
        [InlineKeyboardButton("💱 تحويل عملات", callback_data="tl_curr"),
         InlineKeyboardButton("🔗 اختصار رابط", callback_data="tl_short")],
        [InlineKeyboardButton("📱 QR كود", callback_data="tl_qr"),
         InlineKeyboardButton("🕐 الوقت بالمناطق", callback_data="tl_time")],
    ])


def back_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 القائمة", callback_data="tl_menu")]])


async def child_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    owner_id = context.bot_data["owner_id"]
    uid = update.effective_user.id
    rec = core._bot_record(owner_id)

    text = "🔧 <b>أهلاً ببوت الأدوات!</b>\nاختار أداة تحت 👇"
    if uid != owner_id:
        core._track_user(rec, uid, update.effective_user.full_name, owner_id, inc=False)
        text += core.promo_line()

    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=main_menu_kb())


async def tools_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    owner_id = context.bot_data["owner_id"]
    uid = q.from_user.id
    data = q.data or ""
    session_key = (owner_id, uid)

    if data == "tl_menu":
        TOOL_AWAITING.pop(session_key, None)
        await q.answer()
        await q.edit_message_text("🔧 <b>اختار أداة تحت 👇</b>", parse_mode=ParseMode.HTML, reply_markup=main_menu_kb())
        return

    if data == "tl_pass":
        await q.answer()
        alphabet = string.ascii_letters + string.digits + "!@#$%^&*_-+="
        pwd = "".join(secrets.choice(alphabet) for _ in range(14))
        await q.edit_message_text(f"🔑 كلمة السر الجديدة:\n<code>{pwd}</code>", parse_mode=ParseMode.HTML, reply_markup=back_kb())
        return

    if data == "tl_calc":
        TOOL_AWAITING[session_key] = "calc"
        await q.answer()
        await q.edit_message_text("🧮 ابعتلي تعبير حسابي، مثلاً:\n<code>2+2*3</code>", parse_mode=ParseMode.HTML, reply_markup=back_kb())
        return

    if data == "tl_curr":
        TOOL_AWAITING[session_key] = "curr"
        await q.answer()
        await q.edit_message_text(
            "💱 ابعتلي بالشكل: <code>المبلغ من إلى</code>\nمثلاً: <code>100 USD EUR</code>\n\n"
            f"العملات المتاحة: {', '.join(CURRENCY_RATES.keys())}\n"
            "⚠️ الأسعار تقريبية وثابتة للتوضيح فقط.",
            parse_mode=ParseMode.HTML, reply_markup=back_kb(),
        )
        return

    if data == "tl_short":
        TOOL_AWAITING[session_key] = "short"
        await q.answer()
        await q.edit_message_text("🔗 ابعتلي الرابط الكامل (لازم يبدأ بـ http:// أو https://)", reply_markup=back_kb())
        return

    if data == "tl_qr":
        TOOL_AWAITING[session_key] = "qr"
        await q.answer()
        await q.edit_message_text("📱 ابعتلي أي نص أو رابط بدك تحوّله لـ QR كود", reply_markup=back_kb())
        return

    if data == "tl_time":
        await q.answer()
        now_utc = datetime.now(ZoneInfo("UTC"))
        lines = ["🕐 <b>الوقت الحالي بالمناطق:</b>", "━━━━━━━━━━━━━━━"]
        for label, tz in TIMEZONES:
            local = now_utc.astimezone(ZoneInfo(tz))
            lines.append(f"{label}: <b>{local.strftime('%H:%M')}</b>")
        await q.edit_message_text("\n".join(lines), parse_mode=ParseMode.HTML, reply_markup=back_kb())
        return


def _shorten_blocking(url):
    api = "https://tinyurl.com/api-create.php?url=" + urllib.parse.quote(url, safe="")
    with urllib.request.urlopen(api, timeout=6) as resp:
        return resp.read().decode("utf-8").strip()


async def text_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if msg is None or not msg.text:
        return
    owner_id = context.bot_data["owner_id"]
    uid = msg.from_user.id
    session_key = (owner_id, uid)
    pending = TOOL_AWAITING.get(session_key)
    if not pending:
        return

    text = msg.text.strip()

    if pending == "calc":
        TOOL_AWAITING.pop(session_key, None)
        try:
            result = _safe_eval(text)
            await msg.reply_text(f"🧮 الناتج: <b>{result}</b>", parse_mode=ParseMode.HTML, reply_markup=back_kb())
        except Exception:
            await msg.reply_text("❌ تعبير غير صحيح. جرب مثلاً: 2+2*3", reply_markup=back_kb())
        return

    if pending == "curr":
        TOOL_AWAITING.pop(session_key, None)
        m = re.match(r"^\s*([\d.]+)\s+([A-Za-z]{3})\s+([A-Za-z]{3})\s*$", text)
        if not m:
            await msg.reply_text("❌ الصيغة غلط. مثال: 100 USD EUR", reply_markup=back_kb())
            return
        amount, frm, to = float(m.group(1)), m.group(2).upper(), m.group(3).upper()
        if frm not in CURRENCY_RATES or to not in CURRENCY_RATES:
            await msg.reply_text(f"❌ عملة غير مدعومة. المتاح: {', '.join(CURRENCY_RATES.keys())}", reply_markup=back_kb())
            return
        usd = amount / CURRENCY_RATES[frm]
        result = usd * CURRENCY_RATES[to]
        await msg.reply_text(
            f"💱 {amount:g} {frm} = <b>{result:.2f}</b> {to}\n⚠️ سعر تقريبي وثابت.",
            parse_mode=ParseMode.HTML, reply_markup=back_kb(),
        )
        return

    if pending == "short":
        TOOL_AWAITING.pop(session_key, None)
        if not (text.startswith("http://") or text.startswith("https://")):
            await msg.reply_text("❌ لازم يبدأ الرابط بـ http:// أو https://", reply_markup=back_kb())
            return
        status = await msg.reply_text("⏳ عم اختصر الرابط...")
        try:
            loop = asyncio.get_running_loop()
            short = await loop.run_in_executor(None, _shorten_blocking, text)
            await status.edit_text(f"🔗 الرابط المختصر:\n{short}", reply_markup=back_kb())
        except Exception:
            await status.edit_text("❌ تعذر اختصار الرابط حالياً، جرب لاحقاً.", reply_markup=back_kb())
        return

    if pending == "qr":
        TOOL_AWAITING.pop(session_key, None)
        qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={urllib.parse.quote(text)}"
        try:
            await context.bot.send_photo(chat_id=msg.chat_id, photo=qr_url, caption="📱 QR كودك جاهز", reply_markup=back_kb())
        except Exception:
            await msg.reply_text("❌ تعذر توليد الـ QR حالياً، جرب لاحقاً.", reply_markup=back_kb())
        return


def register(app, owner_id, token):
    app.add_handler(CommandHandler("start", child_start))
    app.add_handler(CallbackQueryHandler(tools_cb, pattern="^tl_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_input_handler))
