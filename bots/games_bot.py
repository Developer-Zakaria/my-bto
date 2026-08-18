# -*- coding: utf-8 -*-
"""🎮 بوت ألعاب — تخمين رقم، حجر/ورقة/مقص، أسئلة وأجوبة، XO. نقاط ولوحة متصدرين."""

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

TRIVIA = [
    {"q": "❓ شو عاصمة الأردن؟", "opts": ["عمّان", "إربد", "الزرقاء"], "correct": 0},
    {"q": "❓ كم عدد أيام السنة الكبيسة؟", "opts": ["365", "366", "364"], "correct": 1},
    {"q": "❓ شو أكبر محيط بالعالم؟", "opts": ["الأطلسي", "الهندي", "الهادئ"], "correct": 2},
    {"q": "❓ كم عدد قارات العالم؟", "opts": ["5", "6", "7"], "correct": 2},
    {"q": "❓ شو أسرع حيوان بري؟", "opts": ["الفهد", "الأسد", "النمر"], "correct": 0},
]

RPS_CHOICES = {"rock": "🗿 حجر", "paper": "📄 ورقة", "scissors": "✂️ مقص"}
RPS_BEATS = {"rock": "scissors", "paper": "rock", "scissors": "paper"}

# (owner_id, uid) -> حالة اللعبة الجارية
SESSIONS = {}


def main_menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔢 تخمين رقم", callback_data="gm_guess_start"),
         InlineKeyboardButton("✊ حجر/ورقة/مقص", callback_data="gm_rps_start")],
        [InlineKeyboardButton("❓ سؤال وجواب", callback_data="gm_trivia_start"),
         InlineKeyboardButton("⭕ XO", callback_data="gm_xo_start")],
        [InlineKeyboardButton("🏆 المتصدرين", callback_data="gm_leaderboard")],
    ])


def back_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 القائمة", callback_data="gm_menu")]])


def _award(rec, owner_id, uid, pts):
    scores = rec.setdefault("scores", {})
    key = str(uid)
    scores[key] = scores.get(key, 0) + pts
    core.persist(owner_id)
    return scores[key]


async def child_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    owner_id = context.bot_data["owner_id"]
    uid = update.effective_user.id
    rec = core._bot_record(owner_id)

    text = "🎮 <b>أهلاً ببوت الألعاب!</b>\nاختار لعبة تحت 👇"
    if uid != owner_id:
        core._track_user(rec, uid, update.effective_user.full_name, owner_id, inc=False)
        text += core.promo_line()

    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=main_menu_kb())


# ---------------------------- تخمين رقم ----------------------------
async def _start_guess(q, owner_id, uid):
    SESSIONS[(owner_id, uid)] = {"game": "guess", "target": random.randint(1, 100), "attempts": 0}
    await q.edit_message_text(
        "🔢 خمّنت رقم بين 1 و100. ابعتلي رقمك كنص 👇",
        reply_markup=back_kb(),
    )


async def _handle_guess_text(update, context, rec, owner_id, uid, session, text):
    if not text.lstrip("-").isdigit():
        await update.message.reply_text("رجاءً ابعت رقم صحيح.")
        return
    guess = int(text)
    session["attempts"] += 1
    target = session["target"]
    if guess == target:
        pts = max(50 - session["attempts"] * 5, 5)
        total = _award(rec, owner_id, uid, pts)
        SESSIONS.pop((owner_id, uid), None)
        await update.message.reply_text(
            f"🎉 صح! الرقم كان {target}. كسبت {pts} نقطة (مجموعك: {total}).",
            reply_markup=back_kb(),
        )
    elif guess < target:
        await update.message.reply_text("⬆️ أكبر من هيك!")
    else:
        await update.message.reply_text("⬇️ أصغر من هيك!")


# ---------------------------- حجر ورقة مقص ----------------------------
def _rps_kb():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🗿", callback_data="gm_rps:rock"),
        InlineKeyboardButton("📄", callback_data="gm_rps:paper"),
        InlineKeyboardButton("✂️", callback_data="gm_rps:scissors"),
    ]])


