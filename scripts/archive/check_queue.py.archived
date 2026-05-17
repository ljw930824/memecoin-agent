import json
data = json.load(open(r"C:\Users\dell\.qclaw\workspace\data\signal-queue.json"))
print("Queue length:", len(data))
if data:
    print("Keys:", list(data[0].keys()))
    for v in data:
        print("  sigId:", v.get("sigId", "MISSING"), "| signalId:", v.get("signalId", "MISSING"))
