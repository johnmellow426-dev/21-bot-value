import requests
import time
import json
import telebot
import os
import datetime
from collections import defaultdict

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
PREDICTION_CHANNEL_ID = os.getenv("PREDICTION_CHANNEL_ID")

VIRTUAL_URL = os.getenv("VIRTUAL_URL", "https://melbet-8093.pro/cyber-api/mainfeedlive/web/cyber/v3/gamesByChamp?cfView=3&champId=1643503&country=192&fcountry=192&gr=1521&lng=ru&ref=8")
STATISTIC_URL_TEMPLATE = os.getenv("STATISTIC_URL_TEMPLATE", "https://melbet-8093.pro/cyber-api/mainfeedlive/web/cyber/v3/statistic?country=192&fcountry=192&gameId={game_id}&gr=1521&lng=ru&ref=8")

bot = telebot.TeleBot(BOT_TOKEN, threaded=False)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
    "Referer": "https://melbet-8093.pro/",
}

# Только старшие карты для прогнозирования
FACE_CARDS = {11: "J", 12: "Q", 13: "K", 1: "A", 14: "A"}

game_history = []
MAX_HISTORY = 100

current_predictions = {
    "player": None,
    "dealer": None,
    "message_id": None,
    "game_id": None
}

prediction_stats = {
    "total": 0,
    "exact": 0,
    "plus_minus_1": 0,
    "plus_minus_2": 0,
    "miss": 0
}

MAX_SLOTS = 4
slots = [{"game_id": None, "game_num": None, "message_id": None, "last_state": ""} for _ in range(MAX_SLOTS)]

def get_utc_game_number():
    now = datetime.datetime.now(datetime.timezone.utc)
    return (now.hour * 60) + now.minute + 1

def get_card_symbol(card_value, suit_code):
    suits = {0: "♠️", 1: "♣️", 2: "♦️", 3: "♥️"}
    values = {1: "A", 14: "A", 2: "2", 3: "3", 4: "4", 5: "5", 6: "6", 7: "7", 8: "8", 9: "9", 10: "10", 11: "J", 12: "Q", 13: "K"}
    return f"{values.get(card_value, '?')}{suits.get(suit_code, '?')}"

def parse_cards_detail(cards_str):
    try:
        cards = json.loads(cards_str)
        symbols = []
        values = []
        for c in cards:
            cv = c.get("CV", 0)
            cs = c.get("CS", 0)
            symbols.append(get_card_symbol(cv, cs))
            values.append(cv)
        return symbols, values
    except:
        return [], []

def analyze_face_cards(target_values):
    """Анализирует ТОЛЬКО старшие карты (A, K, Q, J) и предсказывает одну"""
    if len(game_history) < 5:
        return None
    
    # Считаем частоту ТОЛЬКО старших карт
    face_card_counts = defaultdict(int)
    total_face_cards = 0
    
    for game in game_history[-MAX_HISTORY:]:
        all_values = game.get("player_values", []) + game.get("dealer_values", [])
        for val in all_values:
            if val in FACE_CARDS:  # Только J, Q, K, A
                face_card_counts[val] += 1
                total_face_cards += 1
    
    if not face_card_counts:
        return None
    
    # Находим самую частую старшую карту
    most_common = max(face_card_counts.items(), key=lambda x: x[1])
    card_value = most_common[0]
    count = most_common[1]
    probability = (count / total_face_cards) * 100 if total_face_cards > 0 else 0
    
    return {
        "value": card_value,
        "symbol": FACE_CARDS[card_value],
        "probability": probability,
        "count": count,
        "total": total_face_cards
    }

def send_prediction():
    """Отправляет прогноз на второй канал (только J, Q, K, A)"""
    global current_predictions
    
    if not PREDICTION_CHANNEL_ID:
        return
    
    player_pred = analyze_face_cards("player")
    dealer_pred = analyze_face_cards("dealer")
    
    if not player_pred or not dealer_pred:
        return
    
    msg = f" **ПРОГНОЗ СТАРШИХ КАРТ** | Игра #{get_utc_game_number()}\n\n"
    
    msg += f"👤 **Игрок**: {player_pred['symbol']} ({player_pred['probability']:.1f}%)\n"
    msg += f"   Выпадало: {player_pred['count']}/{player_pred['total']} раз\n\n"
    
    msg += f"🤖 **Дилер**: {dealer_pred['symbol']} ({dealer_pred['probability']:.1f}%)\n"
    msg += f"   Выпадало: {dealer_pred['count']}/{dealer_pred['total']} раз\n\n"
    
    msg += f"📊 Статистика: {len(game_history)} игр\n"
    accuracy = ((prediction_stats['exact'] + prediction_stats['plus_minus_1'] + prediction_stats['plus_minus_2']) / prediction_stats['total'] * 100) if prediction_stats['total'] > 0 else 0
    msg += f"📈 Точность: {accuracy:.1f}% (Точных: {prediction_stats['exact']}, ±1: {prediction_stats['plus_minus_1']}, ±2: {prediction_stats['plus_minus_2']}, Промахи: {prediction_stats['miss']})"
    
    try:
        sent = bot.send_message(PREDICTION_CHANNEL_ID, msg, parse_mode="Markdown")
        current_predictions["message_id"] = sent.message_id
        current_predictions["player"] = player_pred["value"]
        current_predictions["dealer"] = dealer_pred["value"]
        print(f"📤 Прогноз: Игрок={player_pred['symbol']}, Дилер={dealer_pred['symbol']}")
    except Exception as e:
        print(f"❌ Ошибка отправки прогноза: {e}")

