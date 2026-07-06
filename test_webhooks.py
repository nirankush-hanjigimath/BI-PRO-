import os
from signal_engine.config import cfg
from signal_engine.utils.alerts import _post_embed

def test_webhook():
    print("Testing Webhooks...")
    webhooks = [
        ("A+ Channel", cfg.discord_webhook_a_plus, "@everyone"),
        ("A Channel", cfg.discord_webhook_a, "@here"),
        ("B Channel", cfg.discord_webhook_b, None),
        ("C Channel", cfg.discord_webhook_c, None),
        ("System Channel", cfg.discord_webhook_system, "@here"),
    ]
    
    for name, url, content in webhooks:
        if not url:
            print(f"Skipping {name} (URL missing)")
            continue
        print(f"Sending test to {name}...")
        ok = _post_embed(
            "SIGNAL",
            f"Test from Engine: {name}",
            f"This is a test message to verify routing to {name}.",
            webhook_url=url,
            content=content
        )
        print(f"Result for {name}: {'OK' if ok else 'FAIL'}")

if __name__ == "__main__":
    test_webhook()
