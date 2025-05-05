import sys
import asyncio
import json

if sys.platform.startswith('win'):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import ccxt
import pandas as pd
import time
import os
import requests
import discord
from discord.ext import commands
from discord.ext import tasks
from ta.volatility import DonchianChannel
from ta.volume import ChaikinMoneyFlowIndicator
from dotenv import load_dotenv

load_dotenv()

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
client = discord.Client(intents=intents)

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"🔧 Synced {len(synced)} slash command(s).")
    except Exception as e:
        print(f"❌ Sync failed: {e}")

    run_strategy_loop.start()


api_key = os.getenv("API_KEY")
secret = os.getenv("SECRET_KEY")


print("You ready to get trading? 👍")
vers = "3.2.2"

exchange = ccxt.mexc({
    'apiKey': api_key,
    'secret': secret,
    'enableRateLimit': True
})

symbols = ['MOODENG/USDT', 'PIPPIN/USDT']
timeframe = '15m'
limit = 100

in_trade = False
long_trade = False
short_trade = False
profit = 0
entry_price = 0
money_available = 100
risk_percent = 0.1
profit_goal = 0.3
position_size = money_available * risk_percent
pnl_target = position_size * profit_goal

def fetch_ohlcv(symbol):
    data = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
    df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    return df

def apply_indicators(df):
    dc = DonchianChannel(high=df['high'], low=df['low'], close=df['close'], window=20)
    cmf = ChaikinMoneyFlowIndicator(high=df['high'], low=df['low'], close=df['close'], volume=df['volume'], window=20)

    df['donchian_upper'] = dc.donchian_channel_hband()
    df['donchian_lower'] = dc.donchian_channel_lband()
    df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
    df['donchian_middle'] = (df['donchian_upper'] + df['donchian_lower']) / 2
    df['cmf'] = cmf.chaikin_money_flow()

    return df

def fetch_trend(symbol):
    data = exchange.fetch_ohlcv(symbol, '1h', limit=50)
    df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
    last_close = df.iloc[-1]['close']
    last_ema = df.iloc[-1]['ema50']

    if last_close > last_ema:
        return "uptrend"
    elif last_close < last_ema:
        return "downtrend"
    else:
        return "no trend"
    
def open_trade(symbol, price):
    global in_trade, long_trade, short_trade, money_available, profit, entry_price
    entry_price = price
    try:
        if long_trade or short_trade:
            money_available -= position_size
            log_and_print(f"✅ OPEN {'Long' if long_trade else 'Short'} TRADE", symbol, price)
            in_trade = True
    except Exception as e:
        print(f"Exception in open_trade: {e}")
        
def close_trade(symbol, price):
    global in_trade, long_trade, short_trade, money_available, profit, entry_price
    
    try:
        if long_trade == True:
            profit = (price - entry_price) * (position_size / entry_price)
            long_trade = False
        elif short_trade == True: 
            profit = (entry_price - price) * (position_size / entry_price)
            short_trade = False

        money_available += position_size + profit
        log_and_print(f"🚫 CLOSE {'Long' if long_trade else 'Short'} TRADE", symbol, price, profit=profit)
        in_trade = False
    except Exception as e:
        print(f"Exception in close_trade: {e}")
    
def exit_strategy(symbol, price):
    global profit
    current_profit = 0
    if long_trade:
        current_profit = (price - entry_price) * (position_size / entry_price)
    elif short_trade:
        current_profit = (entry_price - price) * (position_size / entry_price)

    try:
        if (long_trade or short_trade) and current_profit >= pnl_target:
            log_and_print("🎯 EXIT TARGET HIT", symbol, price, profit=current_profit)
            close_trade(symbol, price)
        else:
            return "no trades at this time"
    except Exception as e:
        print(f"Exception in exit_strategy: {e}")

def log_and_print(event_type, symbol, price, score=None, profit=None):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")

    print(f"[{timestamp}] {event_type} | Symbol: {symbol} | Price: {price:.6f}", end="")
    if score is not None:
        print(f" | Score: {score:.3f}", end="")
    if profit is not None:
        print(f" | PnL: {profit:.2f}", end="")
    print("") 

    log_entry = {
        "timestamp": timestamp,
        "event": event_type,
        "symbol": symbol,
        "price": round(price, 6),
        "score": round(score, 3) if score is not None else None,
        "profit": round(profit, 2) if profit is not None else None
    }

    try:
        with open("trade_log.json", "r") as f:
            logs = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        logs = []

    logs.append(log_entry)

    with open("trade_log.json", "w") as f:
        json.dump(logs, f, indent=4)

