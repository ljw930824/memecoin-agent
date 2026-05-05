#!/usr/bin/env python3
"""
Diver Monitor v1 - 潜水员策略
整合三个观察策略：
  S1: Binance Alpha Monitor (币安上新监控)
  S2: OI + Funding Rate Scanner (OI放大+费率转负)
  S3: Accumulation Radar (热度做多雷达)

观察区: data/diver_observation_zone.json
推送: Telegram
运行: python scripts/diver_monitor.py
"""

import json
import os
import sys
import time
import re
import requests
import ssl
import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

# ========== 路径配置 ==========
SCRIPT_DIR = Path(__file__).parent.resolve()
WORKSPACE = SCRIPT_DIR.parent
DATA_DIR = WORKSPACE / "data"
DATA_DIR.mkdir(exist_ok=True)
STATE_FILE = DATA_DIR / "diver_observation_zone.json"

# ========== TG 配置 ==========
def load_env():
    env = {}
    env_file = SCRIPT_DIR / ".env.oi"
    if env_file.exists():
        for line in env_file.read_text().strip().split('\n'):
            if '=' in line and not line.startswith('#'):
                k, v = line.split('=', 1)
                env[k.strip()] = v.strip()
    return env

ENV = load_env()
TG_TOKEN = ENV.get('TG_BOT_TOKEN', os.environ.get('TG_BOT_TOKEN', ''))
TG_CHAT = ENV.get('TG_CHAT_ID', os.environ.get('TG_CHAT_ID', ''))

# ========== API 域名 ==========
FAPI = "https://fapi.binance.com"     # 期货 (可能被封)
SPOT = "https://api.binance.com"       # 现货 (通常正常)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}
DEDUP_HOURS = 24

# ========== API 请求 ==========
def api_get(url: str, params=None, timeout: int = 8, use_spot_fallback: bool = True) -> Optional[dict | list]:
    """带降级的HTTP GET，期货API被封时自动切到现货"""
    for attempt in range(2):
        try:
            r = requests.get(url, params=params, timeout=timeout, headers=HEADERS)
            if r.status_code == 200:
                return r.json()
            return None
        except (requests.exceptions.ReadTimeout,
                requests.exceptions.ConnectTimeout,
                requests.exceptions.ConnectionError):
            if use_spot_fallback and 'fapi.binance.com' in url and attempt == 0:
                # 降级到现货 API
                spot_url = url.replace('fapi.binance.com/fapi/v1/', 'api.binance.com/api/v3/')
                spot_url = spot_url.replace('fapi.binance.com/futures/data/', 'api.binance.com/api/v3/')
                if spot_url != url:
                    url = spot_url
                    continue
            return None
        except Exception:
            return None
    return None


# ========== TG推送 ==========
def send_tg(text: str, silent: bool = False):
    if not TG_TOKEN or not TG_CHAT:
        print("[TG] 未配置，仅打印")
        print(text)
        return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    chunks = [text[i:i+3800] for i in range(0, len(text), 3800)]
    for chunk in chunks:
        try:
            r = requests.post(url, json={
                'chat_id': TG_CHAT, 'text': chunk, 'parse_mode': 'HTML'
            }, timeout=10)
            if r.status_code != 200:
                requests.post(url, json={'chat_id': TG_CHAT, 'text': chunk}, timeout=10)
        except Exception as e:
            print(f"[TG] Error: {e}")
        time.sleep(0.3)


# ========== 共用工具 ==========
def fmt_mcap(v):
    if not v: return "?"
    if v >= 1e9: return f"${v/1e9:.1f}B"
    if v >= 1e6: return f"${v/1e6:.0f}M"
    if v >= 1e3: return f"${v/1e3:.0f}K"
    return f"${v:.0f}"


# ========== 状态读写 ==========
def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding='utf-8'))
        except:
            pass
    return {
        "alpha": {"alerts": {}},
        "oi_fr": {"last_fr_snapshot": {}},
        "heat": {"heat_history": {}},
        "observation_zone": [],
        "last_full_scan": None,
    }


def save_state(state):
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding='utf-8'
    )


# ==============================================================
# S1: Binance Alpha Monitor
# ==============================================================
TRIGGER_KW = ["alpha", "airdrop", "tge", "token generation",
              "will list", "will launch", "binance wallet", "hodler"]
