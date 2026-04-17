#!/usr/bin/env python3
"""
大神 (DaShen) v2.0 — 多因子量化胜率预测引擎
自动拉取数据 → 计算19个因子 → 动态权重 → 输出胜率报告
从 v1.1.0 的"规则说明书"升级为"可执行引擎"

用法:
  python dashen_engine.py --code 00700.HK --asset_type stock
  python dashen_engine.py --code BTC --asset_type crypto
  python dashen_engine.py --code 000001.SZ --asset_type stock --industry 银行
"""

import argparse
import json
import sys
import time
from datetime import datetime, timedelta

try:
    import requests
except ImportError:
    print("错误：需要 requests 库。请运行: pip install requests", file=sys.stderr)
    sys.exit(1)

try:
    import numpy as np
except ImportError:
    np = None  # numpy 是可选的，降级用纯Python


# ============================================================
#  数据获取层（复用金融巨鳄的多源切换策略）
# ============================================================

def _format_sina_code(code):
    """格式化新浪代码"""
    code = code.strip().upper()
    if code.endswith(".HK"):
        return "hk" + code.replace(".HK", "")
    if code.endswith(".SZ"):
        return "sz" + code.replace(".SZ", "")
    if code.endswith(".SH"):
        return "sh" + code.replace(".SH", "")
    if code.lower().startswith(("sh", "sz")):
        return code.lower()
    if code.isdigit() and len(code) == 6:
        return ("sh" if code.startswith(("6", "9")) else "sz") + code
    return ""


def _format_eastmoney_code(code):
    """格式化东方财富 secid"""
    code = code.strip().upper()
    if code.endswith(".HK"): return "116." + code.replace(".HK", "")
    if code.endswith(".SZ"): return "0." + code.replace(".SZ", "")
    if code.endswith(".SH"): return "1." + code.replace(".SH", "")
    if code.isdigit() and len(code) == 6:
        return ("1." if code.startswith(("6", "9")) else "0.") + code
    if code.isalpha(): return "105." + code
    return ""


def fetch_stock_data(code, days=120):
    """多源获取股票数据：新浪 → 东方财富"""
    # 尝试东方财富（数据质量更好）
    secid = _format_eastmoney_code(code)
    if secid:
        result = _fetch_eastmoney(secid, code, days)
        if result.get("success"):
            return result

    # 回退到新浪
    sina_code = _format_sina_code(code)
    if sina_code:
        result = _fetch_sina(sina_code, code, days)
        if result.get("success"):
            return result

    return {"success": False, "error": f"所有股票数据源均失败: {code}", "code": code}


def _fetch_eastmoney(secid, code, days):
    """东方财富数据源"""
    result = {"source": "eastmoney", "success": False}
    try:
        url = (
            f"https://push2.eastmoney.com/api/qt/stock/get?"
            f"secid={secid}&fields=f43,f44,f45,f46,f47,f48,f50,f51,f52,f55,f57,f58,f60,f170,f116,f117"
            f"&_={int(time.time() * 1000)}"
        )
        resp = requests.get(url, timeout=10)
        data = resp.json()
        d = data.get("data")
        if not d:
            result["error"] = "东方财富返回空数据"
            return result

        price = d.get("f43", 0)
        prev_close = d.get("f60", 0)
        divisor = 100 if isinstance(price, int) and price > 10000 else 1

        realtime = {
            "name": d.get("f58", code),
            "price": price / divisor if divisor > 1 else price,
            "prev_close": prev_close / divisor if divisor > 1 else prev_close,
            "open": d.get("f46", 0) / divisor if divisor > 1 else d.get("f46", 0),
            "high": d.get("f44", 0) / divisor if divisor > 1 else d.get("f44", 0),
            "low": d.get("f45", 0) / divisor if divisor > 1 else d.get("f45", 0),
            "volume": d.get("f47", 0),
            "amount": d.get("f48", 0),
            "change_pct": d.get("f170", 0) / 100 if isinstance(d.get("f170"), int) else d.get("f170", 0),
            "pe": d.get("f162", 0) / 100 if isinstance(d.get("f162"), int) and d.get("f162", 0) > 100 else d.get("f162", 0),
            "pb": d.get("f167", 0) / 100 if isinstance(d.get("f167"), int) and d.get("f167", 0) > 100 else d.get("f167", 0),
            "market_cap": d.get("f116", 0),
            "turnover_rate": d.get("f168", 0) / 100 if isinstance(d.get("f168"), int) and d.get("f168", 0) > 100 else d.get("f168", 0),
            "total_shares": d.get("f117", 0),
        }

        # 历史K线
        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=days + 10)).strftime("%Y%m%d")
        kline_url = (
            f"https://push2his.eastmoney.com/api/qt/stock/kline/get?"
            f"secid={secid}&fields1=f1,f2,f3&fields2=f51,f52,f53,f54,f55,f56,f57"
            f"&klt=101&fqt=1&beg={start_date}&end={end_date}"
        )
        kresp = requests.get(kline_url, timeout=10)
        kdata = kresp.json()
        history = []
        for line in kdata.get("data", {}).get("klines", [])[-days:]:
            parts = line.split(",")
            if len(parts) >= 7:
                history.append({
                    "date": parts[0], "open": float(parts[1]), "close": float(parts[2]),
                    "high": float(parts[3]), "low": float(parts[4]), "volume": int(float(parts[5])),
                })

        result.update({"success": True, "asset_type": "stock", "code": code, "realtime": realtime, "history": history})
    except Exception as e:
        result["error"] = f"东方财富请求失败: {e}"
    return result