# Trading system 
async def strategy(df, symbol, for_button):
    global long_trade, short_trade, in_trade, profit, money_available, entry_price
    last = df.iloc[-1]
    messages = []

    trend = fetch_trend(symbol)
    if trend == "uptrend": 
        trend_emoji = "📈"
    elif trend == "downtrend":
        trend_emoji = "📉"
    else:
        trend_emoji = "❔"

    timestamp = last['timestamp'].strftime("%Y-%m-%d %H:%M:%S")

    if long_trade:
        profit = (last['close'] - entry_price) * (position_size / entry_price)
    elif short_trade:
        profit = (entry_price - last['close']) * (position_size / entry_price)
    else:
        profit = 0

    exit_strategy(symbol, last['close'])

    cmf_strength = last['cmf']
    price_above_ema = (last['close'] - last['ema50']) / last['ema50']
    price_above_middle = (last['close'] - last['donchian_middle']) / last['donchian_middle']

    atr = df['high'] - df['low']
    recent_volatility = atr.tail(20).mean() / last['close']

    if recent_volatility == 0:
        recent_volatility = 0.0001

    price_above_ema_scaled = price_above_ema / recent_volatility
    price_above_middle_scaled = price_above_middle / recent_volatility

    cmf_component = max(min(cmf_strength * abs(cmf_strength), 1), -1)

    signal_score = (cmf_component * 0.3) + (price_above_ema_scaled * 0.4) + (price_above_middle_scaled * 0.3)
    strong_signal = False
        
    strong_signal = False
    try:
        if last['close'] > last['donchian_middle'] and last['cmf'] > 0 and last['close'] > last['ema50']:
            if signal_score >= 0.10:
                message = f"{trend_emoji} {trend.upper()} | 🚀 STRONG BUY SIGNAL! Symbol: `{symbol}` Price: `{last['close']}` Score: `{signal_score:.2f}`"
                try:
                    strong_signal = True
                    log_and_print(f"{trend_emoji} {trend.upper()} | 🚀 STRONG BUY", symbol, last['close'], score=signal_score)
                    if money_available >= 10 and not in_trade:
                        long_trade = True
                        open_trade(symbol, last['close'])
                    if for_button: messages.append(message)
                except Exception as e:
                    print(f"❌ Failed to print alert: {e}")

            if not strong_signal: 
                log_and_print(f"{trend_emoji} {trend.upper()} | ✅BUY BIAS", symbol, last['close'], score=signal_score)
                message = f"{trend_emoji} {trend.upper()} | ✅ BUY BIAS: {signal_score:.2f} Price: {last['close']} coin: {symbol}" 
                if for_button: messages.append(message)

        elif last['close'] < last['donchian_middle'] and last['cmf'] < 0 and last['close'] < last['ema50']:
            if signal_score <= -0.10:
                message = f"{trend.upper()} | ⤵️ STRONG SELL SIGNAL! Symbol: `{symbol}` Price: `{last['close']}` Score: `{signal_score:.2f}`"
                try:
                    strong_signal = True
                    log_and_print(f"{trend_emoji} {trend.upper()} | ⤵️STRONG SELL", symbol, last['close'], score=signal_score)
                    if money_available >= 10 and not in_trade:
                        short_trade = True
                        open_trade(symbol, last['close'])
                    if for_button: messages.append(message)
                except Exception as e:
                    print(f"❌ Failed to send Discord alert: {e}")
            if not strong_signal: 
                log_and_print(f"{trend_emoji} {trend.upper()} | ❌SELL BIAS", symbol, last['close'], score=signal_score)
                message = f"{trend_emoji} {trend.upper()} | ❌ SELL BIAS: {signal_score:.2f} Price: {last['close']} coin: {symbol}"
                if for_button: messages.append(message)

        else:
            log_and_print(f"{trend_emoji} {trend.upper()} | ⏳ HOLD", symbol, last['close'], score=signal_score)
            message = f"{trend_emoji} {trend.upper()} | ⏳ HOLD Score: {signal_score:.2f} Price: {last['close']} coin: {symbol}"
            if for_button: messages.append(message)

        return messages

    except Exception as e:
        print(f"Exception in strategy: {e}")

class TradeView(discord.ui.View):
    @discord.ui.button(label="View the signals", style=discord.ButtonStyle.primary, custom_id="view_signals")
    async def view_signals(self, interaction: discord.Interaction, button: discord.ui.Button):
        messages = []
        for symbol in symbols:
            df = fetch_ohlcv(symbol)
            df = apply_indicators(df)
            signal = await strategy(df, symbol, for_button=True)
            if signal:
                messages.append(signal)

        content = "\n\n".join(str(m) for m in messages) if messages else "No strong signals right now."
        await interaction.response.send_message(content=content, ephemeral=True)

#Discord interaction
@bot.tree.command(name="tradepanel", description="Trading panel duh")
async def tradepanel(interaction: discord.Interaction):
    embed = discord.Embed(
        title="📊 Trade Panel",
        description="This is your Trade Panel go make a bag 💰",
        color=discord.Color.blue(),
    )
    embed.add_field(name="Version", value=vers, inline=False)

    view = TradeView()
    view.add_item(discord.ui.Button(label="Visit GitHub", style=discord.ButtonStyle.link, url="https://github.com/EtheralXD/PyTrader.v2"))

    await interaction.response.send_message(embed=embed, view=view,  ephemeral=True)

@tasks.loop(minutes=15)
async def run_strategy_loop():
    for symbol in symbols:
        df = fetch_ohlcv(symbol)
        df = apply_indicators(df)
        await strategy(df, symbol, for_button=False)

bot.run(os.getenv("TOKEN"))