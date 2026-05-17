import subprocess, json, os

BAW_CMD = os.path.expanduser("~\\AppData\\Roaming\\QClaw\\npm-global\\baw.cmd")
env = dict(os.environ)
env["PATH"] = env.get("PATH", "") + ";" + os.path.expanduser("~\\AppData\\Roaming\\QClaw\\npm-global")

# Get all balances
r = subprocess.run([BAW_CMD, "wallet", "balance", "--json"], capture_output=True, text=True, timeout=15, env=env)
data = json.loads(r.stdout)
print("All balances:")
for t in data.get("data", []):
    sym = t.get("symbol", "?")
    bal = t.get("balance", "?")
    val = t.get("value", "?")
    chain = t.get("binanceChainId", "?")
    print(f"  {sym}: balance={bal} value={val} chain={chain}")
