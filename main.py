import requests
import time
import json
import telebot
import os

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

current_game_id = None
current_game_num = None  # Номер игры из gamesByChamp
last_update_state = ""
total_counter = 0  # Счетчик тоталов/раундов

def get_card_symbol(card_value, suit_code):
    suits = {0: "♠️", 1: "♣️", 2: "♦️", 3: "♥️"}
    values = {1: "A", 2: "2", 3: "3", 4: "4", 5: "5", 6: "6", 7: "7", 8: "8", 9: "9", 10: "10", 11: "J", 12: "Q", 13: "K"}
    return f"{values.get(card_value, '?')}{suits.get(suit_code, '?')}"

def parse_cards_detail(cards_str):
    try:
        cards = json.loads(cards_str)
        return [get_card_symbol(c.get("CV", 0), c.get("CS", 0)) for c in cards]
    except Exception:
        return []

def get_active_game_info(session):
    """Возвращает ID и номер текущей игры"""
    try:
        resp = session.get(VIRTUAL_URL, headers=HEADERS, timeout=10)
        data = resp.json()
        games = data.get("games", [])
        if not isinstance(games, list) or not games:
            return None, None
        
        first_game = games[0]
        if isinstance(first_game, dict):
            return first_game.get("id"), first_game.get("num")
        return None, None
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return None, None

def main():
    global current_game_id, current_game_num, last_update_state, total_counter
    print("🎮 Трансляция запущена...")
    session = requests.Session()
    
    while True:
        try:
            active_id, active_num = get_active_game_info(session)
            
            if not active_id:
                time.sleep(5)
                continue
            
            # Если новая игра - сбрасываем счетчик тоталов
            if active_id != current_game_id:
                current_game_id = active_id
                current_game_num = active_num
                last_update_state = ""
                total_counter = 0
                print(f"🔄 Новая игра #{active_num} (ID: {active_id})")
            
            # Получаем статистику
            stat_url = STATISTIC_URL_TEMPLATE.format(game_id=active_id)
            resp = session.get(stat_url, headers=HEADERS, timeout=10)
            
            if resp.status_code == 204 or not resp.text.strip():
                time.sleep(3)
                continue
            
            data = resp.json()
            score_detail = data.get("fullScoreDetail", {})
            p1_score = score_detail.get("scoreOpp1", 0)
            p2_score = score_detail.get("scoreOpp2", 0)
            status = data.get("currentPeriodName", "")
            
            stat = data.get("statistic", {}).get("main", {})
            p1_cards = parse_cards_detail(stat.get("P1", "[]"))
            p2_cards = parse_cards_detail(stat.get("P2", "[]"))
            
            is_finished = (status == "Игра завершена")
            current_state = f"{p1_score}_{p2_score}_{'_'.join(p1_cards)}_{'_'.join(p2_cards)}_{is_finished}"
            
            if current_state != last_update_state and (p1_cards or p2_cards):
                total_counter += 1
                cards_p1 = " ".join(p1_cards) if p1_cards else "?"
                cards_p2 = " ".join(p2_cards) if p2_cards else "?"
                
                # Формат сообщения по вашему примеру
                if is_finished:
                    # Определяем результат
                    if p1_score > 21 and p2_score > 21:
                        result = "🔰"  # Ничья (оба перебор)
                    elif p1_score == p2_score:
                        result = "🔰"  # Ничья
                    elif (p1_score <= 21 and p1_score > p2_score) or (p2_score > 21):
                        result = "✅"  # Игрок выиграл
                    else:
                        result = "✅"  # Дилер выиграл (можно добавить другой символ)
                    
                    msg = f"#N{current_game_num}. {result}{p1_score}({cards_p1}) - {p2_score}({cards_p2}) #T{total_counter*10} #O🔵"
                else:
                    # Определяем кто добирает
                    if p1_score < 17:
                        arrow = "◀️"  # Добирает Игрок
                    elif p2_score < 17:
                        arrow = "▶️"  # Добирает Дилер
                    else:
                        arrow = "👈"
                    
                    msg = f"🕒 #N{current_game_num}. {p1_score}({cards_p1}) {arrow} {p2_score}({cards_p2}) #T{total_counter*10}"
                
                bot.send_message(CHANNEL_ID, msg)
                print(f"✅ {msg}")
                
                last_update_state = current_state
                
                if is_finished:
                    time.sleep(5)
            
            time.sleep(2)
            
        except Exception as e:
            print(f"❌ Ошибка: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
