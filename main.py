import requests
import time
import json
import telebot
import os

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
VIRTUAL_URL = os.getenv("VIRTUAL_URL", "https://melbet-8093.pro/cyber-api/mainfeedlive/web/cyber/v3/leftmenu/virtual?champIds=1643503&country=192&fcountry=192&gr=1521&lng=ru&ref=8&sportIds=146")
STATISTIC_URL_TEMPLATE = os.getenv("STATISTIC_URL_TEMPLATE", "https://melbet-8093.pro/cyber-api/mainfeedlive/web/cyber/v3/statistic?country=192&fcountry=192&gameId={game_id}&gr=1521&lng=ru&ref=8")

bot = telebot.TeleBot(BOT_TOKEN)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://melbet-8093.pro/",
    "Origin": "https://melbet-8093.pro",
    "Connection": "keep-alive",
}

current_game_id = None
last_update_state = ""

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

def get_active_game_id(session):
    """Универсальный поиск ID активной игры в любом формате JSON"""
    try:
        resp = session.get(VIRTUAL_URL, headers=HEADERS, timeout=10)
        data = resp.json()
        
        # 1. Если ответ - это сразу список игр
        if isinstance(data, list):
            games_list = data
        # 2. Если ответ - словарь, ищем знакомые ключи
        elif isinstance(data, dict):
            games_list = data.get("games", data.get("events", data.get("data", [])))
            if isinstance(games_list, dict):
                games_list = list(games_list.values())
        else:
            print(f"⚠️ Неожиданный формат: {type(data)}")
            return None

        # Ищем игру, которая УЖЕ идет (nonStarted == False)
        for game in games_list:
            if isinstance(game, dict) and not game.get("nonStarted", True):
                return game.get("id")
        
        # Если все игры еще не начались, берем последнюю в списке (следующую)
        if games_list and isinstance(games_list[-1], dict):
            return games_list[-1].get("id")
            
        return None
    except Exception as e:
        print(f"❌ Ошибка парсинга списка игр: {e}")
        return None

def main():
    global current_game_id, last_update_state
    print("🎮 Автоматическая трансляция запущена...")
    session = requests.Session()
    
    while True:
        try:
            active_id = get_active_game_id(session)
            
            if not active_id:
                print("⏳ Активных игр не найдено, жду...")
                time.sleep(5)
                continue
                
            if active_id != current_game_id:
                current_game_id = active_id
                last_update_state = ""
                print(f"🔄 Найдена новая игра! ID: {active_id}")

            stat_url = STATISTIC_URL_TEMPLATE.format(game_id=active_id)
            resp = session.get(stat_url, headers=HEADERS, timeout=10)
            
            if resp.status_code == 204 or not resp.text.strip():
                print("⏳ Игра архивирована или еще не началась, жду...")
                time.sleep(3)
                continue

            data = resp.json()
            game_num = data.get("num", "?")
            status = data.get("currentPeriodName", "")
            score_detail = data.get("fullScoreDetail", {})
            p1_score = score_detail.get("scoreOpp1", 0)
            p2_score = score_detail.get("scoreOpp2", 0)
            timer_sec = data.get("timer", {}).get("timeSec", 0)
            
            stat = data.get("statistic", {}).get("main", {})
            p1_cards = parse_cards_detail(stat.get("P1", "[]"))
            p2_cards = parse_cards_detail(stat.get("P2", "[]"))
            
            is_finished = (status == "Игра завершена")
            current_state = f"{game_num}_{p1_score}_{p2_score}_{'_'.join(p1_cards)}_{'_'.join(p2_cards)}_{is_finished}"
            
            if current_state != last_update_state and (p1_cards or p2_cards):
                cards_p1 = " ".join(p1_cards) if p1_cards else "?"
                cards_p2 = " ".join(p2_cards) if p2_cards else "?"
                
                if is_finished:
                    msg = f"✅ #N{game_num}. {p1_score}({cards_p1}) - {p2_score}({cards_p2}) #T{timer_sec} #O🔵"
                else:
                    msg = f"🕒 #N{game_num}. {p1_score}({cards_p1}) 👈 {p2_score}({cards_p2}) #T{timer_sec}"
                
                bot.send_message(CHANNEL_ID, msg)
                print(f"✅ Отправлено: {msg}")
                
                last_update_state = current_state
                
                if is_finished:
                    print("🏁 Игра завершена, ожидаю следующую...")
                    time.sleep(5)
            
            time.sleep(2)
            
        except requests.exceptions.Timeout:
            print("❌ Таймаут запроса")
            time.sleep(5)
        except Exception as e:
            print(f"❌ Ошибка: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
