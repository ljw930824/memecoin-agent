import sys, json, urllib.request
sys.stdout.reconfigure(encoding='utf-8')

API = 'https://web3.binance.com/bapi/defi/v1/public/wallet-direct/buw/wallet/web/signal/smart-money/ai'

for chain_id in ['56', 'CT_501']:
    body = json.dumps({'smartSignalType': '', 'page': 1, 'pageSize': 5, 'chainId': chain_id}).encode()
    headers = {'Content-Type': 'application/json', 'Accept-Encoding': 'identity',
               'User-Agent': 'binance-web3/1.1 (Skill)'}
    req = urllib.request.Request(API, data=body, headers=headers, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            success = data.get('success')
            d = data.get('data')
            print(f'Chain {chain_id}: success={success}, data_type={type(d).__name__}')
            if d:
                items = d.get('list', d) if isinstance(d, dict) else d
                print(f'  items: {len(items) if isinstance(items, list) else "N/A"}')
                for item in (items[:5] if isinstance(items, list) else []):
                    score = item.get('signalScore', '?')
                    sym = item.get('tokenSymbol', '?')
                    dirn = item.get('signalDirection', '?')
                    pump = item.get('priceChangePercentage', 0)
                    mcap = item.get('marketCap', 0)
                    sm = item.get('smartMoneyCount', 0)
                    print(f'  {sym}: score={score} dir={dirn} pump={pump}% mcap={mcap} SM={sm}')
            else:
                print(f'  FULL: {json.dumps(data)[:300]}')
    except Exception as e:
        print(f'Chain {chain_id}: ERROR {e}')
