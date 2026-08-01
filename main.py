import os
import time
import json
import datetime
from datetime import timezone
import requests
import telebot

# --- НАСТРОЙКИ ОКРУЖЕНИЯ ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
PREDICTION_CHANNEL_ID = os.getenv("PREDICTION_CHANNEL_ID")
PREDICTION_DETAILED_CHANNEL_ID = os.getenv("PREDICTION_DETAILED_CHANNEL_ID")

VIRTUAL_URL = os.getenv(
    "VIRTUAL_URL",
    "https://melbet-8093.pro/cyber-api/mainfeedlive/web/cyber/v3/gamesByChamp?cfView=3&champId=1643503&country=192&fcountry=192&gr=1521&lng=ru&ref=8"
)
STATISTIC_URL_TEMPLATE = os.getenv(
    "STATISTIC_URL_TEMPLATE",
    "https://melbet-8093.pro/cyber-api/mainfeedlive/web/cyber/v3/statistic?country=192&fcountry=192&gameId={game_id}&gr=1521&lng=ru&ref=8"
)

bot = telebot.TeleBot(BOT_TOKEN, threaded=False)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://melbet-8093.pro/",
}

# --- КОНСТАНТЫ ---
HIGH_CARD_VALUES = {1, 11, 12, 13}

SUITS = {
    0: "♠️",
    1: "♣️",
    2: "♦️",
    3: "♥️"
}

CARD_VALUES = {
    1: "A", 14: "A",
    2: "2", 3: "3", 4: "4", 5: "5", 6: "6", 7: "7", 8: "8", 9: "9", 10: "10",
    11: "J", 12: "Q", 13: "K"
}

TAG_O = "#O🔵"
TAG_G = "#G🔴"
TAG_R = "#R🟢"

# --- ХРАНИЛИЩА ---
active_games = {}
game_history = {}
last_assigned_game_num = None

# --- ЕДИНЫЙ ПРОГНОЗ (общий и детальный одновременно) ---
current_prediction = {
    "message_id": None,              # ID сообщения в общем канале
    "detailed_message_id": None,     # ID сообщения в детальном канале
    "trigger_game_num": None,
    "predicted_value": None,
    "predicted_symbol": None,
    "predicted_suit_code": None,
    "predicted_exact_card": None,
    "target_recipient": None,
    "confidence": 50,
    "target_game_num": None,
    "dogen_level": 1,
    "is_active": False
}


# ============================================================
#   НУМЕРАЦИЯ
# ============================================================

def normalize_game_num(num):

    while num > 1440:

        num -= 1440

    while num < 1:

        num += 1440

    return num

def get_initial_game_number():

    now = datetime.datetime.now(timezone.utc)

    return (now.hour * 60) + now.minute          # без +1

def extract_game_number(game_data):

    global last_assigned_game_num

    if last_assigned_game_num is None:

        num = get_initial_game_number()

        print(f"🔢 Первый номер (по времени): {num}")

    else:

        num = normalize_game_num(last_assigned_game_num + 1)

        print(f"🔢 Следующий номер: {num}")

    last_assigned_game_num = num

    return num

# ============================================================
#   КАРТЫ И ЛОГИКА
# ============================================================

def get_card_symbol(card_value, suit_code):
    val_str = CARD_VALUES.get(card_value, "?")
    suit_str = SUITS.get(suit_code, "?")
    return f"{val_str}{suit_str}"

def parse_cards_detail(cards_str):
    try:
        cards = json.loads(cards_str)
        symbols, values, full_cards = [], [], []
        for c in cards:
            cv, cs = c.get("CV", 0), c.get("CS", 0)
            symbols.append(get_card_symbol(cv, cs))
            values.append(cv)
            full_cards.append((cv, cs))
        return symbols, values, full_cards
    except Exception:
        return [], [], []

