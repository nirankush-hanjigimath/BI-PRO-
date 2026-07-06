import os
import re

env_path = r"c:\Users\Nirankush\Desktop\FYP\Binance Trading\.env"
with open(env_path, "r", encoding="utf-8") as f:
    lines = f.readlines()

new_lines = []
for line in lines:
    if line.strip().startswith("DISCORD_WEBHOOK_URL"):
        new_lines.append(f"# {line}")
    else:
        new_lines.append(line)

with open(env_path, "w", encoding="utf-8") as f:
    f.writelines(new_lines)
    
print(".env patched.")

# Also fix the paper_trader.py
pt_path = r"c:\Users\Nirankush\Desktop\FYP\Binance Trading\signal_engine\paper_trader.py"
with open(pt_path, "r", encoding="utf-8") as f:
    pt_text = f.read()

pt_old = """    webhook_url = os.getenv("DISCORD_WEBHOOK_URL")"""
pt_new = """    webhook_url = cfg.discord_webhook_system"""

# Wait, `cfg` is imported? Let's check:
# if not imported, `from signal_engine.config import cfg` is usually there, but let's just do it directly.
if "webhook_url = os.getenv(\"DISCORD_WEBHOOK_URL\")" in pt_text:
    pt_text = pt_text.replace("webhook_url = os.getenv(\"DISCORD_WEBHOOK_URL\")", "from signal_engine.config import cfg\\n    webhook_url = cfg.discord_webhook_system")
    with open(pt_path, "w", encoding="utf-8") as f:
        f.write(pt_text)
    print("paper_trader.py patched.")

# Fix run_signal_engine.py
rs_path = r"c:\Users\Nirankush\Desktop\FYP\Binance Trading\run_signal_engine.py"
with open(rs_path, "r", encoding="utf-8") as f:
    rs_text = f.read()
    
rs_old = """    if not os.getenv("DISCORD_WEBHOOK_URL") and args.mode != "dry-run":
        print("[FAIL] DISCORD_WEBHOOK_URL missing in .env")
        sys.exit(1)"""

rs_new = """    if not os.getenv("DISCORD_WEBHOOK_SYSTEM") and args.mode != "dry-run":
        print("[FAIL] DISCORD_WEBHOOK_SYSTEM missing in .env")
        sys.exit(1)"""
        
if rs_old in rs_text:
    rs_text = rs_text.replace(rs_old, rs_new)
    with open(rs_path, "w", encoding="utf-8") as f:
        f.write(rs_text)
    print("run_signal_engine.py patched.")

# Fix alert_sender.py
al_path = r"c:\Users\Nirankush\Desktop\FYP\Binance Trading\alert_sender.py"
with open(al_path, "r", encoding="utf-8") as f:
    al_text = f.read()
    
al_text = al_text.replace("os.environ.get(\"DISCORD_WEBHOOK_URL\"", "os.environ.get(\"DISCORD_WEBHOOK_SYSTEM\"")
with open(al_path, "w", encoding="utf-8") as f:
    f.write(al_text)
print("alert_sender.py patched.")

