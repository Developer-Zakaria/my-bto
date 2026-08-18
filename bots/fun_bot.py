# -*- coding: utf-8 -*-
"""🎉 بوت ترفيه — نكت، اقتباسات، حقائق، صراحة، اختبار شخصية. كل المحتوى ثابت بالكود."""

import random

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

JOKES = [
    "ليش الكمبيوتر راح عند الدكتور؟ لأنو كان عندو فايروس! 🤒",
    "واحد سأل صاحبو: ليش تلبس نظارتين؟ قالو: عشان أشوف الصورة مزدوجة الوضوح 😂",
    "شو الفرق بين المعلم والمبرمج؟ المعلم يقول 'افهم غلطك'، المبرمج يقول 'خلص شغال بس ما فاهم ليش' 💻",
    "ليش السمكة ما بتحب تلعب تنس؟ خايفة تعلق بالشبكة 🎾🐟",
    "واحد قال لصاحبو: بدي أصير غني بليلة. قالو: اطفي النور وروح نام 😴",
]

QUOTES = [
    "«النجاح رحلة مو محطة» — استمر ولا توقف.",
    "«الصبر مفتاح الفرج» — كل شي بوقته حلو.",
    "«اعمل اليوم اللي غيرك ما بيعمله، تعيش بكرا اللي غيرك ما بيعيشه».",
    "«العقل السليم بالجسم السليم».",
    "«من جد وجد، ومن زرع حصد».",
]

FACTS = [
    "🐙 الأخطبوط عندو ثلاثة قلوب!",
    "🍯 العسل ما بيفسد أبداً — لقوا عسل بالمقابر الفرعونية لسا صالح للأكل!",
    "🌕 القمر بيبعد عن الأرض حوالي 3.8 سم كل سنة.",
    "🦒 الزرافة نومها أقل من ساعتين باليوم!",
    "❄️ ما في ثلجتين متطابقتين تماماً بالشكل.",
]

CANDID_QUESTIONS = [
    "🤫 صراحة، شو أكتر شي بتندم عليه؟",
    "🤫 صراحة، مين أكتر شخص أثر فيك بحياتك؟",
    "🤫 صراحة، لو رجع الزمن شو كنت رح تغيّر؟",
    "🤫 صراحة، شو أكبر حلم عندك؟",
    "🤫 صراحة، شو أكتر شي بيخوّفك؟",
]

QUIZ_QUESTIONS = [
    {
        "q": "🧠 بعطلة الأسبوع تفضل...",
        "opts": [("تجربة شي جديد ومغامرة", "A"), ("قعدة هادية بالبيت", "B"), ("طلعة مع صحاب", "C")],
    },
    {
        "q": "🧠 لما تواجه مشكلة...",
        "opts": [("بتواجهها فوراً بلا تردد", "A"), ("بتفكر منيح لحالك", "B"), ("بتستشير الأصدقاء", "C")],
    },
    {
        "q": "🧠 أكتر شي بيميزك...",
        "opts": [("الجرأة", "A"), ("الهدوء", "B"), ("العفوية بالتعامل", "C")],
    },
]

QUIZ_RESULTS = {
    "A": "🔥 أنت شخصية مغامرة! بتحب التحديات وما بتخاف تجرب شي جديد.",
    "B": "🌙 أنت شخصية هادئة وعميقة، بتحب التفكير قبل ما تتصرف.",
    "C": "🌟 أنت شخصية اجتماعية بامتياز، الناس بتحبك لأنك عفوي وسهل.",
}

# (owner_id, uid) -> {"idx": int, "scores": {"A":0,"B":0,"C":0}}
QUIZ_STATE = {}


def main_menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("😂 نكتة", callback_data="fun_joke"),
         InlineKeyboardButton("💬 اقتباس", callback_data="fun_quote")],
        [InlineKeyboardButton("💡 حقيقة", callback_data="fun_fact"),
         InlineKeyboardButton("🤫 صراحة", callback_data="fun_candid")],
        [InlineKeyboardButton("🧠 اختبار شخصية", callback_data="fun_quiz_start")],
    ])


def back_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 القائمة", callback_data="fun_menu")]])


async def child_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    owner_id = context.bot_data["owner_id"]
    uid = update.effective_user.id
    rec = core._bot_record(owner_id)

    text = "🎉 <b>أهلاً بك ببوت الترفيه!</b>\nاختار شي تحت 👇"
    if uid != owner_id:
        core._track_user(rec, uid, update.effective_user.full_name, owner_id, inc=False)
        text += core.promo_line()

    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=main_menu_kb())


async def _show_menu(q):
    await q.edit_message_text(
        "🎉 <b>اختار شي تحت 👇</b>", parse_mode=ParseMode.HTML, reply_markup=main_menu_kb()
    )


async def fun_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    owner_id = context.bot_data["owner_id"]
    uid = q.from_user.id
    data = q.data or ""

    if data == "fun_menu":
        QUIZ_STATE.pop((owner_id, uid), None)
        await q.answer()
        await _show_menu(q)
        return

    if data == "fun_joke":
        await q.answer()
        await q.edit_message_text(random.choice(JOKES), reply_markup=back_kb())
        return

    if data == "fun_quote":
        await q.answer()
        await q.edit_message_text(random.choice(QUOTES), reply_markup=back_kb())
        return

    if data == "fun_fact":
        await q.answer()
        await q.edit_message_text(random.choice(FACTS), reply_markup=back_kb())
        return

    if data == "fun_candid":
        await q.answer()
        await q.edit_message_text(random.choice(CANDID_QUESTIONS), reply_markup=back_kb())
        return

    if data == "fun_quiz_start":
        QUIZ_STATE[(owner_id, uid)] = {"idx": 0, "scores": {"A": 0, "B": 0, "C": 0}}
        await q.answer()
        await _send_quiz_question(q, 0)
        return

    if data.startswith("fun_qz:"):
        parts = data.split(":")
        if len(parts) != 3:
            await q.answer()
            return
        _, idx_s, trait = parts
        idx = int(idx_s)
        state = QUIZ_STATE.get((owner_id, uid))
        if not state or state["idx"] != idx:
            await q.answer("ابدأ الاختبار من جديد", show_alert=True)
            return
        state["scores"][trait] = state["scores"].get(trait, 0) + 1
        state["idx"] += 1
        await q.answer()
        if state["idx"] >= len(QUIZ_QUESTIONS):
            best = max(state["scores"], key=lambda k: state["scores"][k])
            QUIZ_STATE.pop((owner_id, uid), None)
            await q.edit_message_text(
                f"✅ <b>نتيجتك:</b>\n\n{QUIZ_RESULTS[best]}",
                parse_mode=ParseMode.HTML, reply_markup=back_kb(),
            )
        else:
            await _send_quiz_question(q, state["idx"])
        return


async def _send_quiz_question(q, idx):
    item = QUIZ_QUESTIONS[idx]
    rows = [[InlineKeyboardButton(label, callback_data=f"fun_qz:{idx}:{trait}")] for label, trait in item["opts"]]
    await q.edit_message_text(item["q"], reply_markup=InlineKeyboardMarkup(rows))


async def fallback_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message is None:
        return
    await update.message.reply_text("🎉 اختار شي من القائمة 👇", reply_markup=main_menu_kb())


def register(app, owner_id, token):
    app.add_handler(CommandHandler("start", child_start))
    app.add_handler(CallbackQueryHandler(fun_cb, pattern="^fun_"))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, fallback_message))
