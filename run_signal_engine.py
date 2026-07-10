"""
run_signal_engine.py
Main entry point for the Institutional Crypto Signal Engine.
Orchestrates the 14-stage pipeline on a 15-minute schedule.
"""

import argparse
import datetime
import os
import sys
import time
import traceback
from typing import Dict, Any, Optional

import schedule
from joblib import Parallel, delayed

from signal_engine.config import cfg
from signal_engine.stage00_data_fetcher import fetch_ohlcv, _refresh_daily_volume_cache
from signal_engine.stage01_liquidity_gate import check_liquidity
from signal_engine.stage02_time_filter import check_time_filter
from signal_engine.stage03_regime import analyze_regime
from signal_engine.stage04_btc_macro import analyze_btc_macro
from signal_engine.stage05_relative_strength import analyze_relative_strength, update_correlation_matrix, get_correlation_cluster
from signal_engine.stage06_trend_quality import analyze_trend_quality
from signal_engine.stage07_volume import analyze_volume
from signal_engine.stage08_volatility import analyze_volatility
from signal_engine.stage09_futures import analyze_futures
from signal_engine.stage10_support_resistance import analyze_sr
from signal_engine.stage11_entry_confirmation import analyze_entry_confirmation
from signal_engine.stage12_confidence import analyze_confidence
from signal_engine.stage13_signal_output import assemble_and_send_signal, send_api_warning
from signal_engine.stage14_portfolio_risk import check_signal, get_portfolio_status
from signal_engine.utils.indicators import atr
from signal_engine.paper_trader import open_paper_position, check_paper_positions, run_daily_summary_check
from signal_engine.utils.logger import get_logger

logger = get_logger("ENGINE", "SYSTEM")
cycle_count = 0


def _print_dry_run_summary(sym: str, res: Dict[str, Any]):
    print("═══════════════════════════════════════════")
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    dir_str = res.get("direction", "NONE")
    print(f"{sym} · {dir_str} · {ts}")
    print("═══════════════════════════════════════════")
    
    liq = res.get('stage01')
    if liq:
        p40 = liq.p40_threshold_usd
        vol = liq.current_volume_usd
        vol_str = f"${vol/1e6:.0f}M" if vol is not None else "N/A"
        p40_str = f"${p40/1e6:.0f}M" if p40 is not None else "N/A"
        print(f"Stage 01 Liquidity:    {'PASS' if liq.overall_pass else 'FAIL'} ({vol_str} > {p40_str} P40)")
    else:
        print("Stage 01 Liquidity:    SKIPPED")
        
    tf = res.get('stage02')
    if tf:
        print(f"Stage 02 Time:         {tf.status}")
    else:
        print("Stage 02 Time:         SKIPPED")
        
    reg = res.get('stage03')
    if reg:
        print(f"Stage 03 Regime:       {reg['regime_1h'].regime} (1h) / {reg['regime_4h'].regime} (4h)")
    else:
        print("Stage 03 Regime:       SKIPPED")
        
    btc = res.get('stage04')
    if btc:
        print(f"Stage 04 BTC Macro:    {btc.classification} ({btc.confidence_modifier:+d})")
    else:
        print("Stage 04 BTC Macro:    SKIPPED")
        
    rs = res.get('stage05')
    if rs:
        print(f"Stage 05 RS:           {rs.classification} ({rs.combined_rs:+.1f}%)")
    else:
        print("Stage 05 RS:           SKIPPED")
        
    tq = res.get('stage06')
    if tq:
        tag = tq.overextension_tag or "NONE"
        print(f"Stage 06 Trend:        {tq.trend_quality} ({tag} {tq.confidence_modifier:+d})")
    else:
        print("Stage 06 Trend:        SKIPPED")
        
    volm = res.get('stage07')
    if volm:
        print(f"Stage 07 Volume:       {volm.volume_classification} ({volm.confidence_modifier:+d})")
    else:
        print("Stage 07 Volume:       SKIPPED")
        
    vty = res.get('stage08')
    if vty:
        print(f"Stage 08 Volatility:   ATR ${vty.atr_14_15m:.2f} | Stop {vty.final_stop_pct:.2f}%")
    else:
        print("Stage 08 Volatility:   SKIPPED")
        
    fut = res.get('stage09')
    if fut:
        print(f"Stage 09 Futures:      {fut.oi_signal or 'NEUTRAL'} ({fut.combined_modifier:+d})")
    else:
        print("Stage 09 Futures:      SKIPPED")
        
    sr = res.get('stage10')
    if sr:
        rr_val = sr.nearest_resistance_pct if dir_str == 'LONG' else sr.nearest_support_pct
        if not rr_val: rr_val = 0.0
        # For simplicity, printing generic R:R representation
        print(f"Stage 10 S/R:          {'FAIL' if sr.sr_reject else 'PASS'} | R:R {rr_val:.1f}:1")
    else:
        print("Stage 10 S/R:          SKIPPED")
        
    ent = res.get('stage11')
    if ent:
        print(f"Stage 11 Entry:        {ent.pattern_name or 'NONE'} ({ent.body_quality} body {ent.confidence_modifier:+d})")
    else:
        print("Stage 11 Entry:        SKIPPED")
        
    conf = res.get('stage12')
    if conf:
        print(f"Stage 12 Confidence:   {conf.final_score}/100 → {conf.grade}")
    else:
        print("Stage 12 Confidence:   SKIPPED")
        
    port = res.get('stage14')
    if port:
        print(f"Stage 14 Portfolio:    {'PASS' if port.approved else 'REJECTED: ' + str(port.reject_reason)}")
    else:
        print("Stage 14 Portfolio:    N/A (rejected earlier)")
        
    dec = res.get('decision', 'NO SIGNAL')
    print(f"DECISION: {dec}")
    print("═══════════════════════════════════════════")


