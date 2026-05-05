with open(r'C:\Users\dell\.qclaw\workspace\scripts\scalper_positions.py', 'r', encoding='utf-8') as f:
    content = f.read()

old = '        w = "⚠️" if p.get("score_drop", 0) >= SIGNAL_WEAKEN_THRESHOLD else ""'
new = '        w = "⚠️ drop:{}".format(int(p.get("score_drop", 0))) if p.get("score_drop", 0) >= 30 else ""'

if old in content:
    content = content.replace(old, new)
    with open(r'C:\Users\dell\.qclaw\workspace\scripts\scalper_positions.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print('OK: score drop threshold updated to 30 points')
else:
    print('NOT FOUND')
    lines = content.split('\n')
    for i in range(328, 340):
        print('{}: {}'.format(i+1, lines[i]))