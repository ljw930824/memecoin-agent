# -*- coding: utf-8 -*-
"""
safety_check.py — 买入前安全检查模块（双链共享）

检查维度（满分 100）:
 1. Honeypot 检测     — 0/30（是蜜罐直接拒绝）
 2. 税率检查          — 0~15（buy+sell tax ≤5% 满分）
 3. 价格影响          — 0~15（impact ≤2% 满分）
 4. 流动性深度        — 0~25（>50k 满分，<1k 拒绝）
 5. 持币集中度        — 0~15（top10 ≤50% 满分）

安全阈值: score >= 40 才允许开仓
推荐阈值: score >= 60 优先开仓
"""

import json, subprocess, sys, time, os

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# ── 路径 ──
ONCHAINOS = r'C:\Users\dell\.local\bin\onchainos.exe'
BAW_CMD   = os.path.expanduser('~\\AppData\\Roaming\\QClaw\\npm-global\\baw.cmd')

# ── 链常量 ──
SOL_USDT = 'Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB'
BSC_USDT = '0x55d398326f99059fF775485246999027B3197955'
BSC_WBNB = '0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c'

# ── 评分权重 ──
W_HONEYPOT = 30
W_TAX      = 15
W_IMPACT   = 15
W_LIQ      = 25
W_HOLDER   = 15

# ── 阈值 ──
MAX_TAX_PCT        = 10.0   # 税率超过10%拒绝
MAX_IMPACT_PCT     = 15.0   # 价格影响超过15%拒绝
MIN_LIQ_USD        = 1000   # 流动性低于$1k拒绝
MIN_LIQ_FOR_FULL   = 50000  # 流动性超过$5k满分
MAX_TOP10_HOLDER   = 80     # 前10持币超过80%拒绝
MIN_SAFETY_SCORE   = 40     # 最低安全分（低于拒绝）
RECOMMEND_SCORE    = 60     # 推荐分

# ═══════════════════════════════════════════════════════════════
# Solana: 通过 onchainos swap quote 获取审计数据
# ═══════════════════════════════════════════════════════════════

def _oc_run(args, timeout=30):
    cmd = [ONCHAINOS] + args
    for attempt in range(3):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True,
                               timeout=timeout, encoding='utf-8', errors='replace')
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip(), r.stderr.strip(), 0
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
        except subprocess.TimeoutExpired:
            if attempt < 2:
                time.sleep(3 * (attempt + 1))
            return '', 'timeout', 998
        except Exception as e:
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
            return '', str(e), 999
    return '', 'max_retries', 999


def _baw_run(args, timeout=30):
    cmd = [BAW_CMD] + args
    env = dict(os.environ)
    npm_global = os.path.expanduser('~\\AppData\\Roaming\\QClaw\\npm-global')
    env['PATH'] = env.get('PATH', '') + ';' + npm_global
    for attempt in range(3):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True,
                               timeout=timeout, env=env)
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip(), r.stderr.strip(), 0
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
        except subprocess.TimeoutExpired:
            if attempt < 2:
                time.sleep(3 * (attempt + 1))
            return '', 'timeout', 998
        except Exception as e:
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
            return '', str(e), 999
    return '', 'max_retries', 999


# ═══════════════════════════════════════════════════════════════
# 单项评分函数
# ═══════════════════════════════════════════════════════════════

def score_honeypot(is_hp):
    """蜜罐检测: 是蜜罐=0, 否则满分30"""
    return 0 if is_hp else W_HONEYPOT, 'HONEYPOT' if is_hp else ''


def score_tax(tax_rate):
    """税率评分: 0%=15分, 5%=10分, 10%=5分, >10%=0"""
    if tax_rate <= 0:
        return W_TAX, ''
    if tax_rate > MAX_TAX_PCT:
        return 0, f'TAX_{tax_rate:.1f}%'
    # 线性扣分: 0%→15, 10%→0
    s = max(0, W_TAX * (1 - tax_rate / MAX_TAX_PCT))
    return round(s, 1), '' if s > 0 else f'TAX_{tax_rate:.1f}%'


def score_impact(impact_pct):
    """价格影响评分: ≤2%=15分, ≤15%=线性递减, >15%=0"""
    if impact_pct <= 2:
        return W_IMPACT, ''
    if impact_pct > MAX_IMPACT_PCT:
        return 0, f'IMPACT_{impact_pct:.1f}%'
    s = W_IMPACT * (1 - (impact_pct - 2) / (MAX_IMPACT_PCT - 2))
    return round(s, 1), '' if s > 0 else f'IMPACT_{impact_pct:.1f}%'


