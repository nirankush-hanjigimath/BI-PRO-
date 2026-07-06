import yaml

with open(r"c:\Users\Nirankush\Desktop\FYP\Binance Trading\config.yaml", "r", encoding="utf-8") as f:
    text = f.read()

insert_text = """
# ── Discord ───────────────────────────────────────────────────────────────────
discord:
  webhook_a_plus: ${DISCORD_WEBHOOK_A_PLUS}
  webhook_a: ${DISCORD_WEBHOOK_A}
  webhook_b: ${DISCORD_WEBHOOK_B}
  webhook_c: ${DISCORD_WEBHOOK_C}
  webhook_system: ${DISCORD_WEBHOOK_SYSTEM}
  send_grade_c: false

# ── Paper trading ─────────────────────────────────────────────────────────────"""

text = text.replace("# ── Paper trading ─────────────────────────────────────────────────────────────", insert_text)

with open(r"c:\Users\Nirankush\Desktop\FYP\Binance Trading\config.yaml", "w", encoding="utf-8") as f:
    f.write(text)

print("Updated config.yaml")
