import ccxt
import pandas as pd
import time
import os
import requests
import discord
from discord.ext import commands
from ta.volatility import DonchianChannel
from ta.volume import ChaikinMoneyFlowIndicator

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
client = discord.Client(intents=intents)

async def on_ready():
    print(f"✅ Logged in as {client.user}")
    try:
        synced = await bot.tree.sync()
        print(f"🔧 Synced {len(synced)} slash command(s).")
    except Exception as e:
        print(f"❌ Sync failed: {e}")

api_key = os.getenv("API_KEY")
secret = os.getenv("SECRET_KEY")
client.run("TOKEN")

print("You ready to get trading? 👍")

exchange = ccxt.mexc({
    'apiKey': api_key,
    'secret': secret,
    'enableRateLimit': True
})

symbols = ['MOODENG/USDT', 'PIPPIN/USDT']
timeframe = '5m'
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
    return df.iloc[-1]['close'] > df.iloc[-1]['ema50']

# Trading system 
async def strategy(df, symbol):
    last = df.iloc[-1]

    if not fetch_trend(symbol):
        print(f"[{last['timestamp']}] ⛔ Warning (No 1H trend confirmation) coin: {symbol}")
        
    
    cmf_strength = last['cmf']
    price_above_ema = (last['close'] - last['ema50']) / last['ema50']
    price_above_middle = (last['close'] - last['donchian_middle']) / last['donchian_middle']

    signal_score = (cmf_strength * 0.5) + (price_above_ema * 0.3) + (price_above_middle * 0.2)
    try:
        if last['close'] > last['donchian_middle'] and last['cmf'] > 0 and last['close'] > last['ema50']:
            if signal_score >= 0.30:
                message = f"🚀 STRONG BUY SIGNAL!\nSymbol: `{symbol}`\nPrice: `{last['close']}`\nScore: `{signal_score:.2f}`\nTime: `{last['timestamp']}`"
                try:
                    await message.channel.send(json={"content": message})
                except Exception as e:
                    print(f"❌ Failed to send Discord alert: {e}")

            print(f"[{last['timestamp']}] ✅ BUY Bias Signal - Score: {signal_score:.2f} - Price: {last['close']} coin: {symbol}")
        elif last['close'] < last['donchian_middle'] and last['cmf'] < 0 and last['close'] < last['ema50']:
            if signal_score <= -0.20:
                message = f"⤵️ STRONG SELL SIGNAL!\nSymbol: `{symbol}`\nPrice: `{last['close']}`\nScore: `{signal_score:.2f}`\nTime: `{last['timestamp']}`"
                try:
                    await message.channel.send(json={"content": message})
                except Exception as e:
                    print(f"❌ Failed to send Discord alert: {e}")
            print(f"[{last['timestamp']}] ❌ SELL Bias Signal - Score: {-signal_score:.2f} - Price: {last['close']} coin: {symbol}")
        else:
            print(f"[{last['timestamp']}] ⏳ HOLD - Score: {signal_score:.2f} - Price: {last['close']} coin: {symbol}")

    except Exception as e:
        print(e)



while True:
    for symbol in symbols:
        df = fetch_ohlcv(symbol)
        df = apply_indicators(df)
        strategy(df, symbol)
        
    now = time.time()
    sleep_time = 300 - (now % 300)
    time.sleep(sleep_time)


#Discord interaction
@bot.tree.command(name="TradePanel", description="Trading panel duh")
async def TradePanel(interaction: discord.Interaction):
    await interaction.response.send_message("")

