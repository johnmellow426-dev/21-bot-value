import os
import re
import asyncio
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from aiogram.enums import ChatMemberStatus

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Загрузка переменных окружения
TOKEN = os.getenv("BOT_TOKEN")
SOURCE = int(os.getenv("SOURCE_CHANNEL"))
TARGET = int(os.getenv("TARGET_CHANNEL"))

# Глобальные переменные
bot = Bot(TOKEN)
dp = Dispatcher()
games = {}
pending = {}

# ============================================================
# ПРОВЕРКА КАНАЛОВ ПРИ ЗАПУСКЕ
# ============================================================
async def check_channels():
    """Проверяет доступ бота к каналам при запуске"""
    print("\n" + "="*60)
    print("🔍 ПРОВЕРКА ДОСТУПА К КАНАЛАМ")
    print("="*60)
    
    try:
        me = await bot.get_me()
        print(f"✅ Бот подключен: @{me.username} (ID: {me.id})")
    except Exception as e:
        print(f"❌ ОШИБКА: Не удалось подключиться к боту. Проверьте BOT_TOKEN.")
        print(f"   Детали: {e}")
        return False
    
    # Проверка SOURCE канала
    print(f"\n📡 Проверка SOURCE канала (ID: {SOURCE})...")
    try:
        source_member = await bot.get_chat_member(chat_id=SOURCE, user_id=me.id)
        print(f"   Статус: {source_member.status}")
        
        if source_member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR]:
            print("   ✅ Бот является администратором SOURCE канала")
        elif source_member.status == ChatMemberStatus.MEMBER:
            print("   ⚠️  ВНИМАНИЕ: Бот подписан на канал, но НЕ является администратором!")
            print("   👉 Бот НЕ будет получать обновления постов.")
            print("   👉 Решение: Добавьте бота в администраторы канала.")
            return False
        elif source_member.status == ChatMemberStatus.LEFT:
            print("   ❌ Бот НЕ состоит в SOURCE канале!")
            return False
        else:
            print(f"   ❌ Неизвестный статус: {source_member.status}")
            return False
            
    except Exception as e:
        print(f"   ❌ ОШИБКА при проверке SOURCE канала: {e}")
        print("   💡 Возможные причины:")
        print("      1. Неверный ID канала (должен начинаться с -100)")
        print("      2. Бот не добавлен в канал")
        print("      3. Бот заблокирован в канале")
        return False
    
    # Проверка TARGET канала
    print(f"\n📢 Проверка TARGET канала (ID: {TARGET})...")
    try:
        target_member = await bot.get_chat_member(chat_id=TARGET, user_id=me.id)
        print(f"   Статус: {target_member.status}")
        
        if target_member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR]:
            print("   ✅ Бот является администратором TARGET канала")
        else:
            print("   ⚠️  Бот НЕ является администратором TARGET канала!")
            print("   👉 Бот не сможет отправлять сообщения в этот канал.")
            return False
            
    except Exception as e:
        print(f"   ❌ ОШИБКА при проверке TARGET канала: {e}")
        return False
    
    print("\n" + "="*60)
    print("✅ ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ УСПЕШНО!")
    print("="*60 + "\n")
    return True

# ============================================================
# ОСНОВНАЯ ЛОГИКА
# ============================================================

def opposite_suit(s):
    """Преобразует масть в противоположную"""
    mapping = {'♥':'♠','♠':'♥','♦':'♣','♣':'♦'}
    result = mapping.get(s, s)
    print(f"   🎨 opposite_suit: '{s}' → '{result}'")
    return result

@dp.channel_post()
async def on_channel_post(msg: types.Message):
    """Обработчик новых постов в канале"""
    print(f"\n{'='*60}")
    print(f"📨 ПОЛУЧЕН НОВЫЙ ПОСТ")
    print(f"   Chat ID: {msg.chat.id}")
    print(f"   Текст: {msg.text!r}")
    print(f"{'='*60}")
    
    # Проверка, что пост из нужного канала
    if msg.chat.id != SOURCE:
        print(f"   ❌ Пропущен: это не SOURCE канал (ожидался {SOURCE})")
        return
    
    if not msg.text:
        print(f"   ❌ Пропущен: нет текста в посте")
        return
    
    # Парсинг текста
    print(f"   🔍 Пытаюсь распарсить текст...")
    m = re.search(r'#N(\d+)\.\s*\d+\((.*?)\)', msg.text)
    
    if not m:
        print(f"   ❌ Regex не сработал!")
        print(f"   💡 Ожидаемый формат: #N1234. 56(A♠K♥)")
        print(f"   💡 Проверьте, что формат постов в канале точно соответствует шаблону")
        return
    
    # Извлечение данных
    n = int(m.group(1))
    cards_text = m.group(2).replace('️','')  # Удаляем невидимые символы
    cards = re.findall(r'([0-9AJQK]+)([♠♥♦♣])', cards_text)
    
    print(f"   ✅ Распознано:")
    print(f"      Номер игры: {n}")
    print(f"      Карты: {cards}")
    
    # Сохранение в память
    games[n] = cards
    print(f"   💾 Сохранено в games[{n}]")
    
    # Проверка на конец суток
    if n == 1440:
        print(f"   🔄 Достигнута игра #1440 - сбрасываю сутки")
        await reset_daily()
    
    # Попытка сделать прогноз
    print(f"   🎯 Пытаюсь сделать прогноз для игры #{n}...")
    await try_predict(n)
    
    # Проверка активных прогнозов
    print(f"   🔎 Проверяю активные прогнозы...")
    await check_pending(n)

