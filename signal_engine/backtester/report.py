"""
signal_engine/backtester/report.py
Generates performance metrics and reports for the backtester.
"""

import os
import pandas as pd
import numpy as np
from datetime import timezone

def generate_report(trades: list):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    results_dir = os.path.join(base_dir, "results")
    os.makedirs(results_dir, exist_ok=True)
    report_path = os.path.join(results_dir, "report.txt")
    
    output = []
    def _print(msg=""):
        print(msg)
        output.append(msg)
        
    _print("================================================================================")
    _print("🚀 INSTITUTIONAL CRYPTO SIGNAL ENGINE - BACKTEST REPORT")
    _print("⚠️ Futures data and liquidity gate mocked to neutral — live results may differ")
    _print("================================================================================\n")
    
    if not trades:
        _print("INSUFFICIENT TRADE COUNT — results not statistically valid (0 trades)")
        with open(report_path, "w", encoding="utf-8") as f:
            f.write("\n".join(output))
        return
        
    # Aggregate partial trades into full positions
    positions = {}
    for t in trades:
        k = t['entry_time']
        if k not in positions:
            positions[k] = {
                'entry_time': t['entry_time'],
                'close_time': t['close_time'],
                'net_usd': 0.0,
                'r_multiple': 0.0,
                'wins': 0,
                'losses': 0
            }
        
        positions[k]['net_usd'] += t['net_usd']
        positions[k]['r_multiple'] += t['r_multiple']
        positions[k]['close_time'] = max(positions[k]['close_time'], t['close_time'])
        
    # Convert to list and determine win/loss per position
    pos_list = sorted(list(positions.values()), key=lambda x: x['entry_time'])
    
    for p in pos_list:
        if p['net_usd'] > 0:
            p['is_win'] = True
        else:
            p['is_win'] = False
            
    total_trades = len(pos_list)
    
    if total_trades < 100:
        _print("INSUFFICIENT TRADE COUNT — results not statistically valid (needs 100+ trades)")
        _print(f"Total Trades Generated: {total_trades}\n")
    else:
        _print(f"Total Trades Generated: {total_trades}\n")
        
    wins = [p for p in pos_list if p['is_win']]
    losses = [p for p in pos_list if not p['is_win']]
    
    win_rate = len(wins) / total_trades if total_trades > 0 else 0
    gross_profit = sum(p['net_usd'] for p in wins)
    gross_loss = abs(sum(p['net_usd'] for p in losses))
    
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
    avg_r = sum(p['r_multiple'] for p in pos_list) / total_trades if total_trades > 0 else 0
    
    avg_win = gross_profit / len(wins) if wins else 0
    avg_loss = gross_loss / len(losses) if losses else 0
    expectancy = (win_rate * avg_win) - ((1 - win_rate) * avg_loss)
    
    # Calculate equity curve and Max Drawdown
    equity = 1000.0  # Starting balance
    peak = equity
    max_dd_pct = 0.0
    
    equity_curve = []
    
    consec_losses = 0
    max_consec_losses = 0
    dd_streak_flag = False
    
    for p in pos_list:
        if not p['is_win']:
            consec_losses += 1
            if consec_losses >= 8:
                dd_streak_flag = True
        else:
            consec_losses = 0
            
        if consec_losses > max_consec_losses:
            max_consec_losses = consec_losses
            
        equity += p['net_usd']
        if equity > peak:
            peak = equity
            
        dd = (peak - equity) / peak
        if dd > max_dd_pct:
            max_dd_pct = dd
            
        equity_curve.append(equity)
        
    # Calculate Sharpe Ratio (simplified, assuming risk-free rate = 0)
    # Using returns per trade
    returns = [p['net_usd'] / 1000.0 for p in pos_list] # approx relative to starting bal
    if len(returns) > 1:
        ret_series = pd.Series(returns)
        # Annualize assuming approx trades per year
        trades_per_year = total_trades / 3.0
        sharpe = (ret_series.mean() / ret_series.std()) * np.sqrt(trades_per_year) if ret_series.std() != 0 else 0
    else:
        sharpe = 0.0
        
    _print(f"--- OVERALL METRICS ---")
    _print(f"Profit Factor:      {profit_factor:.2f}")
    _print(f"Sharpe Ratio:       {sharpe:.2f}")
    _print(f"Win Rate:           {win_rate*100:.1f}%")
    _print(f"Max Drawdown:       {max_dd_pct*100:.1f}%")
    _print(f"Average R Multiple: {avg_r:.2f}R")
    _print(f"Expectancy/Trade:   ${expectancy:.2f}")
    
    if dd_streak_flag:
        _print(f"Max Consec Losses:  {max_consec_losses} [MAX_DRAWDOWN_STREAK]")
    else:
        _print(f"Max Consec Losses:  {max_consec_losses}")
    _print()
    
    # Monthly Returns
    _print("--- MONTHLY RETURNS ---")
    df = pd.DataFrame(pos_list)
    df['month'] = df['entry_time'].dt.to_period('M')
    monthly = df.groupby('month')['net_usd'].sum()
    
    for m, val in monthly.items():
        color_str = "🟢 GREEN" if val >= 0 else "🔴 RED"
        _print(f"{m}: ${val:>7.2f}  {color_str}")
    _print()
    
    # 6-Month Periods
    _print("--- 6-MONTH PERIOD ANALYSIS ---")
    # Split into 6-month bins
    if len(df) > 0:
        start_date = df['entry_time'].min()
        
        # We can just group by 6 month intervals manually
        df['6m_period'] = ((df['entry_time'].dt.year - start_date.year) * 12 + df['entry_time'].dt.month - start_date.month) // 6
        
        periods = df.groupby('6m_period')
        for name, group in periods:
            p_start = group['entry_time'].min().strftime('%Y-%m')
            p_end = group['entry_time'].max().strftime('%Y-%m')
            
            gwins = group[group['is_win']]
            glosses = group[~group['is_win']]
            gp = gwins['net_usd'].sum() if len(gwins) > 0 else 0
            gl = abs(glosses['net_usd'].sum()) if len(glosses) > 0 else 0
            pf = gp / gl if gl > 0 else float('inf')
            
            g_ret = group['net_usd'] / 1000.0
            if len(g_ret) > 1 and g_ret.std() != 0:
                # Annualize for a 6 month period
                ann_factor = len(group) * 2 
                sh = (g_ret.mean() / g_ret.std()) * np.sqrt(ann_factor)
            else:
                sh = 0.0
                
            flag = ""
            if sh < 0.5 or pf < 1.2:
                flag = " [WEAK PERIOD]"
                
            _print(f"Period {name} ({p_start} to {p_end}): Trades={len(group)} | PF={pf:.2f} | Sharpe={sh:.2f}{flag}")
    _print()
    
    _print("--- CALIBRATION CHECK ---")
    if sharpe < 1.0 or profit_factor < 1.5:
        _print("SYSTEM NEEDS RECALIBRATION BEFORE GOING LIVE")
    else:
        _print("SYSTEM VALIDATED — ready for paper trading confirmation")
        
    _print("================================================================================")
    
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(output))
    print(f"\nReport saved to {report_path}")
    
    # --- Discord Completion Alert ---
    metrics = {
        'profit_factor': profit_factor,
        'sharpe': sharpe,
        'win_rate': win_rate * 100,
        'max_drawdown': max_dd_pct * 100,
        'total_trades': total_trades,
        'avg_r': avg_r
    }
    
    try:
        send_completion_alert(metrics)
    except Exception as e:
        print(f"Failed to send Discord alert: {e}")

