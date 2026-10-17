# Crypto-G 最终进度交接 Prompt（2026-10-17）

你正在接手 `D:\Crypto-Google`。本文件是现行交接。先读本文件、`AGENTS.md`，以及 `开发方案资料 Opus5.5/CryptoGoogle-BTC短线交易监控预警系统-开发方案.md` 的第九节和第十一节，再对照代码。数字以代码、测试和基线报告为准，不要靠记忆补。

不要把下面这些当现行规则：`项目交接总prompt.md`、`项目进度总结prompt.md`、`P0-P4项目进度总结prompt.md`。前两份还留着 0.11% 摩擦、`RANGE_MICRO` 五道门禁，或「先不要写 promotions」「等用户确认再做 P4」。第三份是同一天的长交接，事实已并进本文件；两份冲突时以本文件和代码为准。

本文件不替代用户的新指令。用户用中文沟通。Windows PowerShell 里逗号会拆参数，周期列表必须加引号，例如 `--intervals "1m"`。不要在仓库根目录留下 `_tmp_*.py`。不要用 `TODO` 占位。不要为了让基线变好看而改 S1–S5 或方案第四节至第十节的参数。不要主动 commit、push、部署或再出 APK。不要把服务器密码、设备令牌或密钥写进文件或回复。

## 现在停在哪里

规则版本 `short-horizon-v2`，只做 BTCUSDT 现货多单，持有 5 分钟–6 小时。方案已批准，第十一节的 P0–P5 都已完成。

- 离线套件在 P5 之后通过：`python tests/run_python_offline.py`。前端测试是 `npm test`。
- 2026-10-17 后端已部署到 `43.163.203.127`。守护进程 `/opt/shotcrypto/scanner_daemon.py`，服务 `shotcrypto.service`。P5 备份：`/opt/shotcrypto/backups/pre-p5-20261017-090306`。本次 P1 修复备份：`/opt/shotcrypto/backups/pre-p1fix-20261017-102239`。服务重启后为 active。
- 安装包：`D:\Crypto-Google\release\Crypto-G V1.48.apk`。`android/app/build.gradle` 的 versionName 是 `1.48`，versionCode 是 `148`。`config.py` 没有改，`V2_ENGINE_VERSION` 仍是 `Crypto-G V1.47`。V1.47 已经发过，这次修复按 `AGENTS.md` 进到 1.48。下次发版再把 versionName 加 0.01、versionCode 加 1。
- 五个形态都没过第九节门槛。线上买入推送继续标「观察级·未验证」。某个形态以后进入影子期，手机仍收观察级，文案改成「观察级·影子验证」；交易级才受熔断暂停。
- P4 的影子流程只在 `tests/test_evolution.py` 里用合成样本走完。没有把真实 S1–S4 写进影子，也没有为了演示写 `promotions`。
- 方案到 P5 为止。用户没给出新任务时，先停下来问。不要重做 P0–P5，也不要再发明一个阶段。

2026-10-17 按审计修了这些运行行为，没有改 `config.py`，也没有重跑基线：

- S2 关闭文案分开写「日线已跌破 EMA99」和「4H 收盘跌破日线 EMA99」。S4 挂单下界包含突破价本身，上界仍是上方 0.15%。S1 低点窗口和 S2 日线布林下轨保持原样。
- 1 分钟缓存保留 400 根。主循环把这批 1 分钟 K 线整段交给 `tracker.step`。评估记账先去掉 NaN / Inf，写入失败只记日志。
- `PlanFacts` 在策略中文名缺失时不再调用 `includes`。

部署后当次核验，只说明当时已经算出来，不是要保存的价位：`context.healthy` 为真，规则版本 `short-horizon-v2`。三层状态是 1D 多头回调、4H 空头、1H 空头反弹，评分 −22。日线 EMA99、4H EMA99、4H 中轨、1H EMA25 都有价。日线帧少于 100 根时写不出 EMA99。S1、S2 开着；S3/S4 关闭是因为 4H 收盘未站上 4H EMA99。最近两根 15m 没有 S1/S2 形态。

