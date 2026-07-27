import re
import json
import logging
import os
from datetime import datetime
from typing import Optional, List, Dict, Any

from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes, CommandHandler

# === КОНФИГ ===
BOT_TOKEN = os.environ.get("BOT_TOKEN", "7595431774:AAGqVaashXulX08PEpgZHsn7LysPrV6rul0")
SOURCE_CHAT_ID = -1003469691743
PRED_CHANNEL = -1003113077361

DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

HISTORY_FILE = os.path.join(DATA_DIR, "simple_history.json")
RANK_PRED_FILE = os.path.join(DATA_DIR, "active_pred_rank.json")
STATS_RANK_FILE = os.path.join(DATA_DIR, "stats_rank.json")

TOTAL_GAMES = 1440
PREDICT_OFFSET = 3  # Прогнозируем на +3 игры вперед (например, 1215 -> 1218)
CHECK_RANGE = 3     # Основная игра + 2 догона (всего 3 попытки: 0, +1, +2)

LOG_FILE = os.path.join(DATA_DIR, "rank_predictor.log")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


# === УТИЛИТЫ ===
def load_json(file: str, default=None):
    try:
        with open(file, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default if default is not None else {}


def save_json(file: str, data):
    with open(file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def extract_ranks(cards_str: str) -> List[str]:
    """Извлекает только ранги карт (например: ['3', '7', 'J'])"""
    cleaned = re.sub(r'[🔰✅🟩]', '', cards_str)
    ranks = re.findall(r'([A-Z\d]+)\s*[♣♦♥♠]', cleaned)
    return ranks


def parse_game(text: str) -> Optional[Dict]:
    # Убираем префикс экспорта Telegram
    text = re.sub(r'^\[\d{2}\.\d{2}\.\d{4}\s+\d{2}:\d{2}\]\s*[^:]+:\s*', '', text)

    # Паттерн разбирает галочки, очки и списки карт
    pattern = r'#N(\d+)\.\s*(?:✅|🔰)?\s*(\d+)\s*\(([^)]+)\)\s*(?:✅|🔰)?\s*(\d+)\s*\(([^)]+)\)'
    match = re.search(pattern, text)

    if match:
        raw_id = int(match.group(1))
        player_str = match.group(3)
        banker_str = match.group(5)

        player_ranks = extract_ranks(player_str)
        banker_ranks = extract_ranks(banker_str)

        if player_ranks and banker_ranks:
            return {
                "raw_id": raw_id,
                "player_ranks": player_ranks,
                "banker_ranks": banker_ranks,
                "all_ranks": player_ranks + banker_ranks,
                "hour": datetime.now().hour,
                "timestamp": datetime.now().isoformat(),
                "text": text
            }
        else:
            logger.warning(f"Не удалось извлечь карты для игры #{raw_id}: player='{player_str}', banker='{banker_str}'")
    else:
        match_id = re.search(r'#N(\d+)', text)
        if match_id:
            raw_id = int(match_id.group(1))
            logger.warning(f"Не удалось разобрать игру #{raw_id}: {text[:50]}...")

    return None


# === ОБРАБОТКА СООБЩЕНИЙ ===
async def handle_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = None
    for candidate in [update.message, update.edited_message, update.channel_post, update.edited_channel_post]:
        if candidate and candidate.text:
            msg = candidate
            break
    if not msg:
        return

    game = parse_game(msg.text)
    if not game:
        return

    raw_id = game["raw_id"]
    logger.info(f"📥 Игра #{raw_id}: Игрок={game['player_ranks']}, Банкир={game['banker_ranks']}")

    # Сохранение истории
    history = load_json(HISTORY_FILE, [])
    history = [g for g in history if g.get("raw_id") != raw_id]
    history.append(game)
    save_json(HISTORY_FILE, history[-300:])

    # === 1. ПРОВЕРКА АКТИВНЫХ ПРОГНОЗОВ ===
    active_preds = load_json(RANK_PRED_FILE, [])
    updated_preds = []

    for pred in active_preds:
        target_raw = pred["target_raw"]
        target_rank = pred["target_rank"]
        offset = raw_id - target_raw

        # Если игра входит в диапазон проверки (Основная + 2 догона)
        if 0 <= offset < CHECK_RANGE:
            # Ищем ранг в картах Игрока или Банкира
            is_success = target_rank in game["all_ranks"]
            stats = load_json(STATS_RANK_FILE, {"success": 0, "fail": 0})

            if is_success:
                emoji = ["0️⃣", "1️⃣", "2️⃣"][offset]
                try:
                    await context.bot.edit_message_text(
                        chat_id=PRED_CHANNEL,
                        message_id=pred["msg_id"],
                        text=f"✅ Игра №{pred['target']}\n"
                             f"🎴 Значение: *{target_rank}* обоим\n"
                             f"🎯 *ДА* → ✅{emoji}"
                    )
                    stats["success"] = stats.get("success", 0) + 1
                    save_json(STATS_RANK_FILE, stats)
                    logger.info(f"🎉 Прогноз на карту {target_rank} в игре #{pred['target']} зашел (шаг {offset})")
                except Exception as e:
                    logger.error(f"Ошибка редактирования сообщения успехом: {e}")
                # Прогноз закрыт, не добавляем его обратно в список активных
                continue

            elif offset == CHECK_RANGE - 1:
                # Если это был последний догон и ранг так и не выпал
                try:
                    await context.bot.edit_message_text(
                        chat_id=PRED_CHANNEL,
                        message_id=pred["msg_id"],
                        text=f"❌ Игра №{pred['target']}\n"
                             f"🎴 Значение: *{target_rank}* обоим\n"
                             f"🎯 *ДА* 💥 Не зашёл"
                    )
                    stats["fail"] = stats.get("fail", 0) + 1
                    save_json(STATS_RANK_FILE, stats)
                    logger.info(f"💥 Прогноз на карту {target_rank} в игре #{pred['target']} провалился")
                except Exception as e:
                    logger.error(f"Ошибка редактирования сообщения провалом: {e}")
                # Прогноз закрыт
                continue

        # Если прогноз еще актуален и его время не истекло — оставляем
        updated_preds.append(pred)

    save_json(RANK_PRED_FILE, updated_preds)

    # === 2. СОЗДАНИЕ НОВОГО ПРОГНОЗА ===
    # Проверяем, есть ли у Игрока хотя бы 2 карты
    if len(game["player_ranks"]) >= 2:
        second_card_rank = game["player_ranks"][1]  # Индекс 1 = вторая карта игрока

        target_raw = raw_id + PREDICT_OFFSET
        target_norm = (target_raw - 1) % TOTAL_GAMES + 1

        try:
            pred_text = (
                f"🔥 Игра №{target_norm}\n"
                f"🎴 Значение: *{second_card_rank}* обоим\n"
                f"🎯 *ДА*\n"
                f"⏳ Ожидание..."
            )
            sent = await context.bot.send_message(chat_id=PRED_CHANNEL, text=pred_text, parse_mode="Markdown")

            # Сохраняем новый прогноз в массив
            new_pred = {
                "target_raw": target_raw,
                "target": target_norm,
                "target_rank": second_card_rank,
                "msg_id": sent.message_id
            }
            updated_preds.append(new_pred)
            save_json(RANK_PRED_FILE, updated_preds)

            logger.info(f"📤 Выставлен прогноз на карту '{second_card_rank}' на игру #{target_norm} (+{PREDICT_OFFSET})")
        except Exception as e:
            logger.error(f"Ошибка отправки прогноза ранга: {e}")


# === КОМАНДА /stats ===
async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != PRED_CHANNEL:
        return

    stats = load_json(STATS_RANK_FILE, {"success": 0, "fail": 0})
    total = stats["success"] + stats["fail"]
    rate = (stats["success"] / total * 100) if total > 0 else 0

    msg = (
        "📊 *Статистика прогнозов рангов карт*\n\n"
        f"🔹 *Прогноз на 2-ю карту игрока (+3 игры)*\n"
        f"Успехов: {stats['success']}, Провалов: {stats['fail']}\n"
        f"Всего сигналов: {total}\n"
        f"Успешность: *{rate:.1f}%*"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


# === ЗАПУСК ===
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(MessageHandler(filters.Chat(SOURCE_CHAT_ID) & filters.TEXT, handle_update))
    app.add_handler(CommandHandler("stats", stats_command))

    logger.info("✅ Бот прогнозирования рангов карт запущен (+3 игры, 2 догона)")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