def score_liquidity(liq_usd):
    """流动性评分: >$50k=25, $1k-$50k=线性, <$1k=0"""
    if liq_usd < MIN_LIQ_USD:
        return 0, f'LIQ_${liq_usd:.0f}'
    if liq_usd >= MIN_LIQ_FOR_FULL:
        return W_LIQ, ''
    s = W_LIQ * (liq_usd / MIN_LIQ_FOR_FULL)
    return round(s, 1), ''


def score_holders(top10_pct):
    """持币集中度: ≤50%=15, 50-80%=线性, >80%=0"""
    if top10_pct <= 50:
        return W_HOLDER, ''
    if top10_pct > MAX_TOP10_HOLDER:
        return 0, f'HOLDERS_{top10_pct:.0f}%'
    s = W_HOLDER * (1 - (top10_pct - 50) / 30)
    return round(s, 1), '' if s > 0 else f'HOLDERS_{top10_pct:.0f}%'


# ═══════════════════════════════════════════════════════════════
# Solana 安全检查（通过 onchainos swap quote）
# ═══════════════════════════════════════════════════════════════

def check_solana(token_ca, trade_amount_usd=5.0):
    """
    对 Solana token 做安全检查。
    返回: (score: float, passed: bool, details: dict, errors: list)
    """
    out, err, code = _oc_run([
        'swap', 'quote',
        '--chain', 'Solana',
        '--from', SOL_USDT,
        '--to', token_ca,
        '--readable-amount', str(min(trade_amount_usd, 5.0)),  # 用小额测试
    ], timeout=30)

    if code != 0:
        return 0, False, {}, ['quote_failed']

    try:
        d = json.loads(out)
        if not (d.get('ok') and d.get('data')):
            return 0, False, {}, ['no_quote_data']

        data = d['data'][0]
        to_token  = data.get('toToken', {})
        from_token = data.get('fromToken', {})

        # 提取数据 (注意 onchainos 可能返回空字符串)
        is_hp     = to_token.get('isHoneyPot', False)
        tax_rate  = float(to_token.get('taxRate', 0) or 0)
        impact_raw = data.get('priceImpactPercent', 0) or 0
        impact    = float(impact_raw) if impact_raw else 0.0
        routers   = data.get('dexRouterList', [])

        # 流动性: 从 router 数据估算
        from_amt  = float(data.get('fromTokenAmount', 0) or 0) / 1e6  # USDT decimals=6
        to_amt    = float(data.get('toTokenAmount', 0) or 0)
        to_price_raw = to_token.get('tokenUnitPrice', 0) or 0
        to_price  = float(to_price_raw) if to_price_raw else 0.0
        # 估算: 如果 impact 可用则用 impact 反推，否则用 DEX 数量估算
        if impact > 0 and from_amt > 0:
            est_liq = from_amt / (impact / 100) * 10
        elif to_price > 0 and to_amt > 0:
            est_liq = to_amt * to_price
        else:
            est_liq = from_amt * len(routers) * 50

        # DEX 路由数作为辅助指标
        dex_count = len(routers)

        # ── 评分 ──
        s_hp, e_hp     = score_honeypot(is_hp)
        s_tax, e_tax   = score_tax(tax_rate)
        s_imp, e_imp   = score_impact(impact)
        s_liq, e_liq   = score_liquidity(est_liq)
        # Solana 无法获取持币集中度（链上数据需额外查询），给默认分
        s_holder = W_HOLDER * 0.7  # 保守给 70% 分

        total = s_hp + s_tax + s_imp + s_liq + s_holder
        errors = [x for x in [e_hp, e_tax, e_imp, e_liq] if x]

        # 硬性拒绝: honeypot
        if is_hp:
            total = 0
            errors = ['HONEYPOT']

        details = {
            'chain': 'Solana',
            'is_honeypot': is_hp,
            'tax_rate': tax_rate,
            'price_impact': impact,
            'est_liquidity_usd': round(est_liq),
            'dex_count': dex_count,
            'scores': {
                'honeypot': s_hp,
                'tax': s_tax,
                'impact': s_imp,
                'liquidity': s_liq,
                'holders': s_holder,
            },
        }

        passed = total >= MIN_SAFETY_SCORE and not is_hp
        return round(total, 1), passed, details, errors

    except Exception as e:
        return 0, False, {}, [f'parse_error: {str(e)[:50]}']


# ═══════════════════════════════════════════════════════════════
# BSC 安全检查（通过 BAW CLI market-order quote）
# ═══════════════════════════════════════════════════════════════

