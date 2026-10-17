# Crypto-G 架构审计与沙盒压测

对照基准：`开发方案资料 Opus5.5/CryptoGoogle-BTC短线交易监控预警系统-开发方案.md` 第四至十一节，以及 `AGENTS.md`。

审计日期：2026-10-17。  
范围：进程启动到信号闭环的真实调用链、方案一致性、五类沙盒极限压测。  
约束：未改开发方案，未改 `scratch/cryptog/`、`src/` 与服务端生产代码，未写入 `data/research.sqlite3`。压测使用临时目录中的 WAL 库，测完已清理。

结论：正常行情下没有会立刻打垮守护进程的致命缺陷。并发写库 0 次锁错误，15 秒的 AI 响应在 8.009 秒被熔断为 PASS。需要处理的是 9 个重要缺口：影子期一旦开始会让该形态的观察级在手机上消失 14 天；进程重启会重跑学习并可能漏掉一段止损。

---

## 第一部分：系统全链路运行机制

`scratch/remote_scanner_daemon.py` 的 `main` 创建 `Runtime`，并拉起常驻线程。主循环在 `scratch/cryptog/runtime.py` 的 `Runtime.run`。

### 1. 数据采集与环境层

| 线程 | 文件 | 节奏 | 作用 |
| --- | --- | --- | --- |
| `BinanceFeed` | `scratch/cryptog/feed.py`、`market.py` | WebSocket 持续，盘口约 100 毫秒 | 现货 `depth`、`ticker`、`aggTrade`，以及 1m / 5m / 15m / 1h / 4h K 线。每种周期缓存最多 256 根 |
| `ContextFeed` | `scratch/cryptog/context_feed.py` | 启动立刻拉一次；每根 15 分钟收盘后 5 秒再拉；失败则 30 秒重试 | 1D / 4H / 1H 各 300 根，15 分钟大约 30 天。数据源 `https://data-api.binance.vision/api/v3/klines` |
| `DerivativesFeed` | `scratch/cryptog/derivatives.py` | 60 秒 | 资金费率、5 分钟持仓量、主动买卖比，经 `ResearchStore` 写入研究库 |
| `NotificationWorker` | `scratch/cryptog/notifications.py` | 0.5 秒 | 出队、8 秒第二意见、FCM |
| 主循环 | `scratch/cryptog/runtime.py` `Runtime.run` | 约 1 秒一次 | 下面的扫描、账本与学习链 |

日线凑满与降级：

- `scratch/cryptog/indicators.py` 的 `frame` 少于 100 根返回空。
- `context_feed.build_context` 跟着为空。
- `engine_v2.scan` 写「环境数据尚未就绪」，不发买入。300 根日线足够写出 EMA99；不足 100 根时整段环境缺失，扫描跳过。

衍生品降级：

- `score_confirmation` 在快照缺失时给 0 分，状态 `unavailable`，不挡买入。
- 计分项：1 小时持仓量下降至少 3%，资金费率不高于 `-0.0001`，主动卖/买至少 1.5。每项 +8 分，都不作为发信号的必要条件。
- `poll` 遇到 HTTP 500 或超时会抛错。生产线程 `run` 接住异常，快照保留上一次的值。`scan` 使用 `latest()`，不使用 15 分钟新鲜度的 `health()`。

### 2. 引擎 A 扫描与门禁

主循环把 `context_feed.latest()`、`derivatives.latest()`、`tracker.breaker()` 放进快照。行情健康时，`tracker.step` 用最近 1 分钟和 15 分钟 K 线推进虚拟结果，`tracker.watch` 用买一价做秒级分类。

`evaluation.evaluate` 在快照带有 `context` 时只走 `engine_v2.scan`。报价、盘口或 K 线不合法时捕获为 `BLOCK_ENTRY` / `INVALID_INPUT`。

`scan` 的顺序：

1. 三层环境分。权重日线 0.45、4H 0.35、1H 0.20。状态 UP = 1，ABOVE_99 = 0.5，BELOW_99 = −0.5，DOWN = −1。
2. 扫描 S1–S5，回看最近 1–2 根已收盘 K 线。
3. `plan_issue` 与 `widen_stop` 校验成本、目标和止损。
4. 仓位：单笔风险 0.5% 权益，名义比例 = 风险 /（止损距离 + 摩擦）。孪生账本名义金额 `V2_PAPER_NOTIONAL_USDT = 500`。

硬门槛：

