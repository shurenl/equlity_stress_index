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
.venv/bin/python -m pytest
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
- workflow 使用 Node.js 24-compatible action 版本：`actions/checkout@v5`、`actions/setup-python@v6`、`actions/upload-artifact@v7`，避免 GitHub Actions Node.js 20 deprecation warning。
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

如果 GitHub Actions 只显示 `Process completed with exit code 1`，先展开失败 step 上方日志。当前 workflow 已在 `Check required secrets` step 一次性检查：

- `FRED_API_KEY`
- `GMAIL_USERNAME`
- `GMAIL_APP_PASSWORD`

最常见失败原因：

- 没配置某个 repository secret；
- `GMAIL_APP_PASSWORD` 不是 Google App Password；
- Google 账号未开启 2-Step Verification，导致无法创建/使用 App Password；
- Gmail SMTP 登录被 Google 安全策略拒绝。

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

### Credit Long-History Step 1

2026-05-14 已开始 `Credit Long-History Upgrade + Full-Horizon IC Diagnostics`，当前完成 Step 1：

- `config/factors.yaml` 新增 Moody's 长史信用因子：
  - `credit_baa_10y`: FRED `BAA10Y`
  - `credit_aaa_10y`: FRED `AAA10Y`
  - `credit_baa_aaa`: computed `BAA10Y - AAA10Y`
- `credit_hy` 权重从 `0.30` 降到 `0.20`，`credit_ig` 从 `0.10` 降到 `0.05`。
- `vix_term_structure/move/dxy` 权重分别降到 `0.15/0.10/0.10`，总权重保持 1.0。
- `breadth_proxy` 仍保留 FRED `NASDAQNQUS500LCE/NASDAQNQUS500LC`，不切回 Yahoo `RSP/SPY`，原因是此前 Yahoo ETF 限流会破坏每日主流程。
- `FREDFetcher` 支持安全的 `ticker_compute` 表达式，仅允许 FRED ticker、数字常量、括号和 `+ - * /`。
- 新增 `src/factors/credit_long.py`，提供 `CreditBaa10Y`、`CreditAaa10Y`、`CreditBaaAaa` 类。

Moody's level 注意事项：`BAA10Y/AAA10Y` 的债券久期与 ICE BofA OAS 不同，level 不应直接比较；后续诊断应比较 `diff_5d`、z-score、rolling IC。

### Credit Long-History Step 2

2026-05-14 已实现并运行：

```text
scripts/validate_credit_substitute.py
```

输出：

```text
data/diagnostics/credit_substitute_validation.png
```

正式验证结果：

- overlap: `2023-05-15` 到 `2026-05-13`
- overlap observations: `783`
- BAA10Y vs BAMLC0A0CM 5D change Pearson correlation: `0.7826`
- 252D z-score of 5D changes correlation: `0.7955`
- level z-score correlation: `0.8736`
- min required correlation: `0.80`
- passed: `False`

结论：按用户设定的规则，Moody's `BAA10Y` 不能直接作为 `BAMLC0A0CM` 的 5D-change 替代进入 Step 3。虽然 level z-score 相关性尚可，但真正用于因子的 `diff_5d` 与其 z-score 相关性低于 0.80。应暂停诊断模块扩展，先重新审视信用替代假设。

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
- 信用长史 Step 1：完成，新增 Moody's `BAA10Y/AAA10Y/BAA10Y-AAA10Y` 因子和 FRED `ticker_compute`。
- 信用长史 Step 2：完成，替代验证未通过，详见 `data/diagnostics/credit_substitute_validation.png`。
- 诊断 Step 3：完成，新增 `src/diagnostics/regime_split.py` 与 `src/diagnostics/horizon_scan.py`，输出 horizon IC 表格，不含可视化。
- 诊断 Step 4：完成最小 rolling IC 闭环，新增 `credit_baa_10y x ^GSPC x +10D` 的 126D rolling IC 计算和图表输出。
- 诊断 Step 5：完成诊断 PDF 最小完整闭环，新增全因子 rolling IC summary 和 `esi_diagnostics_YYYY-MM-DD.pdf`。
- 诊断 Step 6：完成 README/交接文档更新和配置回归测试，确认 v1 合成层使用 `config/factors.yaml` 新权重。

## Diagnostics 模块当前状态

入口：

```bash
.venv/bin/python -m src.diagnostics.run_diagnostics
.venv/bin/python -m src.diagnostics.run_diagnostics --no-pdf
python -m src.diagnostics.run_diagnostics --factor credit_baa_10y --no-pdf
python -m src.diagnostics.run_diagnostics --long-history-only --no-pdf
```

当前 Step 3 输出：

