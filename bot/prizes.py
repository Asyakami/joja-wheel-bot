# -*- coding: utf-8 -*-
"""
Призы колеса Joja Coffee — 9 секторов (700 мм).
Порядок соответствует макету колеса. Каждый приз имеет:
  code       — короткий машинный код (используется в БД и в редемпшн-коде)
  label      — короткое название для кнопок бота
  desc       — полный текст приза, который бариста озвучивает/выдаёт гостю
  kind       — тип для отчётности: "discount", "gift", "reserve", "none"
  valid_days — срок действия в днях от даты розыгрыша (включительно):
                 0    — только в день розыгрыша («прямо сейчас»)
                 7    — неделя: «действует до» = дата розыгрыша + 7 дней
                 None — срок по дате не ограничен (одноразовый приз)
  multi_use  — True, если приз можно использовать каждый день в течение срока
               (недельные призы). Тогда /redeem не «закрывает» код, а
               добавляет использование; код действует до конца срока.

Чтобы поменять срок приза — поправьте valid_days здесь, больше нигде.
"""
from datetime import date, timedelta

PRIZES = [
    {
        "code": "SYRUP_WEEK",
        "label": "🍯 Сироп/альт. молоко — неделя до 11:00",
        "desc": "Бесплатный сироп или альтернативное молоко к напитку каждый день в течение недели, при заказе до 11:00.",
        "kind": "gift",
        "valid_days": 7,
        "multi_use": True,
    },
    {
        "code": "STORY_10_20",
        "label": "📱 Скидка 10→20% за репост в сторис",
        "desc": "Скидка 10% сразу; скидка увеличивается до 20%, если гость репостнёт сторис с отметкой Joja Coffee.",
        "kind": "discount",
        "valid_days": 0,
        "multi_use": False,
    },
    {
        "code": "WINE_20_GLASS",
        "label": "🍷 20% на винный вечер + бокал в подарок",
        "desc": "Скидка 20% на билет на вечернюю винную дегустацию + бокал в подарок.",
        "kind": "gift",
        "valid_days": None,
        "multi_use": False,
    },
    {
        "code": "MORNING_10",
        "label": "☀️ 10% на заказ до 11:00",
        "desc": "Скидка 10% на заказ при оформлении до 11:00.",
        "kind": "discount",
        "valid_days": 0,
        "multi_use": False,
    },
    {
        "code": "NO_WIN",
        "label": "😉 Упс! В следующий раз",
        "desc": "Приз не выпал — «Упс! В следующий раз».",
        "kind": "none",
        "valid_days": None,
        "multi_use": False,
    },
    {
        "code": "RESERVE_WINE_TABLE",
        "label": "🪑 Бронь стола на винный вечер",
        "desc": "Бронирование стола на ближайший винный вечер.",
        "kind": "reserve",
        "valid_days": None,
        "multi_use": False,
    },
    {
        "code": "EVENING_10",
        "label": "🌙 10% на напитки после 18:00",
        "desc": "Скидка 10% на напитки при заказе после 18:00.",
        "kind": "discount",
        "valid_days": 7,
        "multi_use": True,
    },
    {
        "code": "BARISTA_SURPRISE",
        "label": "🎁 Сюрприз от бариста",
        "desc": "Сюрприз от бариста — на усмотрение бариста (дегустационная порция, печенье и т.п.).",
        "kind": "gift",
        "valid_days": 0,
        "multi_use": False,
    },
    {
        "code": "SIZE_UPGRADE_WEEK",
        "label": "⬆️ Апгрейд M→L после 19:00 — неделя",
        "desc": "Бесплатный апгрейд размера напитка M→L при заказе после 19:00, каждый день в течение недели.",
        "kind": "gift",
        "valid_days": 7,
        "multi_use": True,
    },
]

PRIZE_BY_CODE = {p["code"]: p for p in PRIZES}


def get_prize(code: str):
    return PRIZE_BY_CODE.get(code)


def valid_until(prize, on_date: date):
    """Последний день действия приза (включительно) или None, если срока нет."""
    if not prize:
        return None
    days = prize.get("valid_days")
    if days is None:
        return None
    return on_date + timedelta(days=days)
