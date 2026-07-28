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

# --- ХРАНИЛИЩА ДАННЫХ ---
active_games = {}
game_history = {}

# Глобальный трекинг для идеальной синхронизации номеров
last_known_game_id = None
last_assigned_game_num = None

current_prediction = {
    "message_id": None,
    "trigger_game_num": None,
    "predicted_value": None,
    "predicted_symbol": None,
    "target_game_num": None,
    "dogen_level": 1,
    "is_active": False
}


# --- ФУНКЦИИ ТОЧНОЙ НУМЕРАЦИИ ---

def normalize_game_num(num):
    """Корректирует номер игры при переходе через 00:00 UTC (1..1440)"""
    while num > 1440:
        num -= 1440
    while num < 1:
        num += 1440
    return num

def get_utc_game_number(timestamp):
    """Рассчитывает номер минуты в сутках (1..1440) по времени UTC из API"""
    if timestamp:
        # Если пришел timestamp в миллисекундах
        if timestamp > 1e11:
            timestamp /= 1000
        dt = datetime.datetime.fromtimestamp(timestamp, tz=timezone.utc)
    else:
        dt = datetime.datetime.now(timezone.utc)
    return (dt.hour * 60) + dt.minute + 1

def extract_game_number(game_data):
    """
    Извлекает номер игры на основе данных API Melbet.
    Привязка идет к времени старта матча (S / startDate) и разнице ID.
    """
    global last_known_game_id, last_assigned_game_num
    
    current_id = game_data.get("id")
    calculated_num = None

    # 1. Попытка взять явный короткий номер из полей API
    for key in ["num", "N", "I", "gameNum", "number"]:
        val = game_data.get(key)
        if val is not None:
            try:
                num_int = int(val)
                if 1 <= num_int <= 1440:
                    calculated_num = num_int
                    break
            except ValueError:
                pass

    # 2. Если явного номера нет — считаем по стартовому времени БК (S)
    if calculated_num is None:
        start_time = game_data.get("S") or game_data.get("startDate") or game_data.get("S_T")
        calculated_num = get_utc_game_number(start_time)

    # 3. Синхронизация по последовательности ID
    if last_known_game_id is not None and current_id is not None:
        try:
            id_diff = int(current_id) - int(last_known_game_id)
            # Если это следующая по порядку игра (+1 по ID)
            if id_diff == 1 and last_assigned_game_num is not None:
                calculated_num = normalize_game_num(last_assigned_game_num + 1)
            elif id_diff > 1 and last_assigned_game_num is not None:
                calculated_num = normalize_game_num(last_assigned_game_num + id_diff)
        except ValueError:
            pass

    if current_id:
        last_known_game_id = int(current_id) if str(current_id).isdigit() else current_id
    
    last_assigned_game_num = calculated_num
    return calculated_num


# --- КАРТЫ И ЛОГИКА ---

def get_card_symbol(card_value, suit_code):
    suits = {0: "♠️", 1: "♣️", 2: "♦️", 3: "♥️"}
    values = {1: "A", 14: "A", 2: "2", 3: "3", 4: "4", 5: "5", 6: "6", 7: "7", 8: "8", 9: "9", 10: "10", 11: "J", 12: "Q", 13: "K"}
    return f"{values.get(card_value, '?')}{suits.get(suit_code, '?')}"

def parse_cards_detail(cards_str):
    try:
        cards = json.loads(cards_str)
        symbols, values = [], []
        for c in cards:
            cv, cs = c.get("CV", 0), c.get("CS", 0)
            symbols.append(get_card_symbol(cv, cs))
            values.append(cv)
        return symbols, values
    except Exception:
        return [], []

def get_prediction_for_card(card_value):
    """Определяет прогнозируемое значение на основе первой карты Игрока"""
    if card_value == 6:
        return 13, "K (Король)"
    elif card_value in [10, 7, 9]:
        return 12, "Q (Дама)"
    elif card_value == 8:
        return 11, "J (Валет)"
    else:
        return 1, "A (Туз)"


# --- УПРАВЛЕНИЕ ПРОГНОЗАМИ В TELEGRAM ---

def send_new_prediction(trigger_num, symbol, target_num):
    """Создает новый пост с прогнозом"""
    if not PREDICTION_CHANNEL_ID:
        return
    
    dogen = current_prediction["dogen_level"]
    
    msg = f"Игра №{target_num}\n"
    msg += f"Значение: {symbol}\n"
    msg += f"Догон: {dogen}\n"
    msg += f"Результат:"

    try:
        sent = bot.send_message(PREDICTION_CHANNEL_ID, msg)
        current_prediction["message_id"] = sent.message_id
        current_prediction["trigger_game_num"] = trigger_num
        current_prediction["target_game_num"] = target_num
        current_prediction["predicted_symbol"] = symbol
        current_prediction["is_active"] = True
        print(f"🎯 Опубликован прогноз на игру №{target_num} ({symbol})")
    except Exception as e:
        print(f"❌ Ошибка отправки прогноза: {e}")