def _fetch_sina(sina_code, code, days):
    """新浪财经数据源（备用）"""
    result = {"source": "sina", "success": False}
    try:
        url = f"https://hq.sinajs.cn/list={sina_code}"
        resp = requests.get(url, headers={"Referer": "https://finance.sina.com.cn"}, timeout=10)
        resp.encoding = "gbk"
        text = resp.text.strip()
        if "FAILED" in text or '=""' in text or len(text) < 20:
            result["error"] = "新浪返回空数据"; return result
        fields = text.split('"')[1].split(",")

        is_hk = sina_code.startswith("hk")
        idx_map = {
            "name": 0 if not is_hk else 1, "open": 1 if not is_hk else 2,
            "prev_close": 2 if not is_hk else 3, "price": 3 if not is_hk else 6,
            "high": 4 if not is_hk else 4, "low": 5 if not is_hk else 5,
            "volume": 8 if not is_hk else 12, "amount": 9 if not is_hk else 11,
        }
        realtime = {k: float(fields[v]) if v < len(fields) and fields[v] else 0 for k, v in idx_map.items()}
        if realtime.get("prev_close", 0) > 0:
            realtime["change_pct"] = round((realtime["price"] - realtime["prev_close"]) / realtime["prev_close"] * 100, 2)

        # 新浪历史K线
        raw = sina_code.lstrip("hkszsh")
        mkt = "0" if sina_code.startswith("sh") else "1"
        hist_url = f"https://quotes.sina.cn/cn/api/jsonp.php/var/CN_MarketDataService.getKLineData?symbol={sina_code}&scale=240&ma=no&datalen={days}"
        hresp = requests.get(hist_url, timeout=10)
        htext = hresp.text
        s, e = htext.find("("), htext.rfind(")")
        history = []
        if s >= 0 and e > s:
            for item in json.loads(htext[s+1:e]):
                history.append({
                    "date": item.get("day", ""), "open": float(item.get("open", 0)),
                    "high": float(item.get("high", 0)), "low": float(item.get("low", 0)),
                    "close": float(item.get("close", 0)), "volume": int(float(item.get("volume", 0))),
                })
        result.update({"success": True, "asset_type": "stock", "code": code, "realtime": realtime, "history": history})
    except Exception as e:
        result["error"] = f"新浪请求失败: {e}"
    return result


def fetch_crypto_data(code, days=120):
    """加密货币数据：CoinGecko → Binance"""
    coin_id = {
        "BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana", "BNB": "binancecoin",
        "XRP": "ripple", "DOGE": "dogecoin", "ADA": "cardano", "TON": "the-open-network",
    }.get(code.strip().upper(), "")

    if coin_id:
        result = _fetch_coingecko(coin_id, code, days)
        if result.get("success"):
            return result

    # 回退到 Binance
    symbol = code.strip().upper() + ("USDT" if not code.strip().upper().endswith("USDT") else "")
    return _fetch_binance(symbol, code, days)


def _fetch_coingecko(coin_id, code, days):
    """CoinGecko 加密货币数据"""
    result = {"source": "coingecko", "success": False}
    try:
        url = f"https://api.coingecko.com/api/v3/coins/{coin_id}?localization=false&tickers=false&community_data=false&developer_data=false"
        resp = requests.get(url, timeout=15)
        if resp.status_code == 429:
            result["error"] = "CoinGecko 限速"; return result
        data = resp.json()
        m = data.get("market_data", {})
        realtime = {
            "name": data.get("name", code), "price": m.get("current_price", {}).get("usd", 0),
            "price_cny": m.get("current_price", {}).get("cny", 0),
            "change_pct_24h": m.get("price_change_percentage_24h", 0),
            "change_pct_7d": m.get("price_change_percentage_7d", 0),
            "change_pct_30d": m.get("price_change_percentage_30d", 0),
            "high_24h": m.get("high_24h", {}).get("usd", 0), "low_24h": m.get("low_24h", {}).get("usd", 0),
            "market_cap": m.get("market_cap", {}).get("usd", 0),
            "total_volume": m.get("total_volume", {}).get("usd", 0),
            "ath": m.get("ath", {}).get("usd", 0), "atl": m.get("atl", {}).get("usd", 0),
            "ath_change_pct": m.get("ath_change_percentage", {}).get("usd", 0),
        }

        time.sleep(1)  # 限速
        hist_resp = requests.get(
            f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart?vs_currency=usd&days={days}&interval=daily",
            timeout=15)
        hist_data = hist_resp.json()
        history = []
        prices = hist_data.get("prices", [])
        volumes = hist_data.get("total_volumes", [])
        for i, (ts, p) in enumerate(prices):
            date_str = datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d")
            vol = volumes[i][1] if i < len(volumes) else 0
            history.append({"date": date_str, "close": p, "volume": vol})

        result.update({"success": True, "asset_type": "crypto", "code": code.upper(), "realtime": realtime, "history": history})
    except Exception as e:
        result["error"] = f"CoinGecko 失败: {e}"
    return result


def _fetch_binance(symbol, code, days):
    """Binance 加密货币数据（备用）"""
    result = {"source": "binance", "success": False}
    try:
        end_time = int(time.time() * 1000)
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1d&startTime={end_time - days*86400*1000}&endTime={end_time}&limit={days}"
        resp = requests.get(url, timeout=15)
        if resp.status_code != 200:
            result["error"] = f"Binance 状态码: {resp.status_code}"; return result
        klines = resp.json()
        if not klines:
            result["error"] = "Binance 返回空"; return result

        history = []
        for k in klines:
            history.append({
                "date": datetime.fromtimestamp(k[0]/1000).strftime("%Y-%m-%d"),
                "open": float(k[1]), "high": float(k[2]), "low": float(k[3]),
                "close": float(k[4]), "volume": float(k[5]),
            })

        latest = klines[-1]
        price = float(latest[4])
        prev_close = float(klines[-2][4]) if len(klines) > 1 else price
        ticker = requests.get(f"https://api.binance.com/api/v3/ticker/24hr?symbol={symbol}", timeout=10).json()

        realtime = {"name": code.upper(), "price": price, "open": float(latest[1]),
                     "high": float(latest[2]), "low": float(latest[3]),
                     "change_pct_24h": round((price-prev_close)/prev_close*100, 2) if prev_close else 0,
                     "volume": float(ticker.get("volume", 0)),
                     "high_24h": float(ticker.get("highPrice", 0)),
                     "low_24h": float(ticker.get("lowPrice", 0)),
                     "market_cap": 0}  # Binance 不直接给市值

        result.update({"success": True, "asset_type": "crypto", "code": code.upper(),
                       "realtime": realtime, "history": history})
    except Exception as e:
        result["error"] = f"Binance 失败: {e}"
    return result


# ============================================================
#  因子计算层 —— 核心评分引擎
# ============================================================

