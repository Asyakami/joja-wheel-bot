# -*- coding: utf-8 -*-
from datetime import date

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from . import config, db, sheets
from .prizes import PRIZES, get_prize, valid_until

router = Router()


def is_staff(user_id: int) -> bool:
    # Пустой список STAFF_IDS = доступ открыт всем (удобно на этапе теста).
    # Как только заполните STAFF_IDS в .env — доступ ограничится этим списком.
    if not config.STAFF_IDS:
        return True
    return user_id in config.STAFF_IDS or user_id in config.ADMIN_IDS


def is_admin(user_id: int) -> bool:
    if not config.ADMIN_IDS:
        return True
    return user_id in config.ADMIN_IDS


def _default_location() -> str:
    return config.LOCATIONS[0] if config.LOCATIONS else "Кофейня"


def _display_name(user) -> str:
    name = user.full_name or ""
    if user.username:
        name = f"{name} (@{user.username})".strip()
    return name or str(user.id)


def _parse_date(value) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _fmt_date(d: date) -> str:
    return d.strftime("%d.%m")


def _term_text(prize: dict, until: date | None) -> str:
    """Срок действия приза человеческим языком — для сообщения бариста."""
    if until is None:
        return "без ограничения по дате, одноразовый"
    if prize.get("multi_use"):
        return f"до {_fmt_date(until)} включительно — можно использовать каждый день"
    if prize.get("valid_days") == 0:
        return f"только сегодня ({_fmt_date(until)}) — приз выдаётся сразу"
    return f"до {_fmt_date(until)} включительно"


def _days_left_text(until: date | None, today: date) -> str:
    if until is None:
        return "без срока"
    left = (until - today).days
    if left < 0:
        return f"просрочен с {_fmt_date(until)}"
    if left == 0:
        return f"до {_fmt_date(until)} (последний день)"
    return f"до {_fmt_date(until)} (осталось {left} дн.)"


@router.message(Command("start"))
async def cmd_start(message: Message):
    if not is_staff(message.from_user.id):
        await message.answer(
            "Этот бот только для сотрудников Joja Coffee. "
            "Если вы бариста/промоутер — попросите добавить ваш Telegram ID в настройки бота."
        )
        return
    await message.answer(
        "👋 Бот учёта призов колеса Joja Coffee.\n\n"
        "/spin — записать, какой приз выпал гостю на колесе\n"
        "/redeem КОД — погасить приз при выдаче/использовании\n"
        "/today — отчёт по призам за сегодня\n"
        "/unredeemed — список ещё не погашенных призов\n"
    )


@router.message(Command("spin"))
async def cmd_spin(message: Message):
    if not is_staff(message.from_user.id):
        return
    kb = InlineKeyboardBuilder()
    for p in PRIZES:
        kb.button(text=p["label"], callback_data=f"spin:{p['code']}")
    kb.adjust(1)
    await message.answer(
        "Выберите сектор, который выпал на колесе:", reply_markup=kb.as_markup()
    )