- 摩擦地板 0.24%（单边约 0.10% taker + 0.02% 滑点）。BNB 折扣地板 0.19%，不得把工作成本降到 0.24% 以下。
- 净 TP1 至少 0.50%（毛利至少 0.74%），在挂单区间最差价上检查。
- 净盈亏比 = 净 TP1 /（止损距离 + 摩擦），至少 1.0。
- 止损距离 0.35%–1.20%。结构止损过近时只放宽，不收紧。
- 有效期两根触发周期（15 分钟信号 30 分钟，5 分钟信号 10 分钟）。价格冲出挂单区间上方 0.25% 作废。

出场：

- TP1 卖 50%，止损移到保本加摩擦。剩余跟随 15 分钟 EMA20，或在 TP2 离场。
- 90 分钟进度不足 +0.3R 离场。硬退出 360 分钟。
- 同一根 K 线先看止损，再看目标。`v2_tracker.advance` 与 `barriers.label_v2` 都按这个顺序。

形态开关：

- S1 急跌收回：任何环境都可扫描。4H 空头时，12 小时跌幅门槛从 2.5% 提到 3.5%。
- S2 支撑回踩：日线收盘高于日线 EMA99，且 4H 收盘仍高于日线 EMA99。
- S3 趋势回踩：4H 收盘高于 4H EMA99，且 4H 与 1H 都为多头。
- S4 挤压突破：4H 收盘高于 4H EMA99，4H 非空头，UTC 13:00 至 20:00（20 点整关闭）。
- S5 时段动量：只进研究记录，`scan` 不发买入。
- 5 分钟急跌监视：只报告进行中的急跌，不发买入。

### 3. 状态流转与引擎 B

`_release`（`runtime.py`）调用 `evolution.apply_release`：

- `RESEARCH`：可以推送，文案「观察级·未验证」，不写 `promotions`。
- `SHADOW`：`push_policy` 置 `push=False`，原因「影子记录，不推送」。候选仍返回给账本。
- `TRIAL`：文案「试运行」。满 14 天且有记录后写 `TRIAL_COMPLETE`，进入 `LIVE`（交易级）。
- 回滚只发生在试运行和正式阶段：从峰值回撤超过 6R，或最近 30 笔净收益均值为负。影子期亏损不触发回滚。样本不足 30 笔时，不因期望值为负而回滚。

买入入队条件：`CRYPTOG_ENABLE_BASELINE_ALERTS=1`，机会状态为 `BUY_CANDIDATE`，且该 setup 不在 `ALERTED_SETUPS`。

`NotificationWorker.step` 出队后调用 `ai_review.review_signal`：

- 超时 8 秒。超时、缺密钥、非 JSON、note 含连续 3 位及以上数字、note 长于 40 字，一律记 PASS。
- 合法裁决只有 PASS / DOWNGRADE / VETO，外加固定标签和一句中文，不写价格。
- `veto_blocks` 仅在裁决为 VETO 且 `vetoEnabled` 时取消推送。
- 否决样本满 100 笔后，只有被否决样本的平均 R 差于通过样本时，否决权才保持开启。
- 被否决的信号仍在影子账本结算。
- DOWNGRADE 会写入裁决，当前实现不把推送级别改回观察级。

熔断在 `v2_tracker.breaker_state`：连续 2 笔止损，或北京时间当日 −2R，暂停交易级买入 4 小时。观察级继续。`apply_release` 只在级别为交易级且 `pausedUntil` 仍在未来时拦截。

### 4. 双账本与秒级盯盘

推送与被拦截候选分两条库：

事件库 `monitor-v1.sqlite3`（WAL，超时 10 秒，synchronous FULL）：

- `events`、`outbox`、`opportunities`、`position_notices`
- `v2_outcomes`（`V2Tracker`）
- `ai_reviews`：`id, at_ms, verdict, fallback, payload`
- `ai_evaluations`（`ReviewLog`）

研究库 `research.sqlite3`（WAL，超时 30 秒）16 张表：

- K 线与衍生品：`klines`、`funding_rates`、`open_interest`、`taker_ratio`
- 账本八表：`candidates`、`features`、`shadow_positions`、`labels`、`real_fills`、`model_registry`、`promotions`、`ai_reviews`
- P4：`release_modules`、`l1_reports`
- P5：`cost_reports`、`environment_reports`

研究库 `ai_reviews` 的列是 `id, candidate_id, at_ms, verdict, payload`，与事件库同名表结构不同。

