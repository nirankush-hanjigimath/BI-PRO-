import sys

with open(r"c:\Users\Nirankush\Desktop\FYP\Binance Trading\signal_engine\backtester\report.py", "r", encoding="utf-8") as f:
    report = f.read()

new_code = """    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\\n".join(output))
    print(f"\\nReport saved to {report_path}")
    
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
"""

report = report.replace(
'''    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\\n".join(output))
    print(f"\\nReport saved to {report_path}")''',
new_code
)

with open(r"c:\Users\Nirankush\Desktop\FYP\Binance Trading\signal_engine\backtester\report.py", "w", encoding="utf-8") as f:
    f.write(report)

print("Updated report.py successfully.")
