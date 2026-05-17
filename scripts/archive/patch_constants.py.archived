path = r'C:\Users\dell\.qclaw\workspace\scripts\scalper_v3.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

old = '''CHASE_PUMP_PCT      = 0.15       # If already pumped >15% from alert, skip/reduce
REDUCE_PUMP_PCT     = 0.10       # If pumped 10-15%, reduce position 50%'''

new = '''CHASE_PUMP_PCT      = 0.15       # If already pumped >15% from alert, skip/reduce
REDUCE_PUMP_PCT     = 0.10       # If pumped 10-15%, reduce position 50%

# BNB auto-topup when USDT is low
BNB_TOPUP_THRESHOLD = 10.0     # Auto swap BNB->USDT when USDT below this
BNB_TOPUP_AMOUNT_BNB = 0.008   # BNB amount to swap (~$5 worth)'''

if old in content:
    content = content.replace(old, new)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    print("Constants added!")
else:
    print("Pattern not found!")