## 不能改的边界

引擎 A 在 `scratch/cryptog/engine_v2.py`。常量是 `scratch/cryptog/config.py` 里的 `V2_*`。`FRICTION_PCT = 0.11` 只留给旧记录回放。`config.py` 从 `V2_TIER_RESEARCH` 起有一段与前面重复的赋值，数值相同，后一次生效。不要为了去重去改任何 `V2_*`。P4 发布常量和 P5 环境分界常量都只追加在文件末尾那一次，不要再复制一份。

- 来回成本地板 0.24%（BNB 抵扣时 0.19%）。净 TP1 ≥ 0.50%（毛利 ≥ 0.74%）。净 TP1 / (止损距离 + 成本) ≥ 1.0。在进场区间最差价检查。
- 止损 0.35%–1.20%。结构止损只能放宽，不能收紧去过门槛。
- 有效期是触发周期 2 根 K 线。价格高出进场区 0.25% 作废。
- TP1 卖 50%，止损移到保本加成本，余仓跟踪 15m EMA20 或 TP2。90 分钟未到 +0.3R 时间止损，360 分钟硬离场。
- S1 任何环境都可做；4H 空头时 12 小时跌幅从 2.5% 提高到 3.5%。S2 要日线多头且 4H 收盘仍在日线 EMA99 上。S3/S4 在 4H 收盘站上 4H EMA99 之前关闭。S4 还要 4H 不空，且 UTC 13:00–20:00。S5 只研究，`scan` 不得把它变成 BUY。
- 未晋级前每条 BUY 都是 `观察级·未验证`。熔断只暂停交易级，观察级继续。连续 2 笔止损，或一个北京时间日 −2R，暂停交易级 4 小时。
- 5m 急跌监视只报告，不发 BUY。AI 不写价格，也不发起 BUY。`Runtime.ai.originate_buys = False`。
- 不可学习：只做 BTC、只做多、AI 不写价格、成本地板、止损 ≤ 1.2%、持有 ≤ 6 小时、熔断。`V2_PAPER_NOTIONAL_USDT = 500`。

## 基线（不要重跑去改这些数字）

`model_library/baseline/short-horizon-v2.md` 与同目录 `.json`。统计从 2025-01-26 到 2026-10-17。最后 122 天为样本外，切分前 6 小时为禁区。nTrials = 1，没有做 PBO。2026-10-11 至 10-17 回放 8 条观察级，测试门槛 ≥ 6，见 `tests/test_engine_v2.py`。

- ≥1% 且 6 小时内走完的上涨段约 2.61 段/天（1645 段）。
- ≥1.5% 的 896 段里，前 1/3 出现任一候选的比例 29.0%，低于 50% 上线口径。
- S1：候选 1616，成交 4，全在样本内，期望约 −0.54%；样本外 0。
- S2：候选 912，成交 159；样本外 34 笔，胜率 17.6%，期望 −0.306%，盈利因子 0.256。
- S3：候选 293，成交 5，全在样本内；样本外 0。
- S4：候选 151，成交 0。
- S5：49 条研究记录，不推送；之后 360 分钟扣费收益约 −0.069%。

五个形态都未晋级。不要把这份基线喂进 `Pipeline.consider`。

## 代码地图

| 阶段 | 代码 | 测试 | 运行时 |
| --- | --- | --- | --- |
| P0 / P1 引擎 A | `engine_v2.py`、`config.py`、`cost_model.py`、`kline_store.py`、`derivatives.py`、`barriers.py`、`validation.py`、`baseline.py`、`stop_monitor.py`、`context_feed.py`、`evaluation.py`、`v2_tracker.py` | `tests/test_engine_v2.py` 等 | 有 context 时 `evaluation` 只走 v2 `scan` |
| P2 账本 | `scratch/cryptog/ledger.py` | `tests/test_ledger.py` | `runtime._p2`；成交镜像在 `scratch/remote_scanner_daemon.py` 的 `_p2_on_fill` |
| P3 引擎 B | `scratch/cryptog/ai_review.py` | `tests/test_ai_review.py` | `runtime._p3` |
| P4 发布 | `scratch/cryptog/evolution.py` | `tests/test_evolution.py` | 先 `_release`，再记回放，然后 `_p2`、`_p3`、`_p4` |
| P5 持续 | `scratch/cryptog/continuity.py` | `tests/test_continuity.py` | `_p4` 之后 `_p5` |

