# ESI 项目交接说明

本文档用于后续 agent 或 context compact 后继续开发。每完成一个模块，都应同步更新这里。

## 项目目标

ESI, Equity Stress Index, 用于预测美股短期 5D/10D/20D 下行震荡。它衡量的是风险状态和金融环境，不是美元流动性数量。项目当前保持 v1 线性、可解释、纯文件系统，无数据库依赖。

## 运行方式

```bash
cd "/Users/linshuren/Documents/ESI index"
source .venv/bin/activate
export FRED_API_KEY="你的 FRED key"
python run_daily.py
```

单测：

```bash
pytest tests/test_fetchers.py tests/test_factors.py tests/test_composite.py tests/test_evaluation.py tests/test_reporting.py
```

## GitHub 与定时任务

仓库地址：

```text
https://github.com/shurenl/equlity_stress_index
```

已新增 GitHub Actions workflow：

```text
.github/workflows/daily-esi-report.yml
```

行为：

- 每天北京时间 08:30 自动运行，cron 为 `30 0 * * *` UTC。
- 支持手动触发 `workflow_dispatch`。
- workflow 顶层设置 `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24=true`，提前切到 Node.js 24，避免 GitHub Actions Node.js 20 deprecation warning。
- 安装 Python 3.11 和 `requirements.txt`。
- 使用 GitHub repository secret `FRED_API_KEY`。
- 执行 `python run_daily.py`。
- 使用 Gmail SMTP 发送最新 PDF。
- 上传 artifact：
  - `esi-daily-report`: `reports/*.pdf`
  - `esi-evaluation-tables`: `data/processed/evaluation/*.csv`

首次配置 GitHub 后，必须在 repo settings 中添加：

```text
Settings -> Secrets and variables -> Actions -> New repository secret
Name: FRED_API_KEY
Value: 用户自己的 FRED key
```

Gmail 发送还需要：

```text
Name: GMAIL_USERNAME
Value: 用户的 Gmail 地址

Name: GMAIL_APP_PASSWORD
Value: Google 账号生成的 App Password，不是普通登录密码

Name: REPORT_EMAIL_TO
Value: 收件邮箱；可选，不设置时默认发送给 GMAIL_USERNAME
```

邮件发送入口：

```text
src/email_report.py
```

workflow 会先生成 PDF，再运行 `python -m src.email_report`。PDF 同时保留为 GitHub artifact，便于邮件失败时排查。

## 当前目录结构

```text
 .github/
  workflows/
    daily-esi-report.yml
config/
  factors.yaml
data/
  raw/
  processed/
    evaluation/
reports/
src/
  fetchers/
  factors/
  composite.py
  evaluation.py
  reporting.py
  main.py
tests/
run_daily.py
requirements.txt
README.md
read.md
```

## 数据层

入口：`src/fetchers/`

- `BaseFetcher.update_cache(...)` 负责 parquet 增量缓存、metadata 更新、工作日频率标准化、`ffill(limit=3)`。
- `FREDFetcher` 从环境变量 `FRED_API_KEY` 读取 key。
- `YahooFetcher` 使用 yfinance，支持重试和退避。
- Yahoo 被限流时，已做公开源 fallback：
  - `^VIX`, `^VIX3M`, `^SKEW` 使用 CBOE CSV。
  - `^MOVE` 使用 Convex Trade MOVE CSV。
- `breadth_proxy` 已从 Yahoo `RSP/SPY` 改为 FRED `NASDAQNQUS500LCE/NASDAQNQUS500LC`，避免 ETF 限流。

主要输出：

- `data/raw/*.parquet`
- `data/cache_meta.json`

## 因子层

入口：`src/factors/base.py`

每个因子输出 5 类列：

- `{factor}_raw`
- `{factor}_transformed`
- `{factor}_z_score`
- `{factor}_winsorized`
- `{factor}_nonlinear`

变换规则：

- `diff_5d`: 5 日差分。
- `diff_20d_pct`: 20 日 pct change。
- `ratio_minus_one`: 第一列 / 第二列 - 1。
- `diff_from_ma60`: 相对 60 日均线偏离。
- `ratio_chg_20d`: 第一列 / 第二列的 20 日变化取负，让广度走弱为压力正值。

主要输出：

- `data/processed/factors.parquet`

## 合成层

入口：`src/composite.py`

已实现两种模式：

- `equal_weighted`: 按 `config/factors.yaml` 的 weight 合成。若当日某因子为 NaN，会在当日可用因子之间重归一。
- `ic_weighted`: 用滚动 252D Spearman IC 作为权重，目标为 SPX 未来 10D 回报。实现中使用 `t-horizon` 之前已经可观测的样本，避免未来函数。

主要输出：

- `data/processed/esi.parquet`
- `data/processed/component_contributions_equal_weighted.parquet`
- `data/processed/component_contributions_ic_weighted.parquet`
- `data/processed/ic_weights.parquet`

## 评估层

入口：`src/evaluation.py`

已实现：

