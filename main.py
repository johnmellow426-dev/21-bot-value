import os
import re
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher, types
from aiogram.types import Message
import uvicorn

# === НАСТРОЙКИ ===
TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("RAILWAY_PUBLIC_DOMAIN")
SOURCE = int(os.getenv("SOURCE_CHANNEL"))
TARGET = int(os.getenv("TARGET_CHANNEL"))

bot = Bot(TOKEN)
dp = Dispatcher()

games = {}
pending = {}

def opposite_suit(s):
    return {'♠':'♥','♥':'♠','♦':'♣','♣':'♦'}[s]

@dp.channel_post()
async def on_channel_post(msg: Message):
    if msg.chat.id != SOURCE or not msg.text:
        return
    
    m = re.search(r'#N(\d+)\.\s*\d+\((.*?)\)', msg.text)
    if not m:
        return
    
    n = int(m.group(1))
    cards = re.findall(r'([0-9AJQK]+)([♠♥♦♣])', m.group(2).replace('️',''))
    games[n] = cards
    
    # Сброс при 1440
    if n == 1440:
        await reset_daily()
    
    # Прогноз
    await try_predict(n)
    
    # Проверка ожидающих
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
        f"<code>💎 #{target} → {s}{opp_s} ИГРОК\n"
        f"⏳ Диапазон: #{target} - #{end_check}\n"
        f"⚡ Догон 2</code>"
    )
    
    sent = await bot.send_message(TARGET, text, parse_mode="HTML")
    pending[target] = {
        "rank": rank,
        "msg_id": sent.message_id,
        "text": text,
        "target": target,
        "done": set()
    }

async def check_pending(n):
    for t, info in list(pending.items()):
        check_range = [t, t+1, t+2]
        check_range = [(x-1440 if x > 1440 else x) for x in check_range]
        
        if n in check_range and n not in info["done"]:
            info["done"].add(n)
            if n in games and any(c[0] == info["rank"] for c in games[n]):
                result_text = f"<code>✅ Зашел на #{n} [Основная игра ⚡]</code>"
                await bot.edit_message_text(
                    TARGET, 
                    info["msg_id"], 
                    info["text"] + "\n\n" + result_text, 
                    parse_mode="HTML"
                )
                pending.pop(t)
                return
        
        if len(info["done"]) >= 3 and t in pending:
            result_text = f"<code>❌ Не зашел [Догон ❌]</code>"
            await bot.edit_message_text(
                TARGET, 
                info["msg_id"], 
                info["text"] + "\n\n" + result_text, 
                parse_mode="HTML"
            )
            pending.pop(t)

async def reset_daily():
    for t, info in list(pending.items()):
        result_text = f"<code> СУТОК ПРОШЛИ</code>"
        await bot.edit_message_text(
            TARGET, 
            info["msg_id"], 
            info["text"] + "\n\n" + result_text, 
            parse_mode="HTML"
        )
        pending.pop(t)
    games.clear()

# === FASTAPI + WEBHOOK ===
@asynccontextmanager
async def lifespan(app: FastAPI):
    webhook_url = f"https://{WEBHOOK_URL}/webhook"
    await bot.set_webhook(webhook_url)
    yield
    await bot.delete_webhook()

app = FastAPI(lifespan=lifespan)

@app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()
    update = types.Update(**data)
    await dp.feed_update(bot, update)
    return {"ok": True}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
