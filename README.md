# 🎯 大神 (DaShen) v2.0.0

**从"规则说明书"升级为"可执行引擎"的多因子量化胜率预测系统。**

> 回答一个核心问题：**当前时点买入，赢的概率有多大？**

---

## 核心升级（v1.1.0 → v2.0.0）

```
v1.1.0                          v2.0.0
────────                         ─────────
纯文本SKILL.md                    Python计算引擎 + SKILL.md双驱动
14个因子                          19个因子（+5个新因子）
5档得分 (-2~+2)                   11档得分 (-2.0~+2.0 步长0.5)
手动推理打分                      代码自动拉数据+算分+出报告
无行业差异化                       4种行业权重表
手动判断宏观环境                   半自动宏观判定函数
financial-shrimp命名              financial-tycoon（统一）
```

### v2.0.0 亮点

| 能力 | 说明 |
|------|------|
| 🐍 **Python 引擎** | `scripts/dashen_engine.py` (~730行)，一行命令跑完整分析 |
| 📊 **19个因子** | 趋势4 + 估值3 + 资金3 + 情绪4 + 新增5 |
| 🎯 **11档精度** | 得分步长 0.5，信息精度提升4倍 |
| 🏭 **行业差异化** | 银行/科技成长/周期股/消费 四套权重配置 |
| 🔮 **自动宏观判定** | 基于波动率+趋势推断 牛/熊/中性/危机 |
| 🔗 **Tycoon 互操作** | 与金融巨鳄 v2.0.1 双向联动，定性+定量双重验证 |
| 📡 **多源数据** | 东方财富/新浪/CoinGecko/Binance 自动切换 |

---

## 快速开始

```bash
# 分析腾讯控股
python scripts/dashen_engine.py --code 00700.HK --asset_type stock

# 加密货币
python scripts/dashen_engine.py --code BTC --asset_type crypto

# 指定行业（触发差异化权重）
python scripts/dashen_engine.py --code 600036.SH --asset_type stock --industry 银行
python scripts/dashen_engine.py --code 300750.SZ --asset_type stock --industry 科技成长

# 输出到文件
python scripts/dashen_engine.py --code 00700.HK --output report.json
```

---

## 输出示例

```json
{
  "result": {
    "total_score": 1.18,
    "win_rate": 79.5,
    "confidence": "高",
    "signal": "★★★★★ 强烈买入",
    "recommendation": "强烈买入信号，可考虑重仓"
  }
}
```

---

## 文件结构

```
dashen-skill/
├── SKILL.md                        # 技能主文件（v2.0.0 工程化版）
├── README.md                       # 本文件
├── references/                     # 参考文档
│   ├── stock-factors.md            # 股票14因子详解（v1.x参考）
│   ├── crypto-factors.md           # 加密货币因子详解
│   ├── fund-factors.md             # 基金因子详解
│   ├── macro-factors.md            # 宏观因子详解
│   └── report-template.md          # 报告模板（v1.x参考）
├── templates/                      # 模板
│   └── report-template.md          # 报告模板
└── scripts/                        # 工具脚本 ⭐
    └── dashen_engine.py            # ★ v2.0 核心：多因子胜率预测引擎
```

---

## 与其他 Skill 的关系

| Skill | 角色 | 关系 |
|-------|------|------|
| **金融巨鳄 (tycoon)** | 主分析引擎，定性+风控+大师 | 调用大神做胜率验证 |
| **大神 (我)** | 胜率评分，定量打分引擎 | 输出胜率→嵌入tycoon步骤⑦ |

> 使用原则：**tycoon 给方向，大神给概率，两者一致才行动。**

---

## 胜率区间

| 区间 | 信号 | 操作建议 |
|------|------|----------|
| ≥70% | ★★★★★ 强烈买入 | 可重仓（≤30%风控上限）|
| 55-70% | ★★★★☆ 可以建仓 | 分批买入 |
| 45-55% | ★★★☆☆ 观望 | 等待明确信号 |
| 30-45% | ★★☆☆☆ 谨慎 | 考虑减仓 |
| <30% | ★☆☆☆☆ 回避 | 不宜介入 |

---

## 更新日志

| 版本 | 日期 | 要点 |
|------|------|------|
| **v2.0.0** | 2026-04-17 | Python引擎、19因子、11档精度、行业差异化、宏观自动判定、命名统一 |
| v1.1.0 | 2026-04-14 | 动态权重、Skill互操作、分歧处理规则 |
| v1.0.0 | 2026-04-08 | 初始版本：纯文本规则，四维评分体系 |

---

⚠️ 仅供学习参考，不构成投资建议。投资有风险，入市需谨慎。

---

*贾维斯 × MOSS | 2026-04-17*