def _run_direction(
    sym: str, direction: str, price: float, atr_val: float,
    df_15m, df_4h, reg_dict, btc_macro, rs, tq, volm,
    time_filter
) -> dict:
    res = {}
    
    vty = analyze_volatility(df_15m, sym, direction)
    res['stage08'] = vty
    
    fut = analyze_futures(sym, price_up=(direction == "LONG"), signal_direction=direction)
    res['stage09'] = fut
    
    # Approx targets for S/R
    stop_dist = price * (vty.final_stop_pct / 100.0)
    stop_loss = price - stop_dist if direction == "LONG" else price + stop_dist
    target1 = price + (stop_dist * 2.0) if direction == "LONG" else price - (stop_dist * 2.0)
    
    sr = analyze_sr(df_4h, sym, direction, price, target1, stop_loss)
    res['stage10'] = sr
    
    ent = analyze_entry_confirmation(df_15m, sym, direction, reg_dict["regime_1h"].regime, sr.resistance_levels, sr.support_levels)
    res['stage11'] = ent
    
    conf = analyze_confidence(sym, direction, time_filter, reg_dict, btc_macro, rs, tq, volm, vty, fut.to_futures_data(), sr.to_sr_levels(), ent.to_entry_signal("CLOSED"))
    res['stage12'] = conf
    
    return res