用户成交：

1. `apply_user_action` 先追加 `user_actions.jsonl`。
2. `_p2_on_fill` 另开一个 `Ledger` 调用 `on_fill`。账本异常只记日志，不把成交回执改成失败。
3. 买入开 500 USDT 的 `PAPER`。对得上非 S5 候选时再开 `SYSTEM`，否则关联文案为「主观单」。
4. 卖出且库存归零时，模拟仓按用户价关闭。部分卖出（`inventory_closed=False`）不关闭模拟仓。
5. 模拟仓记账使用第一笔买价和最后一笔卖价，名义金额保持 500。
6. 系统仓平仓调用 `label_v2`，K 线来自 `_bars_between`。路径为空时结果为 None；结果属于 `(None, "SAMPLE_END")` 时不关闭系统仓。

秒级提醒 `stop_monitor.classify_exit` 的类别：计划、距止损 0.15% 以内、15 分钟收盘跌回收回价、止损、90 分钟 / 6 小时、TP1、5 分钟内下跌 1%、1 小时收盘跌破环境支撑。实盘与影子仓使用同一套分类。出场推送还要 `CRYPTOG_ENABLE_EXIT_ALERTS=1`。

标识：`paper:{positionId}`、`system:{positionId}`、`shadow:{candidateId}`、`features:paper:{positionId}`、`label:{positionId}`。晋级行 `{module}:{action}:{at_ms}`。

线上上下文是现拉的。除衍生品外，上下文 K 线不回写 `kline_store`。服务器研究库在部署时新建，不含本地两年 K 线和历史候选。

### 5. 定时自学习与守护

这些任务挂在约 1 秒一次的主循环上，不是独立 cron。

| 任务 | 触发 | 写入 | 不改变 |
| --- | --- | --- | --- |
| 每日复盘 | 北京时间换日，或距上次超过 60 秒且当日平仓集合变了 | `daily:{日期}`，`INSERT OR REPLACE` | 形态参数 |
| 每周假设 | 内存周键为空且配置了复盘密钥 | 每周最多 3 条，`applied` 保持假。样本够则标 `PENDING_P4` | `V2_S*` 与 `promotions` |
| L1 元标签 | 每个 UTC 日第一次 `Pipeline.maintain` | `l1:{now_ms}`。样本少于 200 为 `INSUFFICIENT`。提案范围：P 0.50–0.70，入场偏移 −0.10%–+0.10%，止损缓冲 0–0.20% | `applied` 保持假 |
| P4 晋级 / 回滚 | 每圈 `tick_all`；`maintain` 按内存中的 UTC 日 | `release_modules`、`promotions` | 影子期亏损不回滚 |
| P5 月度成本 | 北京时间跨月后 | 上月真实成交的成本报告。工作成本 = max(实测, 0.24% 地板) | `V2_FRICTION_PCT` |
| P5 季度环境分界 | 上季结束后再加 6 小时 | 在原分界 ±20 分、步长 10 的网格上重估。样本少于 200 或任一侧少于 30 则保持 0，状态 HELD | 三层门禁 |

L2 / L3（梯度提升、CPCV、新形态）尚未实现。P5 里程碑不要求它们。`Runtime.ai.originate_buys = False`，AI 不能发起买入。

晋级门槛在 `validation.promotion_decision`：样本外至少 60 笔；每笔净期望至少 +0.10%，bootstrap 95% 下界大于 0；胜率至少 52%；盈亏比至少 1.30；尝试超过 20 组参数时 DSR 高于 0.95；交易级频率每天 0.5–6 笔。`pbo_value is None` 时当前代码跳过 PBO 门槛。上线另有 `launch_decision`：胜率至少 55%，且至少一半的 ≥1.5% 波段在前三分之一出现候选。基线未达上线线，四个形态都未晋级。不得把基线结果喂进 `Pipeline.consider`。

---

## 第二部分：对照原方案的一致性与偏差

### 完全一致