def send_completion_alert(metrics):
    import requests
    import os
    from datetime import datetime
    
    color = 0x00ff88 if metrics['sharpe'] >= 1.0 and metrics['profit_factor'] >= 1.5 else 0xff4444
    
    payload = {
        "embeds": [{
            "title": "✅ Backtest Complete — BTCUSDT 3 Years",
            "color": color,
            "fields": [
                {"name": "Profit Factor", "value": str(round(metrics['profit_factor'], 2)), "inline": True},
                {"name": "Sharpe Ratio", "value": str(round(metrics['sharpe'], 2)), "inline": True},
                {"name": "Win Rate", "value": str(round(metrics['win_rate'], 1)) + "%", "inline": True},
                {"name": "Max Drawdown", "value": str(round(metrics['max_drawdown'], 1)) + "%", "inline": True},
                {"name": "Total Trades", "value": str(metrics['total_trades']), "inline": True},
                {"name": "Avg R Multiple", "value": str(round(metrics['avg_r'], 2)), "inline": True},
                {"name": "Verdict", "value": "✅ SYSTEM VALIDATED" if color == 0x00ff88 else "❌ NEEDS RECALIBRATION", "inline": False}
            ],
            "footer": {"text": "Institutional Signal Engine • Backtest Report"},
            "timestamp": datetime.utcnow().isoformat()
        }]
    }
    
    webhook = os.getenv("DISCORD_WEBHOOK_URL")
    if webhook:
        requests.post(webhook, json=payload)
    else:
        print("DISCORD_WEBHOOK_URL not set, skipping completion alert.")