def analyze_symbol(sym: str, btc_1h, btc_4h, btc_macro, mode: str) -> dict:
    res = {"symbol": sym, "direction": "NONE", "decision": "NO SIGNAL"}
    try:
        # Stage 00
        df_15m = fetch_ohlcv(sym, "15m")
        df_1h = fetch_ohlcv(sym, "1h")
        df_4h = fetch_ohlcv(sym, "4h")
        if df_15m is None or df_1h is None or df_4h is None:
            return res
            
        # Stage 01
        liq = check_liquidity(sym)
        res['stage01'] = liq
        if not liq.overall_pass:
            res['decision'] = f"REJECTED_LIQUIDITY ({liq.reject_reason})"
            return res
            
        # Stage 02
        tf = check_time_filter(df_1h)
        res['stage02'] = tf
        if tf.status == "BLOCKED" and not tf.override_applied:
            res['decision'] = "REJECTED_TIME"
            return res
            
        # Stage 03
        reg = analyze_regime(df_1h, df_4h, sym)
        res['stage03'] = reg
        
        # Stage 04 - passed in
        res['stage04'] = btc_macro
        
        # Stage 05
        rs = analyze_relative_strength(df_1h, df_4h, btc_1h, btc_4h, sym)
        res['stage05'] = rs
        
        # Stage 06
        tq = analyze_trend_quality(df_4h, df_1h, sym)
        res['stage06'] = tq
        
        # Stage 07
        volm = analyze_volume(df_15m, "15m", sym)
        res['stage07'] = volm
        
        price = float(df_4h["close"].iloc[-1])
        res['current_price'] = price
        atr_val = float(atr(df_4h, 14).iloc[-1])
        
        # Evaluate both LONG and SHORT
        long_res = _run_direction(sym, "LONG", price, atr_val, df_15m, df_4h, reg, btc_macro, rs, tq, volm, tf)
        short_res = _run_direction(sym, "SHORT", price, atr_val, df_15m, df_4h, reg, btc_macro, rs, tq, volm, tf)
        
        long_score = long_res['stage12'].final_score
        short_score = short_res['stage12'].final_score
        
        best_dir = "LONG" if long_score >= short_score else "SHORT"
        best_res = long_res if long_score >= short_score else short_res
        
        res.update(best_res)
        res['direction'] = best_dir
        
        conf = res['stage12']
        if conf.grade == "REJECT":
            res['decision'] = "REJECTED_CONFIDENCE"
            return res
            
        # Stage 14
        cluster, _, stale_matrix = get_correlation_cluster(sym)
        port = check_signal(sym, best_dir, cluster, conf.final_score)
        res['stage14'] = port
        
        if not port.approved:
            res['decision'] = f"REJECTED_PORTFOLIO ({port.reject_reason})"
            return res
            
        res['decision'] = "SIGNAL_APPROVED"
        
        # Stage 13 (Send if not dry-run)
        if mode != "dry-run":
            vty = res['stage08']
            fut = res['stage09']
            sr = res['stage10']
            ent = res['stage11']
            
            stop_dist = price * (vty.final_stop_pct / 100.0)
            stop_loss = price - stop_dist if best_dir == "LONG" else price + stop_dist
            target1 = sr.nearest_resistance if best_dir == "LONG" else sr.nearest_support
            if not target1:
                target1 = price + (stop_dist * 2.0) if best_dir == "LONG" else price - (stop_dist * 2.0)
            target2 = price + (stop_dist * 4.0) if best_dir == "LONG" else price - (stop_dist * 4.0)
            rr_ratio = abs(target1 - price) / stop_dist if stop_dist > 0 else 0
            
            sig = assemble_and_send_signal(
                symbol=sym, direction=best_dir,
                regime=reg["regime_1h"], btc_macro=btc_macro, rs=rs.to_relative_strength(),
                futures=fut.to_futures_data(), sr=sr.to_sr_levels(), entry=ent.to_entry_signal("CLOSED"),
                confidence=conf, entry_price=price, stop_loss=stop_loss, target1=target1, target2=target2,
                rr_ratio=rr_ratio, position_size_pct=vty.position_size_pct, invalidation_price=stop_loss,
                trend_tag=tq.overextension_tag, vol_tag=volm.volume_classification, vol_env=vty.high_vol_environment,
                matrix_stale=stale_matrix, volume_z=volm.volume_z_score, ema_price=price
            )
            
            if mode in ("paper", "live"):
                if conf.final_score >= 72:
                    if volm.volume_z_score >= 0.5:
                        open_paper_position(
                            symbol=sym,
                            direction=best_dir,
                            entry_price=price,
                            stop_loss=stop_loss,
                            target1=target1,
                            target2=target2,
                            size_pct=vty.position_size_pct
                        )
                    else:
                        logger.info(f"Signal for {sym} skipped paper trade due to low volume (Z-Score: {volm.volume_z_score:.2f} < 0.5)")
            
        return res
        
    except Exception as e:
        logger.error(f"Error processing {sym}: {e}\n{traceback.format_exc()}")
        send_api_warning(f"Pipeline Error on {sym}", str(e))
        res['decision'] = "ERROR"
        return res