async def _play_rps(q, rec, owner_id, uid, choice):
    bot_choice = random.choice(list(RPS_CHOICES.keys()))
    if choice == bot_choice:
        result, pts = "🤝 تعادل!", 3
    elif RPS_BEATS[choice] == bot_choice:
        result, pts = "🎉 ربحت!", 10
    else:
        result, pts = "😢 خسرت!", 0
    total = _award(rec, owner_id, uid, pts) if pts else rec.get("scores", {}).get(str(uid), 0)
    await q.edit_message_text(
        f"أنت: {RPS_CHOICES[choice]}\nالبوت: {RPS_CHOICES[bot_choice]}\n\n{result} (+{pts} نقطة، مجموعك: {total})",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔁 كمان", callback_data="gm_rps_start")],
            [InlineKeyboardButton("🔙 القائمة", callback_data="gm_menu")],
        ]),
    )


# ---------------------------- أسئلة وأجوبة ----------------------------
async def _send_trivia(q):
    item = random.choice(TRIVIA)
    idx = TRIVIA.index(item)
    rows = [[InlineKeyboardButton(opt, callback_data=f"gm_tr:{idx}:{i}")] for i, opt in enumerate(item["opts"])]
    await q.edit_message_text(item["q"], reply_markup=InlineKeyboardMarkup(rows))


# ---------------------------- XO ----------------------------
def _xo_winner(board):
    lines = [(0, 1, 2), (3, 4, 5), (6, 7, 8), (0, 3, 6), (1, 4, 7), (2, 5, 8), (0, 4, 8), (2, 4, 6)]
    for a, b, c in lines:
        if board[a] != " " and board[a] == board[b] == board[c]:
            return board[a]
    return None


def _xo_bot_move(board):
    for mark, other in (("O", "X"), ("X", "O")):
        for i in range(9):
            if board[i] == " ":
                board[i] = mark
                win = _xo_winner(board) == mark
                board[i] = " "
                if win:
                    return i
    if board[4] == " ":
        return 4
    corners = [0, 2, 6, 8]
    random.shuffle(corners)
    for c in corners:
        if board[c] == " ":
            return c
    empties = [i for i in range(9) if board[i] == " "]
    return random.choice(empties) if empties else None


def _xo_kb(board):
    rows = []
    for r in range(3):
        row = []
        for c in range(3):
            i = r * 3 + c
            label = board[i] if board[i] != " " else "▫️"
            row.append(InlineKeyboardButton(label, callback_data=f"gm_xo:{i}"))
        rows.append(row)
    rows.append([InlineKeyboardButton("🔙 القائمة", callback_data="gm_menu")])
    return InlineKeyboardMarkup(rows)


async def _start_xo(q, owner_id, uid):
    SESSIONS[(owner_id, uid)] = {"game": "xo", "board": [" "] * 9}
    await q.edit_message_text("⭕ أنت X، البوت O. دورك!", reply_markup=_xo_kb([" "] * 9))


async def _play_xo(q, rec, owner_id, uid, session, pos):
    board = session["board"]
    if board[pos] != " ":
        await q.answer("مكان مشغول", show_alert=True)
        return
    board[pos] = "X"
    winner = _xo_winner(board)
    if winner == "X":
        total = _award(rec, owner_id, uid, 15)
        SESSIONS.pop((owner_id, uid), None)
        await q.edit_message_text(f"🎉 ربحت! (+15 نقطة، مجموعك: {total})", reply_markup=_xo_kb(board))
        return
    if " " not in board:
        total = _award(rec, owner_id, uid, 5)
        SESSIONS.pop((owner_id, uid), None)
        await q.edit_message_text(f"🤝 تعادل! (+5 نقطة، مجموعك: {total})", reply_markup=_xo_kb(board))
        return

    bot_pos = _xo_bot_move(board)
    if bot_pos is not None:
        board[bot_pos] = "O"
    winner = _xo_winner(board)
    if winner == "O":
        SESSIONS.pop((owner_id, uid), None)
        await q.edit_message_text("😢 خسرت! البوت فاز.", reply_markup=_xo_kb(board))
        return
    if " " not in board:
        total = _award(rec, owner_id, uid, 5)
        SESSIONS.pop((owner_id, uid), None)
        await q.edit_message_text(f"🤝 تعادل! (+5 نقطة، مجموعك: {total})", reply_markup=_xo_kb(board))
        return

    await q.edit_message_text("⭕ دورك!", reply_markup=_xo_kb(board))