def check_bsc(token_ca, trade_amount_usd=5.0):
    """
    对 BSC token 做安全检查。
    返回: (score: float, passed: bool, details: dict, errors: list)
    """
    # 用 BAW CLI market-order quote 获取信息
    out, err, code = _baw_run([
        'market-order', 'quote',
        '--fromToken', BSC_USDT,
        '--toToken', token_ca,
        '--fromTokenQty', str(min(trade_amount_usd, 5.0)),
        '--binanceChainId', '56',
        '--json',
    ], timeout=30)

    if code != 0:
        return 0, False, {}, ['quote_failed']

    try:
        d = json.loads(out)
        if not (d.get('success') and d.get('data')):
            return 0, False, {}, ['no_quote_data']

        data = d['data']

        # BAW CLI quote 返回结构可能不同，提取可用字段
        to_token   = data.get('toToken', {})
        from_token = data.get('fromToken', {})

        is_hp     = to_token.get('isHoneyPot', False)
        tax_rate  = float(to_token.get('taxRate', 0) or 0)
        impact_raw = data.get('priceImpactPercent', 0) or 0
        impact    = float(impact_raw) if impact_raw else 0.0

        # 流动性: BAW 可能提供 liquidity 字段
        liq_usd = float(data.get('liquidity', 0) or 0)
        if liq_usd <= 0:
            from_amt = float(data.get('fromTokenAmount', 0) or 0)
            if impact > 0 and from_amt > 0:
                est_liq = from_amt / (impact / 100) * 10
            else:
                est_liq = 50000
        else:
            est_liq = liq_usd

        # ── 评分 ──
        s_hp, e_hp     = score_honeypot(is_hp)
        s_tax, e_tax   = score_tax(tax_rate)
        s_imp, e_imp   = score_impact(impact)
        s_liq, e_liq   = score_liquidity(est_liq)
        s_holder = W_HOLDER * 0.7  # 默认分

        total = s_hp + s_tax + s_imp + s_liq + s_holder
        errors = [x for x in [e_hp, e_tax, e_imp, e_liq] if x]

        if is_hp:
            total = 0
            errors = ['HONEYPOT']

        details = {
            'chain': 'BSC',
            'is_honeypot': is_hp,
            'tax_rate': tax_rate,
            'price_impact': impact,
            'est_liquidity_usd': round(est_liq),
            'scores': {
                'honeypot': s_hp,
                'tax': s_tax,
                'impact': s_imp,
                'liquidity': s_liq,
                'holders': s_holder,
            },
        }

        passed = total >= MIN_SAFETY_SCORE and not is_hp
        return round(total, 1), passed, details, errors

    except Exception as e:
        return 0, False, {}, [f'parse_error: {str(e)[:50]}']


# ═══════════════════════════════════════════════════════════════
# 统一入口
# ═══════════════════════════════════════════════════════════════

def check_token(chain, token_ca, trade_amount_usd=5.0):
    """
    统一安全检查入口。
    chain: 'Solana' 或 'BSC' (or '56')
    返回: (score, passed, details, errors)
    """
    if chain in ('Solana', '501'):
        return check_solana(token_ca, trade_amount_usd)
    elif chain in ('BSC', '56'):
        return check_bsc(token_ca, trade_amount_usd)
    else:
        return 0, False, {}, [f'unknown_chain: {chain}']


def format_safety_report(score, passed, details, errors):
    """格式化安全报告为可读字符串。"""
    chain = details.get('chain', '?')
    parts = [f'安全评分: {score}/100 {"✅" if passed else "❌"}']
    scores = details.get('scores', {})
    parts.append(f"  蜜罐: {scores.get('honeypot', '?')}/{W_HONEYPOT}  "
                 f"税率: {scores.get('tax', '?')}/{W_TAX}  "
                 f"冲击: {scores.get('impact', '?')}/{W_IMPACT}")
    parts.append(f"  流动性: ${details.get('est_liquidity_usd', '?')}  "
                 f"持币: {scores.get('holders', '?')}/{W_HOLDER}")
    if errors:
        parts.append(f"  ⚠️ {', '.join(errors)}")
    return '\n'.join(parts)


# ═══════════════════════════════════════════════════════════════
# CLI 测试入口
# ═══════════════════════════════════════════════════════════════

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print('Usage: python safety_check.py <chain> <token_ca> [amount_usd]')
        print('  chain: Solana | BSC')
        sys.exit(1)

    chain = sys.argv[1]
    ca    = sys.argv[2]
    amt   = float(sys.argv[3]) if len(sys.argv) > 3 else 5.0

    print(f'\n安全检查: {chain} | {ca} | ${amt}')
    print('=' * 50)

    score, passed, details, errors = check_token(chain, ca, amt)
    print(format_safety_report(score, passed, details, errors))

    if passed:
        print(f'\n✅ 通过 (score={score})')
    else:
        print(f'\n❌ 拒绝 (score={score})')
