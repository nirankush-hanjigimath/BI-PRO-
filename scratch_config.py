import os

fpath = r"c:\Users\Nirankush\Desktop\FYP\Binance Trading\signal_engine\config.py"
with open(fpath, "r", encoding="utf-8") as f:
    text = f.read()

# 1. Dataclass
old_dc = """    # External (from .env)
    discord_webhook_url: str"""

new_dc = """    # Discord routing
    discord_webhook_a_plus: str
    discord_webhook_a: str
    discord_webhook_b: str
    discord_webhook_c: str
    discord_webhook_system: str
    send_grade_c: bool"""

# 2. _load() validation
old_val = """    # 3. Validate required env vars
    discord_url = _require_env("DISCORD_WEBHOOK_URL")"""

new_val = """    # 3. Discord webhooks from .env
    webhook_a_plus = os.getenv("DISCORD_WEBHOOK_A_PLUS", "")
    webhook_a = os.getenv("DISCORD_WEBHOOK_A", "")
    webhook_b = os.getenv("DISCORD_WEBHOOK_B", "")
    webhook_c = os.getenv("DISCORD_WEBHOOK_C", "")
    webhook_system = _require_env("DISCORD_WEBHOOK_SYSTEM")  # At least system is required"""

# 3. _load() return
old_ret = """        # Discord (from .env)
        discord_webhook_url = discord_url,"""

new_ret = """        # Discord
        discord_webhook_a_plus = webhook_a_plus,
        discord_webhook_a = webhook_a,
        discord_webhook_b = webhook_b,
        discord_webhook_c = webhook_c,
        discord_webhook_system = webhook_system,
        send_grade_c = bool(y.get("discord", {}).get("send_grade_c", False)),"""

# 4. Standalone print
old_pr = """    print("\\n[DISCORD]")
    masked = cfg.discord_webhook_url[:40] + "..." if len(cfg.discord_webhook_url) > 40 else cfg.discord_webhook_url
    row("discord_webhook_url",           masked)"""

new_pr = """    print("\\n[DISCORD]")
    row("webhook_a_plus", bool(cfg.discord_webhook_a_plus))
    row("webhook_a", bool(cfg.discord_webhook_a))
    row("webhook_b", bool(cfg.discord_webhook_b))
    row("webhook_c", bool(cfg.discord_webhook_c))
    row("webhook_system", bool(cfg.discord_webhook_system))
    row("send_grade_c", cfg.send_grade_c)"""

text = text.replace(old_dc, new_dc).replace(old_val, new_val).replace(old_ret, new_ret).replace(old_pr, new_pr)

with open(fpath, "w", encoding="utf-8") as f:
    f.write(text)

print("Updated config.py")