- 成本地板 0.24%，净 TP1 下限 0.50%，净盈亏比 1.0，且在挂单区间最差价上检查。
- 止损 0.35%–1.20%，过近只放宽。
- TP1 卖 50%，90 分钟未到 +0.3R，最长 360 分钟。同根 K 线止损优先。
- S5 永不买入。5 分钟急跌监视永不买入。
- 熔断只暂停交易级。观察级在研究阶段继续。
- AI 超时、乱码、夹带价格、超长 note 都变成 PASS，不拦截买入或止损推送。被否决信号仍进影子账本。
- 硬约束在 `unlearnable_gaps`：只做 BTC、只做多、AI 不写价格、成本地板、止损最远 1.20%、持仓最长 6 小时、熔断。
- 晋级数字 60 笔、+0.10%、52%、盈亏比 1.30；超过 20 次试验才要求 DSR。上线 55% 与 50% 召回是另一个函数。
- 孪生名义 500 USDT。研究库 16 张表存在。P0–P5 模块都在。
- S1–S5 的跌幅、放量、RSI、带宽、美盘窗口和衍生品加分，与表五及 `config.py` 的 `V2_*` 数值一致。

### 偏差与隐患

**1. 影子期停推，今天尚未发生。**

四个形态目前都在 `RESEARCH`。`push_policy` 对研究阶段返回可以推送，文案仍是「观察级·未验证」。压测中熔断开启时观察级仍然放行。

某个形态通过第九节门槛进入 `SHADOW` 之后，`evolution.py` 第 82–100 行会把推设置为「影子记录，不推送」，该形态的买入会在手机上消失 14 天。这与第九节「影子 14 天：只记录、不推送」一致，与第五节、第六节「观察级要推送」以及熔断文案「观察级继续」冲突。

第八节的影子仓是账本概念：每个 S1–S4 候选，包括观察级和被 AI 否决的，都会开影子仓。发布阶段改成 SHADOW 不会关掉这笔影子记录，关掉的是手机推送。

**2. 重启丢失的内存状态。**

只在内存中、重启即失：

- `Pipeline._day`（`now_ms // 86_400_000`，UTC 日）
- `Runtime.engine_b` 的复盘日、复盘时间、复盘签名、否决开关、否决审计日、假设周
- 环境线程与衍生品线程的内存快照和上次尝试时间。进程起来后会重拉。

持久化、重启仍在：`ALERTED_SETUPS`、`OPEN_TRACKS`、出队冷却（`COOLDOWN_SECONDS = 90`）、`v2_outcomes`、`release_modules`、假设行、`daily:{日期}`。挂单到期写在信号的 `expires_at` 上，不是内存计时器。

实测：同一 UTC 日新建 `Pipeline` 再跑 `maintain`，`l1:{now_ms}` 因为时间戳不同再插一行，1 条变成 2 条。假设周键丢失后，空状态再请求一次，DeepSeek 被调用 2 次，表里 6 行，后 3 行是周上限。没有密钥时不会发出第二次请求。每日复盘主键固定，重写是幂等的。审查线程是守护线程，审查完成到出队完成之间若进程退出，会至少再审一次。

1 分钟缓存只有 256 根，约 4.3 小时，短于最长 6 小时持仓。`advance` 只跳过 `t <= lastBar` 的 K 线，不补空洞。停机超过这段窗口后，中间的止损分钟不会回放。

**3. 配置重复赋值与两张 `ai_reviews`。**

`config.py` 第 104–150 行把 `V2_BNB_FRICTION_PCT` 到 `V2_PAPER_NOTIONAL_USDT` 又赋了一遍。数值与前面相同，后一次生效。`V2_FRICTION_PCT`、`V2_TIER_RESEARCH` 以及文件末尾的 L1 / P4 / P5 常量没有重复。实测赋值次数：`V2_S1_MIN_DROP_PCT` 2、`V2_PAPER_NOTIONAL_USDT` 2、`V2_FRICTION_PCT` 1、`V2_TIER_RESEARCH` 1、`V2_L1_MIN_SAMPLES` 1。当前没有数值错位。只改前面那一份会被后面盖掉。

`notifications.py` 第 61–81 行先写事件库并调用 `set_verdict`，再写研究库。研究库失败被吞掉。镜像失败时，两张同名表的裁决可以不一致，虚拟结果上仍可能是 PASS。

**4. S1–S5 与表五的三处形态差异。**

