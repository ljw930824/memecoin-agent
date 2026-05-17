import json, urllib.request, sys
sys.stdout.reconfigure(encoding='utf-8')

url = 'https://web3.binance.com/bapi/defi/v1/public/wallet-direct/buw/wallet/web/signal/smart-money/ai'
headers = {
    'Content-Type': 'application/json',
    'Accept-Encoding': 'identity',
    'User-Agent': 'binance-web3/1.1 (Skill)'
}
chain = sys.argv[1] if len(sys.argv) > 1 else '56'
body = json.dumps({'smartSignalType': '', 'page': 1, 'pageSize': 50, 'chainId': chain}).encode()
req = urllib.request.Request(url, data=body, headers=headers)
try:
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = resp.read()
        data = json.loads(raw)
    # Debug: show type and first 200 chars
    print(f'Response type: {type(data).__name__}')
    if isinstance(data, list):
        signals = data
    elif isinstance(data, dict):
        print(f'Keys: {list(data.keys())[:10]}')
        inner = data.get('data', data)
        if isinstance(inner, list):
            signals = inner
        elif isinstance(inner, dict):
            signals = inner.get('list', [])
        else:
            signals = []
    else:
        signals = []
    buy_signals = [s for s in signals if s.get('direction') == 'buy']
    print(f'BSC signals: {len(signals)} total, {len(buy_signals)} buy')
    for s in buy_signals[:8]:
        ca = s.get('contractAddress', '?')
        print(f"  {s.get('ticker','?')} | SM:{s.get('smartMoneyCount','?')} | tag:{s.get('tokenTag','?')} | mcap:{s.get('alertMarketCap','?')} | price:{s.get('currentPrice','?')} | status:{s.get('status','?')}")
        print(f"    CA: {ca}")
except Exception as e:
    print(f'Error: {e}')
