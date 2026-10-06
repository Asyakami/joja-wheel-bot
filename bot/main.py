# -*- coding: utf-8 -*-
import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, MenuButtonCommands

from . import config, db, sheets
from .handlers import router

# Список, который бариста видят по кнопке «Меню» слева от поля ввода в Telegram.
BOT_COMMANDS = [
    BotCommand(command="spin", description="🎡 Записать приз, выпавший гостю"),
    BotCommand(command="redeem", description="✅ Погасить код приза (после команды — код)"),
    BotCommand(command="today", description="📊 Отчёт за сегодня"),
    BotCommand(command="unredeemed", description="⏳ Действующие и просроченные призы"),
    BotCommand(command="start", description="👋 Приветствие и список команд"),
]


async def _setup_menu(bot: Bot):
    """Включает кнопку «Меню» со списком команд. Сбой не должен мешать запуску."""
    try:
        await bot.set_my_commands(BOT_COMMANDS)
        await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
    except Exception:
        logging.exception("Не удалось настроить меню команд — бот работает без него")


async def main():
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)

    if not config.BOT_TOKEN:
        raise SystemExit(
            "BOT_TOKEN не задан. Установите переменную окружения BOT_TOKEN "
            "(токен от @BotFather) — см. README."
        )

    db.init_db()
    # Подключаемся к Google Sheets и готовим структуру листов сразу при старте,
    # чтобы первый /spin не ждал настройки таблицы.
    await asyncio.to_thread(sheets.warmup)

    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.include_router(router)
    await _setup_menu(bot)

    logging.info("Joja wheel bot starting (polling)...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
