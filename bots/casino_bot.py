# -*- coding: utf-8 -*-
"""🎲 بوت كازينو — نقاط وهمية للتسلية فقط. لا فلوس حقيقية، لا إيداع، لا سحب."""

import random
from datetime import datetime, timezone

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

import bot as core

DISCLAIMER = "🎲 نقاط وهمية للتسلية فقط — بلا أي قيمة نقدية حقيقية، ما في إيداع ولا سحب ولا فلوس حقيقية."
START_BALANCE = 1000
DAILY_BONUS = 200
BET_TIERS = [20, 50, 100, 200]
SLOT_SYMS = ["🍒", "🍋", "🍇", "⭐", "7️⃣"]
BJ_RANKS = [
    ("2", 2), ("3", 3), ("4", 4), ("5", 5), ("6", 6), ("7", 7), ("8", 8),
    ("9", 9), ("10", 10), ("J", 10), ("Q", 10), ("K", 10), ("A", 11),
]

# (owner_id, uid) -> {"player": [...], "dealer": [...], "bet": int}
BJ_STATE = {}


def _casino(rec):
    c = rec.setdefault("casino", {})
    c.setdefault("balances", {})
    c.setdefault("last_daily", {})
    return c


def _get_balance(rec, uid):
    c = _casino(rec)
    key = str(uid)
    if key not in c["balances"]:
        c["balances"][key] = START_BALANCE
    return c["balances"][key]


def _add_balance(rec, owner_id, uid, delta):
    c = _casino(rec)
    key = str(uid)
    c["balances"][key] = max(0, c["balances"].get(key, START_BALANCE) + delta)
    core.persist(owner_id)
    return c["balances"][key]


def main_menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎰 سلوتس", callback_data="cs_bet_menu:slots"),
         InlineKeyboardButton("🎡 عجلة الحظ", callback_data="cs_bet_menu:wheel")],
        [InlineKeyboardButton("🎲 نرد", callback_data="cs_dice_menu"),
         InlineKeyboardButton("🃏 بلاك جاك", callback_data="cs_bj_start")],
        [InlineKeyboardButton("🎁 مكافأة يومية", callback_data="cs_daily"),
         InlineKeyboardButton("🏆 المتصدرين", callback_data="cs_leaderboard")],
        [InlineKeyboardButton("💰 رصيدي", callback_data="cs_balance")],
    ])


def back_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="cs_menu")]])


async def child_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    owner_id = context.bot_data["owner_id"]
    uid = update.effective_user.id
    rec = core._bot_record(owner_id)
    bal = _get_balance(rec, uid)
    core.persist(owner_id)

    text = f"🎰 <b>أهلاً ببوت الكازينو!</b>\n💰 رصيدك: <b>{bal}</b> نقطة\n\n{DISCLAIMER}"
    if uid != owner_id:
        core._track_user(rec, uid, update.effective_user.full_name, owner_id, inc=False)
        text += core.promo_line()

    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=main_menu_kb())


async def child_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    owner_id = context.bot_data["owner_id"]
    rec = core._bot_record(owner_id)
    bal = _get_balance(rec, update.effective_user.id)
    core.persist(owner_id)
    await update.message.reply_text(
        f"🎰 <b>اختار لعبة تحت 👇</b>\n💰 رصيدك: {bal}", parse_mode=ParseMode.HTML, reply_markup=main_menu_kb()
    )


def _bet_kb(game):
    row = [InlineKeyboardButton(str(b), callback_data=f"cs_bet:{game}:{b}") for b in BET_TIERS]
    return InlineKeyboardMarkup([row, [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="cs_menu")]])


def _dice_bet_kb():
    rows = []
    for b in BET_TIERS:
        rows.append([
            InlineKeyboardButton(f"فردي ({b})", callback_data=f"cs_dice:{b}:odd"),
            InlineKeyboardButton(f"زوجي ({b})", callback_data=f"cs_dice:{b}:even"),
        ])
    rows.append([InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="cs_menu")])
    return InlineKeyboardMarkup(rows)


def _leaderboard_text(rec):
    balances = rec.get("casino", {}).get("balances", {})
    if not balances:
        return "🏆 ما في رصيد مسجّل بعد."
    items = sorted(balances.items(), key=lambda x: x[1], reverse=True)[:10]
    lines = ["🏆 <b>متصدرين الكازينو</b>", "━━━━━━━━━━━━━━━"]
    for i, (uid, bal) in enumerate(items, 1):
        lines.append(f"{i}. <code>{uid}</code> — {bal} نقطة")
    lines.append(f"\n{DISCLAIMER}")
    return "\n".join(lines)


def _hand_value(cards):
    total = sum(v for _, v in cards)
    aces = sum(1 for r, v in cards if r == "A")
    while total > 21 and aces:
        total -= 10
        aces -= 1
    return total


def _hand_str(cards):
    return " ".join(r for r, _ in cards)