- S4 挂单区间是突破位上方 0.02%–0.15%（`engine_v2.py` 约第 280 行）。正好踩在突破价上进不了区间。方案要求回踩突破位、不追价。代码拒绝了追收盘价。
- S2 支撑除 4H 下轨、前低和日线 EMA 簇外，还包含日线布林下轨（约第 210–211 行）。
- S1 低点只在最近 4 根 15 分钟里找（约第 159 行）。方案没有把低点限制在一小时内。
- S3 / S4 止损额外减去 `0.15 × ATR15`。表五没写这截缓冲；第六节与 `AGENTS.md` 要求有。代码跟随第六节。
- S4 时段判断是小时小于 20，所以 20:00 UTC 关闭。方案写法是 13:00–20:00。
- S2 关闭文案（约第 125–126 行）在门未开时一律写「日线已跌破 EMA99」。实测日线收盘 100、日线 EMA99 为 90、4H 收盘 88 时，门是关的，文案仍说日线已跌破。

**5. 方案有、活路径没有接上的部分。**

- 第四节流水线第 3 步的元标签没有进入 `scan`。级别来自发布阶段。
- L1 的 `applied` 保持假。这与交接约定一致，与第九节「能改什么」里有界的 P、入场偏移和止损缓冲不一致。
- 第九节「上线第一天用两年历史 K 线回填候选和标签」没有接到七张账本表。`kline_store.backfill` 只回填 K 线。`record_candidate` 只在线上 `_p2` 调用。
- L2 / L3 未实现。P5 里程碑尚未要求。

---

## 第三部分：五组沙盒压测

全部在临时目录的 WAL 库中运行。`data/research.sqlite3` 的修改时间未变（`dbUntouched: true`）。临时脚本已删除，仓库根目录没有留下 `_tmp_*.py`。

### 场景 1：高频并发与 SQLite 锁

四路同时写 25.8 秒：扫描线程写候选与结算、20 笔各自独立连接的 `MANUAL_FILL`、晋级与成本维护、衍生品 upsert。

| 项目 | 次数 |
| --- | ---: |
| 扫描写候选 | 1087 |
| 成交镜像 | 20 |
| 晋级与成本维护 | 325 |
| 衍生品 upsert | 9 |
| `database is locked` | 0 |
| 结束后仍存活的线程 | 0 |

没有死锁。另用独占事务把对方超时压到 50 毫秒，得到 `OperationalError: database is locked`。生产 `busy_timeout` 为 30 秒，所以卡住的写会阻塞而不是立刻失败。`_p2_on_fill` 在 JSONL 追加之后吞掉账本异常，极端锁等待会留下「日志有成交、孪生仓没有」。

`Ledger.lock` 是可重入锁。通知线程与运行时共用同一 `Ledger`。成交镜像和衍生品写入使用各自的连接。

### 场景 2：极端闪崩与脏数据

用真实的 120 根上下文重跑：

| 输入 | 结果 |
| --- | --- |
| 1 分钟下跌 8% | `evaluate` 返回 `WAIT_CONFIRMATION`，无异常 |
| 零成交量、高低价相等、K 线乱序或缺失、卖一价 NaN | `scan` 不抛异常，坏行情的信号为 None |
| 日线 80 根 | `build_context` / `frame` 返回 None |
| 30 根零成交量的急跌监视 | `active` 为假，跌幅 0 |
| `score_confirmation(None)` | 不可用，0 分 |
| 合约 HTTP 500 | `poll` 抛 `HTTPError`。生产 `run` 接住，首次失败后快照为不可用 |
| 合约超时 | `poll` 抛 `TimeoutError`。生产 `run` 同样接住 |

`engine_v2.py` 与 `derivatives.py` 在这些输入下没有未捕获异常逃出生产捕获路径。

潜在崩溃点不在这组行情，而在主循环记账：`storage.canonical` 使用 `allow_nan=False`。决策里若带上 NaN，`EventStore.record_evaluation` 抛出 `ValueError: Out of range float values are not JSON compliant`。`runtime.py` 约第 164 行的这次写入在各阶段 try/except 之外。`score_confirmation` 遇到 NaN 字段时状态仍是 `ok`、分数 0，并把 NaN 放进结果。线上报价里的 NaN 会更早被记成 `QUOTE_INVALID`。正常币安 JSON 不含 NaN。这是潜伏路径。

### 场景 3：DeepSeek 恶意与超时响应

| 输入 | 耗时 | 裁决 | 是否拦截推送 |
| --- | --- | --- | --- |
| 休眠 15 秒，超时设为 8 秒 | 8.009 秒 | PASS / TIMEOUT | 否 |
| 非 JSON 字符串 | 立即 | PASS / FORMAT | 否 |
| note 为「止损改到65432」 | 立即 | PASS / FORMAT | 否，价格不会被采纳 |
| 5000 字 note | 立即 | PASS / FORMAT，note 长度 0 | 否 |
| 合法 DOWNGRADE | 立即 | DOWNGRADE | 否，信号级别仍是观察级 |
| JSON 解析失败 | 立即 | PASS / JSONDecodeError | 否 |