def check_prediction_for_game(player_values, dealer_values):
    """Проверяет наличие карты в зашедшей игре"""
    predicted = current_prediction.get("predicted_value")
    if not predicted:
        return False
    
    all_values = player_values + dealer_values
    for val in all_values:
        if predicted == 1 and val in [1, 14]:
            return True
        if val == predicted:
            return True
    return False

def finalize_prediction(status_code):
    """
    Завершает прогноз.
    status_code: 
      0  -> ✅0️⃣ (заход в целевой игре)
      1  -> ✅1️⃣ (заход в целевой + 1)
      2  -> ✅2️⃣ (заход в целевой + 2)
      -1 -> ❌ (минус)
    """
    if not current_prediction.get("message_id"):
        return
    
    target_num = current_prediction["target_game_num"]
    symbol = current_prediction["predicted_symbol"]
    dogen = current_prediction["dogen_level"]

    if status_code == 0:
        res_str = "✅0️⃣"
    elif status_code == 1:
        res_str = "✅1️⃣"
    elif status_code == 2:
        res_str = "✅2️⃣"
    else:
        res_str = "❌"

    msg = f"Игра №{target_num}\n"
    msg += f"Значение: {symbol}\n"
    msg += f"Догон: {dogen}\n"
    msg += f"Результат: {res_str}"

    try:
        bot.edit_message_text(
            chat_id=PREDICTION_CHANNEL_ID,
            message_id=current_prediction["message_id"],
            text=msg
        )
        print(f"📌 Прогноз №{target_num} рассчитан: {res_str}")
    except Exception as e:
        print(f"❌ Ошибка обновления прогноза: {e}")

    if status_code >= 0:
        current_prediction["dogen_level"] = 1
    else:
        current_prediction["dogen_level"] *= 2

    current_prediction["is_active"] = False
    current_prediction["message_id"] = None


# --- СБОР ДАННЫХ ---

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


# --- ОСНОВНОЙ ЦИКЛ ---

def main():
    global active_games, game_history, current_prediction
    print("🚀 Запуск: трансляция + синхронизированная нумерация по ID...")
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
                    print(f"🆕 Начата игра #{game_num} (ID в базе: {game_id})")
                
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
                p1_cards, p1_values = parse_cards_detail(stat.get("P1", "[]"))
                p2_cards, p2_values = parse_cards_detail(stat.get("P2", "[]"))
                
                is_finished = (status == "Игра завершена")
                
                # --- ОБРАБОТКА ЗАВЕРШЕННОЙ ИГРЫ ---
                if is_finished and game_num not in game_history:
                    first_card = p1_values[0] if p1_values else None
                    
                    game_history[game_num] = {
                        "player_first_card": first_card,
                        "player_values": p1_values,
                        "dealer_values": p2_values
                    }
                    
                    if len(game_history) > 50:
                        oldest = min(game_history.keys())
                        del game_history[oldest]
                    
                    print(f"📝 Игра #{game_num} завершена, первая карта Игрока: {first_card}")
                    
                    # 1. ПРОВЕРКА ТЕКУЩЕГО АКТИВНОГО ПРОГНОЗА
                    if current_prediction.get("is_active"):
                        target_num = current_prediction["target_game_num"]
                        plus_1_num = normalize_game_num(target_num + 1)
                        plus_2_num = normalize_game_num(target_num + 2)

                        is_hit = check_prediction_for_game(p1_values, p2_values)

                        if game_num == target_num:
                            if is_hit:
                                finalize_prediction(0)
                        elif game_num == plus_1_num:
                            if is_hit:
                                finalize_prediction(1)
                        elif game_num == plus_2_num:
                            if is_hit:
                                finalize_prediction(2)
                            else:
                                finalize_prediction(-1)
                    
                    # 2. СОЗДАНИЕ НОВОГО ПРОГНОЗА
                    if first_card and not current_prediction.get("is_active"):
                        pred_val, pred_sym = get_prediction_for_card(first_card)
                        target_num = normalize_game_num(game_num + 3)
                        
                        current_prediction["predicted_value"] = pred_val
                        send_new_prediction(game_num, pred_sym, target_num)
                
                # --- ТРАНСЛЯЦИЯ В ТЕЛЕГРАМ-КАНАЛ ---
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
                            tags.append("#O🔵")
                        if (len(p1_values) == 2 and all(v in (1, 14) for v in p1_values)) or (len(p2_values) == 2 and all(v in (1, 14) for v in p2_values)):
                            tags.append("#G🔴")
                        if len(p1_cards) == 2 and len(p2_cards) == 2:
                            tags.append("#R🟢")
                        
                        tags_str = f" {' '.join(tags)}" if tags else ""
                        msg = f"#N{game_num}. {res_p1}{p1_score}({cards_p1}) - {res_p2}{p2_score}({cards_p2}) #T{total_points}{tags_str}"
                    
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
            
            # Очистка памяти
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
