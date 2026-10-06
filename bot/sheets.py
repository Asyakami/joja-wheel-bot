# -*- coding: utf-8 -*-
"""
Синхронизация спинов/погашений в Google Sheets.

Необязательный модуль: если GOOGLE_SERVICE_ACCOUNT_JSON или GOOGLE_SHEET_ID
не заданы в окружении — синхронизация тихо отключена, бот работает как
раньше, только через SQLite. Любая ошибка здесь (нет сети, не хватает прав
у сервисного аккаунта и т.п.) не должна ронять бота — только пишется в лог.

Лист «Spins» — журнал всех розыгрышей. Колонки:
  A Код · B Приз · C Тип · D Локация · E Сотрудник (спин) · F Создано ·
  G Погашено · H Кем погашено · I Действует до · J Осталось дней ·
  K Статус · L Использований
Колонки J и K — формулы (считаются от сегодняшней даты), поэтому статус
«Просрочен» появляется сам, без участия бота. Лист «Активные» — готовая
выборка для бариста: только действующие призы, ближайший срок сверху.
"""
import json
import logging
import re
from datetime import date

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
    "Действует до",
    "Осталось дней",
    "Статус",
    "Использований",
]
_NCOLS = len(_HEADER)

# Номера колонок (с 1) — для update_cell.
_COL_USES = 12

# Статусы (колонка K). Фильтр по ним — основной способ поиска у бариста.
STATUS_ACTIVE = "Активен"
STATUS_EXPIRING = "Истекает"  # остался сегодняшний или завтрашний день
STATUS_EXPIRED = "Просрочен"
STATUS_REDEEMED = "Погашен"
STATUS_NO_DEADLINE = "Без срока"  # одноразовый приз без даты окончания
STATUS_NO_PRIZE = "Без приза"

_ACTIVE_SHEET = "Активные"

_disabled = not (config.GOOGLE_SERVICE_ACCOUNT_JSON and config.GOOGLE_SHEET_ID)
_sheet = None


def _days_formula(r: int) -> str:
    return f'=IF(I{r}="","",I{r}-TODAY())'


def _status_formula(r: int) -> str:
    return (
        f'=IF(C{r}="none","{STATUS_NO_PRIZE}",'
        f'IF(G{r}<>"","{STATUS_REDEEMED}",'
        f'IF(I{r}="","{STATUS_NO_DEADLINE}",'
        f'IF(I{r}<TODAY(),"{STATUS_EXPIRED}",'
        f'IF(I{r}-TODAY()<=1,"{STATUS_EXPIRING}","{STATUS_ACTIVE}")))))'
    )


def _date_serial(iso_date: str | None):
    """'2026-10-13' -> порядковый номер даты Google Sheets (число, не зависит от локали)."""
    if not iso_date:
        return ""
    try:
        return (date.fromisoformat(iso_date) - date(1899, 12, 30)).days
    except ValueError:
        return ""


def _rgb(r: float, g: float, b: float) -> dict:
    return {"red": r, "green": g, "blue": b}


