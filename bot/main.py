# -*- coding: utf-8 -*-
import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from . import config, db
from .handlers import router


async def main():
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)

    if not config.BOT_TOKEN:
        raise SystemExit(
            "BOT_TOKEN не задан. Установите переменную окружения BOT_TOKEN "
            "(токен от @BotFather) — см. README."
        )

    db.init_db()

    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.include_router(router)

    logging.info("Joja wheel bot starting (polling)...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