EXCLUDE_KW = ["delisting", "delist", "maintenance", "launchpool",
              "megadrop", "buyback", "perpetual contract", "futures will launch"]
TIER1_VCS = ["binance labs", "yzi labs", "coinbase ventures", "a16z", "paradigm",
             "polychain", "sequoia", "multicoin", "pantera", "dragonfly"]
TIER_ICONS = {"S": "🟢🟢", "A": "🟡🟡", "B": "🟠", "C": "⚪"}
TIER_SCORES = {"S": 92, "A": 78, "B": 58, "C": 40}


def scan_alpha(state: dict) -> list:
    signals = []
    alerts = state.setdefault('alpha', {}).setdefault('alerts', {})
    now = datetime.now(timezone(timedelta(hours=8)))

    try:
        r = api_get(
            "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query",
            params={"type": 1, "catalogId": 48, "pageNo": 1, "pageSize": 20},
            use_spot_fallback=False, timeout=10
        )
        if not r:
            return []
        articles = r.get("data", {}).get("catalogs", [{}])[0].get("articles", [])
    except Exception as e:
        print(f"[S1] 公告抓取失败: {e}")
        return []

    for art in articles:
        title = art.get("title", "")
        tl = title.lower()
        if not any(kw in tl for kw in TRIGGER_KW):
            continue
        if any(kw in tl for kw in EXCLUDE_KW):
            continue

        m = re.search(r"\(([A-Z0-9]{2,10})\)", title)
        if not m:
            m = re.search(r"（([A-Z0-9]{2,10})）", title)
        if not m:
            continue

        sym = m.group(1)
        pid = f"{sym}_{now.strftime('%Y-%m-%d')}"
        if pid in alerts:
            continue

        # 简单评级
        t1 = sum(1 for vc in TIER1_VCS if vc in tl)
        if "yzi labs" in tl or "binance labs" in tl:
            tier, reason = "S", "币安/YZi亲儿子"
        elif t1 >= 2:
            tier, reason = "A", f"{t1}家Tier1机构"
        elif t1 == 1:
            tier, reason = "B", "有Tier1机构"
        else:
            tier, reason = "C", "标准上新"

        alerts[pid] = {"symbol": sym, "tier": tier, "found_at": now.isoformat()}
        print(f"[S1] 发现Alpha ${sym} [{tier}]: {title[:60]}")

        signals.append({
            'strategy': 'S1_ALPHA',
            'symbol': sym,
            'signal': f'Alpha {tier}级',
            'tier': tier,
            'tier_reason': reason,
            'score': TIER_SCORES.get(tier, 50),
            'raw_title': title,
        })

    return signals


# ==============================================================
# S2: OI放大 + 费率转负
# ==============================================================
def scan_oi_fr(state: dict) -> list:
    signals = []
    prev_fr = state.setdefault('oi_fr', {}).setdefault('last_fr_snapshot', {})

    # 尝试期货API，被封则降级到现货
    fr_data = api_get(f"{FAPI}/fapi/v1/premiumIndex")
    ticker_data = api_get(f"{FAPI}/fapi/v1/ticker/24hr")

    if not fr_data or not ticker_data:
        print("[S2] 期货API被封，降级到现货数据（费率/OI不可用）")
        return []

    fr_map = {p['symbol']: float(p['lastFundingRate']) for p in fr_data}
    ticker_map = {t['symbol']: t for t in ticker_data if t['symbol'].endswith('USDT')}

    # 找费率刚转负的
    just_neg = [s for s in fr_map
                if prev_fr.get(s) is not None
                and prev_fr[s] >= 0
                and fr_map[s] < 0]

    if not just_neg:
        state['oi_fr']['last_fr_snapshot'] = fr_map
        return []

    print(f"[S2] {len(just_neg)} 个费率刚转负: {just_neg}")

    for sym in just_neg:
        coin = sym.replace('USDT', '')
        t = ticker_map.get(sym, {})

        # OI历史
        oi_chg = 0
        segs = []
        try:
            oi_hist = api_get(
                f"{FAPI}/futures/data/openInterestHist",
                params={'symbol': sym, 'period': '1h', 'limit': 48}
            )
            if oi_hist and len(oi_hist) >= 12:
                vals = [float(x['sumOpenInterestValue']) for x in oi_hist]
                sl = len(vals) // 4
                if sl >= 3:
                    segs = [
                        sum(vals[:sl]) / sl,
                        sum(vals[sl:sl*2]) / sl,
                        sum(vals[sl*2:sl*3]) / sl,
                        sum(vals[sl*3:]) / max(1, len(vals[sl*3:]))
                    ]
                    oi_chg = (segs[3] - segs[0]) / segs[0] * 100 if segs[0] > 0 else 0
        except:
            pass

        if oi_chg > 0:  # OI在涨
            signals.append({
                'strategy': 'S2_OI_FR',
                'symbol': coin,
                'price': float(t.get('lastPrice', 0)),
                'vol_24h': float(t.get('quoteVolume', 0)),
                'oi_change': oi_chg,
                'fr_current': fr_map[sym],
                'fr_prev': prev_fr.get(sym, 0),
                'signal': 'OI放大 + 费率转负',
                'score': 75,
            })
        time.sleep(0.1)

    state['oi_fr']['last_fr_snapshot'] = fr_map
    return signals