def _setup_structure(spreadsheet, ws):
    """Идемпотентно настраивает оформление листов. Вызывается при каждом старте."""
    sid = ws.id

    # --- существующие правила условного форматирования удаляем, чтобы не копились дубли
    n_rules = 0
    try:
        meta = spreadsheet.fetch_sheet_metadata(
            params={"fields": "sheets(properties(sheetId),conditionalFormats)"}
        )
        for s in meta.get("sheets", []):
            if s.get("properties", {}).get("sheetId") == sid:
                n_rules = len(s.get("conditionalFormats", []))
    except Exception:
        logger.exception("Не удалось прочитать правила форматирования листа Spins")

    full_row = {
        "sheetId": sid,
        "startRowIndex": 1,
        "startColumnIndex": 0,
        "endColumnIndex": _NCOLS,
    }
    status_col = {
        "sheetId": sid,
        "startRowIndex": 1,
        "startColumnIndex": 10,
        "endColumnIndex": 11,
    }

    def rule(index, rng, status, fmt):
        return {
            "addConditionalFormatRule": {
                "index": index,
                "rule": {
                    "ranges": [rng],
                    "booleanRule": {
                        "condition": {
                            "type": "CUSTOM_FORMULA",
                            "values": [{"userEnteredValue": f'=$K2="{status}"'}],
                        },
                        "format": fmt,
                    },
                },
            }
        }

    requests = [
        {"deleteConditionalFormatRule": {"sheetId": sid, "index": 0}} for _ in range(n_rules)
    ]
    requests += [
        # шапка: закрепить и выделить
        {
            "updateSheetProperties": {
                "properties": {"sheetId": sid, "gridProperties": {"frozenRowCount": 1}},
                "fields": "gridProperties.frozenRowCount",
            }
        },
        {
            "repeatCell": {
                "range": {
                    "sheetId": sid,
                    "startRowIndex": 0,
                    "endRowIndex": 1,
                    "startColumnIndex": 0,
                    "endColumnIndex": _NCOLS,
                },
                "cell": {
                    "userEnteredFormat": {
                        "textFormat": {"bold": True},
                        "backgroundColor": _rgb(0.90, 0.90, 0.90),
                    }
                },
                "fields": "userEnteredFormat(textFormat,backgroundColor)",
            }
        },
        # «Действует до» показываем датой дд.мм.гггг
        {
            "repeatCell": {
                "range": {
                    "sheetId": sid,
                    "startRowIndex": 1,
                    "startColumnIndex": 8,
                    "endColumnIndex": 9,
                },
                "cell": {
                    "userEnteredFormat": {
                        "numberFormat": {"type": "DATE", "pattern": "dd.mm.yyyy"}
                    }
                },
                "fields": "userEnteredFormat.numberFormat",
            }
        },
        # фильтр по всем колонкам — чтобы бариста могли отбирать по статусу/коду
        {
            "setBasicFilter": {
                "filter": {
                    "range": {
                        "sheetId": sid,
                        "startRowIndex": 0,
                        "startColumnIndex": 0,
                        "endColumnIndex": _NCOLS,
                    }
                }
            }
        },
        # подсветка (порядок важен: первое сработавшее правило выигрывает)
        rule(
            0,
            full_row,
            STATUS_EXPIRED,
            {"backgroundColor": _rgb(0.96, 0.80, 0.80), "textFormat": {"foregroundColor": _rgb(0.62, 0, 0)}},
        ),
        rule(1, full_row, STATUS_EXPIRING, {"backgroundColor": _rgb(1.0, 0.90, 0.60)}),
        rule(2, full_row, STATUS_REDEEMED, {"textFormat": {"foregroundColor": _rgb(0.55, 0.55, 0.55)}}),
        rule(3, status_col, STATUS_ACTIVE, {"backgroundColor": _rgb(0.85, 0.94, 0.85)}),
    ]
    spreadsheet.batch_update({"requests": requests})

    # --- формулы статуса для уже существующих строк (старые строки без срока → «Без срока»)
    last = len(ws.col_values(1))
    if last >= 2:
        ws.update(
            values=[[_days_formula(r), _status_formula(r)] for r in range(2, last + 1)],
            range_name=f"J2:K{last}",
            raw=False,
            value_input_option="USER_ENTERED",
        )

    # --- лист «Активные»: только действующие призы, ближайший срок сверху
    import gspread

    try:
        act = spreadsheet.worksheet(_ACTIVE_SHEET)
    except gspread.WorksheetNotFound:
        act = spreadsheet.add_worksheet(title=_ACTIVE_SHEET, rows=500, cols=7)
    formula = (
        '={"Код","Приз","Локация","Действует до","Осталось дней","Статус","Использований";'
        'IFERROR(SORT(QUERY(Spins!A2:L,'
        f'"select A,B,D,I,J,K,L where K=\'{STATUS_ACTIVE}\' or K=\'{STATUS_EXPIRING}\' '
        f'or K=\'{STATUS_NO_DEADLINE}\'",0),4,TRUE),'
        '{"","","","","","",""})}'
    )
    act.update(
        values=[[formula]], range_name="A1", raw=False, value_input_option="USER_ENTERED"
    )
    aid = act.id
    spreadsheet.batch_update(
        {
            "requests": [
                {
                    "updateSheetProperties": {
                        "properties": {"sheetId": aid, "gridProperties": {"frozenRowCount": 1}},
                        "fields": "gridProperties.frozenRowCount",
                    }
                },
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": aid,
                            "startRowIndex": 0,
                            "endRowIndex": 1,
                            "startColumnIndex": 0,
                            "endColumnIndex": 7,
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "textFormat": {"bold": True},
                                "backgroundColor": _rgb(0.90, 0.90, 0.90),
                            }
                        },
                        "fields": "userEnteredFormat(textFormat,backgroundColor)",
                    }
                },
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": aid,
                            "startRowIndex": 1,
                            "startColumnIndex": 3,
                            "endColumnIndex": 4,
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "numberFormat": {"type": "DATE", "pattern": "dd.mm.yyyy"}
                            }
                        },
                        "fields": "userEnteredFormat.numberFormat",
                    }
                },
            ]
        }
    )


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
            ws = spreadsheet.add_worksheet(title="Spins", rows=1000, cols=_NCOLS)
        if ws.col_count < _NCOLS:
            ws.add_cols(_NCOLS - ws.col_count)
        if ws.row_values(1) != _HEADER:
            ws.update(values=[_HEADER], range_name="A1")
        _sheet = ws
        # Оформление и формулы — отдельно: сбой здесь не мешает журналу писаться.
        try:
            _setup_structure(spreadsheet, ws)
        except Exception:
            logger.exception("Не удалось настроить оформление таблицы — журнал работает без него")
        return _sheet
    except Exception:
        logger.exception("Не удалось подключиться к Google Sheets — продолжаем без выгрузки")
        return None