def get_prediction_for_card(card_value):
    if card_value == 6:
        return 13, "K (Король)"
    elif card_value in [10, 7, 9]:
        return 12, "Q (Дама)"
    elif card_value == 8:
        return 11, "J (Валет)"
    else:
        return 1, "A (Туз)"

def predict_exact_card_and_suit(predicted_value, trigger_suit):
    if predicted_value not in HIGH_CARD_VALUES:
        return None, None
    if trigger_suit is None or trigger_suit not in SUITS:
        return None, None
    card_short_val = CARD_VALUES.get(predicted_value, str(predicted_value))
    exact_card_str = f"{card_short_val}{SUITS[trigger_suit]}"
    return trigger_suit, exact_card_str

def predict_target_recipient(predicted_value, first_card, history):
    score_p1 = 50
    score_p2 = 50
    recent_games = list(history.values())[-10:]
    p1_hits = 0
    p2_hits = 0

    for g in recent_games:
        p1_has = (predicted_value in g.get("player_values", [])) or (predicted_value == 1 and 14 in g.get("player_values", []))
        p2_has = (predicted_value in g.get("dealer_values", [])) or (predicted_value == 1 and 14 in g.get("dealer_values", []))
        if p1_has:
            p1_hits += 1
        if p2_has:
            p2_hits += 1

    if p1_hits > p2_hits:
        score_p1 += 15
    elif p2_hits > p1_hits:
        score_p2 += 15

    if first_card in [6, 8]:
        score_p1 += 10
    elif first_card in [7, 9, 10]:
        score_p2 += 10

    total = score_p1 + score_p2
    if score_p1 >= score_p2:
        target = "👤 Игрок (P1)"
        confidence = int((score_p1 / total) * 100)
    else:
        target = "🎩 Дилер (P2)"
        confidence = int((score_p2 / total) * 100)
    return target, confidence


# ============================================================
#   ЕДИНЫЙ ПРОГНОЗ (публикуется в оба канала)
# ============================================================

def send_new_prediction(trigger_num, symbol, exact_card, recipient, confidence, target_num):
    """Отправляет прогноз в оба канала одновременно"""
    dogen = current_prediction["dogen_level"]
    
    # --- Общий прогноз (только значение) ---
    if PREDICTION_CHANNEL_ID:
        general_msg = f"Игра №{target_num}\nЗначение: {symbol}\nДогон: {dogen}\nРезультат:"
        try:
            sent_general = bot.send_message(PREDICTION_CHANNEL_ID, general_msg)
            current_prediction["message_id"] = sent_general.message_id
            print(f"🎯 Общий прогноз на №{target_num} ({symbol})")
        except Exception as e:
            print(f"❌ Ошибка отправки общего прогноза: {e}")
    
    # --- Детальный прогноз (с дополнительной информацией) ---
    if PREDICTION_DETAILED_CHANNEL_ID:
        detailed_msg = f"🎯 Игра №{target_num}\nЗначение: {symbol}\n"
        if exact_card:
            detailed_msg += f"🃏 Точная карта: {exact_card}\n"
        detailed_msg += f"Кому: {recipient} ({confidence}%)\nДогон: {dogen}\nРезультат:"
        try:
            sent_detailed = bot.send_message(PREDICTION_DETAILED_CHANNEL_ID, detailed_msg)
            current_prediction["detailed_message_id"] = sent_detailed.message_id
            print(f"📊 Детальный прогноз на №{target_num}")
        except Exception as e:
            print(f"❌ Ошибка отправки детального прогноза: {e}")
    
    # Обновляем статус
    current_prediction["trigger_game_num"] = trigger_num
    current_prediction["target_game_num"] = target_num
    current_prediction["predicted_symbol"] = symbol
    current_prediction["predicted_exact_card"] = exact_card
    current_prediction["target_recipient"] = recipient
    current_prediction["confidence"] = confidence
    current_prediction["is_active"] = True

def check_prediction_for_game(player_values, dealer_values, predicted_val):
    if not predicted_val:
        return False
    all_values = player_values + dealer_values
    for val in all_values:
        if predicted_val == 1 and val in [1, 14]:
            return True
        if val == predicted_val:
            return True
    return False

