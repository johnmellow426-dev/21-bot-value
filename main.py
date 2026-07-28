import requests
import time
import json
import telebot
import os

# --- НАСТРОЙКИ ИЗ ПЕРЕМЕННЫХ СРЕДЫ RAILWAY ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
# ВАЖНО: Убедитесь, что в переменной API_URL на Railway НЕТ параметра &gameId=...
API_URL = os.getenv("API_URL", "https://melbet-8093.pro/cyber-api/mainfeedlive/web/cyber/v3/statistic?country=192&fcountry=192&gr=1521&lng=ru&ref=8")

bot = telebot.TeleBot(BOT_TOKEN)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://melbet-8093.pro/",
    "Origin": "https://melbet-8093.pro",
    "Connection": "keep-alive",
}

# Глобальная переменная для хранения состояния
current_game = {"num": 0, "last_update": ""}

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

def main():
    global current_game  # Говорим Python использовать глобальную переменную
    print("🎮 Запуск трансляции...")
    session = requests.Session()
    
    while True:
        try:
            resp = session.get(API_URL, headers=HEADERS, timeout=10)
            
            # Диагностика блокировок
            if "application/json" not in resp.headers.get("Content-Type", ""):
                print(f"⚠️ БЛОКИРОВКА! Статус: {resp.status_code}")
                print(f"Ответ сервера: {resp.text[:200]}")
                time.sleep(10)
                continue

            data = resp.json()
            game_num = data.get("num", 0)
            status = data.get("currentPeriodName", "")
            score_detail = data.get("fullScoreDetail", {})
            p1_score = score_detail.get("scoreOpp1", 0)
            p2_score = score_detail.get("scoreOpp2", 0)
            
            stat = data.get("statistic", {}).get("main", {})
            p1_cards = parse_cards_detail(stat.get("P1", "[]"))
            p2_cards = parse_cards_detail(stat.get("P2", "[]"))
            
            is_finished = (status == "Игра завершена")
            current_state = f"{game_num}_{p1_score}_{p2_score}_{'_'.join(p1_cards)}"
            
            if game_num != current_game["num"] or current_state != current_game["last_update"]:
                if p1_cards or p2_cards:
                    cards_p1 = " ".join(p1_cards) if p1_cards else "?"
                    cards_p2 = " ".join(p2_cards) if p2_cards else "?"
                    arrow = "👈" if not is_finished else ""
                    result = "✅ #O🔵" if is_finished else "🕒"
                    
                    msg = f"{result} #N{game_num}. {p1_score}({cards_p1}){arrow} {p2_score}({cards_p2})"
                    bot.send_message(CHANNEL_ID, msg)
                    print(f"✅ Отправлено: {msg}")
                
                # Обновляем глобальную переменную
                current_game = {"num": game_num, "last_update": current_state}
            
            time.sleep(3)
            
        except requests.exceptions.RequestException as e:
            print(f"❌ Ошибка сети: {e}")
            time.sleep(5)
        except json.JSONDecodeError as e:
            print(f"❌ Ошибка JSON: {e}")
            time.sleep(5)
        except Exception as e:
            print(f"❌ Неизвестная ошибка: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