界面在 `src/components/HorizonPanels.tsx`，接到雷达、预警卡片、预警弹窗、自选持仓、AI 页和系统守护。`parseMarketState` 接受 `short-horizon-v2`。云端没有实验室字段时，四个形态仍显示研究 / 观察级，并写明尚未同步。AI 页标题是「复盘与假设」。持仓页的一键 500 USDT 仍是 `QuickPaperPanel`。

## P2 账本

七张表在研究库 `research.sqlite3`，不在 `EventStore`（`monitor-v1.sqlite3`）。不要把两份库并成一张，也不要拆掉 v1 回放。

表：`candidates`、`features`（版本 `features-v2`）、`shadow_positions`（`SHADOW` / `PAPER` / `SYSTEM`）、`labels`、`real_fills`、`model_registry`、`promotions`、`ai_reviews`。P4 另建 `release_modules`、`l1_reports`。P5 另建 `cost_reports`、`environment_reports`。后四张不替代前面的表。

编号：`paper:{positionId}`、`system:{positionId}`、`shadow:{candidateId}`、`features:paper:{positionId}`、`label:{positionId}`。晋级行编号是 `{module}:{action}:{at_ms}`。

实盘成交源是模型库 `user_actions.jsonl` 的 `MANUAL_FILL`。账本出错只记日志，不能把这笔成交的确认改成失败。买入时开 500 USDT 模拟仓；对得上信号才开系统孪生仓，否则记「主观单」。卖出且整笔关闭时，模拟仓按成交数量加权的买价和卖价计算净收益，名义金额仍是 500 USDT。研究库没有对应 K 线时，系统仓先用进程内缓存 K 线结算，缓存也没有再向币安补该持仓区间。每个 S1–S4 候选都开影子仓，包括观察级和 AI 否决。S5 只进 `candidates`。影子仓按收盘 K 线结算。

离线样本不要改断言：S2，买入 100、卖出 100.4，1 分钟低点 99.4，止损 99.5。模拟仓净 +0.16%。系统仓 `STOP`，标签 −1，净 −0.74%，MFE 0.2%，MAE −0.6%，R = −1。2025-01-26 以来的基线候选没有灌进这七张表。

## P3 引擎 B

不要推倒 `review_signal` 或 `veto_audit`。第二意见只许通过 / 降级为观察 / 否决；标签从固定八个里选；`note` 不超过 40 字且不能有连续三位数字。8 秒超时，超时、缺密钥、坏 JSON 都当 PASS，不取消推送。否决过的信号仍在影子仓结算。研究库 `ai_reviews` 是裁决来源；写入失败会重试，失败后这次推送按 PASS，不把事件库里的另一套裁决当成权威。试运行或交易级收到 `DOWNGRADE` 时，发送前改成「观察级」。

`veto_blocks` 只有 `verdict == VETO` 且 `vetoEnabled` 为真才取消推送。满 100 笔否决后，若否决样本的平均 R 不低于通过样本，就把 `vetoEnabled` 设为假。假设每周最多 3 条，`applied` 永远是假。假设检验仍调用 `promotion_decision`；PBO 缺失时这条门槛不通过，所以结果是 `CHECKED` 而不是 `PENDING_P4`。不写 `promotions`，也不改参数。日复盘、否决开关和周假设在进程启动时从研究库恢复，同一北京时间日、同一周不会因为重启再请求一次 DeepSeek。`Runtime` 没有默认 `review_key`；没配密钥时每周假设不会请求 DeepSeek。

## P4 发布

阶段只针对 S1–S4：`RESEARCH` → `SHADOW` → `TRIAL` → `LIVE`。回滚回到 `RESEARCH`。S5 不进这条流程。