def check_prediction(game_data):
    """Проверяет точность прогноза (только для старших карт)"""
    global current_predictions, prediction_stats
    
    if not current_predictions.get("player") or not current_predictions.get("dealer"):
        return
    
    player_values = game_data.get("player_values", [])
    dealer_values = game_data.get("dealer_values", [])
    
    if not player_values or not dealer_values:
        return
    
    # Берем первую карту каждого
    actual_player = player_values[0]
    actual_dealer = dealer_values[0]
    
    pred_player = current_predictions["player"]
    pred_dealer = current_predictions["dealer"]
    
    def check_accuracy(pred, actual):
        if pred == actual:
            return "exact"
        elif abs(pred - actual) <= 1:
            return "plus_minus_1"
        elif abs(pred - actual) <= 2:
            return "plus_minus_2"
        else:
            return "miss"
    
    player_result = check_accuracy(pred_player, actual_player)
    dealer_result = check_accuracy(pred_dealer, actual_dealer)
    
    prediction_stats["total"] += 2
    for result in [player_result, dealer_result]:
        prediction_stats[result] += 1
    
    msg = f"📋 **ПРОВЕРКА ПРОГНОЗА**\n\n"
    
    msg += f"👤 **Игрок**:\n"
    msg += f"Прогноз: {FACE_CARDS.get(pred_player, pred_player)}\n"
    msg += f"Факт: {get_card_symbol(actual_player, 0)[:-2]} (значение: {actual_player})\n"
    result_emoji = {"exact": "✅", "plus_minus_1": "🟡", "plus_minus_2": "🟠", "miss": "❌"}
    msg += f"Результат: {result_emoji[player_result]}\n\n"
    
    msg += f"🤖 **Дилер**:\n"
    msg += f"Прогноз: {FACE_CARDS.get(pred_dealer, pred_dealer)}\n"
    msg += f"Факт: {get_card_symbol(actual_dealer, 0)[:-2]} (значение: {actual_dealer})\n"
    msg += f"Результат: {result_emoji[dealer_result]}\n\n"
    
    accuracy = ((prediction_stats["exact"] + prediction_stats["plus_minus_1"] + prediction_stats["plus_minus_2"]) / prediction_stats["total"] * 100) if prediction_stats["total"] > 0 else 0
    msg += f" **Общая точность**: {accuracy:.1f}%\n"
    msg += f"Точных: {prediction_stats['exact']} | ±1: {prediction_stats['plus_minus_1']} | ±2: {prediction_stats['plus_minus_2']} | Промахи: {prediction_stats['miss']}"
    
    try:
        bot.send_message(PREDICTION_CHANNEL_ID, msg, parse_mode="Markdown")
        print(f"✅ Проверка: Игрок={player_result}, Дилер={dealer_result}")
    except Exception as e:
        print(f"❌ Ошибка отправки проверки: {e}")
    
    current_predictions["player"] = None
    current_predictions["dealer"] = None
    current_predictions["message_id"] = None

def send_or_edit_message(slot_index, msg, is_finished):
    global slots
    slot = slots[slot_index]
    
    try:
        if slot["message_id"] is None:
            sent = bot.send_message(CHANNEL_ID, msg, parse_mode=None)
            slots[slot_index]["message_id"] = sent.message_id
        else:
            bot.edit_message_text(chat_id=CHANNEL_ID, message_id=slot["message_id"], text=msg, parse_mode=None)
        
        if is_finished:
            slots[slot_index]["is_finished"] = True
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        slots[slot_index]["message_id"] = None

def find_or_allocate_slot(game_id):
    for i, slot in enumerate(slots):
        if slot["game_id"] == game_id:
            return i
    
    for i, slot in enumerate(slots):
        if slot["game_id"] is None:
            return i
    
    for i, slot in enumerate(slots):
        if slot.get("is_finished", False):
            slots[i] = {"game_id": None, "game_num": None, "message_id": None, "last_state": ""}
            return i
    
    return 0

def get_active_games(session):
    try:
        resp = session.get(VIRTUAL_URL, headers=HEADERS, timeout=10)
        data = resp.json()
        games = data.get("games", [])
        return games if isinstance(games, list) else []
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return []

