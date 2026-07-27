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

# Каналы для прогнозов
PRED_CHANNEL = -1003113077361       # Канал для Рангов карт (+3 игры)
SUIT_PRED_CHANNEL = -1003113077361  # ⚠️ УКАЖИТЕ ID КАНАЛА ДЛЯ МАСТЕЙ (+7 игр)

DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

HISTORY_FILE = os.path.join(DATA_DIR, "simple_history.json")

# Файлы для рангов
RANK_PRED_FILE = os.path.join(DATA_DIR, "active_pred_rank.json")
STATS_RANK_FILE = os.path.join(DATA_DIR, "stats_rank.json")

# Файлы для мастей
SUIT_PRED_FILE = os.path.join(DATA_DIR, "active_pred_suit.json")
SUIT_QUEUE_FILE = os.path.join(DATA_DIR, "queue_pred_suit.json")
STATS_SUIT_FILE = os.path.join(DATA_DIR, "stats_suit.json")

TOTAL_GAMES = 1440
CHECK_RANGE = 3  # Основная игра + 2 догона

# Карта зеркализации мастей
SUIT_MIRROR = {
    '♣': '♦',
    '♦': '♣',
    '♠': '♥',
    '♥': '♠'
}

SUIT_NAMES = {
    '♣': '♣️ Трефы',
    '♦': '♦️ Буби',
    '♠': '♠️ Пики',
    '♥': '♥️ Черви'
}

LOG_FILE = os.path.join(DATA_DIR, "baccarat_predictor.log")

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


def parse_cards_and_suits(cards_str: str) -> tuple[List[str], List[str]]:
    """Извлекает отдельно ранги и масти карт"""
    cleaned = re.sub(r'[🔰✅🟩]', '', cards_str)
    ranks = re.findall(r'([A-Z\d]+)\s*[♣♦♥♠]', cleaned)
    suits = re.findall(r'[♣♦♥♠]', cleaned)
    return ranks, suits