- `RESEARCH`：继续「观察级·未验证」，不写 `promotions`。
- `SHADOW`：继续推送观察级，文案「观察级·影子验证」。只拦交易级。进入影子的那一刻不写 `promotions`。满 14 天且 `records >= 1` 才写 `SHADOW_COMPLETE` 并进入试运行。满 14 天但没有记录就留在影子。
- `TRIAL`：推送，文案「试运行」。满 14 天写 `TRIAL_COMPLETE`，进入 `LIVE`。
- `LIVE`：文案「交易级」。熔断未结束时不推送，原因「交易级暂停，熔断中」。回滚写 `ROLLBACK`。

回滚只在试运行和正式阶段检查，而且先于时间晋级。本阶段已平影子仓的峰值到谷值超过 6R 就回滚。最近 30 笔净收益均值小于 0 也回滚；不足 30 笔不按期望值回滚。影子期即使亏过 6R 也不回滚。

进入影子要过 `validation.promotion_decision` 的样本外摘要。`pbo_value is None` 或 `>= 0.30` 都算缺口，不能因为没做 PBO 就放行。`maintain` 只用研究库里已平的 `SHADOW` / `SYSTEM` 标签。同一 UTC 日的 L1 报告已存在时，重启不再插第二条。基线报告不在这七张表里，所以当前库不会因此把 S1–S4 送进影子。`_p4` 和 `_p5` 每 30 秒跑一次，不再每秒扫全表。

L1 `fit_meta_label` 少于 200 个样本时是 `INSUFFICIENT`。提案的 P 阈值 0.50–0.70，进场偏移 −0.10%–+0.10%，止损缓冲 0–0.20%。`applied` 永远是假，不改 `V2_S*`。

## P5 持续作业

每周假设仍在 P3，`applied` 保持为假。`continuity.py` 只加两件报告：

- 北京时间进入新月份后，用上月实盘成交写成本报告。工作成本取实测和地板的较大值。地板仍是 0.24%。引擎 A 的挂单和结算仍用这个地板，报告不改 `V2_FRICTION_PCT`。
- 上一季度结束后再等满 6 小时，用该季已平样本重估环境分界。搜索范围是先验 0 的左右 20 分，步长 10。样本少于 200，或两侧不足 30 笔，就保持 0。结果是 `HELD`，不改三层环境门禁。
- 这两份报告不写 `promotions`。晋级与回滚仍只由 P4 在影子完成、试运行完成或回滚时写入。

## 数据与服务器

本地研究库：`D:\Crypto-Google\data\research.sqlite3`。服务器研究库：`/opt/shotcrypto/model_library/research.sqlite3`。`*.sqlite3` 被 gitignore，不要提交数据库。

本地已有约 730 天的 1d、4h、1h、15m、5m。1 分钟续传停在 open time 约 `1749426360000`，不是代码异常。基线出场用 5 分钟，不依赖这批 1 分钟。资金费率历史表当时是空的。OI 和主动买卖比从 `DerivativesFeed` 开始累积，没有回填进基线。

服务器研究库是部署启动时建的表，没有上传本地两年 K 线，也没有历史候选。线上三层环境由 `context_feed` 向币安现货接口现拉：1D / 4H / 1H 各 300 根，15m 约 30 天。

登录用本机已固定的主机密钥（`.ssh_known_hosts`），或环境变量 `CRYPTO_G_SSH_PASS`。账户 `ubuntu`。不要把密码写进文件或回复。

## 新对话怎么开工

1. 读本文件、`AGENTS.md`、方案第九节和第十一节。细节以对应的代码和测试为准。
2. 用户没有新任务就停下来问。不要重做 P0–P5，不要改 S1–S5，不要重跑基线去改报告里的数字，不要把假设或 L1 提案写成规则，不要主动部署或再出 APK。
3. 五个形态都未晋级。线上买入推送继续标「观察级·未验证」。
4. 用户明确要求改代码时，改完跑 `python tests/run_python_offline.py`。动到界面时再跑 `npm test`，并核对受影响的页面。
