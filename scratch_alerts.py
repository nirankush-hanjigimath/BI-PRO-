import os

fpath = r"c:\Users\Nirankush\Desktop\FYP\Binance Trading\signal_engine\utils\alerts.py"
with open(fpath, "r", encoding="utf-8") as f:
    text = f.read()

# 1. Routing function
new_routing = """
def get_webhook_for_grade(grade):
    from signal_engine.config import cfg
    if grade == 'A+':
        return cfg.discord_webhook_a_plus
    elif grade == 'A':
        return cfg.discord_webhook_a
    elif grade == 'B':
        return cfg.discord_webhook_b
    elif grade == 'C':
        return cfg.discord_webhook_c if cfg.send_grade_c else None
    else:
        return None

def _get_webhook() -> Optional[str]:
    from signal_engine.config import cfg
    url = cfg.discord_webhook_system
    if not url:
        _log.error("SYSTEM webhook is not set in .env — alert skipped")
        return None
    return url
"""

old_routing = """def _get_webhook() -> Optional[str]:
    url = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
    if not url:
        _log.error("DISCORD_WEBHOOK_URL is not set in .env — alert skipped")
        return None
    return url"""

text = text.replace(old_routing, new_routing.strip())

# 2. _post_embed signature and payload
old_post = """    footer_text: Optional[str] = None,
    webhook_url: Optional[str] = None,
) -> bool:
    \"\"\"
    Core sender. Returns True on success, False on any failure.
    NEVER raises — all exceptions are caught and logged.
    \"\"\"
    from signal_engine.config import cfg
    if getattr(cfg, 'mode', None) == 'backtest':
        return False
    url = webhook_url or _get_webhook()
    if not url:
        return False

    embed   = _build_embed(alert_type, title, description, fields, symbol, footer_text)
    payload = json.dumps({"embeds": [embed]})"""

new_post = """    footer_text: Optional[str] = None,
    webhook_url: Optional[str] = None,
    content: Optional[str] = None,
) -> bool:
    \"\"\"
    Core sender. Returns True on success, False on any failure.
    NEVER raises — all exceptions are caught and logged.
    \"\"\"
    from signal_engine.config import cfg
    if getattr(cfg, 'mode', None) == 'backtest':
        return False
    url = webhook_url or _get_webhook()
    if not url:
        return False

    embed   = _build_embed(alert_type, title, description, fields, symbol, footer_text)
    payload_dict = {"embeds": [embed]}
    if content:
        payload_dict["content"] = content
    payload = json.dumps(payload_dict)"""

text = text.replace(old_post, new_post)

# 3. Add @here to loss limits
old_dll = """    return _post_embed(
        "CRITICAL",
        "🛑 Daily Loss Limit Hit — Signals Halted","""

new_dll = """    return _post_embed(
        "CRITICAL",
        "🛑 Daily Loss Limit Hit — Signals Halted","""

# Wait, I'll just replace the whole return statement of loss limits
old_dll2 = """    return _post_embed(
        "CRITICAL",
        "🛑 Daily Loss Limit Hit — Signals Halted",
        (
            f"Portfolio drawdown today: **−{abs(current_loss_pct):.2f}%**\\n"
            f"Daily limit: **−3.00%**\\n"
            f"Virtual account: **${account_usd:,.2f}**\\n\\n"
            "All signals halted for the rest of this UTC day.\\n"
            "Signals resume automatically at **00:00 UTC**."
        ),
    )"""

new_dll2 = """    return _post_embed(
        "CRITICAL",
        "🛑 Daily Loss Limit Hit — Signals Halted",
        (
            f"Portfolio drawdown today: **−{abs(current_loss_pct):.2f}%**\\n"
            f"Daily limit: **−3.00%**\\n"
            f"Virtual account: **${account_usd:,.2f}**\\n\\n"
            "All signals halted for the rest of this UTC day.\\n"
            "Signals resume automatically at **00:00 UTC**."
        ),
        content="@here"
    )"""

old_wll = """    return _post_embed(
        "CRITICAL",
        "🚨 Weekly Loss Limit Hit — Manual Reset Required",
        (
            f"Portfolio drawdown this week: **−{abs(current_loss_pct):.2f}%**\\n"
            f"Weekly limit: **−8.00%**\\n"
            f"Virtual account: **${account_usd:,.2f}**\\n\\n"
            "All signals **permanently halted** until manual reset.\\n"
            "To resume: delete or reset the `weekly_halted` flag in `engine_state.json`."
        ),
    )"""

new_wll = """    return _post_embed(
        "CRITICAL",
        "🚨 Weekly Loss Limit Hit — Manual Reset Required",
        (
            f"Portfolio drawdown this week: **−{abs(current_loss_pct):.2f}%**\\n"
            f"Weekly limit: **−8.00%**\\n"
            f"Virtual account: **${account_usd:,.2f}**\\n\\n"
            "All signals **permanently halted** until manual reset.\\n"
            "To resume: delete or reset the `weekly_halted` flag in `engine_state.json`."
        ),
        content="@here"
    )"""

text = text.replace(old_dll2, new_dll2).replace(old_wll, new_wll)

with open(fpath, "w", encoding="utf-8") as f:
    f.write(text)

print("Updated alerts.py")
