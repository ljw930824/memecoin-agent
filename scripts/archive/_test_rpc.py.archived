import urllib.request, json, sys
sys.stdout.reconfigure(encoding='utf-8')

endpoints = [
    'https://api.mainnet-beta.solana.com',
    'https://rpc.ankr.com/solana',
    'https://solana-api.projectserum.com',
    'https://solana.rpc.blxrbdn.com',
]

for rpc in endpoints:
    try:
        data = json.dumps({"jsonrpc":"2.0","id":1,"method":"getHealth"}).encode()
        req = urllib.request.Request(rpc, data=data, headers={'Content-Type':'application/json'})
        r = urllib.request.urlopen(req, timeout=10)
        print(f'{rpc}: OK - {r.read().decode()[:80]}')
    except Exception as e:
        print(f'{rpc}: FAIL - {str(e)[:80]}')