def check_detailed_prediction_for_game(p1_full, p2_full, predicted_val, predicted_suit, target_recipient):
    """Проверяет детальный прогноз (значение и точную карту)"""
    if not predicted_val:
        return False, False

    check_cards_for_value = p1_full if "P1" in (target_recipient or "") else p2_full

    val_hit = False
    exact_hit = False

    # 1. Значение у адресата
    for cv, cs in check_cards_for_value:
        if (predicted_val == 1 and cv in [1, 14]) or (cv == predicted_val):
            val_hit = True
            break

    # 2. Точная карта у любого из двоих
    if predicted_suit is not None:
        for cv, cs in (p1_full + p2_full):
            if ((predicted_val == 1 and cv in [1, 14]) or (cv == predicted_val)) and cs == predicted_suit:
                exact_hit = True
                break

    return val_hit, exact_hit

def finalize_prediction(status_code, exact_hit=False):
    """Обновляет оба прогноза с результатом"""
    if not current_prediction.get("is_active"):
        return
    
    target_num = current_prediction["target_game_num"]
    symbol = current_prediction["predicted_symbol"]
    exact_card = current_prediction["predicted_exact_card"]
    recipient = current_prediction["target_recipient"]
    confidence = current_prediction["confidence"]
    dogen = current_prediction["dogen_level"]

    res_str = {0: "✅0️⃣", 1: "✅1️⃣", 2: "✅2️⃣"}.get(status_code, "❌")
    if exact_hit and status_code >= 0:
        res_str += " 🎯 (ТОЧНАЯ КАРТА!)"

    # --- Обновляем общий прогноз ---
    if current_prediction.get("message_id") and PREDICTION_CHANNEL_ID:
        general_msg = f"Игра №{target_num}\nЗначение: {symbol}\nДогон: {dogen}\nРезультат: {res_str}"
        try:
            bot.edit_message_text(
                chat_id=PREDICTION_CHANNEL_ID,
                message_id=current_prediction["message_id"],
                text=general_msg
            )
            print(f"📌 Общий прогноз №{target_num} рассчитан: {res_str}")
        except Exception as e:
            print(f"❌ Ошибка обновления общего прогноза: {e}")

    # --- Обновляем детальный прогноз ---
    if current_prediction.get("detailed_message_id") and PREDICTION_DETAILED_CHANNEL_ID:
        detailed_msg = f"🎯 Игра №{target_num}\nЗначение: {symbol}\n"
        if exact_card:
            detailed_msg += f"🃏 Точная карта: {exact_card}\n"
        detailed_msg += f"Кому: {recipient} ({confidence}%)\nДогон: {dogen}\nРезультат: {res_str}"
        try:
            bot.edit_message_text(
                chat_id=PREDICTION_DETAILED_CHANNEL_ID,
                message_id=current_prediction["detailed_message_id"],
                text=detailed_msg
            )
            print(f"📌 Детальный прогноз №{target_num} рассчитан: {res_str}")
        except Exception as e:
            print(f"❌ Ошибка обновления детального прогноза: {e}")

    # Обновляем догон
    if status_code >= 0:
        current_prediction["dogen_level"] = 1
    else:
        current_prediction["dogen_level"] *= 2

    current_prediction["is_active"] = False
    current_prediction["message_id"] = None
    current_prediction["detailed_message_id"] = None


