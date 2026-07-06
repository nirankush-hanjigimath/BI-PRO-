import os

# 1. stage13_signal_output.py
f13 = r"c:\Users\Nirankush\Desktop\FYP\Binance Trading\signal_engine\stage13_signal_output.py"
with open(f13, "r", encoding="utf-8") as f:
    text13 = f.read()

old13 = """            {"name": "Entry", "value": f"${entry_price:,.4f}", "inline": True},
            {"name": "Stop Loss", "value": f"${stop_loss:,.4f} (Swing)", "inline": True},
            {"name": "Target 1 (1R)", "value": f"${target1:,.4f} ← close 50% here", "inline": True},
            {"name": "Target 2 (2R)", "value": f"${target2:,.4f} ← trail stop after", "inline": True},
            {"name": "R:R Ratio", "value": f"{rr_ratio:.2f}:1", "inline": True},
            {"name": "Position Size", "value": f"{position_size_pct:.1f}% of account", "inline": True},
            {"name": "Invalidation", "value": f"${invalidation_price:,.4f} — if breached thesis is wrong", "inline": False},"""

new13 = """            {"name": "Entry", "value": f"${entry_price:,.4f}" if entry_price is not None else "N/A", "inline": True},
            {"name": "Stop Loss", "value": f"${stop_loss:,.4f} (Swing)" if stop_loss is not None else "N/A", "inline": True},
            {"name": "Target 1 (1R)", "value": f"${target1:,.4f} ← close 50% here" if target1 is not None else "N/A", "inline": True},
            {"name": "Target 2 (2R)", "value": f"${target2:,.4f} ← trail stop after" if target2 is not None else "N/A", "inline": True},
            {"name": "R:R Ratio", "value": f"{rr_ratio:.2f}:1" if rr_ratio is not None else "N/A", "inline": True},
            {"name": "Position Size", "value": f"{position_size_pct:.1f}% of account" if position_size_pct is not None else "N/A", "inline": True},
            {"name": "Invalidation", "value": f"${invalidation_price:,.4f} — if breached thesis is wrong" if invalidation_price is not None else "N/A", "inline": False},"""

text13 = text13.replace(old13, new13)
with open(f13, "w", encoding="utf-8") as f:
    f.write(text13)


# 2. stage10_support_resistance.py
f10 = r"c:\Users\Nirankush\Desktop\FYP\Binance Trading\signal_engine\stage10_support_resistance.py"
with open(f10, "r", encoding="utf-8") as f:
    text10 = f.read()

old10_1 = """    slog.info(f"Nearest Res: {nearest_res} ({nearest_res_pct:+.2f}%) | Nearest Sup: {nearest_sup} ({nearest_sup_pct:+.2f}%)")"""
new10_1 = """    res_p = f"{nearest_res_pct:+.2f}%" if nearest_res_pct is not None else "N/A"
    sup_p = f"{nearest_sup_pct:+.2f}%" if nearest_sup_pct is not None else "N/A"
    slog.info(f"Nearest Res: {nearest_res} ({res_p}) | Nearest Sup: {nearest_sup} ({sup_p})")"""

old10_2 = """    if not reject:
        slog.info(f"S/R Check PASSED. Final T1={adj_target1:.2f} R:R={adj_rr:.2f}")"""
new10_2 = """    if not reject:
        t1_s = f"{adj_target1:.2f}" if adj_target1 is not None else "N/A"
        rr_s = f"{adj_rr:.2f}" if adj_rr is not None else "N/A"
        slog.info(f"S/R Check PASSED. Final T1={t1_s} R:R={rr_s}")"""

text10 = text10.replace(old10_1, new10_1).replace(old10_2, new10_2)

# Also check lines 161 and 175 inside stage10
old10_3 = """                reason = f"SR_REJECT: Nearest resistance ({nearest_res:.2f}) is only {nearest_res_pct:.2f}% above entry (< 0.8%)\""""
new10_3 = """                r_res = f"{nearest_res:.2f}" if nearest_res is not None else "N/A"
                r_pct = f"{nearest_res_pct:.2f}" if nearest_res_pct is not None else "N/A"
                reason = f"SR_REJECT: Nearest resistance ({r_res}) is only {r_pct}% above entry (< 0.8%)\""""