def main():
    global game_history, current_predictions
    print(" Трансляция + ПРОГНОЗЫ (J, Q, K, A) запущены...")
    session = requests.Session()
    
    last_prediction_time = 0
    
    while True:
        try:
            games = get_active_games(session)
            
            if not games:
                time.sleep(3)
                continue
            
            current_time = time.time()
            if current_time - last_prediction_time > 30:
                send_prediction()
                last_prediction_time = current_time
            
            active_game_ids = set()
            
            for game_data in games[:MAX_SLOTS]:
                game_id = game_data.get("id")
                if not game_id:
                    continue
                
                active_game_ids.add(game_id)
                
                stat_url = STATISTIC_URL_TEMPLATE.format(game_id=game_id)
                try:
                    resp = session.get(stat_url, headers=HEADERS, timeout=5)
                    if resp.status_code == 204:
                        continue
                    
                    data = resp.json()
                    score_detail = data.get("fullScoreDetail", {})
                    p1_score = score_detail.get("scoreOpp1", 0)
                    p2_score = score_detail.get("scoreOpp2", 0)
                    total_points = p1_score + p2_score
                    status = data.get("currentPeriodName", "")
                    
                    stat = data.get("statistic", {}).get("main", {})
                    p1_cards, p1_values = parse_cards_detail(stat.get("P1", "[]"))
                    p2_cards, p2_values = parse_cards_detail(stat.get("P2", "[]"))
                    
                    is_finished = (status == "Игра завершена")
                    
                    if is_finished and not any(g["id"] == game_id for g in game_history):
                        game_record = {
                            "id": game_id,
                            "player_values": p1_values,
                            "dealer_values": p2_values,
                            "timestamp": datetime.datetime.now()
                        }
                        game_history.append(game_record)
                        
                        if len(game_history) > MAX_HISTORY:
                            game_history = game_history[-MAX_HISTORY:]
                        
                        check_prediction(game_record)
                        print(f"📝 Добавлена игра #{len(game_history)}")
                    
                    slot_index = find_or_allocate_slot(game_id)
                    slot = slots[slot_index]
                    
                    if slot["game_id"] is None:
                        game_num = get_utc_game_number()
                        slots[slot_index]["game_id"] = game_id
                        slots[slot_index]["game_num"] = game_num
                        slots[slot_index]["is_finished"] = False
                    
                    current_state = f"{p1_score}_{p2_score}_{'_'.join(p1_cards)}_{'_'.join(p2_cards)}_{is_finished}"
                    
                    if current_state != slot["last_state"] and (p1_cards or p2_cards):
                        cards_p1 = " ".join(p1_cards) if p1_cards else "?"
                        cards_p2 = " ".join(p2_cards) if p2_cards else "?"
                        
                        if not is_finished:
                            if p1_score < 17:
                                arrow = "◀️"
                            elif p2_score < 17:
                                arrow = "▶️"
                            else:
                                arrow = ""
                            msg = f" #N{slot['game_num']}. {p1_score}({cards_p1}) {arrow} {p2_score}({cards_p2}) #T{total_points}"
                        else:
                            p1_win = (p1_score <= 21 and p1_score > p2_score) or (p2_score > 21 and p1_score <= 21)
                            p2_win = (p2_score <= 21 and p2_score > p1_score) or (p1_score > 21 and p2_score <= 21)
                            draw = (p1_score == p2_score) or (p1_score > 21 and p2_score > 21)
                            
                            res_p1 = "✅" if p1_win else ("🔰" if draw else "")
                            res_p2 = "✅" if p2_win else ("🔰" if draw else "")
                            
                            tags = []
                            if p1_score == 21 or p2_score == 21:
                                tags.append("#O🔵")
                            
                            is_p1_golden = (len(p1_values) == 2 and all(v in (1, 14) for v in p1_values))
                            is_p2_golden = (len(p2_values) == 2 and all(v in (1, 14) for v in p2_values))
                            if is_p1_golden or is_p2_golden:
                                tags.append("#G🔴")
                            
                            if len(p1_cards) == 2 and len(p2_cards) == 2:
                                tags.append("#R")
                            
                            tags_str = " ".join(tags)
                            msg = f"#N{slot['game_num']}. {res_p1}{p1_score}({cards_p1}) - {res_p2}{p2_score}({cards_p2}) #T{total_points} {tags_str}".strip()
                        
                        send_or_edit_message(slot_index, msg, is_finished)
                        slots[slot_index]["last_state"] = current_state
                        
                        if is_finished:
                            time.sleep(1)
                
                except Exception as e:
                    print(f"❌ Ошибка: {e}")
            
            for i, slot in enumerate(slots):
                if slot["game_id"] and slot["game_id"] not in active_game_ids and slot.get("is_finished", False):
                    slots[i] = {"game_id": None, "game_num": None, "message_id": None, "last_state": ""}
            
            time.sleep(3)
            
        except Exception as e:
            print(f"❌ Критическая ошибка: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