- IC 矩阵：signals × targets × horizons，含 `ic`, `t_stat`, `p_value`, `n`。
- Hit ratio：ESI 高分位时未来 10D 回撤 >3%/>5% 的概率。
- Signal quality：未来 10D 最大回撤 >5% 的 precision/recall/F1。
- Conditional distribution：按 ESI 分位桶统计未来 10D 回报。
- Benchmark correlation：ESI vs NFCI/STLFSI4。
- Data coverage：检查原始序列是否覆盖 2020 起点。

主要输出：

- `data/processed/evaluation/ic_matrix.csv`
- `data/processed/evaluation/hit_ratio.csv`
- `data/processed/evaluation/signal_quality.csv`
- `data/processed/evaluation/benchmark_correlation.csv`
- `data/processed/evaluation/conditional_returns.csv`
- `data/processed/evaluation/data_coverage.csv`

## 报告层

入口：`src/reporting.py`

使用 matplotlib `PdfPages` 生成每日 PDF：

- Snapshot
- 252D ESI trend
- ESI composition 独立页：配置权重、最新 z-score、最新 nonlinear、最新 contribution
- ESI component details 独立小图页：每个 component 单独显示最近 252D z-score 走势，并标注 raw、transformed、z-score、nonlinear、weight、contribution。
- 当日分量贡献柱状图
- 最近 60D 因子 z-score heatmap
- IC matrix table
- Hit ratio 和 conditional return chart
- ESI vs NFCI/STLFSI4
- Benchmark correlation 和 data coverage diagnostics
- 每张图都带 Interpretation 文本，说明该图如何阅读以及对 ESI 的含义。
- 数值显示规则：`NaN` 显示为 `NA`；`-0.000` 统一显示为 `0.000`。若 `dxy`、`vix_term_structure`、`credit_ig` 等 component 的 nonlinear/contribution 为 0，通常表示其 `|z| < 0.5`，被 nonlinear 规则主动压成 0，不代表原始数据缺失。

主要输出：

- `reports/esi_daily_report_YYYY-MM-DD.pdf`

## 已知限制

1. FRED 当前公开 `BAMLH0A0HYM2` 和 `BAMLC0A0CM` 在本环境只从 2023-05 开始，导致信用因子无法覆盖 2020-03 和 2022-Q2。
2. 因为信用历史不足，用户设定的 HY OAS 对 SPX 未来 10D 回报 IC 显著为负这一验证项当前不能完整成立。
3. `QQQ` 目标暂未纳入评估输出，原因是 Yahoo 当前限流，且 v1 尚未接入 ETF 付费或带 key 的稳定数据源。
4. 报告层先使用 matplotlib 原生表格，视觉可读但还不是最终 ULSI 风格复刻。

## 下一步建议

1. 优先解决信用历史回填。2026-05-13 已确认 FRED/ALFRED 的 `BAMLH0A0HYM2` 当前公开历史只从 2023-05 开始。建议下一步实现 `LocalCsvFetcher`：
   - 支持 `local_csv` source；
   - CSV 至少包含 `date,value` 或 `date,<ticker>`；
   - 先用本地授权/手工下载的 ICE/BofA HY 与 IG OAS 历史补齐到 2020；
   - 然后重新运行 factor/composite/evaluation/report。
2. 完善报告视觉风格，使其接近用户提供的 ULSI PDF。
3. 把 `QQQ` 目标接到稳定数据源。
4. 增加已知压力期验证测试：
   - 2020-03
   - 2022-Q2
   - 2023-03 SVB
5. 增加 CLI 参数：`--start`, `--end`, `--skip-fetch`, `--mode`。

## 模块完成状态

- 数据层：完成，测试 `tests/test_fetchers.py`。
- 因子层：完成，测试 `tests/test_factors.py`。
- 合成层：完成，测试 `tests/test_composite.py`。
- 评估层：完成，测试 `tests/test_evaluation.py`。
- 报告层：完成基础版，测试 `tests/test_reporting.py`。

## 最近更新记录

- 2026-05-13: 新增 GitHub Actions 每日定时任务，自动生成 PDF 并上传 artifact。
- 2026-05-14: 新增 Gmail SMTP 自动发送 PDF 报告，需要配置 `GMAIL_USERNAME`、`GMAIL_APP_PASSWORD`、可选 `REPORT_EMAIL_TO`。
- 2026-05-14: GitHub Actions workflow 新增 `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24=true`，处理 Node.js 20 deprecation warning。
- 2026-05-13: 报告层新增 ESI composition 独立页。
- 2026-05-13: 报告层新增 component detail 小图页，拆开显示每个 ESI 组成项。
- 2026-05-13: 修复报告数值显示，避免 `dxy`、`vix_term_structure`、`credit_ig` 的 0 nonlinear/contribution 被误读为缺失。
- 2026-05-13: 报告层所有图页新增 Interpretation 文本。
- 2026-05-13: 继续确认信用历史 blocker，FRED/ALFRED 无法直接回填 2020 历史。