async def try_predict(n):
    """Пытается сделать прогноз на основе текущей игры"""
    print(f"\n   [try_predict] Анализ для игры #{n}")
    
    # Проверка наличия данных
    if n not in games:
        print(f"      ❌ Игра #{n} не найдена в games")
        return
    
    if n-4 not in games:
        print(f"      ❌ Игра #{n-4} не найдена в games (нужна история из 5 игр)")
        return
    
    # Проверка количества карт
    if len(games[n]) < 2:
        print(f"      ❌ В игре #{n} меньше 2 карт ({len(games[n])})")
        return
    
    if len(games[n-4]) < 2:
        print(f"      ❌ В игре #{n-4} меньше 2 карт ({len(games[n-4])})")
        return
    
    # Проверка условия на картинку
    rank, suit = games[n][1]
    print(f"      📊 Вторая карта игры #{n}: {rank}{suit}")
    
    if rank not in 'AKQJ':
        print(f"      ❌ Вторая карта не является картинкой (A/K/Q/J)")
        return
    
    print(f"      ✅ Условие выполнено: вторая карта - картинка ({rank})")
    
    # Формирование прогноза
    s = games[n-4][1][1]
    opp_s = opposite_suit(s)
    
    target = n+3 if n+3 <= 1440 else (n+3) - 1440
    end_check = target+2 if target+2 <= 1440 else (target+2) - 1440
    
    print(f"      🎲 Формирую прогноз:")
    print(f"         Масть из игры #{n-4}: {s}")
    print(f"         Противоположная масть: {opp_s}")
    print(f"         Целевая игра: #{target}")
    print(f"         Диапазон проверки: #{target} - #{end_check}")
    
    text = (
        f"💎 #{target} → {s}{opp_s}\n"
        f"⏳ Диапазон: #{target} - #{end_check}\n"
        f"⚡ Догон 2"
    )
    
    # Отправка сообщения
    try:
        print(f"      📤 Отправляю прогноз в TARGET канал...")
        sent = await bot.send_message(TARGET, text)
        print(f"      ✅ Сообщение отправлено (message_id: {sent.message_id})")
        
        pending[target] = {
            "rank": rank,
            "msg_id": sent.message_id,
            "text": text,
            "target": target,
            "done": set()
        }
        print(f"      💾 Прогноз сохранен в pending[{target}]")
    except Exception as e:
        print(f"      ❌ ОШИБКА при отправке сообщения: {e}")

async def check_pending(n):
    """Проверяет активные прогнозы на текущую игру"""
    print(f"\n   [check_pending] Проверка прогнозов для игры #{n}")
    
    for t, info in list(pending.items()):
        check_range = [(t+i-1440 if t+i>1440 else t+i) for i in range(3)]
        print(f"      🔎 Прогноз #{t}: диапазон {check_range}")
        
        if n in check_range and n not in info["done"]:
            info["done"].add(n)
            print(f"         ➕ Добавляю игру #{n} в проверенные")
            
            if n in games:
                has_rank = any(c[0] == info["rank"] for c in games[n])
                print(f"         🃏 Проверяю наличие карты {info['rank']} в игре #{n}: {has_rank}")
                
                if has_rank:
                    result = f"✅ Зашел на #{n} [Основная игра ⚡]"
                    print(f"         🎉 ПОПАЛ! Редактирую сообщение...")
                    await bot.edit_message_text(
                        chat_id=TARGET,
                        message_id=info["msg_id"],
                        text=info["text"] + "\n\n" + result
                    )
                    pending.pop(t)
                    print(f"         ✅ Прогноз #{t} удален из pending")
                    return
            else:
                print(f"         ⚠️  Игра #{n} не найдена в games")
        
        if len(info["done"]) >= 3 and t in pending:
            result = f"❌ Не зашел [Догон ❌]"
            print(f"         ❌ Прогноз #{t} не сработал (проверено 3 игры)")
            await bot.edit_message_text(
                chat_id=TARGET,
                message_id=info["msg_id"],
                text=info["text"] + "\n\n" + result
            )
            pending.pop(t)
            print(f"         ✅ Прогноз #{t} удален из pending")

async def reset_daily():
    """Сбрасывает все данные в конце суток"""
    print(f"\n   [reset_daily] Сброс суточной статистики")
    
    for t, info in list(pending.items()):
        try:
            await bot.edit_message_text(
                chat_id=TARGET,
                message_id=info["msg_id"],
                text=info["text"] + "\n\n⏰ СУТОК ПРОШЛИ"
            )
            print(f"      ✅ Прогноз #{t} закрыт")
        except Exception as e:
            print(f"      ❌ Ошибка при закрытии прогноза #{t}: {e}")
        pending.pop(t)
    
    games.clear()
    print(f"      🗑️  Очищена память games")

@dp.message(CommandStart())
async def cmd_start(msg: types.Message):
    """Обработчик команды /start"""
    await msg.answer("Бот запущен! Ожидаю игры...")

async def main():
    """Главная функция запуска бота"""
    print("\n" + "="*60)
    print("🚀 ЗАПУСК БОТА")
    print("="*60)
    
    # Проверка каналов
    if not await check_channels():
        print("\n❌ ПРОВЕРКА КАНАЛОВ НЕ ПРОЙДЕНА. Бот остановлен.")
        await bot.session.close()
        return
    
    print("🎧 Бот запущен и слушает обновления...")
    print("   Нажмите Ctrl+C для остановки\n")
    
    await bot.delete_webhook()
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n👋 Бот остановлен пользователем")
    except Exception as e:
        print(f"\n\n❌ КРИТИЧЕСКАЯ ОШИБКА: {e}")
        import traceback
        traceback.print_exc()
