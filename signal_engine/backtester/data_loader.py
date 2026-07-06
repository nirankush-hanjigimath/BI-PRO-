"""
signal_engine/backtester/data_loader.py
Downloads and caches historical Binance spot data for backtesting.
"""

import os
import sys
import time
import requests
import pandas as pd
from datetime import datetime, timezone, timedelta

# Binance limits
MAX_LIMIT = 1000

def _get_cache_path(symbol: str, timeframe: str) -> str:
    base_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(base_dir, "data")
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, f"{symbol}_{timeframe}.parquet")

def _interval_to_ms(interval: str) -> int:
    unit = interval[-1]
    value = int(interval[:-1])
    if unit == 'm':
        return value * 60 * 1000
    elif unit == 'h':
        return value * 60 * 60 * 1000
    elif unit == 'd':
        return value * 24 * 60 * 60 * 1000
    return 60 * 1000

def load_candles(symbol: str, timeframe: str, years: int = 3) -> pd.DataFrame:
    """Load historical candles, downloading if necessary or if cache is stale."""
    cache_path = _get_cache_path(symbol, timeframe)
    
    # Check cache
    if os.path.exists(cache_path):
        mtime = os.path.getmtime(cache_path)
        age_hours = (time.time() - mtime) / 3600
        if age_hours < 24:
            try:
                df = pd.read_parquet(cache_path)
                # Ensure it has enough data
                start_ts = int((datetime.now(timezone.utc) - timedelta(days=years*365)).timestamp() * 1000)
                if df.index[0].timestamp() * 1000 <= start_ts + (24*3600*1000): # Allow 1 day slack
                    print(f"[CACHE] Loaded {len(df)} candles for {symbol} {timeframe}")
                    return df
                else:
                    print(f"[CACHE] Cached data for {symbol} {timeframe} is too short. Re-downloading...")
            except Exception as e:
                print(f"[CACHE] Error reading parquet {cache_path}: {e}")
        else:
            print(f"[CACHE] Cache for {symbol} {timeframe} is older than 24h. Re-downloading...")
            
    # Download
    print(f"[DOWNLOAD] Fetching {years} years of {timeframe} data for {symbol}...")
    
    end_time_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_time_ms = int((datetime.now(timezone.utc) - timedelta(days=years*365)).timestamp() * 1000)
    
    interval_ms = _interval_to_ms(timeframe)
    expected_candles = (end_time_ms - start_time_ms) // interval_ms
    
    all_klines = []
    current_end = end_time_ms
    
    while current_end > start_time_ms:
        url = "https://api.binance.com/api/v3/klines"
        params = {
            "symbol": symbol,
            "interval": timeframe,
            "endTime": current_end,
            "limit": MAX_LIMIT
        }
        
        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if not data:
                break
                
            all_klines.extend(data)
            
            # Progress tracking
            pct = min(100.0, (len(all_klines) / expected_candles) * 100)
            sys.stdout.write(f"\r[DOWNLOAD] Progress: {pct:.1f}% ({len(all_klines)} candles)")
            sys.stdout.flush()
            
            # Set new end time to the open time of the oldest candle fetched - 1 ms
            oldest_open_time = data[0][0]
            if current_end == oldest_open_time - 1:
                break # Avoid infinite loop if stuck
            current_end = oldest_open_time - 1
            
            time.sleep(0.1)  # Rate limit respect
            
        except Exception as e:
            print(f"\n[DOWNLOAD ERROR] Failed to fetch data: {e}")
            time.sleep(2) # Retry delay
            
    print() # New line after progress
    
    if not all_klines:
        raise ValueError(f"Failed to fetch any data for {symbol} {timeframe}")
        
    # Process into DataFrame
    # Binance returns newest at end of array, but since we fetched backwards, we have blocks of 1000
    # where each block is chronological, but the blocks themselves are appended in reverse chronological order.
    # E.g. Block 1: Oct 1 - Oct 10, Block 2: Sep 20 - Sep 30.
    # So we need to sort by timestamp.
    
    df = pd.DataFrame(all_klines, columns=[
        "timestamp", "open", "high", "low", "close", "volume",
        "close_time", "quote_volume", "trades", "taker_base", "taker_quote", "ignore"
    ])
    
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df.set_index("timestamp", inplace=True)
    df.sort_index(inplace=True)
    
    # Remove duplicates if any (due to overlapping boundaries)
    df = df[~df.index.duplicated(keep='first')]
    
    # Trim to exact start_time
    start_dt = pd.to_datetime(start_time_ms, unit="ms", utc=True)
    df = df[df.index >= start_dt]
    
    # Convert numeric columns
    numeric_cols = ["open", "high", "low", "close", "volume", "quote_volume"]
    for col in numeric_cols:
        df[col] = df[col].astype(float)
        
    # Keep only necessary columns to save space
    df = df[["open", "high", "low", "close", "volume", "quote_volume"]]
    
    # Save to parquet
    df.to_parquet(cache_path)
    print(f"[CACHE] Saved {len(df)} candles to {cache_path}")
    
    return df

if __name__ == "__main__":
    print("================================================================================")
    print("backtester/data_loader.py -- Standalone Test")
    print("================================================================================")
    
    symbol = "BTCUSDT"
    tf = "1h"
    years = 3
    
    print(f"Testing loader for {symbol} {tf} ({years} years)...")
    df = load_candles(symbol, tf, years)
    
    print("\nData Summary:")
    print(f"Total Candles: {len(df)}")
    print(f"Start Date: {df.index[0]}")
    print(f"End Date: {df.index[-1]}")
    print("================================================================================")