@router.callback_query(F.data.startswith("spin:"))
async def cb_spin_prize(callback: CallbackQuery):
    if not is_staff(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    prize_code = callback.data.split(":", 1)[1]
    prize = get_prize(prize_code)
    if not prize:
        await callback.answer("Приз не найден", show_alert=True)
        return

    location = _default_location()
    until = valid_until(prize, db.today_local())
    spin = db.create_spin(
        prize_code=prize_code,
        location=location,
        staff_tg_id=callback.from_user.id,
        staff_name=_display_name(callback.from_user),
        valid_until=until.isoformat() if until else None,
    )
    sheets.log_spin(spin, prize)

    if prize["kind"] == "none":
        text = (
            f"😉 Записано: «{prize['desc']}»\n"
            f"Код не выдаётся — гость ничего не выиграл на этот раз."
        )
    else:
        if prize.get("multi_use"):
            how = (
                "Сообщите этот код гостю. Каждый раз, когда гость пользуется призом, "
                "гасите код командой:"
            )
        else:
            how = (
                "Сообщите этот код гостю. Когда приз будет использован/выдан — "
                "погасите его командой:"
            )
        text = (
            f"✅ Записано!\n\n"
            f"<b>Приз:</b> {prize['desc']}\n"
            f"<b>Код для гостя:</b> <code>{spin['redeem_code']}</code>\n"
            f"<b>Срок:</b> {_term_text(prize, until)}\n\n"
            f"{how}\n<code>/redeem {spin['redeem_code']}</code>"
        )
    await callback.message.edit_text(text, parse_mode="HTML")
    await callback.answer()


@router.message(Command("redeem"))
async def cmd_redeem(message: Message):
    if not is_staff(message.from_user.id):
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(
            "Укажите код после команды, например:\n<code>/redeem JOJA-AB12CD</code>",
            parse_mode="HTML",
        )
        return
    code = parts[1].strip()
    existing = db.find_spin(code)
    if not existing:
        await message.answer(f"Код {code} не найден. Проверьте написание.")
        return
    prize = get_prize(existing["prize_code"])
    if existing["redeemed_at"]:
        await message.answer(
            f"⚠️ Код {code} уже был погашен {existing['redeemed_at']} "
            f"({existing['redeemed_by_name'] or 'сотрудник не указан'}).\n"
            f"Приз: {prize['desc'] if prize else existing['prize_code']}"
        )
        return

    until = _parse_date(existing.get("valid_until"))
    if until is not None and db.today_local() > until:
        await message.answer(
            f"⛔ Срок действия кода {code} истёк {_fmt_date(until)}.\n"
            f"Приз: {prize['desc'] if prize else existing['prize_code']}\n"
            f"Код не погашен. Если нужно сделать исключение — решает администратор."
        )
        return

    if prize and prize.get("multi_use"):
        # Недельный приз: код не закрывается, считаем использования до конца срока.
        updated = db.register_use(code)
        sheets.log_use(updated)
        await message.answer(
            f"✅ Использование №{updated['uses']} записано: {prize['desc']}\n"
            f"Код: {code}\n"
            f"Действует {_days_left_text(until, db.today_local())} — гость может приходить ещё."
        )
        return

    updated = db.redeem_spin(
        code, message.from_user.id, _display_name(message.from_user)
    )
    sheets.log_redeem(updated)
    prize = get_prize(updated["prize_code"])
    await message.answer(
        f"✅ Погашено: {prize['desc'] if prize else updated['prize_code']}\n"
        f"Код: {code}"
    )


@router.message(Command("today"))
async def cmd_today(message: Message):
    if not is_staff(message.from_user.id):
        return
    rows = db.daily_report()
    if not rows:
        await message.answer("Сегодня спинов ещё не было.")
        return

    counts: dict[str, int] = {}
    redeemed_count = 0
    for r in rows:
        counts[r["prize_code"]] = counts.get(r["prize_code"], 0) + 1
        if r["redeemed_at"]:
            redeemed_count += 1

    lines = [f"📊 Отчёт за сегодня — всего спинов: {len(rows)}\n"]
    for p in PRIZES:
        c = counts.get(p["code"], 0)
        if c:
            lines.append(f"• {p['label']}: {c}")
    lines.append(f"\nПогашено: {redeemed_count} / {len(rows)}")
    await message.answer("\n".join(lines))


@router.message(Command("unredeemed"))
async def cmd_unredeemed(message: Message):
    if not is_staff(message.from_user.id):
        return
    rows = db.unredeemed_older_than()
    # Исключаем призы без ценности (NO_WIN у них код вообще не выдаётся, но на
    # всякий случай фильтруем и здесь).
    rows = [r for r in rows if r["prize_code"] != "NO_WIN"]
    if not rows:
        await message.answer("Непогашенных призов нет. 🎉")
        return

    today = db.today_local()
    active, expired = [], []
    for r in rows:
        until = _parse_date(r.get("valid_until"))
        (expired if until and until < today else active).append((r, until))
    # Сначала те, у кого срок ближе; без срока — в конце.
    active.sort(key=lambda x: (x[1] is None, x[1] or date.max))

    def line(r, until):
        prize = get_prize(r["prize_code"])
        label = prize["label"] if prize else r["prize_code"]
        extra = f", использован {r['uses']} р." if r.get("uses") else ""
        return f"• {r['redeem_code']} — {label} · {_days_left_text(until, today)}{extra}"

    lines = [f"⏳ Действующие призы: {len(active)}\n"]
    for r, until in active[:30]:
        lines.append(line(r, until))
    if len(active) > 30:
        lines.append(f"…и ещё {len(active) - 30}.")
    if expired:
        lines.append(f"\n⛔ Просрочено: {len(expired)}")
        # самые свежие просрочки — они ближе всего к «ещё можно разобраться»
        for r, until in sorted(expired, key=lambda x: x[1], reverse=True)[:10]:
            lines.append(line(r, until))
        if len(expired) > 10:
            lines.append(f"…и ещё {len(expired) - 10} (полный список — в таблице, фильтр «Просрочен»).")
    await message.answer("\n".join(lines))
