import sys, requests, json
sys.stdout.reconfigure(encoding='utf-8')

API = 'https://web3.binance.com/bapi/defi/v1/public/wallet-direct/buw/wallet/web/signal/smart-money/ai'
HEADERS = {'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json', 'Referer': 'https://www.binance.com'}

# Try different parameter formats
tests = [
    {'chainId': 56, 'pageSize': 5},
    {'chainId': '56', 'pageSize': 5},
    {'chain': 56, 'pageSize': 5},
    {'chain': 'BSC', 'pageSize': 5},
    {'pageSize': 5, 'chainId': 56},
    {'chainId': 56, 'pageSize': 5, 'type': 'BUY'},
    {'chainId': 'bsc', 'pageSize': 5},
    {'chainId': 'bsc_mainnet', 'pageSize': 5},
]

for t in tests:
    try:
        r = requests.get(API, params=t, timeout=8, headers=HEADERS)
        d = r.json()
        code = d.get('code')
        success = d.get('success')
        data = d.get('data')
        print(f"params={t} -> status={r.status_code} code={code} success={success} data_type={type(data).__name__}")
        if data:
            print(f"  -> {json.dumps(data)[:200]}")
    except Exception as e:
        print(f"params={t} -> ERROR: {e}")