- `data/diagnostics/horizon_ic_matrix.parquet`
- `data/diagnostics/horizon_classification.parquet`

实现文件：

- `config/diagnostics.yaml`
- `src/diagnostics/__init__.py`
- `src/diagnostics/horizon_scan.py`
- `src/diagnostics/regime_split.py`
- `src/diagnostics/run_diagnostics.py`
- `tests/test_diagnostics.py`

Step 3 关键观察：

- 大多数信用短史因子、VIX term、MOVE 的最大 `|t-stat|` 出现在负 horizon，说明它们在当前定义下更像同步/滞后压力确认，而不是纯领先信号。
- `credit_baa_10y` 在 `^GSPC/^NDX` 上被分类为 `LEADING`，但最强 horizon 仍出现在 `-10D`，需要 Step 4 rolling IC 进一步确认长期稳定性。
- `esi_equal_weighted` 与 `esi_ic_weighted` 均出现 `REVERSED` 标签，解释了 v1 报告里 ESI IC 符号反的问题：未来正 horizon 上存在显著反向相关段。
- `QQQ` 暂未进入 Step 3 诊断，因为本地仍没有稳定 QQQ 缓存映射；当前诊断目标为 `^GSPC` 和 `^NDX`。

Step 4 当前入口：

```bash
export FRED_API_KEY="your_fred_api_key"
.venv/bin/python -m src.diagnostics.run_diagnostics --rolling-credit-demo --no-pdf
```

Step 4 输出：

- `data/diagnostics/rolling_ic_credit_baa_10y_GSPC.parquet`
- `data/diagnostics/rolling_ic_credit_baa_10y_GSPC_summary.parquet`
- `data/diagnostics/credit_long_history_ic_analysis.png`

实现文件：

- `src/diagnostics/rolling_ic.py`
- `src/diagnostics/run_diagnostics.py`
- `tests/test_diagnostics.py`

Step 4 实现细节：

- `rolling_ic_series()` 仅支持正向 horizon。
- 对 `horizon=10`，输出日期 `t` 的 rolling IC 只使用到 `t-10-1` 的样本，避免未来函数。
- 当前 Codex 进程没有继承 `FRED_API_KEY`，因此本地复跑只能使用已有 `SP500` 短史缓存，得到 1551 个有效窗口；在用户 shell 设置 `FRED_API_KEY` 后重新运行同一命令，会自动把 `SP500` 缓存扩展到 1990 起点，再生成真正的 1990-2026 长史图。
- 短史复跑结果：`credit_baa_10y +10D` rolling IC 平均值 `-0.00278`，最后一年均值 `0.0351`，期望负号一致性约 `51.8%`。这个结果不能替代长史结论，只说明当前 2020 后窗口内信号稳定性很弱。

Step 5 输出：

- `data/diagnostics/rolling_ic_all.parquet`
- `data/diagnostics/rolling_ic_summary.parquet`
- `reports/diagnostics/esi_diagnostics_YYYY-MM-DD.pdf`

Step 5 实现文件：

- `src/diagnostics/reporting_diag.py`
- `src/diagnostics/rolling_ic.py`
- `src/diagnostics/run_diagnostics.py`
- `tests/test_diagnostics.py`

Step 5 报告内容：

- Executive Summary：分类标签数量、leading/reversed 因子清单、`credit_baa_10y` rolling IC 摘要。
- Factor Classification：来自 horizon scan 的分类表。
- Rolling IC Summary：全 signal × target × horizon 的 126D rolling IC 汇总。
- Horizon IC Scan：按目标分别画 IC by horizon 折线图。
- Rolling IC Mean Heatmap：当前先聚焦 `^GSPC`，颜色表示平均 rolling IC。
- Credit Substitute Validation：嵌入 `credit_substitute_validation.png`。
- Credit Long-History Rolling IC：嵌入 `credit_long_history_ic_analysis.png`。

Step 5 当前关键发现：

- 全量 rolling summary 共 72 行：12 个 signal × 2 个目标 × 3 个 horizon。`QQQ` 仍跳过。
- `esi_equal_weighted` 和 `esi_ic_weighted` 的 rolling mean IC 多为正，和 stress 因子期望负号相反，继续支持“当前 ESI 更像同步/反转指标而非领先下行指标”的判断。
- `vix_term_structure`、`move`、`dxy` 的 rolling mean IC 多为正，和 Step 3 的 `REVERSED` 分类一致。
- `credit_baa_10y` 对 `^GSPC +5D` 的 rolling mean IC 为负，但 `+10D/+20D` 变弱或转正；这需要长史 SP500 缓存后再重新评估。
- 为避免无效长史窗口拖慢计算，`rolling_ic_series()` 已改为只在 signal 和 forward return 同时非空的交集日期上滚动。

