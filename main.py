import os
import re
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart

TOKEN = os.getenv("BOT_TOKEN")
SOURCE = int(os.getenv("SOURCE_CHANNEL"))
TARGET = int(os.getenv("TARGET_CHANNEL"))

bot = Bot(TOKEN)
dp = Dispatcher()

games = {}
pending = {}

def opposite_suit(s):
    return {'':'♥','♥':'♠','♦':'♣','♣':'♦'}[s]

@dp.channel_post()
async def on_channel_post(msg: types.Message):
    if msg.chat.id != SOURCE or not msg.text:
        return
    
    m = re.search(r'#N(\d+)\.\s*\d+\((.*?)\)', msg.text)
    if not m:
        return
    
    n = int(m.group(1))
    cards = re.findall(r'([0-9AJQK]+)([♠♥♦♣])', m.group(2).replace('️',''))
    games[n] = cards
    
    if n == 1440:
        await reset_daily()
    
    await try_predict(n)
    await check_pending(n)

async def try_predict(n):
    if n not in games or n-4 not in games:
        return
    if len(games[n]) < 2 or len(games[n-4]) < 2:
        return
    
    rank, _ = games[n][1]
    if rank not in 'AKQJ':
        return
    
    s = games[n-4][1][1]
    opp_s = opposite_suit(s)
    target = n+3 if n+3 <= 1440 else (n+3) - 1440
    end_check = target+2 if target+2 <= 1440 else (target+2) - 1440
    
    text = (
        f"💎 #{target} → {s}{opp_s}\n"
        f"⏳ Диапазон: #{target} - #{end_check}\n"
        f"⚡ Догон 2"
    )
    
    sent = await bot.send_message(TARGET, text)
    pending[target] = {
        "rank": rank,
        "msg_id": sent.message_id,
        "text": text,
        "target": target,
        "done": set()
    }

async def check_pending(n):
    for t, info in list(pending.items()):
        check_range = [(t+i-1440 if t+i>1440 else t+i) for i in range(3)]
        
        if n in check_range and n not in info["done"]:
            info["done"].add(n)
            if n in games and any(c[0] == info["rank"] for c in games[n]):
                result = f"✅ Зашел на #{n} [Основная игра ⚡]"
                await bot.edit_message_text(TARGET, info["msg_id"], info["text"] + "\n\n" + result)
                pending.pop(t)
                return
        
        if len(info["done"]) >= 3 and t in pending:
            result = f"❌ Не зашел [Догон ❌]"
            await bot.edit_message_text(TARGET, info["msg_id"], info["text"] + "\n\n" + result)
            pending.pop(t)

async def reset_daily():
    for t, info in list(pending.items()):
        await bot.edit_message_text(TARGET, info["msg_id"], info["text"] + "\n\n⏰ СУТОК ПРОШЛИ")
        pending.pop(t)
    games.clear()

@dp.message(CommandStart())
async def cmd_start(msg: types.Message):
    await msg.answer("Бот запущен! Ожидаю игры...")

async def main():
    await bot.delete_webhook()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
