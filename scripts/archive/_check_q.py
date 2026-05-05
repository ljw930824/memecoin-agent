import json, sys, os
sys.stdout.reconfigure(encoding='utf-8')
f = os.path.join(os.path.expanduser('~'), '.qclaw', 'workspace', 'data', 'signal-queue.json')
with open(f, encoding='utf-8') as fp:
    q = json.load(fp)
print(f'Total: {len(q)}')
if q:
    s = q[0]
    print(f'First: source={s.get("source")} ticker={s.get("ticker")} score={s.get("score")}')
srcs = {}
for s in q:
    src = s.get('source','?')
    srcs[src] = srcs.get(src, 0) + 1
print(f'Sources: {srcs}')
