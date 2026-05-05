import json, sys
path = r"C:\Users\dell\.qclaw\workspace\data\signal-queue.json"
data = json.load(open(path, encoding="utf-8", newline=""))
fixed = 0
for sig in data:
    if "sigId" not in sig and "signalId" in sig:
        sig["sigId"] = sig["signalId"]
        fixed += 1
with open(path, "w", encoding="utf-8", newline="") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
print("Fixed", fixed, "entries")
data2 = json.load(open(path, encoding="utf-8", newline=""))
missing = [v.get("signalId") for v in data2 if "sigId" not in v]
print("Remaining missing sigId:", missing)
print("Total queue:", len(data2))
