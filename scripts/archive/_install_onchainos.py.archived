import urllib.request, json, sys
sys.stdout.reconfigure(encoding='utf-8')

# Step 1: Get latest release tag
try:
    r = urllib.request.urlopen('https://api.github.com/repos/okx/onchainos-skills/releases/latest', timeout=15)
    data = json.loads(r.read())
    tag = data['tag_name']
    name = data['name']
    print(f'Latest tag: {tag}')
    print(f'Release name: {name}')
    for a in data.get('assets', []):
        print(f'  Asset: {a["name"]} ({a["size"]//1024}KB)')
except Exception as e:
    print(f'GitHub API failed: {e}')