def warmup():
    """Подключиться к таблице и подготовить структуру (вызывается при старте бота)."""
    _get_sheet()


def _row_from_range(updated_range: str) -> int | None:
    """'Spins!A5:L5' -> 5."""
    m = re.search(r"[A-Z]+(\d+)", updated_range.split("!")[-1])
    return int(m.group(1)) if m else None


def log_spin(spin: dict, prize: dict | None):
    """Добавляет новую строку при каждом /spin."""
    ws = _get_sheet()
    if ws is None:
        return
    try:
        multi = bool(prize and prize.get("multi_use"))
        res = ws.append_row(
            [
                spin["redeem_code"],
                prize["label"] if prize else spin["prize_code"],
                prize["kind"] if prize else "",
                spin["location"],
                spin.get("staff_name") or str(spin["staff_tg_id"]),
                spin["created_at"],
                "",
                "",
                _date_serial(spin.get("valid_until")),
                "",
                "",
                0 if multi else "",
            ],
            value_input_option="USER_ENTERED",
        )
        row = _row_from_range((res or {}).get("updates", {}).get("updatedRange", ""))
        if row:
            ws.update(
                values=[[_days_formula(row), _status_formula(row)]],
                range_name=f"J{row}:K{row}",
                raw=False,
                value_input_option="USER_ENTERED",
            )
        else:
            logger.warning("Не удалось определить строку для формул статуса: %s", spin.get("redeem_code"))
    except Exception:
        logger.exception("Не удалось записать спин %s в Google Sheets", spin.get("redeem_code"))


def log_redeem(spin: dict):
    """Отмечает погашение в уже существующей строке (по коду)."""
    ws = _get_sheet()
    if ws is None:
        return
    try:
        cell = ws.find(spin["redeem_code"], in_column=1)
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


def log_use(spin: dict):
    """Обновляет счётчик использований многоразового (недельного) приза."""
    ws = _get_sheet()
    if ws is None:
        return
    try:
        cell = ws.find(spin["redeem_code"], in_column=1)
        if cell is None:
            return
        ws.update_cell(cell.row, _COL_USES, spin.get("uses") or 0)
    except Exception:
        logger.exception("Не удалось обновить использования %s в Google Sheets", spin.get("redeem_code"))