8 秒熔断和「连续三位数字 / 超过 40 字」规则拦住了改价和超长文本。慢调用返回后，休眠中的守护线程仍会继续跑完，大量慢请求会积累线程，但不会堵住买入或止损推送。

### 场景 4：持仓与孪生仓边界

| 情形 | 结果 |
| --- | --- |
| 同一根 K 线低点触及止损且高点触及 TP1 | 结果 STOP，只有一条 STOP 腿。`label_v2` 同样是 STOP |
| 五次买入、四次部分卖出、一次卖光 | 模拟仓名义 500，按 100 进、100.5 出，净 +0.26%。四次部分卖出的 `closed` 为假，最后一次为真。临时库没有 K 线，系统仓保持 OPEN，`labelId` 为空 |
| 无关联信号的主观单 | `subjective` 为真，没有系统孪生。平仓关联「主观单」，标签 `label:paper:pos-sub` |
| 连续两笔止损 | `consecutiveStops` 为 2，当日 R 为 −2.0，暂停原因「连续 2 笔止损」。观察级仍放行。影子阶段返回「影子记录，不推送」 |

### 场景 5：前端缺省与异常字段

用 `react-dom/server` 渲染 `HorizonPanels` 及相关解析。

| 输入 | 结果 |
| --- | --- |
| 空对象 | `parseMarketState` 得到 `UNAVAILABLE`，`dataReady` 为假。环境、实验室、守护、复盘、孪生、计划卡不抛异常 |
| NaN 评分与 NaN 价位 | 来源仍可为服务端，层和价位被丢掉。熔断落成「未熔断」 |
| 缺少 `evolution` / `breaker` | 实验室为空时改用本地「云端尚未返回晋级进度」。熔断为空 |
| `parseCloudSignal({})` 与 NaN 入场价 | 返回 null，到不了会崩的计划卡 |
| `PlanFacts` 缺少 `strategyNameZh`，级别为「观察级·未验证」 | 抛出 `Cannot read properties of undefined (reading 'includes')` |
| 同上但级别正好是「试运行」 | 短路判断在 `.includes` 之前，不抛 |

市场卡片在空对象和 NaN 下不白屏。白屏只出现在绕过 `parseCloudSignal`、把缺中文名的信号直接交给 `PlanFacts` 时。正常云端解析会补上「云端候选」。

---

## 第四部分：问题汇总与修复建议

本次只列方案，不改代码。

### 致命 P0

无。正常行情、20 笔连续成交、脏 K 线和 AI 恶意响应都没有打垮进程。

### 重要 P1

1. 影子期 14 天停推。位置：`scratch/cryptog/evolution.py` `push_policy` 约第 82–84 行，`apply_release` 约第 99–100 行；`scratch/cryptog/runtime.py` `_release` 约第 240–252 行。现状：今天四个形态都在研究阶段，观察级仍推送。晋级进入 SHADOW 后，该形态买入在手机上消失 14 天。若遵守第九节，保持不推交易级，并在实验室卡片上写明「进入影子后 14 天收不到这个形态」。若遵守第五节，影子期继续发观察级，交易级推迟到试运行。二选一之前不要改。

2. 重启丢掉日闸和周闸。位置：`scratch/cryptog/evolution.py` `maintain` 约第 405–408 行；`scratch/cryptog/ai_review.py` `maintain` 约第 572 行。实测同日 L1 从 1 条变成 2 条，空状态下第二次假设请求再写出周上限行。修复：调用前读取已有 `l1_reports` 与 `hypothesis:{week}`，把日和周持久化。没有新日、新周时不要再请求。

3. 两张 `ai_reviews` 会分叉。位置：`scratch/cryptog/notifications.py` 约第 61–81 行。事件库先写入，研究库失败被吞掉，候选裁决可以仍是 PASS。修复：研究库写入失败要暴露出来，并指定研究库为裁决来源。

4. DOWNGRADE 不改推送级别。位置：`scratch/cryptog/notifications.py` 约第 65–71 行。试运行或交易级卡片不会改回观察级。修复：发送前把级别改成观察级。