old10_4 = """                reason = f"SR_REJECT: Nearest support ({nearest_sup:.2f}) is only {nearest_sup_pct:.2f}% below entry (< 0.8%)\""""
new10_4 = """                s_sup = f"{nearest_sup:.2f}" if nearest_sup is not None else "N/A"
                s_pct = f"{nearest_sup_pct:.2f}" if nearest_sup_pct is not None else "N/A"
                reason = f"SR_REJECT: Nearest support ({s_sup}) is only {s_pct}% below entry (< 0.8%)\""""
                
old10_5 = """                    slog.info(f"Target1 {target1:.2f} obstructed by resistance {nearest_res:.2f}. Adjusting Target1.")"""
new10_5 = """                    t1_f = f"{target1:.2f}" if target1 is not None else "N/A"
                    nr_f = f"{nearest_res:.2f}" if nearest_res is not None else "N/A"
                    slog.info(f"Target1 {t1_f} obstructed by resistance {nr_f}. Adjusting Target1.")"""

old10_6 = """                    slog.info(f"Target1 {target1:.2f} obstructed by support {nearest_sup:.2f}. Adjusting Target1.")"""
new10_6 = """                    t1_f = f"{target1:.2f}" if target1 is not None else "N/A"
                    ns_f = f"{nearest_sup:.2f}" if nearest_sup is not None else "N/A"
                    slog.info(f"Target1 {t1_f} obstructed by support {ns_f}. Adjusting Target1.")"""

text10 = text10.replace(old10_3, new10_3).replace(old10_4, new10_4).replace(old10_5, new10_5).replace(old10_6, new10_6)

with open(f10, "w", encoding="utf-8") as f:
    f.write(text10)


# 3. stage08_volatility.py
f8 = r"c:\Users\Nirankush\Desktop\FYP\Binance Trading\signal_engine\stage08_volatility.py"
with open(f8, "r", encoding="utf-8") as f:
    text8 = f.read()
    
old8 = """    slog.info(
        f"Vol 7d={vol_7d:.1f}% 30d={vol_30d:.1f}% | High Vol Env={high_vol_env} ({data_quality})"
    )
    slog.info(
        f"Stop Base={base_stop:.4f} Swing={swing_stop_dist:.4f} → Final={final_stop_pct:.2f}%"
    )
    slog.info(
        f"Risk=${risk_amount:.2f} → Pos Size=${position_size_usd:.2f} ({pos_size_pct:.1f}%)"
    )"""

new8 = """    v7 = f"{vol_7d:.1f}" if vol_7d is not None else "N/A"
    v30 = f"{vol_30d:.1f}" if vol_30d is not None else "N/A"
    slog.info(
        f"Vol 7d={v7}% 30d={v30}% | High Vol Env={high_vol_env} ({data_quality})"
    )
    sb = f"{base_stop:.4f}" if base_stop is not None else "N/A"
    ss = f"{swing_stop_dist:.4f}" if swing_stop_dist is not None else "N/A"
    sf = f"{final_stop_pct:.2f}" if final_stop_pct is not None else "N/A"
    slog.info(
        f"Stop Base={sb} Swing={ss} → Final={sf}%"
    )
    ra = f"{risk_amount:.2f}" if risk_amount is not None else "N/A"
    psu = f"{position_size_usd:.2f}" if position_size_usd is not None else "N/A"
    psp = f"{pos_size_pct:.1f}" if pos_size_pct is not None else "N/A"
    slog.info(
        f"Risk=${ra} → Pos Size=${psu} ({psp}%)"
    )"""
text8 = text8.replace(old8, new8)
with open(f8, "w", encoding="utf-8") as f:
    f.write(text8)


# 4. stage12_confidence.py
f12 = r"c:\Users\Nirankush\Desktop\FYP\Binance Trading\signal_engine\stage12_confidence.py"
with open(f12, "r", encoding="utf-8") as f:
    text12 = f.read()

old12 = """    slog.info(f"Raw Score: {raw_score:.1f} | Modifiers: {mod_total} | Final: {final_score} ({grade})")"""
new12 = """    rs_str = f"{raw_score:.1f}" if raw_score is not None else "N/A"
    slog.info(f"Raw Score: {rs_str} | Modifiers: {mod_total} | Final: {final_score} ({grade})")"""

text12 = text12.replace(old12, new12)
with open(f12, "w", encoding="utf-8") as f:
    f.write(text12)

print("All patches applied successfully.")