async def _bj_deal(q, rec, owner_id, uid):
    bet = BET_TIERS[0]
    bal = _get_balance(rec, uid)
    if bal < bet:
        await q.edit_message_text(f"❌ رصيدك مش كافي (أقل رهان {bet}).\n💰 رصيدك: {bal}", reply_markup=back_kb())
        return
    _add_balance(rec, owner_id, uid, -bet)
    player = [random.choice(BJ_RANKS), random.choice(BJ_RANKS)]
    dealer = [random.choice(BJ_RANKS), random.choice(BJ_RANKS)]
    BJ_STATE[(owner_id, uid)] = {"player": player, "dealer": dealer, "bet": bet}

    if _hand_value(player) == 21:
        await _bj_finish(q, rec, owner_id, uid, natural=True)
        return

    await q.edit_message_text(
        f"🃏 <b>بلاك جاك</b> (رهان {bet})\n"
        f"يدّك: {_hand_str(player)} ({_hand_value(player)})\n"
        f"يد الديلر: {dealer[0][0]} ❓\n\n{DISCLAIMER}",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🃏 اسحب", callback_data="cs_bj_hit"),
            InlineKeyboardButton("✋ قف", callback_data="cs_bj_stand"),
        ]]),
    )


async def _bj_finish(q, rec, owner_id, uid, natural=False, stood=False):
    state = BJ_STATE.pop((owner_id, uid), None)
    if not state:
        return
    player, dealer, bet = state["player"], state["dealer"], state["bet"]
    pval = _hand_value(player)

    if pval > 21:
        outcome = f"💥 فرقعت (Bust)! خسرت {bet} نقطة."
        payout = 0
    elif natural:
        payout = int(bet * 2.5)
        outcome = f"🂡 بلاك جاك طبيعي! ربحت {payout - bet} نقطة صافي."
    else:
        while _hand_value(dealer) < 17:
            dealer.append(random.choice(BJ_RANKS))
        dval = _hand_value(dealer)
        if dval > 21 or pval > dval:
            payout = bet * 2
            outcome = f"🎉 ربحت! (+{payout - bet} نقطة صافي)"
        elif dval == pval:
            payout = bet
            outcome = "🤝 تعادل، رجع رهانك."
        else:
            payout = 0
            outcome = f"😢 خسرت {bet} نقطة."

    total = _add_balance(rec, owner_id, uid, payout)
    await q.edit_message_text(
        f"يدّك: {_hand_str(player)} ({pval})\nيد الديلر: {_hand_str(dealer)} ({_hand_value(dealer)})\n\n"
        f"{outcome}\n💰 رصيدك: {total}\n\n{DISCLAIMER}",
        reply_markup=back_kb(),
    )


async def casino_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    owner_id = context.bot_data["owner_id"]
    uid = q.from_user.id
    rec = core._bot_record(owner_id)
    data = q.data or ""

    if data == "cs_menu":
        BJ_STATE.pop((owner_id, uid), None)
        await q.answer()
        bal = _get_balance(rec, uid)
        core.persist(owner_id)
        await q.edit_message_text(
            f"🎰 <b>اختار لعبة تحت 👇</b>\n💰 رصيدك: {bal}", parse_mode=ParseMode.HTML, reply_markup=main_menu_kb()
        )
        return

    if data == "cs_balance":
        await q.answer()
        bal = _get_balance(rec, uid)
        core.persist(owner_id)
        await q.edit_message_text(f"💰 رصيدك: <b>{bal}</b> نقطة\n\n{DISCLAIMER}", parse_mode=ParseMode.HTML, reply_markup=back_kb())
        return

    if data == "cs_leaderboard":
        await q.answer()
        await q.edit_message_text(_leaderboard_text(rec), parse_mode=ParseMode.HTML, reply_markup=back_kb())
        return

    if data == "cs_daily":
        c = _casino(rec)
        last = c["last_daily"].get(str(uid))
        now = datetime.now(timezone.utc)
        if last:
            elapsed = now - datetime.fromisoformat(last)
            if elapsed.total_seconds() < 86400:
                remaining = int((86400 - elapsed.total_seconds()) / 3600) + 1
                await q.answer(f"⏳ رجّعلك بعد {remaining} ساعة تقريباً", show_alert=True)
                return
        c["last_daily"][str(uid)] = now.isoformat()
        total = _add_balance(rec, owner_id, uid, DAILY_BONUS)
        await q.answer(f"🎁 خدت {DAILY_BONUS} نقطة!")
        await q.edit_message_text(f"🎁 مبروك! خدت {DAILY_BONUS} نقطة.\n💰 رصيدك: {total}", reply_markup=back_kb())
        return

    if data.startswith("cs_bet_menu:"):
        game = data.split(":", 1)[1]
        await q.answer()
        label = "🎰 سلوتس" if game == "slots" else "🎡 عجلة الحظ"
        await q.edit_message_text(f"{label} — اختار مبلغ الرهان:", reply_markup=_bet_kb(game))
        return

    if data == "cs_dice_menu":
        await q.answer()
        await q.edit_message_text("🎲 اختار توقعك ومبلغ الرهان:", reply_markup=_dice_bet_kb())
        return

    if data.startswith("cs_bet:"):
        _, game, bet_s = data.split(":")
        bet = int(bet_s)
        bal = _get_balance(rec, uid)
        if bal < bet:
            await q.answer("❌ رصيدك مش كافي", show_alert=True)
            return
        await q.answer()
        if game == "slots":
            await _play_slots(q, rec, owner_id, uid, bet)
        else:
            await _play_wheel(q, rec, owner_id, uid, bet)
        return

    if data.startswith("cs_dice:"):
        _, bet_s, guess = data.split(":")
        bet = int(bet_s)
        bal = _get_balance(rec, uid)
        if bal < bet:
            await q.answer("❌ رصيدك مش كافي", show_alert=True)
            return
        await q.answer()
        await _play_dice(q, rec, owner_id, uid, bet, guess)
        return

    if data == "cs_bj_start":
        await q.answer()
        await _bj_deal(q, rec, owner_id, uid)
        return

    if data == "cs_bj_hit":
        state = BJ_STATE.get((owner_id, uid))
        if not state:
            await q.answer("ابدأ لعبة جديدة", show_alert=True)
            return
        await q.answer()
        state["player"].append(random.choice(BJ_RANKS))
        if _hand_value(state["player"]) > 21:
            await _bj_finish(q, rec, owner_id, uid)
        else:
            await q.edit_message_text(
                f"🃏 يدّك: {_hand_str(state['player'])} ({_hand_value(state['player'])})\n"
                f"يد الديلر: {state['dealer'][0][0]} ❓",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🃏 اسحب", callback_data="cs_bj_hit"),
                    InlineKeyboardButton("✋ قف", callback_data="cs_bj_stand"),
                ]]),
            )
        return

    if data == "cs_bj_stand":
        if (owner_id, uid) not in BJ_STATE:
            await q.answer("ابدأ لعبة جديدة", show_alert=True)
            return
        await q.answer()
        await _bj_finish(q, rec, owner_id, uid, stood=True)
        return


