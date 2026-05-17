import re

path = r'C:\Users\dell\.qclaw\workspace\scripts\scalper_v3.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

old = '''        if pump_pct <= 0.03:
            score += 8;  reasons.append(f"early_entry({pump_pct*100:.1f}%)")
        elif pump_pct <= CHASE_PUMP_PCT:
            score += 3;  reasons.append(f"pump+{pump_pct*100:.1f}%")
        elif pump_pct <= 0.25:
            score -= 8;  reasons.append(f"chase_warn+{pump_pct*100:.1f}%")
        elif pump_pct > 0.25:
            score -= 20; reasons.append(f"CHASE_SKIP+{pump_pct*100:.1f}%")
        elif pump_pct < -0.05:
            score += 5;  reasons.append(f"dip_entry({pump_pct*100:.1f}%)")
        elif pump_pct <= -0.10:
            score -= 15; reasons.append(f"dumped({pump_pct*100:.1f}%)")'''

new = '''        # Check negative pump FIRST (price dropped), then positive ranges
        if pump_pct < -0.10:
            score -= 15; reasons.append(f"dumped({pump_pct*100:.1f}%)")
        elif pump_pct < -0.05:
            score += 5;  reasons.append(f"dip_entry({pump_pct*100:.1f}%)")
        elif pump_pct <= 0.03:
            score += 8;  reasons.append("early_entry")
        elif pump_pct <= CHASE_PUMP_PCT:
            score += 3;  reasons.append(f"pump+{pump_pct*100:.1f}%")
        elif pump_pct <= 0.25:
            score -= 8;  reasons.append(f"chase_warn+{pump_pct*100:.1f}%")
        else:
            score -= 20; reasons.append(f"CHASE_SKIP+{pump_pct*100:.1f}%")'''

if old in content:
    content = content.replace(old, new)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    print('Patched successfully!')
else:
    print('Pattern not found!')
    # Show the actual content around that area
    idx = content.find('pump_pct')
    print(repr(content[max(0,idx-50):idx+300]))
