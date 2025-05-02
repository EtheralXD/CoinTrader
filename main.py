import sys
import asyncio

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
vers = "v2.1"

exchange = ccxt.mexc({
    'apiKey': api_key,
    'secret': secret,
    'enableRateLimit': True
})

symbols = ['MOODENG/USDT', 'PIPPIN/USDT']
timeframe = '15m'
limit = 100

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


# Trading system 
async def strategy(df, symbol, for_button):
    last = df.iloc[-1]
    messages = []

    trend = fetch_trend(symbol)
    if trend == "uptrend": 
        trend_emoji = "📈"
    elif trend == "downtrend":
        trend_emoji = "📉"
    else:
        trend_emoji = "❔"

    if trend == "no trend":
        timestamp = last['timestamp'].strftime("%Y-%m-%d %H:%M:%S")
        message = f"{timestamp} ⛔ Warning (No 1H trend confirmation) coin: {symbol}"
        print(message)
    if for_button: messages.append(message)
    else:
        timestamp = last['timestamp'].strftime("%Y-%m-%d %H:%M:%S")
        message = f"{timestamp} {trend_emoji} 1H trend is confirmed ({trend.upper()}) coin: {symbol}"
        print(message)
    if for_button: messages.append(message)

        
    
    cmf_strength = last['cmf']
    price_above_ema = (last['close'] - last['ema50']) / last['ema50']
    price_above_middle = (last['close'] - last['donchian_middle']) / last['donchian_middle']

    signal_score = (cmf_strength * 0.5) + (price_above_ema * 0.3) + (price_above_middle * 0.2)
    try:
        if last['close'] > last['donchian_middle'] and last['cmf'] > 0 and last['close'] > last['ema50']:
            if signal_score >= 0.30:
                message = f"🚀 STRONG BUY SIGNAL!\nSymbol: `{symbol}`\nPrice: `{last['close']}`\nScore: `{signal_score:.2f}`"
                try:
                    print(message)
                    if for_button: messages.append(message)
                except Exception as e:
                    print(f"❌ Failed to print alert: {e}")

            print(f"✅ BUY Bias Signal - Score: {signal_score:.2f} - Price: {last['close']} coin: {symbol}")
        elif last['close'] < last['donchian_middle'] and last['cmf'] < 0 and last['close'] < last['ema50']:
            if signal_score <= -0.20:
                message = f"⤵️ STRONG SELL SIGNAL!\nSymbol: `{symbol}`\nPrice: `{last['close']}`\nScore: `{signal_score:.2f}`"
                try:
                    print(message)
                    if for_button: messages.append(message)
                except Exception as e:
                    print(f"❌ Failed to send Discord alert: {e}")
            print(f"❌ SELL Bias Signal - Score: {-signal_score:.2f} - Price: {last['close']} coin: {symbol}")
        else:
            message = f"⏳ HOLD - Score: {signal_score:.2f} - Price: {last['close']} coin: {symbol}"
            print(message)
            if for_button: messages.append(message)

        return messages

    except Exception as e:
        print(e)

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

@tasks.loop(minutes=5)
async def run_strategy_loop():
    for symbol in symbols:
        df = fetch_ohlcv(symbol)
        df = apply_indicators(df)
        await strategy(df, symbol, for_button=False)

bot.run(os.getenv("TOKEN"))