def run_cycle(symbols: list, mode: str):
    global cycle_count
    cycle_count += 1
    start_time = time.time()
    logger.info(f"=== Starting Cycle {cycle_count} ({mode}) ===")
    
    update_correlation_matrix()
    _refresh_daily_volume_cache(symbols)
    
    btc_1h = fetch_ohlcv("BTCUSDT", "1h")
    btc_4h = fetch_ohlcv("BTCUSDT", "4h")
    
    if btc_1h is None or btc_4h is None:
        logger.error("Failed to fetch BTC base data. Aborting cycle.")
        return
        
    btc_macro = analyze_btc_macro(btc_1h, btc_4h)
    
    results = Parallel(n_jobs=2, prefer="threads")(
        delayed(analyze_symbol)(sym, btc_1h, btc_4h, btc_macro, mode) for sym in symbols
    )
    
    signals_fired = sum(1 for r in results if r.get('decision') == "SIGNAL_APPROVED")
    
    if mode == "dry-run":
        for r in results:
            _print_dry_run_summary(r['symbol'], r)
            
    if mode in ("paper", "live"):
        current_prices = {r['symbol']: r.get('current_price') for r in results if r.get('current_price') is not None}
        check_paper_positions(current_prices)
        run_daily_summary_check()
            
    duration = time.time() - start_time
    logger.info(f"=== Cycle {cycle_count} Complete | Duration: {duration:.1f}s | Signals: {signals_fired} ===")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["dry-run", "paper", "live", "backtest"], default="dry-run")
    parser.add_argument("--symbol", type=str, help="Run single symbol")
    parser.add_argument("--years", type=int, default=3, help="Years of data for backtest")
    parser.add_argument("--force-live", action="store_true", help="Override live gate")
    args = parser.parse_args()
    
    symbols = [args.symbol] if args.symbol else cfg.symbols
    
    print("================================================================================")
    print("🚀 INSTITUTIONAL CRYPTO SIGNAL ENGINE")
    print(f"Mode: {args.mode.upper()}")
    print(f"Symbols: {len(symbols)} tracked")
    print("================================================================================")
    
    if args.mode == "backtest":
        if not args.symbol:
            print("[FAIL] --symbol is required for backtest mode.")
            sys.exit(1)
            
        from signal_engine.backtester.engine import BacktestEngine
        from signal_engine.backtester.report import generate_report
        
        bt = BacktestEngine(args.symbol, args.years)
        bt.run()
        generate_report(bt.trades)
        sys.exit(0)
        
    # Startup Checks
    webhook_sys = os.getenv("DISCORD_WEBHOOK_SYSTEM")
    if webhook_sys:
        print(f"[DEBUG] DISCORD_WEBHOOK_SYSTEM loaded. Length: {len(webhook_sys)}. Starts with: {webhook_sys[:40]}...")
        if args.mode != "dry-run":
            print(f"[DEBUG] Attempting to send startup test message to {webhook_sys[:40]}...")
            try:
                import requests
                r = requests.post(webhook_sys, json={"content": "🚀 Railway startup test"}, timeout=10.0)
                print(f"[DEBUG] Startup test response: {r.status_code} - {r.text}")
                r.raise_for_status()
            except Exception as e:
                import traceback
                print(f"[DEBUG] Startup test FAILED: {e}")
                traceback.print_exc()
    elif args.mode != "dry-run":
        print("[FAIL] DISCORD_WEBHOOK_SYSTEM missing in .env")
        sys.exit(1)
        
    if args.mode == "live" and not args.force_live:
        if not os.path.exists(cfg.state_file.replace("engine_state", "paper_state")):
            print("[FAIL] Cannot enter live mode without 14-day paper_state.json history.")
            print("Use --force-live to override.")
            sys.exit(1)
            
    if args.force_live:
        print("\n⚠️ WARNING: FORCING LIVE MODE WITHOUT 14-DAY GATE ⚠️\n")
        
    # Initial run
    run_cycle(symbols, args.mode)
    
    # Schedule
    schedule.every(15).minutes.do(run_cycle, symbols=symbols, mode=args.mode)
    
    print("\n[Scheduler Active] Running every 15 minutes. Press Ctrl+C to exit.\n")
    try:
        while True:
            schedule.run_pending()
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutdown requested. Exiting.")


if __name__ == "__main__":
    main()
