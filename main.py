import requests
import time
import json
import telebot
from datetime import datetime

# --- НАСТРОЙКИ ---
BOT_TOKEN = "7595431774:AAGqVaashXulX08PEpgZHsn7LysPrV6rul0"
CHANNEL_ID = "-1003113077361"
API_URL = "https://melbet-8093.pro/cyber-api/mainfeedlive/web/cyber/v3/statistic?country=192&fcountry=192&gameId=739799539&gr=1521&lng=ru&ref=8"

bot = telebot.TeleBot(BOT_TOKEN)

# Храним состояние текущей игры
current_game = {
    "num": 0,
    "p1_score": 0,
    "p2_score": 0,
    "p1_cards": [],
    "p2_cards": [],
    "status": "",
    "timer": 0,
    "last_update": ""
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

def get_card_symbol(card_value, suit_code):
    """Преобразуем значение карты в символ с мастью"""
    suits = {0: "♠️", 1: "♣️", 2: "♦️", 3: "♥️"}
    values = {
        1: "A", 2: "2", 3: "3", 4: "4", 5: "5",
        6: "6", 7: "7", 8: "8", 9: "9", 10: "10",
        11: "J", 12: "Q", 13: "K"
    }
    suit = suits.get(suit_code, "️")
    value = values.get(card_value, str(card_value))
    return f"{value}{suit}"

def parse_cards_detail(cards_str):
    """Парсим карты с деталями (значение и масть)"""
    try:
        cards = json.loads(cards_str)
        result = []
        for card in cards:
            cv = card.get("CV", 0)  # Card Value
            cs = card.get("CS", 0)  # Card Suit
            result.append(get_card_symbol(cv, cs))
        return result
    except:
        return []

def format_message(game_num, p1_score, p2_score, p1_cards, p2_cards, status, timer, is_finished=False):
    """Форматируем сообщение для трансляции"""
    cards_p1 = " ".join(p1_cards) if p1_cards else "?"
    cards_p2 = " ".join(p2_cards) if p2_cards else "?"
    
    # Определяем кто выиграл
    if is_finished:
        if p1_score > 21 or (p2_score <= 21 and p2_score > p1_score):
            arrow = ""  # Дилер выиграл
            result = "✅"
        elif p2_score > 21 or (p1_score <= 21 and p1_score > p2_score):
            arrow = ""  # Игрок выиграл
            result = "✅"
        else:
            arrow = "🤝"  # Ничья
            result = "✅"
    else:
        arrow = "🕒"
        result = ""
    
    msg = f"{arrow} #N{game_num}. {p1_score}({cards_p1}) {'👈' if not is_finished else ''} {p2_score}({cards_p2}) #T{timer}"
    
    if is_finished:
        msg = f"{result}{msg} #O🔵"
    
    return msg

def main():
    global current_game
    print("🎮 Лайв-трансляция запущена...")
    
    while True:
        try:
            resp = requests.get(API_URL, headers=HEADERS, timeout=5)
            data = resp.json()
            
            game_num = data.get("num", 0)
            status = data.get("currentPeriodName", "")
            full_score = data.get("fullScore", "0-0")
            score_detail = data.get("fullScoreDetail", {})
            p1_score = score_detail.get("scoreOpp1", 0)
            p2_score = score_detail.get("scoreOpp2", 0)
            timer_info = data.get("timer", {})
            timer_sec = timer_info.get("timeSec", 0)
            
            # Парсим карты
            stat = data.get("statistic", {}).get("main", {})
            p1_cards_raw = stat.get("P1", "[]")
            p2_cards_raw = stat.get("P2", "[]")
            
            p1_cards = parse_cards_detail(p1_cards_raw)
            p2_cards = parse_cards_detail(p2_cards_raw)
            
            # Проверяем, изменилось ли состояние
            is_finished = (status == "Игра завершена")
            current_state = f"{game_num}_{p1_score}_{p2_score}_{'_'.join(p1_cards)}_{'_'.join(p2_cards)}"
            
            # Если новая игра или изменились карты
            if game_num != current_game["num"] or current_state != current_game["last_update"]:
                
                # Если новая игра - отправляем стартовое сообщение
                if game_num != current_game["num"] and not is_finished:
                    msg = f"🎲 **Старт игры #{game_num}**"
                    bot.send_message(CHANNEL_ID, msg, parse_mode="Markdown")
                
                # Отправляем обновление
                if p1_cards or p2_cards:  # Только если есть карты
                    msg = format_message(
                        game_num, p1_score, p2_score,
                        p1_cards, p2_cards, status, timer_sec, is_finished
                    )
                    
                    bot.send_message(CHANNEL_ID, msg)
                    print(f" Отправлено: {msg}")
                
                # Обновляем состояние
                current_game = {
                    "num": game_num,
                    "p1_score": p1_score,
                    "p2_score": p2_score,
                    "p1_cards": p1_cards,
                    "p2_cards": p2_cards,
                    "status": status,
                    "timer": timer_sec,
                    "last_update": current_state
                }
            
            time.sleep(2)  # Опрос каждые 2 секунды для лайва
            
        except Exception as e:
            print(f"❌ Ошибка: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