Step 6 收尾：

- `README.md` 已补充每日 ESI、Moody's 长史因子、诊断 CLI、诊断输出文件和测试命令。
- 新增 `tests/test_config.py`：
  - 验证 `config/factors.yaml` 权重总和为 1.0；
  - 验证 `credit_hy/credit_ig` 已降权，Moody's 三个长史信用因子存在并使用新权重；
  - 验证 `config/diagnostics.yaml` 的 expected signs 覆盖所有因子和两种 ESI 模式。
- v1 合成层确认无旧权重硬编码：
  - `src/composite.py::config_weights()` 直接读取 `config/factors.yaml`；
  - `build_equal_weighted()` 使用配置权重，并在当日可用因子之间重归一；
  - `build_ic_weighted()` 使用滚动 IC 权重，非 YAML 固定权重。

Step 7 目标长史修复：

- 用户在终端设置 `FRED_API_KEY` 后，diagnostics 已刷新 `fred_SP500.parquet`，但 FRED `SP500` 当前本地有效起点只有 `2016-05-16`，无法满足 1990-2026 长史 IC 要求。
- 新增 diagnostics 专用 target resolver：
  - `src/diagnostics/target_loader.py`
  - `data/local_targets/.gitkeep`
  - `tests/test_diagnostics.py::test_target_loader_prefers_local_csv_over_fred_cache`
- `src/diagnostics/run_diagnostics.py` 的 target 加载改为优先读取 `data/local_targets/GSPC.csv`，没有本地 CSV 时再回退 FRED `SP500` 缓存。
- 本地 CSV 支持列名：
  - `date,close`
  - `Date,Close`
  - `date,adj close`
  - `date,value`
- `data/local_targets/*` 已加入 `.gitignore`，不会把手工数据源提交到仓库。
- 下一步若要真正跑 1990-2026：放入 `data/local_targets/GSPC.csv` 后运行 `.venv/bin/python -m src.diagnostics.run_diagnostics`。

## 最近更新记录

- 2026-05-13: 新增 GitHub Actions 每日定时任务，自动生成 PDF 并上传 artifact。
- 2026-05-14: 新增 Gmail SMTP 自动发送 PDF 报告，需要配置 `GMAIL_USERNAME`、`GMAIL_APP_PASSWORD`、可选 `REPORT_EMAIL_TO`。
- 2026-05-14: GitHub Actions workflow 升级到 `checkout@v5`、`setup-python@v6`，开始移除 Node.js 20 action target。
- 2026-05-14: Credit Long-History Step 1 完成配置和代码接入，新增 Moody's `BAA10Y/AAA10Y/BAA10Y-AAA10Y` 因子。
- 2026-05-14: Credit Long-History Step 2 完成验证脚本，BAA10Y vs BAMLC0A0CM 5D-change 替代验证未通过，停止进入 Step 3。
- 2026-05-14: Diagnostics Step 3 完成 horizon scan 与 regime split 基础模块，生成 IC 矩阵和分类表。
- 2026-05-14: Diagnostics Step 4 完成 `credit_baa_10y x ^GSPC x +10D` rolling IC 最小闭环；当前本进程缺少 `FRED_API_KEY`，需用户 shell 复跑以扩展 SP500 到 1990。
- 2026-05-14: Diagnostics Step 5 完成全因子 rolling IC summary 和诊断 PDF；优化 rolling 索引为有效交集以避免无效长史窗口拖慢。
- 2026-05-14: Diagnostics Step 6 完成 README 更新和 `tests/test_config.py`，锁定新权重与 diagnostics expected signs 覆盖。
- 2026-05-15: Diagnostics Step 7 新增本地目标 CSV 优先加载，解决 FRED `SP500` 历史不足导致 rolling IC 不能回到 1990 的问题。
- 2026-05-18: GitHub Actions 每日邮件改为同时发送 `esi_daily_report_*.pdf` 和 `esi_diagnostics_*.pdf`；workflow 先运行 `scripts/update_local_gspc.py` 生成 1990 至今 SPX 长史，再跑 diagnostics；`actions/upload-artifact` 升级到 `v7` 并设置 `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24=true`。
- 2026-05-13: 报告层新增 ESI composition 独立页。
- 2026-05-13: 报告层新增 component detail 小图页，拆开显示每个 ESI 组成项。
- 2026-05-13: 修复报告数值显示，避免 `dxy`、`vix_term_structure`、`credit_ig` 的 0 nonlinear/contribution 被误读为缺失。
- 2026-05-13: 报告层所有图页新增 Interpretation 文本。
- 2026-05-13: 继续确认信用历史 blocker，FRED/ALFRED 无法直接回填 2020 历史。
