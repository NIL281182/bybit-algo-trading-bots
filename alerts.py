#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
alerts.py — отправка уведомлений в Telegram.

Использует threading, чтобы не блокировать основной поток бота при проблемах
с сетью или Telegram API.
"""

import os
import json
import logging
import threading
from urllib import request, error

logger = logging.getLogger(__name__)


def _send_telegram_request(bot_token: str, chat_id: str, text: str, parse_mode: str = "Markdown"):
    """Синхронный POST в Telegram (вызывается в отдельном потоке)."""
    if not bot_token or not chat_id:
        return

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}

    try:
        req = request.Request(url, data=data, headers=headers, method="POST")
        with request.urlopen(req, timeout=10) as resp:
            if resp.status != 200:
                logger.warning(f"Telegram ответил {resp.status}: {resp.read().decode()}")
    except error.HTTPError as e:
        logger.warning(f"Telegram HTTP ошибка {e.code}: {e.read().decode()}")
    except Exception as e:
        logger.warning(f"Telegram отправка не удалась: {e}")


def send_alert(text: str, parse_mode: str = "Markdown"):
    """
    Отправляет сообщение в Telegram в фоновом потоке.
    Если переменные окружения не заданы — молча игнорирует.
    """
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not bot_token or not chat_id:
        return

    t = threading.Thread(target=_send_telegram_request, args=(bot_token, chat_id, text, parse_mode))
    t.daemon = True
    t.start()


# --- Готовые шаблоны сообщений ---

def alert_startup(strategy_name: str, symbol: str):
    send_alert(
        f"🤖 *{strategy_name}* запущен\\!\n"
        f"Инструмент: `{symbol}`\n"
        f"Время: `{logging.Formatter().formatTime(logging.LogRecord(None, 0, '', 0, '', (), None))}`"
    )


def alert_entry(symbol: str, side: str, entry: float, stop: float, qty: float, equity: float):
    send_alert(
        f"🚀 *Вход в позицию* `{symbol}`\n\n"
        f"*Сторона:* {side}\n"
        f"*Вход:* `{entry:,.2f}`\n"
        f"*Стоп:* `{stop:,.2f}`\n"
        f"*Qty:* `{qty:,.6f}`\n"
        f"*Equity:* `{equity:,.2f} USDT`"
    )


def alert_exit(symbol: str, reason: str, price: float = None):
    price_str = f"\n*Цена:* `{price:,.2f}`" if price else ""
    send_alert(
        f"📉 *Выход из позиции* `{symbol}`\n\n"
        f"*Причина:* {reason}{price_str}"
    )


def alert_error(message: str, exc_info: str = None):
    exc_str = f"\n```\n{exc_info[:400]}\n```" if exc_info else ""
    send_alert(
        f"⚠️ *Критическая ошибка*\n\n"
        f"{message}{exc_str}"
    )


def alert_balance_zero():
    send_alert("⚠️ *Баланс 0* — бот не может открыть позицию.")


def alert_insufficient_qty(raw_qty: float):
    send_alert(
        f"⚠️ *Qty слишком мал*\\!\n\n"
        f"Расчётное количество: `{raw_qty:,.6f}`\n"
        f"Меньше минимально допустимого. Сделка пропущена."
    )
