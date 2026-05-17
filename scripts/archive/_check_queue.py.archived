import json, time
with open(r'C:\Users\dell\.qclaw\workspace\data\signal-queue.json', 'r', encoding='utf-8') as f:
    q = json.load(f)
print(f'Total signals: {len(q)}')
now = int(time.time())
for s in q:
    age = (now - s.get('ts', 0)) // 60
    if age < 60:
        print(f"  {s.get('ticker','?')} | chain={s.get('chain','?')} | score={s.get('score',0)} | age={age}min")