5. 缺少 PBO 仍算通过。位置：`scratch/cryptog/validation.py` 约第 221 行，`if pbo_value is not None`。第九节要求 PBO 低于 0.30。修复：PBO 缺失记入缺口，不得当成通过。

6. 卖出时系统仓对不上 K 线。位置：`scratch/cryptog/ledger.py` `record_sell` 约第 555–559 行，`_bars_between` 约第 470 行。实测全平后 PAPER 关闭，研究库没有 1 分钟线时 SYSTEM 仍为 OPEN，`labelId` 为空。进程一直活着时，`settle` 仍可用 WebSocket 缓存逐段推进。修复：平仓标签不要只依赖空的 `klines` 表，改用进程内已推进的系统仓状态，或按持仓区间补 K 线。第九节的两年候选回填另做，不要把基线灌进 `Pipeline.consider`。

7. 评估写入未捕获 NaN。位置：`scratch/cryptog/runtime.py` 约第 164 行；`scratch/cryptog/storage.py` `canonical` 约第 8 行 `allow_nan=False`；`scratch/cryptog/derivatives.py` `score_confirmation` 约第 21–42 行。实测带 NaN 的 `record_evaluation` 抛 `ValueError`，主循环没有接住，`finally` 会关掉进程。修复：主循环这次记账纳入与 `_p2` 相同的异常捕获；衍生品字段先拒绝非有限数，再放进决策。

8. 1 分钟缓存短于 6 小时持仓。位置：`scratch/cryptog/market.py` 约第 118 行，最多 256 根。`v2_tracker.advance` 约第 68–71 行只跳过已处理时间，不补空洞。修复：至少保留 360 根 1 分钟 K 线，或从 `kline_store` 结算。

9. S2 关闭文案指错原因。位置：`scratch/cryptog/engine_v2.py` 约第 125–126 行。日线仍在 EMA99 上方、只是 4H 收盘跌破该线时，文案仍写「日线已跌破」。修复：`daily_bull` 与 `h4_intact` 分开写原因。

### 优化 P2

- `scratch/cryptog/config.py` 第 104–150 行重复赋值。数值相同，后一次生效。先不要删。只改前面那一份不会生效。
- `scratch/cryptog/engine_v2.py` 约第 280 行。S4 回踩区间应包含突破价本身，而不只是上方 0.02%–0.15%。
- `scratch/cryptog/engine_v2.py` 约第 210–211 行。S2 多触发了日线布林下轨。是否保留，需要确认是否允许超出表五。
- `scratch/cryptog/engine_v2.py` 约第 159 行。S1 低点只在最近 4 根 15 分钟里找。方案没有这一小时限制。
- `scratch/cryptog/ledger.py` 约第 437–443 行与第 543–551 行。分笔成交的模拟仓净收益只用第一买价和最后卖价。应按数量加权。名义金额保持 500 与固定孪生仓一致。
- `scratch/cryptog/ai_review.py`。慢调用在 8 秒返回后，守护线程仍会跑完。大量超时会积累线程。
- `scratch/cryptog/continuity.py` 与 `Pipeline.tick_all` 每约 1 秒跑一次。空库压测 26 秒内 325 次维护、0 次锁错误。标签变多以后会更重。报告本身是 `INSERT OR IGNORE`，不会改规则。
- `runtime.py` 每秒 `record_evaluation` 写一条 zlib 事件。这是磁盘增长，不是锁失败。
- `HorizonPanels.tsx` `PlanFacts` 约第 107 行。`strategyNameZh` 缺失时 `.includes` 会抛。正常解析会补默认名。修复时改为可选调用。
- 元标签没有进入活路径第 3 步。L1 提案保持不应用。L2 / L3 尚未建设，P5 不要求提前做。
- 盘口来自 depth 流。方案里的名字是 bookTicker。数据在，名字不同。

### 压测中保持正确、不要当成缺陷的行为

成本地板、净 TP1、盈亏比、止损带宽、TP1 半仓、90 分钟与 360 分钟、S5 与急跌监视不发买入、熔断只停交易级、同根止损优先、AI 坏响应不拦截、被否决信号仍结算、硬约束不可学习、晋级数字、500 USDT 孪生仓、WAL 扛住了并发、市场卡片空对象与 NaN 不白屏。

---

## 等待下一步

上面 9 条重要项和优化项都只是修复方案。指定编号后再改对应文件。不要把基线结果灌进晋级，不要为了改善基线去改 S1–S5 或方案第四至第十节的数字。