# ==============================================================
# S3: 热度做多雷达
# ==============================================================
def get_square_heat() -> set:
    """币安广场热搜"""
    try:
        r = requests.get(
            "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query",
            params={"type": 1, "catalogId": 93, "pageNo": 1, "pageSize": 10},
            headers=HEADERS, timeout=8
        )
        if r.status_code == 200:
            articles = r.json().get("data", {}).get("catalogs", [{}])[0].get("articles", [])
            coins = set()
            for a in articles:
                m = re.search(r"\(([A-Z0-9]{2,10})\)", a.get("title", ""))
                if m:
                    coins.add(m.group(1))
            return coins
    except:
        pass
    return set()


def scan_heat(state: dict) -> list:
    signals = []
    now = datetime.now(timezone(timedelta(hours=8)))
    heat_hist = state.setdefault('heat', {}).setdefault('heat_history', {})

    # 全市场行情（降级到现货）
    tickers = api_get(f"{SPOT}/api/v3/ticker/24hr")
    if not tickers:
        print("[S3] 无法获取行情数据")
        return []

    ticker_map = {t['symbol']: t for t in tickers if t['symbol'].endswith('USDT')}

    # 广场热搜
    sq_set = get_square_heat()
    print(f"[S3] 广场热搜: {list(sq_set)[:5]}")

    # CoinGecko Trending
    cg_set = set()
    try:
        r = requests.get("https://api.coingecko.com/api/v3/search/trending", timeout=8)
        if r.status_code == 200:
            for item in r.json().get("coins", []):
                cg_set.add(item["item"]["symbol"].upper())
    except:
        pass
    print(f"[S3] CG Trending: {list(cg_set)[:5]}")

    # 扫描Top100成交量
    top_syms = sorted(
        [(s, t) for s, t in ticker_map.items()
         if float(t.get('quoteVolume', 0)) > 10_000_000],
        key=lambda x: float(x[1].get('quoteVolume', 0)), reverse=True
    )[:100]

    heat_signals = []
    chase_signals = []

    for sym, t in top_syms:
        coin = sym.replace('USDT', '')
        vol = float(t.get('quoteVolume', 0))
        px_chg = float(t.get('priceChangePercent', 0))
        price = float(t.get('lastPrice', 0))

        # 热度分
        heat = 0
        in_sq = coin in sq_set
        in_cg = coin in cg_set
        if in_sq: heat += 30
        if in_cg: heat += 20

        if heat >= 40:
            is_new = coin not in heat_hist
            heat_hist[coin] = now.strftime('%Y-%m-%d %H:%M')
            sources = []
            if in_sq: sources.append("广场")
            if in_cg: sources.append("CG")

            heat_signals.append({
                'strategy': 'S3_HEAT',
                'symbol': coin,
                'price': price,
                'vol_24h': vol,
                'px_chg': px_chg,
                'heat': heat,
                'is_new': is_new,
                'sources': '/'.join(sources),
                'signal': f'热度榜 {heat}分',
                'score': min(heat + 15, 90),
            })

        # 追多信号：涨幅大 + 成交大
        if px_chg > 5 and vol > 20_000_000:
            is_new_chase = coin not in heat_hist
            chase_signals.append({
                'strategy': 'S3_CHASE',
                'symbol': coin,
                'price': price,
                'vol_24h': vol,
                'px_chg': px_chg,
                'is_new': is_new_chase,
                'signal': '追多(放量上涨)',
                'score': min(65 + int(px_chg), 88),
            })

        time.sleep(0.05)

    # 清理7天前历史
    cutoff = (now - timedelta(days=7)).strftime('%Y-%m-%d')
    heat_hist.clear()
    heat_hist.update({k: v for k, v in heat_hist.items() if v >= cutoff})

    signals.extend(heat_signals[:5])
    signals.extend(chase_signals[:5])
    return signals


