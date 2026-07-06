import os

fpath = r"c:\Users\Nirankush\Desktop\FYP\Binance Trading\signal_engine\stage13_signal_output.py"
with open(fpath, "r", encoding="utf-8") as f:
    text = f.read()

# Remove legacy discord webhook loading
old_load = """load_dotenv()
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")"""

new_load = """load_dotenv()

last_signal_time = {}"""
text = text.replace(old_load, new_load)

# _post_discord signature
old_post = """def _post_discord(embed: dict) -> bool:
    \"\"\"Sends the embed to the Discord webhook.\"\"\"
    from signal_engine.config import cfg
    if getattr(cfg, 'mode', None) == 'backtest':
        return False
    slog = get_logger("STAGE13", "DISCORD")
    if not DISCORD_WEBHOOK_URL:
        slog.error("DISCORD_WEBHOOK_URL not set in .env")
        return False
        
    data = {"embeds": [embed]}
    try:
        r = requests.post(DISCORD_WEBHOOK_URL, json=data, timeout=5.0)"""

new_post = """def _post_discord(embed: dict, webhook_url: str = None, content: str = None) -> bool:
    \"\"\"Sends the embed to the Discord webhook.\"\"\"
    from signal_engine.config import cfg
    if getattr(cfg, 'mode', None) == 'backtest':
        return False
    slog = get_logger("STAGE13", "DISCORD")
    
    url = webhook_url or getattr(cfg, 'discord_webhook_system', None)
    if not url:
        slog.error("No valid webhook URL found.")
        return False
        
    data = {"embeds": [embed]}
    if content:
        data["content"] = content
    try:
        r = requests.post(url, json=data, timeout=5.0)"""

text = text.replace(old_post, new_post)


# deduplication in assemble_and_send_signal
old_assemble = """    slog = get_logger("STAGE13", symbol)
    slog.info(f"Assembling signal for {direction} with Grade {confidence.grade}...")

    # Combine tags for risks"""

new_assemble = """    slog = get_logger("STAGE13", symbol)
    
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    if symbol in last_signal_time:
        diff_mins = (now_utc - last_signal_time[symbol]).total_seconds() / 60.0
        if diff_mins < 10.0:
            slog.info(f"Deduplication triggered: dropping duplicate {symbol} signal ({diff_mins:.1f}m since last)")
            return Signal(
                symbol=symbol, direction=direction, timestamp=now_utc,
                regime=regime, btc_macro=btc_macro, relative_strength=rs, futures=futures, sr=sr, entry=entry, confidence=confidence,
                entry_price=entry_price, stop_loss=stop_loss, target1=target1, target2=target2, rr_ratio=rr_ratio,
                position_size_pct=position_size_pct, invalidation_price=invalidation_price, narrative="", risks="", tags=[]
            )
            
    last_signal_time[symbol] = now_utc
    slog.info(f"Assembling signal for {direction} with Grade {confidence.grade}...")

    # Combine tags for risks"""

text = text.replace(old_assemble, new_assemble)

# Route embed based on grade
old_embed_send = """    _post_discord(embed)
    return sig_obj"""

new_embed_send = """    from signal_engine.utils.alerts import get_webhook_for_grade
    webhook_url = get_webhook_for_grade(confidence.grade)
    
    if not webhook_url:
        slog.info(f"No webhook configured for grade {confidence.grade}, or sending disabled.")
        return sig_obj
        
    content_str = None
    if confidence.grade == 'A+':
        content_str = "@everyone"
    elif confidence.grade == 'A':
        content_str = "@here"
        
    _post_discord(embed, webhook_url=webhook_url, content=content_str)
    return sig_obj"""

text = text.replace(old_embed_send, new_embed_send)


with open(fpath, "w", encoding="utf-8") as f:
    f.write(text)

print("Updated stage13_signal_output.py")
