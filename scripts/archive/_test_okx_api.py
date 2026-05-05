import urllib.request, json, hmac, hashlib, base64, datetime

API_KEY = "34c952c9-9418-479f-889b-a590e5f54d6e"
SECRET_KEY = "C4BC811C5E9DF3CECD5BFA5D63E5133A"
PASSPHRASE = "mcp"

def sign(timestamp, method, path, body=""):
    msg = f"{timestamp}{method}{path}{body}"
    return base64.b64encode(hmac.new(SECRET_KEY.encode(), msg.encode(), hashlib.sha256).digest()).decode()

def api_get(path):
    ts = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z')
    sig = sign(ts, "GET", path)
    req = urllib.request.Request(f"https://web3.okx.com{path}",
        headers={"OK-ACCESS-KEY": API_KEY, "OK-ACCESS-TIMESTAMP": ts,
                 "OK-ACCESS-PASSPHRASE": PASSPHRASE, "OK-ACCESS-SIGN": sig})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())

print("Testing OKX DEX API...")
try:
    chains = api_get("/api/v6/dex/aggregator/supported/chain")
    print("Supported chains:")
    for c in chains.get("data", []):
        print(f"  chainIndex={c.get('chainIndex')} | {c.get('chainName')} | symbol={c.get('nativeTokenSymbol')}")
except Exception as e:
    print(f"Error: {e}")