# ---------------------------- المتصدرين ----------------------------
def _leaderboard_text(rec):
    scores = rec.get("scores", {})
    if not scores:
        return "🏆 ما في نقاط بعد، العب أول لعبة!"
    items = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:10]
    lines = ["🏆 <b>المتصدرين</b>", "━━━━━━━━━━━━━━━"]
    for i, (uid, pts) in enumerate(items, 1):
        lines.append(f"{i}. <code>{uid}</code> — {pts} نقطة")
    return "\n".join(lines)


async def games_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    owner_id = context.bot_data["owner_id"]
    uid = q.from_user.id
    rec = core._bot_record(owner_id)
    data = q.data or ""
    session_key = (owner_id, uid)

    if data == "gm_menu":
        SESSIONS.pop(session_key, None)
        await q.answer()
        await q.edit_message_text("🎮 <b>اختار لعبة تحت 👇</b>", parse_mode=ParseMode.HTML, reply_markup=main_menu_kb())
        return

    if data == "gm_guess_start":
        await q.answer()
        await _start_guess(q, owner_id, uid)
        return

    if data == "gm_rps_start":
        await q.answer()
        await q.edit_message_text("✊ اختار سلاحك:", reply_markup=_rps_kb())
        return

    if data.startswith("gm_rps:"):
        choice = data.split(":", 1)[1]
        await q.answer()
        await _play_rps(q, rec, owner_id, uid, choice)
        return

    if data == "gm_trivia_start":
        await q.answer()
        await _send_trivia(q)
        return

    if data.startswith("gm_tr:"):
        _, idx_s, opt_s = data.split(":")
        idx, opt = int(idx_s), int(opt_s)
        item = TRIVIA[idx]
        if opt == item["correct"]:
            total = _award(rec, owner_id, uid, 5)
            await q.answer("✅ صح! +5 نقطة")
            await q.edit_message_text(f"✅ إجابة صحيحة! مجموعك: {total}", reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❓ سؤال تاني", callback_data="gm_trivia_start")],
                [InlineKeyboardButton("🔙 القائمة", callback_data="gm_menu")],
            ]))
        else:
            correct_ans = item["opts"][item["correct"]]
            await q.answer("❌ غلط")
            await q.edit_message_text(f"❌ غلط! الجواب الصحيح: {correct_ans}", reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❓ سؤال تاني", callback_data="gm_trivia_start")],
                [InlineKeyboardButton("🔙 القائمة", callback_data="gm_menu")],
            ]))
        return

    if data == "gm_xo_start":
        await q.answer()
        await _start_xo(q, owner_id, uid)
        return

    if data.startswith("gm_xo:"):
        pos = int(data.split(":", 1)[1])
        session = SESSIONS.get(session_key)
        if not session or session.get("game") != "xo":
            await q.answer("ابدأ لعبة جديدة", show_alert=True)
            return
        await q.answer()
        await _play_xo(q, rec, owner_id, uid, session, pos)
        return

    if data == "gm_leaderboard":
        await q.answer()
        await q.edit_message_text(_leaderboard_text(rec), parse_mode=ParseMode.HTML, reply_markup=back_kb())
        return


async def text_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if msg is None or not msg.text:
        return
    owner_id = context.bot_data["owner_id"]
    uid = msg.from_user.id
    session = SESSIONS.get((owner_id, uid))
    if not session or session.get("game") != "guess":
        return
    rec = core._bot_record(owner_id)
    await _handle_guess_text(update, context, rec, owner_id, uid, session, msg.text.strip())


def register(app, owner_id, token):
    app.add_handler(CommandHandler("start", child_start))
    app.add_handler(CallbackQueryHandler(games_cb, pattern="^gm_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_input_handler))