# ==============================================================
# 观察区合并
# ==============================================================
def merge_zone(state: dict, new_signals: list):
    zone = state.setdefault('observation_zone', [])
    existing_syms = {s['symbol'] for s in zone}

    for sig in new_signals:
        sym = sig['symbol']
        found = False
        for entry in zone:
            if entry['symbol'] == sym:
                entry.update(sig)
                entry['updated_at'] = datetime.now(timezone(timedelta(hours=8))).isoformat()
                found = True
                break
        if not found:
            sig['added_at'] = datetime.now(timezone(timedelta(hours=8))).isoformat()
            zone.append(sig)

    zone.sort(key=lambda x: x.get('score', 0), reverse=True)
    state['observation_zone'] = zone[:20]


# ==============================================================
# 格式化推送
# ==============================================================
def format_report(signals: list) -> str:
    if not signals:
        return ""
    now = datetime.now(timezone(timedelta(hours=8))).strftime('%m-%d %H:%M')
    groups = {}
    for s in signals:
        st = s.get('strategy', 'UNKNOWN')
        groups.setdefault(st, []).append(s)

    lines = [f"📡 <b>潜水员策略观察区</b>  {now}\n"]

    labels = {
        'S1_ALPHA': 'S1 币安Alpha上新',
        'S2_OI_FR': 'S2 OI放大+费率转负',
        'S3_HEAT': 'S3 热度做多',
        'S3_CHASE': 'S3 追多信号',
    }

    for st, label in labels.items():
        items = groups.get(st, [])
        if not items:
            continue
        lines.append(f"\n<b>{label}</b> ({len(items)}个)")
        for s in items[:5]:
            coin = s.get('symbol', '')
            score = s.get('score', 0)
            tier = s.get('tier', '')
            icon = TIER_ICONS.get(tier, '')
            extra = []
            if s.get('px_chg'):
                extra.append(f"{s['px_chg']:+.1f}%")
            if s.get('vol_24h'):
                extra.append(f"${s['vol_24h']/1e6:.0f}M")
            extra_str = f" | {' '.join(extra)}" if extra else ""

            lines.append(
                f"  {icon} <b>${coin}</b> {score}分 | {s.get('signal', '')}{extra_str}"
            )
            if s.get('tier_reason'):
                lines.append(f"    └ {s['tier_reason']}")

    return '\n'.join(lines)


# ==============================================================
# 主扫描
# ==============================================================
def run_scan():
    ts = time.time()
    print(f"\n{'='*50}")
    print(f"🤿 Diver Monitor v1  扫描开始")
    print(f"{'='*50}")

    state = load_state()
    all_signals = []

    # S1: Alpha Monitor
    print("[S1] Binance Alpha...")
    try:
        s1 = scan_alpha(state)
        print(f"  -> {len(s1)} 信号")
        all_signals.extend(s1)
    except Exception as e:
        print(f"  -> 失败: {e}")

    # S2: OI + 费率
    print("[S2] OI + Funding Rate...")
    try:
        s2 = scan_oi_fr(state)
        print(f"  -> {len(s2)} 信号")
        all_signals.extend(s2)
    except Exception as e:
        print(f"  -> 失败: {e}")

    # S3: 热度雷达
    print("[S3] Accumulation Radar...")
    try:
        s3 = scan_heat(state)
        print(f"  -> {len(s3)} 信号")
        all_signals.extend(s3)
    except Exception as e:
        print(f"  -> 失败: {e}")

    state['last_full_scan'] = datetime.now(timezone(timedelta(hours=8))).isoformat()
    merge_zone(state, all_signals)
    save_state(state)

    elapsed = time.time() - ts
    print(f"\n  总计 {len(all_signals)} 个信号，耗时 {elapsed:.1f}s")

    if all_signals:
        msg = format_report(all_signals)
        if msg:
            send_tg(msg)
            print("  -> TG推送成功")
    else:
        print("  -> 无新信号")

    return all_signals


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    run_scan()
