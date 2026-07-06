"""
signal_engine/backtester/engine.py
Walk-forward simulation engine for the crypto signal pipeline.
"""

import sys
import time
from typing import Dict, List, Any
from unittest.mock import patch
import pandas as pd
from datetime import datetime, timezone, timedelta

from signal_engine.backtester.data_loader import load_candles
from run_signal_engine import analyze_symbol, _run_direction
from signal_engine.stage01_liquidity_gate import LiquidityResult
from signal_engine.stage09_futures import FuturesResult
from signal_engine.stage02_time_filter import TimeFilterResult

class BacktestEngine:
    def __init__(self, symbol: str, years: int = 3):
        self.symbol = symbol
        self.years = years
        self.trades = []
        self.df_15m = None
        self.df_1h = None
        self.df_4h = None
        
        self.btc_1h = None
        self.btc_4h = None
        
    def load_data(self):
        print("Loading data for backtest...")
        self.df_15m = load_candles(self.symbol, "15m", self.years)
        self.df_1h = load_candles(self.symbol, "1h", self.years)
        self.df_4h = load_candles(self.symbol, "4h", self.years)
        
        if self.symbol != "BTCUSDT":
            self.btc_1h = load_candles("BTCUSDT", "1h", self.years)
            self.btc_4h = load_candles("BTCUSDT", "4h", self.years)
        else:
            self.btc_1h = self.df_1h
            self.btc_4h = self.df_4h
            
    def _get_historical_slice(self, df: pd.DataFrame, current_time: pd.Timestamp, lookback_candles: int) -> pd.DataFrame:
        """Get the historical data slice available exactly at current_time."""
        idx = df.index.searchsorted(current_time, side='right')
        # idx is the insertion point. The actual valid rows are up to idx (exclusive)
        # We want the last lookback_candles rows before idx
        start_idx = max(0, idx - lookback_candles)
        subset = df.iloc[start_idx:idx].copy()
        
        if len(subset) > 0:
            subset.attrs["signal_idx"] = -1
        return subset
        
    def run(self):
        self.load_data()
        
        print("Starting backtest engine...")
        
        # Walk-forward parameters
        # Roll 30-day windows. 
        # Total data is 3 years. We iterate through the 15m dataset chronologically.
        
        total_candles = len(self.df_15m)
        start_idx = 300  # Need at least 300 15m candles to start (and corresponding 4h)
        
        # Find index where 4h also has at least 200 candles (for EMA200)
        # 200 * 4h = 800 hours = 3200 15m candles. Let's start safely at index 4000
        start_idx = max(300, 4000)
        
        open_position = None
        
        # Mocks
        def mock_fetch_ohlcv(sym, tf):
            # We use the current_time from outer scope
            lookback = 300
            if sym == self.symbol:
                if tf == "15m": return self._get_historical_slice(self.df_15m, current_time, lookback)
                if tf == "1h": return self._get_historical_slice(self.df_1h, current_time, lookback)
                if tf == "4h": return self._get_historical_slice(self.df_4h, current_time, lookback)
            elif sym == "BTCUSDT":
                if tf == "1h": return self._get_historical_slice(self.btc_1h, current_time, lookback)
                if tf == "4h": return self._get_historical_slice(self.btc_4h, current_time, lookback)
            return None
            
        def mock_check_liquidity(sym):
            try:
                return LiquidityResult(
                    symbol=sym,
                    volume_pass=True,
                    spread_pass=True,
                    overall_pass=True,
                    current_volume_usd=0.0,
                    p40_threshold_usd=0.0,
                    current_spread_pct=0.0,
                    reject_reason=None
                )
            except Exception as e:
                print(f"[MOCK ERROR] Liquidity gate: {e}")
                class DummyLiq:
                    overall_pass = False
                    reject_reason = f"Mock Error: {e}"
                return DummyLiq()
            
        def mock_analyze_futures(sym, price_up, signal_direction):
            return FuturesResult(
                symbol=sym, 
                oi_current=0.0, 
                oi_previous=0.0, 
                oi_change_pct=0.0, 
                oi_signal="NEUTRAL", 
                funding_rate=0.0, 
                funding_signal="NEUTRAL", 
                long_ratio=50.0, 
                short_ratio=50.0, 
                ls_signal="BALANCED", 
                combined_modifier=0, 
                tags=[], 
                blocked=False
            )
            
        def mock_check_time_filter(df_1h, volume_zscore=0):
            # Evaluate using the actual timestamp of the last candle
            from signal_engine.stage02_time_filter import check_time_filter
            dt_utc = df_1h.index[-1]
            return check_time_filter(volume_zscore=volume_zscore, _override_utc=dt_utc)
            
        def mock_get_portfolio_status():
            return {"open_positions": 0, "signals_halted": False}
            
        def mock_check_signal(sym, dir, cluster, conf):
            # Mock Portfolio risk checks to PASS
            from signal_engine.stage14_portfolio_risk import PortfolioCheckResult
            return PortfolioCheckResult(
                approved=True,
                reject_reason=None,
                open_position_count=0,
                cluster_position_count=0,
                cooldown_remaining_minutes=0,
                daily_pnl_pct=0.0,
                weekly_pnl_pct=0.0,
                halted=False
            )

        def mock_get_correlation_cluster(sym):
            return ("Crypto", 1.0, False)

        timestamps = self.df_15m.index[start_idx:]
        
        # Setup patching
        patch_fetch = patch('run_signal_engine.fetch_ohlcv', side_effect=mock_fetch_ohlcv)
        patch_liq = patch('run_signal_engine.check_liquidity', side_effect=mock_check_liquidity)
        patch_fut = patch('run_signal_engine.analyze_futures', side_effect=mock_analyze_futures)
        patch_tf = patch('run_signal_engine.check_time_filter', side_effect=mock_check_time_filter)
        patch_cluster = patch('run_signal_engine.get_correlation_cluster', side_effect=mock_get_correlation_cluster)
        patch_port = patch('run_signal_engine.check_signal', side_effect=mock_check_signal)
        
        def mock_send_api_warning(title, msg):
            with open("backtest_errors.log", "a", encoding="utf-8") as f:
                f.write(f"[{current_time}] {title}: {msg}\n")
                
        patch_warn = patch('run_signal_engine.send_api_warning', side_effect=mock_send_api_warning)
        
        import logging
        logging.getLogger('backtester').setLevel(logging.ERROR)
        logging.disable(logging.CRITICAL)

        with patch_fetch, patch_liq, patch_fut, patch_tf, patch_cluster, patch_port, patch_warn:
            from signal_engine.stage04_btc_macro import analyze_btc_macro
            
            for i, current_time in enumerate(timestamps):
                # Progress
                if i % 1000 == 0:
                    pct = (i / len(timestamps)) * 100
                    sys.stdout.write(f"\r[SIMULATION] {current_time.strftime('%Y-%m-%d')} | {pct:.1f}%")
                    sys.stdout.flush()
                    
                current_candle = self.df_15m.loc[current_time]
                
                try:
                        # Check Open Position
                    if open_position is not None:
                        high = current_candle['high']
                        low = current_candle['low']
                    
                        hit_sl = False
                        hit_t1 = False
                        hit_t2 = False
                    
                        if open_position['direction'] == "LONG":
                            if low <= open_position['sl']: hit_sl = True
                            elif high >= open_position['t2']: hit_t2 = True
                            elif high >= open_position['t1']: hit_t1 = True
                        else:
                            if high >= open_position['sl']: hit_sl = True
                            elif low <= open_position['t2']: hit_t2 = True
                            elif low <= open_position['t1']: hit_t1 = True
                        
                        if hit_sl:
                            self._close_trade(open_position, open_position['sl'], current_time, "STOP_LOSS")
                            open_position = None
                        elif hit_t2:
                            self._close_trade(open_position, open_position['t2'], current_time, "TARGET_2")
                            open_position = None
                        elif hit_t1 and not open_position['t1_hit']:
                            self._close_trade(open_position, open_position['t1'], current_time, "TARGET_1", partial=True)
                            open_position['t1_hit'] = True
                            open_position['sl'] = open_position['entry'] # Move to BE
                        
                        # Skip analysis if position is still open (one trade at a time per symbol)
                        if open_position is not None:
                            continue
                        
                    # Only check signal on the hour (e.g. 00, 15, 30, 45 if we wanted, but run_signal_engine runs every 15m)
                    # We fetch BTC macro once
                    btc_1h_slice = self._get_historical_slice(self.btc_1h, current_time, 300)
                    btc_4h_slice = self._get_historical_slice(self.btc_4h, current_time, 300)
                
                    if len(btc_1h_slice) < 50 or len(btc_4h_slice) < 50:
                        continue
                    
                    btc_macro = analyze_btc_macro(btc_1h_slice, btc_4h_slice)
                
                    # Run the pipeline (returns dict with decision)
                    res = analyze_symbol(self.symbol, btc_1h_slice, btc_4h_slice, btc_macro, mode="backtest")
                
                    if res.get("decision") == "SIGNAL_APPROVED":
                        direction = res["direction"]
                        entry_price = float(current_candle["close"])
                    
                        # Apply slippage
                        slippage = 0.0005
                        filled_price = entry_price * (1 + slippage) if direction == "LONG" else entry_price * (1 - slippage)
                    
                        vty = res['stage08']
                        sr = res['stage10']
                    
                        stop_dist = entry_price * (vty.final_stop_pct / 100.0)
                        sl = entry_price - stop_dist if direction == "LONG" else entry_price + stop_dist
                        t1 = sr.adjusted_target1 if sr.adjusted_target1 else (entry_price + (stop_dist * 2.0) if direction == "LONG" else entry_price - (stop_dist * 2.0))
                        t2 = entry_price + (stop_dist * 4.0) if direction == "LONG" else entry_price - (stop_dist * 4.0)
                    
                        open_position = {
                            "direction": direction,
                            "entry": filled_price,
                            "sl": sl,
                            "t1": t1,
                            "t2": t2,
                            "size_pct": vty.position_size_pct,
                            "open_time": current_time,
                            "t1_hit": False
                        }
                    
                except Exception as e:
                    with open('backtest_errors.log', 'a', encoding='utf-8') as f:
                        f.write(f'[{current_time}] Per-candle loop error: {e}\n')
                    continue
        print("\n[SIMULATION] Complete.")
        
    def _close_trade(self, pos: dict, exit_price: float, close_time: pd.Timestamp, reason: str, partial: bool = False):
        direction = pos['direction']
        entry = pos['entry']
        
        # Fees: 0.04% maker fee
        fee_rate = 0.0004
        
        if direction == "LONG":
            gross_pnl_pct = (exit_price - entry) / entry
        else:
            gross_pnl_pct = (entry - exit_price) / entry
            
        net_pnl_pct = gross_pnl_pct - (fee_rate * 2) # Entry and Exit fees
        
        size_multiplier = 0.5 if (partial or pos['t1_hit']) else 1.0
        position_size = 1000.0 * (pos['size_pct'] / 100.0) * size_multiplier
        
        gross_usd = position_size * gross_pnl_pct
        net_usd = position_size * net_pnl_pct
        fee_usd = position_size * (fee_rate * 2)
        
        # R-Multiple
        risk_dist = abs(entry - pos['sl'])
        risk_pct = risk_dist / entry if entry > 0 else 1.0
        account_risk_usd = (1000.0 * (pos['size_pct'] / 100.0)) * risk_pct
        
        r_multiple = net_usd / account_risk_usd if account_risk_usd > 0 else 0.0
        
        self.trades.append({
            "symbol": self.symbol,
            "direction": direction,
            "entry_time": pos['open_time'],
            "close_time": close_time,
            "entry_price": entry,
            "exit_price": exit_price,
            "reason": reason,
            "gross_usd": gross_usd,
            "net_usd": net_usd,
            "fees_usd": fee_usd,
            "r_multiple": r_multiple,
            "partial": partial
        })