def parse_game(text: str) -> Optional[Dict]:
    text = re.sub(r'^\[\d{2}\.\d{2}\.\d{4}\s+\d{2}:\d{2}\]\s*[^:]+:\s*', '', text)

    pattern = r'#N(\d+)\.\s*(?:✅|🔰)?\s*(\d+)\s*\(([^)]+)\)\s*(?:✅|🔰)?\s*(\d+)\s*\(([^)]+)\)'
    match = re.search(pattern, text)

    if match:
        raw_id = int(match.group(1))
        player_str = match.group(3)
        banker_str = match.group(5)

        player_ranks, player_suits = parse_cards_and_suits(player_str)
        banker_ranks, banker_suits = parse_cards_and_suits(banker_str)

        if player_ranks and banker_ranks:
            return {
                "raw_id": raw_id,
                "player_ranks": player_ranks,
                "player_suits": player_suits,
                "banker_ranks": banker_ranks,
                "banker_suits": banker_suits,
                "all_ranks": player_ranks + banker_ranks,
                "timestamp": datetime.now().isoformat()
            }
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
    logger.info(f"📥 Игра #{raw_id}: Игрок={game['player_ranks']}({game['player_suits']})")

    # Сохранение истории
    history = load_json(HISTORY_FILE, [])
    history = [g for g in history if g.get("raw_id") != raw_id]
    history.append(game)
    save_json(HISTORY_FILE, history[-300:])

    # =========================================================================
    # 1. ОБРАБОТКА ПРОГНОЗОВ РАНГОВ (+3 игры)
    # =========================================================================
    active_rank_preds = load_json(RANK_PRED_FILE, [])
    updated_rank_preds = []

    for pred in active_rank_preds:
        offset = raw_id - pred["target_raw"]
        if 0 <= offset < CHECK_RANGE:
            is_success = pred["target_rank"] in game["all_ranks"]
            stats = load_json(STATS_RANK_FILE, {"success": 0, "fail": 0})

            if is_success:
                emoji = ["0️⃣", "1️⃣", "2️⃣"][offset]
                try:
                    await context.bot.edit_message_text(
                        chat_id=PRED_CHANNEL,
                        message_id=pred["msg_id"],
                        text=f"✅ Игра №{pred['target']}\n"
                             f"🎴 Значение: *{pred['target_rank']}* обоим\n"
                             f"🎯 *ДА* → ✅{emoji}",
                        parse_mode="Markdown"
                    )
                    stats["success"] = stats.get("success", 0) + 1
                    save_json(STATS_RANK_FILE, stats)
                except Exception as e:
                    logger.error(f"Ошибка редактирования ранга: {e}")
                continue
            elif offset == CHECK_RANGE - 1:
                try:
                    await context.bot.edit_message_text(
                        chat_id=PRED_CHANNEL,
                        message_id=pred["msg_id"],
                        text=f"❌ Игра №{pred['target']}\n"
                             f"🎴 Значение: *{pred['target_rank']}* обоим\n"
                             f"🎯 *ДА* 💥 Не зашёл",
                        parse_mode="Markdown"
                    )
                    stats["fail"] = stats.get("fail", 0) + 1
                    save_json(STATS_RANK_FILE, stats)
                except Exception as e:
                    logger.error(f"Ошибка редактирования ранга: {e}")
                continue
        updated_rank_preds.append(pred)
    save_json(RANK_PRED_FILE, updated_rank_preds)

    # Создание прогноза ранга (+3 игры)
    if len(game["player_ranks"]) >= 2:
        second_card_rank = game["player_ranks"][1]
        target_raw = raw_id + 4
        target_norm = (target_raw - 1) % TOTAL_GAMES + 1

        try:
            pred_text = (
                f"🔥 Игра №{target_norm}\n"
                f"🎴 Значение: *{second_card_rank}* обоим\n"
                f"🎯 *ДА*\n"
                f"⏳ Ожидание..."
            )
            sent = await context.bot.send_message(chat_id=PRED_CHANNEL, text=pred_text, parse_mode="Markdown")
            updated_rank_preds.append({
                "target_raw": target_raw,
                "target": target_norm,
                "target_rank": second_card_rank,
                "msg_id": sent.message_id
            })
            save_json(RANK_PRED_FILE, updated_rank_preds)
        except Exception as e:
            logger.error(f"Ошибка отправки прогноза рангов: {e}")

    # =========================================================================
    # 2. ОБРАБОТКА И ПУБЛИКАЦИЯ ПРОГНОЗОВ МАСТЕЙ (+7 игр)
    # =========================================================================
    active_suit_pred = load_json(SUIT_PRED_FILE, {})
    suit_queue = load_json(SUIT_QUEUE_FILE, {})

    # A) Проверка опубликованного прогноза
    if active_suit_pred and "target_raw" in active_suit_pred:
        offset = raw_id - active_suit_pred["target_raw"]
        if 0 <= offset < CHECK_RANGE:
            # Проверяем наличие масти ТОЛЬКО У ИГРОКА
            is_success = active_suit_pred["target_suit"] in game["player_suits"]
            stats = load_json(STATS_SUIT_FILE, {"success": 0, "fail": 0})

            if is_success:
                emoji = ["0️⃣", "1️⃣", "2️⃣"][offset]
                try:
                    await context.bot.edit_message_text(
                        chat_id=SUIT_PRED_CHANNEL,
                        message_id=active_suit_pred["msg_id"],
                        text=f"✅ Игра №{active_suit_pred['target']}\n"
                             f"🎨 Игрок масть: *{SUIT_NAMES[active_suit_pred['target_suit']]}*\n"
                             f"🎯 *ДА* → ✅{emoji}",
                        parse_mode="Markdown"
                    )
                    stats["success"] = stats.get("success", 0) + 1
                    save_json(STATS_SUIT_FILE, stats)
                    active_suit_pred = {}
                    save_json(SUIT_PRED_FILE, {})
                except Exception as e:
                    logger.error(f"Ошибка обновления прогноза масти: {e}")

            elif offset == CHECK_RANGE - 1:
                try:
                    await context.bot.edit_message_text(
                        chat_id=SUIT_PRED_CHANNEL,
                        message_id=active_suit_pred["msg_id"],
                        text=f"❌ Игра №{active_suit_pred['target']}\n"
                             f"🎨 Игрок масть: *{SUIT_NAMES[active_suit_pred['target_suit']]}*\n"
                             f"🎯 *ДА* 💥 Не зашёл",
                        parse_mode="Markdown"
                    )
                    stats["fail"] = stats.get("fail", 0) + 1
                    save_json(STATS_SUIT_FILE, stats)
                    active_suit_pred = {}
                    save_json(SUIT_PRED_FILE, {})
                except Exception as e:
                    logger.error(f"Ошибка обновления прогноза масти: {e}")

    # Б) Публикация из очереди (когда осталось 2 игры: publish_raw == current_raw)
    if not active_suit_pred and suit_queue:
        if raw_id >= suit_queue.get("publish_raw", 0):
            try:
                pred_text = (
                    f"🔥 Игра №{suit_queue['target']}\n"
                    f"🎨 Игрок масть: *{SUIT_NAMES[suit_queue['target_suit']]}*\n"
                    f"🎯 *ДА*\n"
                    f"⏳ Ожидание..."
                )
                sent = await context.bot.send_message(chat_id=SUIT_PRED_CHANNEL, text=pred_text, parse_mode="Markdown")

                active_suit_pred = {
                    "target_raw": suit_queue["target_raw"],
                    "target": suit_queue["target"],
                    "target_suit": suit_queue["target_suit"],
                    "msg_id": sent.message_id
                }
                save_json(SUIT_PRED_FILE, active_suit_pred)

                # Очищаем очередь после отправки
                suit_queue = {}
                save_json(SUIT_QUEUE_FILE, {})
                logger.info(f"📤 Опубликован прогноз масти на игру #{active_suit_pred['target']}")
            except Exception as e:
                logger.error(f"Ошибка отправки прогноза масти в канал: {e}")

    # В) Постановка НОВОГО прогноза мастей в очередь (если ВСЕ пусто: и в канале, и в очереди)
    if not active_suit_pred and not suit_queue:
        if len(game["player_suits"]) >= 2:
            second_card_suit = game["player_suits"][1]  # 2-я карта игрока
            target_suit = SUIT_MIRROR.get(second_card_suit)

            if target_suit:
                target_raw = raw_id + 7
                target_norm = (target_raw - 1) % TOTAL_GAMES + 1
                publish_raw = raw_id + 5  # Публикация за 2 игры до целевой

                suit_queue = {
                    "source_raw": raw_id,
                    "publish_raw": publish_raw,
                    "target_raw": target_raw,
                    "target": target_norm,
                    "target_suit": target_suit
                }
                save_json(SUIT_QUEUE_FILE, suit_queue)
                logger.info(f"⏳ Запланирован прогноз масти '{target_suit}' на игру #{target_norm} (публикация в #{publish_raw})")


