# -*- coding: utf-8 -*-
"""
Синхронизация спинов/погашений в Google Sheets.

Необязательный модуль: если GOOGLE_SERVICE_ACCOUNT_JSON или GOOGLE_SHEET_ID
не заданы в окружении — синхронизация тихо отключена, бот работает как
раньше, только через SQLite. Любая ошибка здесь (нет сети, не хватает прав
у сервисного аккаунта и т.п.) не должна ронять бота — только пишется в лог.
"""
import json
import logging

from . import config

logger = logging.getLogger(__name__)

_HEADER = [
    "Код",
    "Приз",
    "Тип",
    "Локация",
    "Сотрудник (спин)",
    "Создано",
    "Погашено",
    "Кем погашено",
]

_disabled = not (config.GOOGLE_SERVICE_ACCOUNT_JSON and config.GOOGLE_SHEET_ID)
_sheet = None


def _get_sheet():
    """Возвращает лист 'Spins', создавая его и шапку при первом обращении."""
    global _sheet
    if _disabled:
        return None
    if _sheet is not None:
        return _sheet
    try:
        import gspread  # импорт здесь, чтобы отсутствие пакета не ломало остальной бот

        info = json.loads(config.GOOGLE_SERVICE_ACCOUNT_JSON)
        client = gspread.service_account_from_dict(info)
        spreadsheet = client.open_by_key(config.GOOGLE_SHEET_ID)
        try:
            ws = spreadsheet.worksheet("Spins")
        except gspread.WorksheetNotFound:
            ws = spreadsheet.add_worksheet(title="Spins", rows=1000, cols=len(_HEADER))
        if ws.row_values(1) != _HEADER:
            ws.update("A1", [_HEADER])
        _sheet = ws
        return _sheet
    except Exception:
        logger.exception("Не удалось подключиться к Google Sheets — продолжаем без выгрузки")
        return None


def log_spin(spin: dict, prize: dict | None):
    """Добавляет новую строку при каждом /spin."""
    ws = _get_sheet()
    if ws is None:
        return
    try:
        ws.append_row(
            [
                spin["redeem_code"],
                prize["label"] if prize else spin["prize_code"],
                prize["kind"] if prize else "",
                spin["location"],
                spin.get("staff_name") or str(spin["staff_tg_id"]),
                spin["created_at"],
                "",
                "",
            ],
            value_input_option="USER_ENTERED",
        )
    except Exception:
        logger.exception("Не удалось записать спин %s в Google Sheets", spin.get("redeem_code"))


def log_redeem(spin: dict):
    """Отмечает погашение в уже существующей строке (по коду)."""
    ws = _get_sheet()
    if ws is None:
        return
    try:
        cell = ws.find(spin["redeem_code"])
        if cell is None:
            return
        ws.update_cell(cell.row, 7, spin.get("redeemed_at") or "")
        ws.update_cell(
            cell.row,
            8,
            spin.get("redeemed_by_name") or str(spin.get("redeemed_by_tg_id") or ""),
        )
    except Exception:
        logger.exception("Не удалось отметить погашение %s в Google Sheets", spin.get("redeem_code"))