def process_prediction_check(game_num, p1_values, p2_values, p1_full, p2_full):
    """Проверяет оба прогноза для завершенной игры"""
    if not current_prediction.get("is_active"):
        return
    
    target_num = current_prediction["target_game_num"]
    plus_1_num = normalize_game_num(target_num + 1)
    plus_2_num = normalize_game_num(target_num + 2)
    pred_val = current_prediction.get("predicted_value")
    pred_suit = current_prediction.get("predicted_suit_code")
    recipient = current_prediction.get("target_recipient")
    
    # Проверяем основное значение (для общего прогноза)
    is_hit = check_prediction_for_game(p1_values, p2_values, pred_val)
    
    # Проверяем детальный прогноз
    is_detailed_hit, exact_hit = check_detailed_prediction_for_game(
        p1_full, p2_full, pred_val, pred_suit, recipient
    )

    # Логика: если значение не совпало - общий прогноз проигран
    # Для детального проверяем отдельно
    if game_num == target_num:
        if is_hit:
            finalize_prediction(0, exact_hit if is_detailed_hit else False)
    elif game_num == plus_1_num:
        if is_hit:
            finalize_prediction(1, exact_hit if is_detailed_hit else False)
    elif game_num == plus_2_num:
        if is_hit:
            finalize_prediction(2, exact_hit if is_detailed_hit else False)
        else:
            finalize_prediction(-1, False)


def process_new_prediction(game_num, first_card_value, first_card_suit):
    """Создает новый прогноз (в оба канала)"""
    if not first_card_value:
        return

    pred_val, pred_sym = get_prediction_for_card(first_card_value)
    target_num = normalize_game_num(game_num + 3)

    # Проверяем, активен ли уже прогноз
    if current_prediction.get("is_active"):
        return

    # Рассчитываем детальные данные
    suit_code, exact_card_str = predict_exact_card_and_suit(pred_val, first_card_suit)
    recipient, confidence = predict_target_recipient(pred_val, first_card_value, game_history)

    # Сохраняем данные прогноза
    current_prediction["predicted_value"] = pred_val
    current_prediction["predicted_suit_code"] = suit_code
    
    # Отправляем прогноз в оба канала
    send_new_prediction(game_num, pred_sym, exact_card_str, recipient, confidence, target_num)


# ============================================================
#   СБОР ДАННЫХ И ОСНОВНОЙ ЦИКЛ
# ============================================================

def get_active_games_info(session):
    try:
        resp = session.get(VIRTUAL_URL, headers=HEADERS, timeout=10)
        data = resp.json()
        games = data.get("games", [])
        result = []
        for idx, g in enumerate(games):
            result.append({
                "id": g.get("id"),
                "index": idx,
                "is_finished": g.get("scores", {}).get("currentPeriodName") == "Игра завершена",
                "raw_data": g
            })
        return result
    except Exception as e:
        print(f"❌ Ошибка получения списка игр: {e}")
        return []