# === КОМАНДА /stats ===
async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    if chat_id == PRED_CHANNEL:
        stats = load_json(STATS_RANK_FILE, {"success": 0, "fail": 0})
        total = stats["success"] + stats["fail"]
        rate = (stats["success"] / total * 100) if total > 0 else 0

        msg = (
            "📊 *Статистика прогнозов рангов*\n\n"
            f"Успехов: {stats['success']}, Провалов: {stats['fail']}\n"
            f"Всего: {total}, Успешность: *{rate:.1f}%*"
        )
        await update.message.reply_text(msg, parse_mode="Markdown")

    elif chat_id == SUIT_PRED_CHANNEL:
        stats = load_json(STATS_SUIT_FILE, {"success": 0, "fail": 0})
        total = stats["success"] + stats["fail"]
        rate = (stats["success"] / total * 100) if total > 0 else 0

        msg = (
            "📊 *Статистика прогнозов мастей Игроку*\n\n"
            f"Успехов: {stats['success']}, Провалов: {stats['fail']}\n"
            f"Всего: {total}, Успешность: *{rate:.1f}%*"
        )
        await update.message.reply_text(msg, parse_mode="Markdown")


# === ЗАПУСК ===
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(MessageHandler(filters.Chat(SOURCE_CHAT_ID) & filters.TEXT, handle_update))
    app.add_handler(CommandHandler("stats", stats_command))

    logger.info("✅ Бот запущен: раздельные каналы для Рангов (+3) и Мастей (+7 с отложенным постом)")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
