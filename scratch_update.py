import sys

def replace_in_file(filepath, old_text, new_text):
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
    content = content.replace(old_text, new_text)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)

# Fix run_signal_engine.py
replace_in_file(
    r"c:\Users\Nirankush\Desktop\FYP\Binance Trading\run_signal_engine.py",
    "position_size_pct=vty.final_position_size_pct,",
    "position_size_pct=vty.position_size_pct,"
)

# Fix engine.py
replace_in_file(
    r"c:\Users\Nirankush\Desktop\FYP\Binance Trading\signal_engine\backtester\engine.py",
    "\"size_pct\": vty.final_position_size_pct,",
    "\"size_pct\": vty.position_size_pct,"
)

print("Attribute bugs fixed.")