def main():
    global active_games, game_history, last_assigned_game_num
    print("🚀 Запуск бота...")
    session = requests.Session()

    while True:
        try:
            games_info = get_active_games_info(session)
            if not games_info:
                time.sleep(3)
                continue

            current_game_ids = set(g["id"] for g in games_info)

            for g_info in games_info:
                game_id = g_info["id"]

                if game_id not in active_games:
                    game_num = extract_game_number(g_info["raw_data"])
                    active_games[game_id] = {
                        "message_id": None,
                        "game_num": game_num,
                        "last_state": "",
                        "is_finished": False
                    }
                    print(f"🆕 Начата игра #{game_num} (ID: {game_id})")

                slot = active_games[game_id]
                game_num = slot["game_num"]

                stat_url = STATISTIC_URL_TEMPLATE.format(game_id=game_id)
                resp = session.get(stat_url, headers=HEADERS, timeout=5)
                if resp.status_code == 204 or not resp.text.strip():
                    continue

                data = resp.json()
                score_detail = data.get("fullScoreDetail", {})
                p1_score = score_detail.get("scoreOpp1", 0)
                p2_score = score_detail.get("scoreOpp2", 0)
                total_points = p1_score + p2_score
                status = data.get("currentPeriodName", "")

                stat = data.get("statistic", {}).get("main", {})
                p1_cards, p1_values, p1_full = parse_cards_detail(stat.get("P1", "[]"))
                p2_cards, p2_values, p2_full = parse_cards_detail(stat.get("P2", "[]"))

                is_finished = (status == "Игра завершена")

                if is_finished and game_num not in game_history:
                    first_card_value = p1_values[0] if p1_values else None
                    first_card_suit = p1_full[0][1] if p1_full else None

                    game_history[game_num] = {
                        "player_first_card": first_card_value,
                        "player_values": p1_values,
                        "dealer_values": p2_values,
                        "player_full_cards": p1_full,
                        "dealer_full_cards": p2_full
                    }

                    if len(game_history) > 50:
                        oldest = min(game_history.keys())
                        del game_history[oldest]

                    print(f"📝 Игра #{game_num} завершена | Триггер: {first_card_value} масть {first_card_suit}")

                    # Проверяем активные прогнозы (общий и детальный вместе)
                    process_prediction_check(game_num, p1_values, p2_values, p1_full, p2_full)
                    
                    # Создаем новый прогноз только если старый уже завершен
                    if not current_prediction.get("is_active"):
                        process_new_prediction(game_num, first_card_value, first_card_suit)

                current_state = f"{p1_score}_{p2_score}_{'_'.join(p1_cards)}_{'_'.join(p2_cards)}_{is_finished}"

                if current_state != slot["last_state"] and (p1_cards or p2_cards):
                    cards_p1 = " ".join(p1_cards) if p1_cards else "?"
                    cards_p2 = " ".join(p2_cards) if p2_cards else "?"

                    if not is_finished:
                        arrow = "◀️" if p1_score < 17 else ("▶️" if p2_score < 17 else "")
                        if arrow:
                            msg = f"#N{game_num}. {p1_score}({cards_p1}) {arrow} {p2_score}({cards_p2}) #T{total_points}"
                        else:
                            msg = f"#N{game_num}. {p1_score}({cards_p1}) {p2_score}({cards_p2}) #T{total_points}"
                    else:
                        p1_win = (p1_score <= 21 and p1_score > p2_score) or (p2_score > 21 and p1_score <= 21)
                        p2_win = (p2_score <= 21 and p2_score > p1_score) or (p1_score > 21 and p2_score <= 21)
                        draw = (p1_score == p2_score) or (p1_score > 21 and p2_score > 21)

                        res_p1 = "✅" if p1_win else ("🔰" if draw else "")
                        res_p2 = "✅" if p2_win else ("🔰" if draw else "")

                        tags = []
                        if p1_score == 21 or p2_score == 21:
                            tags.append(TAG_O)
                        if (len(p1_values) == 2 and all(v in (1, 14) for v in p1_values)) or \
                           (len(p2_values) == 2 and all(v in (1, 14) for v in p2_values)):
                            tags.append(TAG_G)
                        if len(p1_cards) == 2 and len(p2_cards) == 2:
                            tags.append(TAG_R)

                        tags_str = f" {' '.join(tags)}" if tags else ""
                        msg = f"#N{game_num}. {res_p1}{p1_score}({cards_p1}) - {res_p2}{p2_score}({cards_p2}) #T{total_points}{tags_str}\n (ID: {game_id})"

                    try:
                        if slot["message_id"] is None:
                            sent = bot.send_message(CHANNEL_ID, msg)
                            slot["message_id"] = sent.message_id
                        else:
                            bot.edit_message_text(chat_id=CHANNEL_ID, message_id=slot["message_id"], text=msg)
                    except Exception as e:
                        print(f"⚠️ Ошибка отправки в Telegram: {e}")

                    slot["last_state"] = current_state
                    if is_finished:
                        slot["is_finished"] = True

            finished_to_remove = [
                gid for gid, data in active_games.items()
                if data["is_finished"] and gid not in current_game_ids
            ]
            for gid in finished_to_remove:
                del active_games[gid]

            time.sleep(3)

        except Exception as e:
            print(f"❌ Критическая ошибка цикла: {e}")
            time.sleep(5)


if __name__ == "__main__":
    main()
