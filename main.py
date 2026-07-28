import requests
import time
import json
import telebot
import os
import datetime

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
VIRTUAL_URL = os.getenv("VIRTUAL_URL", "https://melbet-8093.pro/cyber-api/mainfeedlive/web/cyber/v3/gamesByChamp?cfView=3&champId=1643503&country=192&fcountry=192&gr=1521&lng=ru&ref=8")
STATISTIC_URL_TEMPLATE = os.getenv("STATISTIC_URL_TEMPLATE", "https://melbet-8093.pro/cyber-api/mainfeedlive/web/cyber/v3/statistic?country=192&fcountry=192&gameId={game_id}&gr=1521&lng=ru&ref=8")

bot = telebot.TeleBot(BOT_TOKEN)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://melbet-8093.pro/",
}

# Состояние
current_game_id = None
current_game_num = None  # Номер игры (кешируется при старте)
current_message_id = None
last_update_state = ""

def get_utc_game_number():
    """00:00 → 1, 23:59 → 1440"""
    now = datetime.datetime.now(datetime.timezone.utc)
    return (now.hour * 60) + now.minute + 1

def get_card_symbol(card_value, suit_code):
    suits = {0: "♠️", 1: "♣️", 2: "♦️", 3: "♥️"}
    # Туз может приходить как 1 или 14 — обрабатываем оба варианта
    values = {
        1: "A", 14: "A",
        2: "2", 3: "3", 4: "4", 5: "5", 6: "6", 7: "7", 8: "8", 9: "9", 10: "10",
        11: "J", 12: "Q", 13: "K"
    }
    suit = suits.get(suit_code, "?")
    value = values.get(card_value)
    if value is None:
        print(f"️ Неизвестный код карты: CV={card_value}, CS={suit_code}")
        value = str(card_value)
    return f"{value}{suit}"

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
    except Exception as e:
        print(f"❌ Ошибка парсинга карт: {e}, raw={cards_str[:100]}")
        return [], []

def get_active_game_id(session):
    try:
        resp = session.get(VIRTUAL_URL, headers=HEADERS, timeout=10)
        data = resp.json()
        games = data.get("games", [])
        if not isinstance(games, list) or not games:
            return None
        first_game = games[0]
        if isinstance(first_game, dict) and "id" in first_game:
            return first_game["id"]
        return None
    except Exception as e:
        print(f" Ошибка получения списка игр: {e}")
        return None

def send_or_edit_message(msg, is_finished):
    global current_message_id
    try:
        if current_message_id is None:
            sent = bot.send_message(CHANNEL_ID, msg, parse_mode=None)
            current_message_id = sent.message_id
            print(f"📤 Создано новое сообщение, ID={current_message_id}")
        else:
            bot.edit_message_text(
                chat_id=CHANNEL_ID,
                message_id=current_message_id,
                text=msg,
                parse_mode=None
            )
            print(f"✏️ Отредактировано сообщение ID={current_message_id}")
        
        # Сбрасываем ID только после финального редактирования завершённой игры
        if is_finished:
            print(f"🏁 Игра завершена, сбрасываем message_id для следующей игры")
            current_message_id = None
    except telebot.apihelper.ApiTelegramException as e:
        print(f"❌ Telegram API ошибка: {e}. Сбрасываем message_id.")
        current_message_id = None
        # Пробуем отправить как новое
        try:
            sent = bot.send_message(CHANNEL_ID, msg, parse_mode=None)
            current_message_id = sent.message_id if not is_finished else None
        except Exception as e2:
            print(f"❌ Повторная отправка тоже не удалась: {e2}")
    except Exception as e:
        print(f"❌ Ошибка отправки/редактирования: {e}")
        current_message_id = None

def main():
    global current_game_id, current_game_num, last_update_state
    print("🎮 Трансляция запущена (исправлены туз, редактирование, нумерация)...")
    session = requests.Session()
    
    while True:
        try:
            active_id = get_active_game_id(session)
            
            if not active_id:
                time.sleep(5)
                continue
            
            # Если новая игра — сбрасываем всё и кешируем номер
            if active_id != current_game_id:
                current_game_id = active_id
                current_game_num = get_utc_game_number()  # Кешируем номер на старте
                last_update_state = ""
                current_message_id = None
                print(f"🔄 Новая игра #{current_game_num} (ID: {active_id})")

            stat_url = STATISTIC_URL_TEMPLATE.format(game_id=active_id)
            resp = session.get(stat_url, headers=HEADERS, timeout=10)
            
            if resp.status_code == 204 or not resp.text.strip():
                time.sleep(5)
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
            current_state = f"{p1_score}_{p2_score}_{'_'.join(p1_cards)}_{'_'.join(p2_cards)}_{is_finished}"
            
            if current_state != last_update_state and (p1_cards or p2_cards):
                cards_p1 = " ".join(p1_cards) if p1_cards else "?"
                cards_p2 = " ".join(p2_cards) if p2_cards else "?"
                
                if not is_finished:
                    if p1_score < 17:
                        arrow = "◀️"
                    elif p2_score < 17:
                        arrow = "▶️"
                    else:
                        arrow = "👈"
                    msg = f" #N{current_game_num}. {p1_score}({cards_p1}) {arrow} {p2_score}({cards_p2}) #T{total_points}"
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
                        tags.append("#G")
                    
                    if len(p1_cards) == 2 and len(p2_cards) == 2:
                        tags.append("#R🟢")
                    
                    tags_str = " ".join(tags)
                    msg = f"#N{current_game_num}. {res_p1}{p1_score}({cards_p1}) - {res_p2}{p2_score}({cards_p2}) #T{total_points} {tags_str}".strip()
                
                send_or_edit_message(msg, is_finished)
                last_update_state = current_state
                
                if is_finished:
                    time.sleep(5)
            
            time.sleep(5)
            
        except requests.exceptions.Timeout:
            print("❌ Таймаут запроса")
            time.sleep(5)
        except Exception as e:
            print(f"❌ Ошибка: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