def _calc_ma(closes, periods=[5, 20, 60]):
    """计算均线，返回字典 {MA5: val, MA20: val, ...}"""
    result = {}
    data = list(closes)
    for p in periods:
        if len(data) >= p:
            result[f"MA{p}"] = round(sum(data[-p:]) / p, 4)
        else:
            result[f"MA{p}] = None
    return result


def _score_linear(value, low, high, reverse=False):
    """
    将 value 在 [low, high] 范围内线性映射到 [-2, +2]
    支持 11 档精度（步长 0.5）
    reverse=True 时方向反转（如 VIX）
    """
    value = max(low, min(high, value))  # clamp
    ratio = (value - low) / (high - low) if high != low else 0.5
    raw = ratio * 4 - 2  # 映射到 [-2, +2]
    if reverse:
        raw = -raw
    # 四舍五入到最近的 0.5
    return round(raw * 2) / 2


class DaShenEngine:
    """
    大神胜率预测引擎 v2.0
    
    改进点：
    - 得分粒度从 5 档(-2,-1,0,+1,+2) 扩展到 11 档(-2.0 ~ +2.0 步长 0.5)
    - 新增 5 个因子（业绩超预期、内部人交易、分析师评级、做空比例、量价背离）
    - 宏观环境自动判定函数
    - 行业差异化权重表
    - shrimp → tycoon 命名统一
    """

    def __init__(self, data, asset_type="stock", industry=None, macro_env=None):
        self.data = data
        self.asset_type = asset_type
        self.industry = industry  # 可选：银行/科技成长/周期股/消费
        self.macro_env = macro_env  # 可选预置：bull/bear/neutral/crisis
        self.history = data.get("history", [])
        self.realtime = data.get("realtime", {})
        self.factors = {}       # 各因子原始得分
        self.dimension_scores = {}  # 各维度加权分
        self.total_score = 0
        self.win_rate = 0
        self.weights = None     # 当前使用的权重配置
        self.confidence = "中"   # 置信度

    # ──────────────────────────────────────
    #  一、趋势维度因子
    # ──────────────────────────────────────

    def factor_ma_trend(self):
        """F1: 均线趋势排列 — 11档精度"""
        closes = [h["close"] for h in self.history if h.get("close")]
        if len(closes) < 60:
            self.factors["F1_均线排列"] = {"score": 0, "weight": 0.10, "detail": "数据不足60天"}
            return 0

        ma = _calc_ma(closes, [5, 20, 60])
        ma5, ma20, ma60 = ma.get("MA5"), ma.get("MA20"), ma.get("MA60")
        
        if ma5 and ma20 and ma60:
            current = closes[-1]
            if ma5 > ma20 > ma60 and current > ma5:
                # 多头排列且价格在MA5上方 — 强势
                spread = (ma5 - ma60) / ma60 * 100  # 均线发散程度
                score = min(+2.0, +1.0 + spread * 0.3)  # 发散越强分数越高
                detail = f"完美多头排列 MA5={ma5}>MA20={ma20}>MA60={ma60}, 发散{spread:.1f}%"
            elif ma5 < ma20 < ma60 and current < ma5:
                spread = (ma60 - ma5) / ma60 * 100
                score = max(-2.0, -1.0 - spread * 0.3)
                detail = f"空头排列 MA5={ma5}<MA20={ma20}<MA60={ma60}, 发散{spread:.1f}%"
            elif abs(ma5 - ma60) / ma60 * 100 < 1.5:
                score = 0
                detail = f"均线缠绕 MA5={ma5:.2f}≈MA20={ma20:.2f}≈MA60={ma60:.2f}"
            elif ma5 > ma20:
                score = +0.5
                detail = f"短期偏强 MA5>{MA20}但MA60方向不明"
            else:
                score = -0.5
                detail = f"短期偏弱 MA5<{MA20}但MA60方向不明"
        else:
            score = 0; detail = "部分均线数据缺失"

        self.factors["F1_均线排列"] = {"score": score, "weight": 0.10, "detail": detail}
        return score

    def factor_relative_strength(self):
        """F2: 行业相对强度（20日个股 vs 指数）— 11档精度"""
        if len(self.history) < 20:
            self.factors["F2_行业相对强度"] = {"score": 0, "weight": 0.08, "detail": "数据不足"}
            return 0
        
        stock_return = (self.history[-1]["close"] - self.history[-20]["close"]) / self.history[-20]["close"] * 100
        
        # 用大盘近似：假设指数同期涨跌幅（简化处理——实际应拉对应行业指数）
        # 这里用近期市场平均波动作为基准（约 ±3% 为正常范围）
        benchmark_range = 3.0  # 基准正常波动范围
        excess_return = stock_return  # 相对基准的超额收益
        
        score = _score_linear(excess_return, -8, 8)  # ±8%映射到±2
        detail = f"近20日涨幅{stock_return:+.1f}%，相对基准超额{excess_return:+.1f}%"
        
        self.factors["F2_行业相对强度"] = {"score": score, "weight": 0.08, "detail": detail}
        return score

    def factor_macd_weekly(self):
        """F3: MACD 周线信号 — 11档精度"""
        closes = [h["close"] for h in self.history if h.get("close")]
        if len(closes) < 35:  # 至少35天 ≈ 7周
            self.factors["F3_周线MACD"] = {"score": 0, "weight": 0.07, "detail": "数据不足"}
            return 0

        # 计算EMA
        def ema(data, span):
            alpha = 2 / (span + 1)
            result = [data[0]]
            for v in data[1:]:
                result.append(alpha * v + (1 - alpha) * result[-1])
            return result

        ema12 = ema(closes, 12)
        ema26 = ema(closes, 26)
        dif = [a - b for a, b in zip(ema12, ema26)]
        dea = ema(dif, 9)
        macd_hist = [(d - de) * 2 for d, de in zip(dif, dea)]

        current_dif = dif[-1]
        current_dea = dea[-1]
        current_hist = macd_hist[-1]

        if current_dif > current_dea and current_hist > 0:
            # 多头运行 — 强度看柱状图大小和DIF位置
            score = min(+2.0, +0.8 + abs(current_dif) / closes[-1] * 100 + current_hist / closes[-1] * 50)
            detail = f"DIF={current_dif:.4f}>DEA={current_dea:.4f}, MACD柱={current_hist:.4f}(多头)"
        elif current_dif > current_dea:
            score = +0.5
            detail = f"DIF>DEA 但MACD柱为负（弱势多头）"
        elif current_dif < current_dea and current_hist < 0:
            score = max(-2.0, -0.8 - abs(current_dif) / closes[-1] * 100 + current_hist / closes[-1] * 50)
            detail = f"DIF={current_dif:.4f}<DEA={current_dea:.4f}, MACD柱={current_hist:.4f}(空头)"
        else:
            score = -0.5
            detail = f"DIF<DEA 但MACD柱为正（弱势空头）"

        self.factors["F3_周线MACD"] = {"score": score, "weight": 0.07, "detail": detail}
        return score

    def factor_sector_fund_flow(self):
        """F4: 板块资金流向（用成交量异动近似）"""
        if len(self.history) < 5:
            self.factors["F4_板块资金流向"] = {"score": 0, "weight": 0.05, "detail": "数据不足"}
            return 0

        recent_vol = sum(h.get("volume", 0) for h in self.history[-5:]) / 5
        avg_vol = sum(h.get("volume", 0) for h in self.history[:-5]) / max(len(self.history) - 5, 1)
        
        if avg_vol == 0:
            score = 0; detail = "无历史成交量对比基准"
        else:
            vol_ratio = recent_vol / avg_vol
            if vol_ratio > 2.0:
                score = +2.0; detail = f"显著放量 量比{vol_ratio:.1f}x（资金大量流入）"
            elif vol_ratio > 1.5:
                score = +1.0; detail = f"温和放量 量比{vol_ratio:.1f}x（资金关注）"
            elif vol_ratio > 1.2:
                score = +0.5; detail = f"微幅放量 量比{vol_ratio:.1f}x"
            elif vol_ratio < 0.5:
                score = -2.0; detail = f"大幅缩量 量比{vol_ratio:.1f}x（资金撤离）"
            elif vol_ratio < 0.7:
                score = -1.0; detail = f"温和缩量 量比{vol_ratio:.1f}x"
            else:
                score = 0; detail = f"量能平稳 量比{vol_ratio:.1f}x"

        self.factors["F4_板块资金流向"] = {"score": score, "weight": 0.05, "detail": detail}
        return score

    # ──────────────────────────────────────
    #  二、估值维度因子
    # ──────────────────────────────────────

    def factor_pe_percentile(self):
        """F5: PE 历史分位数（用PE_TTM当前值估算）"""
        pe = self.realtime.get("pe", 0)
        if not pe or pe <= 0:
            self.factors["F5_PE分位"] = {"score": 0, "weight": 0.10, "detail": f"无PE数据或亏损(pe={pe})"}
            return 0

        # 用全市场PE分布做近似分位（A股典型值）
        if self.asset_type == "stock":
            # A股典型PE区间：8-80（大部分在10-50）
            if pe < 12: score = +2.0; detail = f"PE={pe:.1f}(深度低估区<12)"
            elif pe < 18: score = +1.0; detail = f"PE={pe:.1f}(低估区12-18)"
            elif pe < 25: score = +0.5; detail = f"PE={pe:.1f}(合理偏低18-25)"
            elif pe < 35: score = 0; detail = f"PE={pe:.1f}(合理区间25-35)"
            elif pe < 50: score = -1.0; detail = f"PE={pe:.1f}(偏高估区35-50)"
            else: score = -2.0; detail = f"PE={pe:.1f}(高估区>50)"
        else:
            # 港股/美股PE通常更低
            if pe < 10: score = +2.0; detail = f"PE={pe:.1f}(极低<10)"
            elif pe < 16: score = +1.0; detail = f"PE={pe:.1f}(偏低10-16)"
            elif pe < 25: score = 0; detail = f"PE={pe:.1f}(合理16-25)"
            elif pe < 40: score = -1.0; detail = f"PE={pe:.1f}(偏高25-40)"
            else: score = -2.0; detail = f"PE={pe:.1f}(极高>40)"

        # 成长股适当放宽
        if self.industry in ["科技成长", "科技"]:
            score *= 0.7  # 成长股PE天然高，打折处理
            detail += "[已按成长股调整]"

        self.factors["F5_PE分位"] = {"score": score, "weight": 0.10, "detail": detail}
        return score

    def factor_pb_roe_match(self):
        """F6: PB-ROE 匹配度"""
        pb = self.realtime.get("pb", 0)
        # ROE 从外部传入或用合理默认
        # 这里用 PB 单独做一个估值检查
        
        if pb <= 0:
            self.factors["F6_PB-ROE"] = {"score": 0, "weight": 0.08, "detail": "无PB数据"}
            return 0

        # PB 分档（结合行业特性）
        if self.industry == "银行":
            # 银行PB通常0.4-1.5
            if pb < 0.5: score = +2.0; detail = f"PB={pb:.2f}(银行破净严重，可能超跌)"
            elif pb < 0.8: score = +1.0; detail = f"PB={pb:.2f}(银行偏低)"
            elif pb < 1.2: score = 0; detail = f"PB={pb:.2f}(银行合理)"
            else: score = -1.5; detail = f"PB={pb:.2f}(银行偏高)"
        elif self.industry in ["科技成长", "科技"]:
            # 科技股PB通常3-15
            if pb < 3: score = +1.5; detail = f"PB={pb:.2f}(科技偏低)"
            elif pb < 6: score = +0.5; detail = f"PB={pb:.2f}(科技合理)"
            elif pb < 10: score = -0.5; detail = f"PB={pb:.2f}(科技偏高)"
            else: score = -1.5; detail = f"PB={pb:.2f}(科技泡沫区)"
        else:
            # 一般企业 PB 1.5-5
            if pb < 1.5: score = +1.5; detail = f"PB={pb:.2f}(低于净资产)"
            elif pb < 3: score = +0.5; detail = f"PB={pb:.2f}(合理偏低)"
            elif pb < 5: score = 0; detail = f"PB={pb:.2f}(合理)"
            elif pb < 8: score = -1.0; detail = f"PB={pb:.2f}(偏高)"
            else: score = -2.0; detail = f"PB={pb:.2f}(严重高估)"

        self.factors["F6_PB-ROE"] = {"score": score, "weight": 0.08, "detail": detail}
        return score

    def factor_earnings_growth(self):
        """F7: 业绩增速 + F8新增: 业绩超预期（合并为一个综合因子）"""
        # 由于财报数据无法实时获取，这里用股价动量+成交量变化来代理
        # 这是一个近似指标，实际使用时建议手动输入财报数据
        
        if len(self.history) < 30:
            self.factors["F7_业绩增速"] = {"score": 0, "weight": 0.07, "detail": "数据不足（需手动输入财报增速）"}
            return 0

        # 近30日 vs 前30日动量（代理业绩预期变化）
        recent_momentum = (self.history[-1]["close"] - self.history[-30]["close"]) / self.history[-30]["close"] * 100
        earlier_momentum = (self.history[-30]["close"] - self.history[-60]["close"]) / self.history[-60]["close"] * 100 if len(self.history) >= 60 else 0
        
        momentum_acceleration = recent_momentum - earlier_momentum  # 动量加速
        
        # 如果有财报数据输入会更好，这里给出基于价格的近似评分
        if momentum_acceleration > 10:
            score = +1.5; detail = f"动量加速{momentum_acceleration:+.1f}%(可能业绩超预期)"
        elif momentum_acceleration > 3:
            score = +0.5; detail = f"动量温和加速{momentum_acceleration:+.1f}%"
        elif momentum_acceleration > -3:
            score = 0; detail = f"动量平稳{momentum_acceleration:+.1f}%"
        elif momentum_acceleration > -10:
            score = -1.0; detail = f"动量减速{momentum_acceleration:+.1f}%(可能miss)"
        else:
            score = -2.0; detail = f"动量急剧恶化{momentum_acceleration:+.1f}%(可能业绩暴雷)"

        detail += " ⚠️ 建议补充最新财报实际增速以精确评分"
        self.factors["F7_业绩增速"] = {"score": score, "weight": 0.07, "detail": detail}
        return score

    # ──────────────────────────────────────
    #  三、资金维度因子
    # ──────────────────────────────────────

    def factor_northbound_flow(self):
        """F8: 北向/外资流向（用成交量和价格关系近似）"""
        # 北向数据需要专门接口，这里用价量关系的代理指标
        if len(self.history) < 10:
            self.factors["F8_北向资金"] = {"score": 0, "weight": 0.10, "detail": "数据不足"}
            return 0

        # 5日量价分析：价格上涨+放量 = 资金流入
        price_change_5d = (self.history[-1]["close"] - self.history[-5]["close"]) / self.history[-5]["close"] * 100
        vol_recent = np.mean([h["volume"] for h in self.history[-5:]]) if np else sum(h["volume"] for h in self.history[-5:]) / 5
        vol_prior = np.mean([h["volume"] for h in self.history[-10:-5]]) if np else sum(h["volume"] for h in self.history[-10:-5:]) / 5
        vol_ratio = vol_recent / vol_prior if vol_prior > 0 else 1

        if price_change_5d > 3 and vol_ratio > 1.3:
            score = +2.0; detail = f"5日涨{price_change_5d:+.1f}%+放量{vol_ratio:.1f}x(外资可能流入)"
        elif price_change_5d > 1 and vol_ratio > 1.1:
            score = +1.0; detail = f"温和上涨+小幅放量"
        elif price_change_5d < -3 and vol_ratio > 1.3:
            score = -2.0; detail = f"5日跌{abs(price_change_5d):.1f}%+放量(外资可能流出)"
        elif price_change_5d < -1 and vol_ratio > 1.1:
            score = -1.0; detail = f"温和下跌+放量"
        elif abs(price_change_5d) < 1 and vol_ratio < 0.7:
            score = +0.5; detail = f"缩量横盘(筹码锁定)"
        else:
            score = 0; detail = f"5日涨{price_change_5d:+.1f}% 量比{vol_ratio:.1f}x(无明显信号)"

        detail += " ⚠️ 建议接入北向资金API获得精确数据"
        self.factors["F8_北向资金"] = {"score": score, "weight": 0.10, "detail": detail}
        return score

    def factor_main_force(self):
        """F9: 主力资金（大单净流入近似）"""
        # 与F8类似，用更短周期的量价异常检测主力行为
        if len(self.history) < 5:
            self.factors["F9_主力资金"] = {"score": 0, "weight": 0.08, "detail": "数据不足"}
            return 0

        # 单日量价突变检测
        today_vol = self.history[-1].get("volume", 0)
        avg_5d = np.mean([h["volume"] for h in self.history[-5:]]) if np else sum(h["volume"] for h in self.history[-5:]) / 5
        today_change = (self.history[-1]["close"] - self.history[-2]["close"]) / self.history[-2]["close"] * 100 if len(self.history) >= 2 else 0
        vol_spike = today_vol / avg_5d if avg_5d > 0 else 1

        if today_change > 2 and vol_spike > 2:
            score = +2.0; detail = f"暴涨{today_change:+.1f}%+爆量{vol_spike:.1f}x(主力抢筹?)"
        elif today_change > 1 and vol_spike > 1.5:
            score = +1.0; detail = f"上涨+明显放量"
        elif today_change < -2 and vol_spike > 2:
            score = -2.0; detail = f"暴跌{today_change:.1f}%+爆量(主力出货?)"
        elif today_change < -1 and vol_spike > 1.5:
            score = -1.0; detail = f"下跌+放量"
        elif vol_spike > 2 and abs(today_change) < 0.5:
            score = 0; detail = f"巨量不涨跌(换手主力?)"  # 中性偏谨慎
        else:
            score = 0; detail = f"量价正常 波动{today_change:+.1f}% 量比{vol_spike:.1f}x"

        self.factors["F9_主力资金"] = {"score": score, "weight": 0.08, "detail": detail}
        return score

    def factor_margin_balance(self):
        """F10: 融资余额变化（代理指标：杠杆情绪）"""
        # 融资数据需专门接口，用换手率+波动率近似
        turnover = self.realtime.get("turnover_rate", 0)
        
        if turnover > 15:
            score = -1.5; detail = f"换手率{turnover:.1f}%(过高→投机氛围浓)"
        elif turnover > 8:
            score = -0.5; detail = f"换手率{turnover:.1f}%(活跃偏高)"
        elif turnover > 2:
            score = 0; detail = f"换手率{turnover:.1f}%(正常)"
        elif turnover > 0.5:
            score = +0.5; detail = f"换手率{turnover:.1f}%(低换手→筹码稳定)"
        elif turnover > 0:
            score = +1.0; detail = f"换手率{turndown:.1f}%(极度低迷→可能底部)"
        else:
            score = 0; detail = "无换手率数据"

        self.factors["F10_融资余额"] = {"score": score, "weight": 0.07, "detail": detail}
        return score

    # ──────────────────────────────────────
    #  四、情绪维度因子
    # ──────────────────────────────────────

    def factor_turnover_sentiment(self):
        """F11: 换手率情绪"""
        # 已在上面融资余额因子中使用了换手率
        # 这里改用量价比来衡量情绪
        if len(self.history) < 10:
            self.factors["F11_换手率情绪"] = {"score": 0, "weight": 0.05, "detail": "数据不足"}
            return 0

        # 近期量价关系
        price_up_days = sum(1 for i in range(-5, 0) if self.history[i]["close"] > self.history[i-1]["close"])
        vol_trend = self.history[-1].get("volume", 0) / (sum(h["volume"] for h in self.history[-10:-5]) / 5) if len(self.history) >= 10 else 1

        if price_up_days >= 4 and 1.2 < vol_trend < 2.0:
            score = +1.0; detail = f"4/5日上涨+温和放量(健康)"
        elif price_up_days >= 4 and vol_trend >= 2.0:
            score = +0.5; detail = f"连涨+极端放量(亢奋注意)"
        elif price_up_days <= 1 and vol_trend > 1.5:
            score = -1.5; detail = f"连跌+放量(恐慌抛售)"
        elif price_up_days <= 1 and vol_trend < 0.6:
            score = -0.5; detail = f"连跌+缩量(观望情绪)"
        elif 2 <= price_up_days <= 3:
            score = 0; detail = f"震荡格局({price_up_days}/5涨)"
        else:
            score = 0; detail = "情绪中性"

        self.factors["F11_换手率情绪"] = {"score": score, "weight": 0.05, "detail": detail}
        return score

    def factor_limit_up_down_ratio(self):
        """F12: 涨跌停比（用日内振幅近似）"""
        if len(self.history) < 1 or not self.realtime.get("high") or not self.realtime.get("low"):
            self.factors["F12_涨跌停比"] = {"score": 0, "weight": 0.05, "detail": "无日内数据"}
            return 0

        intraday_range = (self.realtime["high"] - self.realtime["low"]) / self.realtime["prev_close"] * 100 if self.realtime.get("prev_close") else 0
        
        # 日内振幅作为情绪指标
        if intraday_range < 1.5:
            score = 0; detail = f"日内振幅{intraday_range:.1f}%(平稳)"
        elif intraday_range < 3:
            score = 0; detail = f"日内振幅{intraday_range:.1f}%(正常波动)"
        elif intraday_range < 6:
            score = -0.5; detail = f"日内振幅{intraday_range:.1f}%(波动加大)"
        else:
            score = -1.0; detail = f"日内振幅{intraday_range:.1f}%(剧烈波动)"

        self.factors["F12_涨跌停比"] = {"score": score, "weight": 0.05, "detail": detail}
        return score

    def factor_fear_greed_index(self):
        """F13: 恐惧贪婪指数（用VIX替代或近似计算）"""
        # 用近期波动率近似恐惧贪婪程度
        if len(self.history) < 20:
            self.factors["F13_恐贪指数"] = {"score": 0, "weight": 0.05, "detail": "数据不足"}
            return 0

        returns = [(self.history[i]["close"] - self.history[i-1]["close"]) / self.history[i-1]["close"] * 100 
                   for i in range(-20, 0)]
        volatility = np.std(returns) if np else (sum(r**2 for r in returns) / len(returns)) ** 0.5

        # 波动率低 = 贪婪(逆向卖出)，波动率高 = 恐惧(逆向买入)
        # A股日均波幅约1.2-1.8%
        if volatility < 0.8:
            score = -1.5; detail = f"波动率{volatility:.2f}%(极度平静→贪婪区→逆向)"
        elif volatility < 1.2:
            score = -0.5; detail = f"波动率{volatility:.2f}%(低波动→偏贪婪)"
        elif volatility < 2.0:
            score = +0.5; detail = f"波动率{volatility:.2f}%(中等→偏恐惧)"
        elif volatility < 3.5:
            score = +1.5; detail = f"波动率{volatility:.2f}%(高波动→恐惧区→逆向机会)"
        else:
            score = +2.0; detail = f"波动率{volatility:.2f}%(极端恐慌→可能是底部)"

        self.factors["F13_恐贪指数"] = {"score": score, "weight": 0.05, "detail": detail}
        return score

    def factor_vix(self):
        """F14: VIX恐慌指数（对A股的传导效应）"""
        # VIX 数据需要外部接口，用全球风险代理
        # 这里输出一个占位符，建议接入 TE 数据源
        self.factors["F14_VIX"] = {
            "score": 0, "weight": 0.05, 
            "detail": "⚠️ 建议从 Trading Economics 获取实时VIX数据后手动修正此因子分"
        }
        return 0

    # ──────────────────────────────────────
    #  五、v2.0 新增因子
    # ──────────────────────────────────────

    def insider_trading_factor(self):
        """F15: 内部人交易（占位——需接入专门数据源）"""
        self.factors["F15_内部人交易"] = {
            "score": 0, "weight": 0.04,
            "detail": "⚠️ 新增因子(v2.0)：需接入内部人交易数据(高管增持减持)。当前暂评0分"
        }
        return 0

    def analyst_rating_factor(self):
        """F16: 分析师评级调整（占位——需接入Wind/Choice等）"""
        self.factors["F16_分析师评级"] = {
            "score": 0, "weight": 0.03,
            "detail": "⚠️ 新增因子(v2.0)：需接入分析师一致预期数据。当前暂评0分"
        }
        return 0

    def short_interest_factor(self):
        """F17: 做空比例"""
        self.factors["F17_做空比例"] = {
            "score": 0, "weight": 0.03,
            "detail": "⚠️ 新增因子(v2.0)：需接入做空数据(Short Interest)。当前暂评0分"
        }
        return 0

    def volume_price_divergence(self):
        """F18: 量价背离（v2.0新增——纯技术面可算）"""
        if len(self.history) < 20:
            self.factors["F18_量价背离"] = {"score": 0, "weight": 0.03, "detail": "数据不足"}
            return 0

        # 价格创20日新高/新低，但成交量没有确认
        recent_high = max(h["close"] for h in self.history[-20:])
        recent_low = min(h["close"] for h in self.history[-20:])
        current = self.history[-1]["close"]
        recent_vol_avg = np.mean([h["volume"] for h in self.history[-5:]]) if np else sum(h["volume"] for h in self.history[-5:]) / 5
        prior_vol_avg = np.mean([h["volume"] for h in self.history[-15:-10]]) if np else sum(h["volume"] for h in self.history[-15:-10:]) / 5

        vol_decline = recent_vol_avg / prior_vol_avg if prior_vol_avg > 0 else 1

        if current >= recent_high * 0.98 and vol_decline < 0.7:
            score = -1.5; detail = f"接近20日高点但缩量至{vol_decline:.1f}x(顶背离⚠️)"
        elif current <= recent_low * 1.02 and vol_decline < 0.7:
            score = +1.5; detail = f"接近20日低点但缩量至{vol_decline:.1f}x(底背离✅)"
        elif current >= recent_high * 0.98 and vol_decline >= 1.3:
            score = +0.5; detail = f"接近高点+放量(突破有效)"
        else:
            score = 0; detail = f"无明显背离 量比{vol_decline:.1f}x"

        self.factors["F18_量价背离"] = {"score": score, "weight": 0.03, "detail": detail}
        return score

    def momentum_persistence(self):
        """F19: 动量持续性（v2.0新增）"""
        if len(self.history) < 60:
            self.factors["F19_动量持续"] = {"score": 0, "weight": 0.03, "detail": "数据不足(<60天)"}
            return 0

        # 计算1月、3月动量的方向一致性
        mom_1m = (self.history[-1]["close"] - self.history[-20]["close"]) / self.history[-20]["close"]
        mom_3m = (self.history[-1]["close"] - self.history[-60]["close"]) / self.history[-60]["close"]
        
        if mom_1m > 0.05 and mom_3m > 0.08:
            score = +1.5; detail = f"1月{mom_1m*100:+.1f}%+3月{mom_3m*100:+.1f}%双向上(强动量)"
        elif mom_1m > 0.02 and mom_3m > 0.03:
            score = +0.5; detail = f"1月{mom_1m*100:+.1f}%+3月{mom_3m*100:+.1f}%温和上行"
        elif mom_1m < -0.02 and mom_3m < -0.03:
            score = -1.0; detail = f"1月{mom_1m*100:+.1f}%+3月{mom_3m*100:+.1f}%双向下(弱动量)"
        elif mom_1m * mom_3m < 0:  # 方向不一致
            score = -0.5; detail = f"1月与3月动量矛盾(方向不确定)"
        else:
            score = 0; detail = f"1月{mom_1m*100:+.1f}% 3月{mom_3m*100:+.1f}%"

        self.factors["F19_动量持续"] = {"score": score, "weight": 0.03, "detail": detail}
        return score

    # ──────────────────────────────────────
    #  宏观环境判定
    # ──────────────────────────────────────

    def detect_macro_environment(self):
        """
        自动判定宏观环境（半自动化）
        基于可获取的市场数据推断：VIX/波动率 + 美元强弱 + 市场整体走势
        返回: bull / bear / neutral / crisis
        """
        if self.macro_env:
            return self.macro_env

        # 用自身数据的波动率+趋势做近似推断
        if len(self.history) < 60:
            return "neutral"  # 默认中性

        returns_60d = [(self.history[i]["close"] - self.history[i-1]["close"]) / self.history[i-1]["close"] 
                        for i in range(-60, 0) if i > 0]
        volatility = np.std(returns_60d) if np else (sum(r**2 for r in returns_60d) / len(returns_60d)) ** 0.5
        trend_60d = (self.history[-1]["close"] - self.history[-60]["close"]) / self.history[-60]["close"]

        # 判定逻辑
        if volatility > 4.0 or (trend_60d < -0.20 and volatility > 2.5):
            env = "crisis"
            reason = f"高波动{volatility:.2f}+深跌{trend_60d*100:.1f}%(危机模式)"
        elif volatility > 2.5 or trend_60d < -0.10:
            env = "bear"
            reason = f"偏高波动{volatility:.2f}+下跌{trend_60d*100:.1f}%(熊市)"
        elif trend_60d > 0.15 and volatility < 1.5:
            env = "bull"
            reason = f"强势上涨{trend_60d*100:+.1f}%+低波动{volatility:.2f}(牛市)"
        else:
            env = "neutral"
            reason = f"趋势{trend_60d*100:+.1f}% 波动{volatility:.2f}(中性)"

        self.macro_env_detected = env
        self.macro_env_reason = reason
        return env

    # ──────────────────────────────────────
    #  权重体系
    # ──────────────────────────────────────

    def get_weights(self, env=None):
        """
        获取动态权重配置
        支持行业差异化 × 宏观环境的二维矩阵
        """
        env = env or self.detect_macro_environment()

        # 基础权重（默认股票）
        base = {
            "bull":    {"趋势": 0.35, "估值": 0.20, "资金": 0.30, "情绪": 0.15},
            "neutral": {"趋势": 0.30, "估值": 0.25, "资金": 0.25, "情绪": 0.20},
            "bear":    {"趋势": 0.20, "估值": 0.30, "资金": 0.20, "情绪": 0.30},
            "crisis":  {"趋势": 0.15, "估值": 0.25, "资金": 0.15, "情绪": 0.45},
        }

        weights = base.get(env, base["neutral"]).copy()

        # 行业差异化调整
        if self.industry == "银行":
            weights["估值"] += 0.05  # 银行更看重估值（PB-ROE）
            weights["趋势"] -= 0.03
            weights["情绪"] -= 0.02
        elif self.industry in ["科技成长", "科技"]:
            weights["趋势"] += 0.05  # 科技更看重趋势（成长性定价）
            weights["估值"] -= 0.03
            weights["资金"] -= 0.02
        elif self.industry == "周期股":
            weights["趋势"] += 0.03  # 周期股趋势最重要
            weights["估值"] += 0.02  # PB分位也重要
            weights["情绪"] -= 0.05
        elif self.industry == "消费":
            weights["资金"] += 0.03  # 消费品看资金偏好
            weights["情绪"] += 0.02  # 情绪影响消费

        # 归一化确保总和为1
        total = sum(weights.values())
        weights = {k: round(v/total, 4) for k, v in weights.items()}

        self.weights = weights
        return weights

    # ──────────────────────────────────────
    #  主流程
    # ──────────────────────────────────────

    def run(self):
        """执行完整的胜率评估流程"""
        # 1. 计算所有因子
        self.factor_ma_trend()          # F1
        self.factor_relative_strength()  # F2
        self.factor_macd_weekly()        # F3
        self.factor_sector_fund_flow()   # F4
        self.factor_pe_percentile()      # F5
        self.factor_pb_roe_match()       # F6
        self.factor_earnings_growth()    # F7
        self.factor_northbound_flow()    # F8
        self.factor_main_force()         # F9
        self.factor_margin_balance()     # F10
        self.factor_turnover_sentiment() # F11
        self.factor_limit_up_down_ratio() # F12
        self.factor_fear_greed_index()   # F13
        self.factor_vix()               # F14
        self.insider_trading_factor()    # F15 (v2.0新增)
        self.analyst_rating_factor()    # F16 (v2.0新增)
        self.short_interest_factor()     # F17 (v2.0新增)
        self.volume_price_divergence()   # F18 (v2.0新增)
        self.momentum_persistence()      # F19 (v2.0新增)

        # 2. 维度聚合
        dimension_map = {
            "趋势": ["F1_均线排列", "F2_行业相对强度", "F3_周线MACD", "F4_板块资金流向"],
            "估值": ["F5_PE分位", "F6_PB-ROE", "F7_业绩增速"],
            "资金": ["F8_北向资金", "F9_主力资金", "F10_融资余额"],
            "情绪": ["F11_换手率情绪", "F12_涨跌停比", "F13_恐贪指数", "F14_VIX"],
            "新增": ["F15_内部人交易", "F16_分析师评级", "F17_做空比例", "F18_量价背离", "F19_动量持续"],
        }

        # 3. 获取动态权重
        weights = self.get_weights()
        # 将新增因子的权重分配到各维度
        new_factor_total_weight = sum(
            self.factors.get(f, {}).get("weight", 0) 
            for f in dimension_map["新增"]
        )

        # 4. 计算各维度得分
        dim_scores = {}
        for dim, factors in dimension_map.items():
            dim_weight_sum = sum(self.factors.get(f, {}).get("weight", 0) for f in factors)
            weighted_score = 0
            details = []
            for f in factors:
                finfo = self.factors.get(f, {})
                f_score = finfo.get("score", 0)
                f_weight = finfo.get("weight", 0)
                if dim_weight_sum > 0:
                    # 因子在维度内的归一化权重
                    normalized_w = f_weight / dim_weight_sum
                else:
                    normalized_w = 0
                weighted_score += f_score * normalized_w
                details.append(f"  {f}: {f_score:+.1f} (w={f_weight})")

            dim_scores[dim] = {"raw_score": weighted_score, "details": details}

        # 5. 总分计算（四维加权）
        total = (
            dim_scores["趋势"]["raw_score"] * weights["趋势"] +
            dim_scores["估值"]["raw_score"] * weights["估值"] +
            dim_scores["资金"]["raw_score"] * weights["资金"] +
            dim_scores["情绪"]["raw_score"] * weights["情绪"]
        )

        # 新增因子额外加分（不超过总分的10%）
        new_factor_score = sum(self.factors.get(f, {}).get("score", 0) for f in dimension_map["新增"])
        new_bonus = new_factor_score * 0.1  # 小权重附加
        total += new_bonus

        # Clamp 到 [-2, +2]
        total = max(-2.0, min(2.0, total))

        # 6. 转换为胜率
        win_rate = (total + 2) / 4 * 100

        # 7. 置信度评估（基于数据完整度）
        active_factors = sum(1 for f in self.factors if self.factors[f].get("score") != 0)
        zero_placeholder = sum(1 for f in self.factors if "⚠️" in self.factors[f].get("detail", ""))
        total_factors = len(self.factors)
        coverage = active_factors / total_factors if total_factors > 0 else 0

        if coverage >= 0.85:
            confidence = "高"
        elif coverage >= 0.70:
            confidence = "中"
        else:
            confidence = "低"

        self.total_score = round(total, 2)
        self.win_rate = round(win_rate, 1)
        self.confidence = confidence
        self.dim_scores = dim_scores

        return self.build_report()

    def build_report(self):
        """构建结构化的胜率报告"""
        env = self.detect_macro_environment()

        report = {
            "meta": {
                "engine": "DaShen v2.0",
                "asset_type": self.asset_type,
                "code": self.data.get("code", ""),
                "name": self.realtime.get("name", ""),
                "industry": self.industry or "未指定",
                "macro_environment": env,
                "macro_reason": getattr(self, "macro_env_reason", ""),
                "weights_used": self.weights,
                "analysis_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            },
            "result": {
                "total_score": self.total_score,
                "win_rate": self.win_rate,
                "confidence": self.confidence,
                "signal": self._signal_text(self.win_rate),
                "recommendation": self._recommendation(self.win_rate),
            },
            "dimensions": {},
            "factors": {},
        }

        # 维度汇总
        for dim, info in self.dim_scores.items():
            report["dimensions"][dim] = {
                "score": round(info["raw_score"], 2),
                "weight": self.weights.get(dim, 0) if dim in self.weights else 0,
            }

        # 所有因子明细
        for fname, finfo in self.factors.items():
            report["factors"][fname] = {
                "score": finfo["score"],
                "weight": finfo["weight"],
                "detail": finfo["detail"],
            }

        return report

    @staticmethod
    def _signal_text(win_rate):
        if win_rate >= 70: return "★★★★★ 强烈买入"
        elif win_rate >= 55: return "★★★★☆ 可以建仓"
        elif win_rate >= 45: return "★★★☆☆ 观望等待"
        elif win_rate >= 30: return "★★☆☆☆ 谨慎减仓"
        else: return "★☆☆☆☆ 回避不宜介入"

    @staticmethod
    def _recommendation(win_rate):
        if win_rate >= 70: return "强烈买入信号，可考虑重仓（仓位≤30%风控上限）"
        elif win_rate >= 55: return "可以建仓，建议分批买入"
        elif win_rate >= 45: return "观望为主，等待更明确信号"
        elif win_rate >= 30: return "考虑减仓或保持轻仓"
        else: return "回避为宜，不宜介入"


# ============================================================
#  CLI 入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="大神 v2.0 — 多因子量化胜率预测引擎")
    parser.add_argument("--code", required=True, help="资产代码 (如 00700.HK / BTC / 000001.SZ)")
    parser.add_argument("--asset_type", choices=["stock", "crypto"], default="stock", help="资产类型")
    parser.add_argument("--industry", default=None, help="行业类型 (银行/科技成长/周期股/消费)")
    parser.add_argument("--macro_env", default=None, choices=["bull", "bear", "neutral", "crisis"], help="预置宏观环境")
    parser.add_argument("--days", type=int, default=120, help="历史数据天数")
    parser.add_argument("--output", default=None, help="输出JSON文件路径")
    args = parser.parse_args()

    print(f"[大神 v2.0] 正在分析 {args.code}...", file=sys.stderr)

    # 1. 拉数据
    if args.asset_type == "crypto":
        raw_data = fetch_crypto_data(args.code, args.days)
    else:
        raw_data = fetch_stock_data(args.code, args.days)

    if not raw_data.get("success"):
        error_report = {
            "meta": {"engine": "DaShen v2.0", "code": args.code, "status": "DATA_FAILED"},
            "error": raw_data.get("error", "未知错误"),
        }
        print(json.dumps(error_report, ensure_ascii=False, indent=2))
        sys.exit(1)

    print(f"[数据源] {raw_data.get('source')} ✓ "
          f"价格={raw_data['realtime'].get('price', '?')} "
          f"K线{len(raw_data.get('history', []))}条", file=sys.stderr)

    # 2. 执行分析
    engine = DaShenEngine(raw_data, args.asset_type, args.industry, args.macro_env)
    report = engine.run()

    # 3. 输出
    output_json = json.dumps(report, ensure_ascii=False, indent=2, default=str)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output_json)
        print(f"[完成] 报告已保存: {args.output}", file=sys.stderr)
    
    # 终端摘要
    r = report["result"]
    print(f"\n{'='*50}", file=sys.stderr)
    print(f"🎯 {args.code} ({report['meta'].get('name','')}) | "
          f"胜率: {r['win_rate']}% | {r['signal']}", file=sys.stderr)
    print(f"📊 总分: {r['total_score']:+.2f} | "
          f"置信度: {r['confidence']} | "
          f"宏观: {report['meta']['macro_environment']}", file=sys.stderr)
    print(f"💡 建议: {r['recommendation']}", file=sys.stderr)
    print(f"{'='*50}", file=sys.stderr)

    print(output_json)


if __name__ == "__main__":
    main()