async def _play_slots(q, rec, owner_id, uid, bet):
    _add_balance(rec, owner_id, uid, -bet)
    spin = [random.choice(SLOT_SYMS) for _ in range(3)]
    if spin[0] == spin[1] == spin[2]:
        mult = {"7️⃣": 10, "⭐": 5}.get(spin[0], 3)
        payout = bet * mult
        outcome = f"🎉 ثلاثة متطابقين! ربحت {payout - bet} نقطة صافي."
    elif len(set(spin)) == 2:
        payout = int(bet * 1.5)
        outcome = f"🙂 تطابق جزئي! ربحت {payout - bet} نقطة صافي."
    else:
        payout = 0
        outcome = f"😢 خسرت {bet} نقطة."
    total = _add_balance(rec, owner_id, uid, payout)
    await q.edit_message_text(
        f"🎰 {' '.join(spin)}\n\n{outcome}\n💰 رصيدك: {total}\n\n{DISCLAIMER}",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔁 كمان", callback_data="cs_bet_menu:slots")],
            [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="cs_menu")],
        ]),
    )


WHEEL_PRIZES = [0, 0.5, 1, 1.5, 2, 3]
WHEEL_WEIGHTS = [20, 25, 25, 15, 10, 5]


async def _play_wheel(q, rec, owner_id, uid, bet):
    _add_balance(rec, owner_id, uid, -bet)
    mult = random.choices(WHEEL_PRIZES, weights=WHEEL_WEIGHTS, k=1)[0]
    payout = int(bet * mult)
    net = payout - bet
    outcome = f"🎉 ربحت {net} نقطة صافي!" if net > 0 else (f"🤝 رجع رهانك." if net == 0 else f"😢 خسرت {bet - payout} نقطة.")
    total = _add_balance(rec, owner_id, uid, payout)
    await q.edit_message_text(
        f"🎡 العجلة وقفت على x{mult}\n\n{outcome}\n💰 رصيدك: {total}\n\n{DISCLAIMER}",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔁 كمان", callback_data="cs_bet_menu:wheel")],
            [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="cs_menu")],
        ]),
    )


async def _play_dice(q, rec, owner_id, uid, bet, guess):
    _add_balance(rec, owner_id, uid, -bet)
    roll = random.randint(1, 6)
    is_even = roll % 2 == 0
    won = (guess == "even" and is_even) or (guess == "odd" and not is_even)
    payout = int(bet * 1.8) if won else 0
    outcome = f"🎉 ربحت {payout - bet} نقطة صافي!" if won else f"😢 خسرت {bet} نقطة."
    total = _add_balance(rec, owner_id, uid, payout)
    await q.edit_message_text(
        f"🎲 النرد طلع: {roll} ({'زوجي' if is_even else 'فردي'})\n\n{outcome}\n💰 رصيدك: {total}\n\n{DISCLAIMER}",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔁 كمان", callback_data="cs_dice_menu")],
            [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="cs_menu")],
        ]),
    )


def register(app, owner_id, token):
    app.add_handler(CommandHandler("start", child_start))
    app.add_handler(CommandHandler("menu", child_menu))
    app.add_handler(CallbackQueryHandler(casino_cb, pattern="^cs_"))
