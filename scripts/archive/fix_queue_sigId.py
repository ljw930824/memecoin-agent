#!/usr/bin/env python3
"""Fix signal-queue.json: add sigId field from signalId where missing."""
import json, os, sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

path = os.path.expanduser("~/.qclaw/workspace/data/signal-queue.json")
with open(path, encoding="utf-8") as f:
    queue = json.load(f)

fixed = 0
for item in queue:
    if "sigId" not in item and "signalId" in item:
        item["sigId"] = item["signalId"]
        fixed += 1

with open(path, "w", encoding="utf-8") as f:
    json.dump(queue, f, indent=2, ensure_ascii=False)

print(f"Fixed {fixed} entries in signal-queue.json (total: {len(queue)})")
for item in queue[:5]:
    print(f"  {item.get('ticker','?')} sigId={item.get('sigId','MISSING')[:20]} signalId={item.get('signalId','?')[:20]}")