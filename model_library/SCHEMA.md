# Crypto-G 量化模型分析库

永久数据在东京服务器，不在手机里，也不会因为清空 App 流水而被删掉。

| 文件 | 内容 |
| --- | --- |
| `/opt/shotcrypto/model_library/alerts.jsonl` | 每一条买入预警，触发时追加一行 |
| `/opt/shotcrypto/model_library/user_actions.jsonl` | 模拟买入、App 平仓、币安补记、仍在持有 |
| `/opt/shotcrypto/model_library/outcomes.jsonl` | 按预警绑定版本的退出规则结算的参考行情路径 |
| `/opt/shotcrypto/model_library/open_tracks.json` | 尚未结束的跟踪状态，可重写；不是档案 |

三个 `.jsonl` 只追加，不覆盖、不截断。用 `alertId` 把同一条预警的三份记录对在一起。

手机打不开这些文件。手机只负责把「记入自选持仓」和「补记卖出」送到 `http://43.163.203.127:8788/model-library/action`。请求头 `X-Library-Token` 只允许追加日记，不能下单。

## 没在 App 点平仓时怎么记

V1.11 新预警保存 `tradeRules` 快照及 `ruleVersion=three-models-v1`。突破、反弹、震荡分别最多观察 240、90、240 分钟，从预警生成时计时；触及止损、失效位、全部止盈或时间上限即结束。手机模拟持仓则从用户记录入场时开始独立计时，两者不是同一笔成交。

跟踪状态包含 `deadlineMs`、`maxHoldMinutes`、`tp1Fraction`、`remainingFraction`、`exitLegs`。突破 TP1 退出 50%，反弹退出 70%，震荡退出 100%；若两个目标重合则 TP1 全部退出。止损不自动抬高。模型库不代替用户下单或自动修改手机持仓。

退出腿保存参考价格、比例和原因。目标触达用目标价作参考，失效/止损用观测价；它们都不是交易所成交。超过 10 秒没有连续报价标记 `observationGap`。超过截止时刻才恢复报价，不能用之后的涨幅补算盈利：退出价未知，状态为 `TIME_EXIT_PRICE_UNAVAILABLE`，`referenceNetPct=null`。恰好截止时刻收到报价可以记录时间退出参考价。`settledAtMs` 是实际处理时刻，观察分钟数不超过截止时间。

`referenceOnly=true`、`performanceEligible=false` 明确禁止把这种采样路径直接纳入实盘胜率。参考净收益按各退出比例加权并扣除总计 0.11% 假设摩擦；不含真实撮合、滑点和资金成本验证。

没有新规则快照的旧预警继续原 12 小时观察窗口，不能混入新版本统计。到期判断先于报价更新，窗口之外的触达不算入旧路径。

`userExitStatus` 有三种：

- `ALERT_ONLY`：只有预警，没有记入持仓
- `SIM_OPEN_UNREPORTED`：记了模拟买入，结算时还没有平仓或补记。这是行情路径，不是你的币安成交价
- `REPORTED`：结算前，App 已经收到平仓或补记

之后补记的卖出价写在 `user_actions.jsonl`，类型是 `BACKFILL_CLOSE`。已经写好的 outcome 行不再改。分析时以最后一条 `USER_CLOSE` 或 `BACKFILL_CLOSE` 作为你的卖出；没有这两条，就不要把行情触达价当成你的成交价。

`ruleScore` 是规则匹配分，不是上涨概率，也不是胜率。

## V1.12 事件、成交和当前报告

新增 `delivery_events.jsonl` 记录冷却抑制、发送前拒绝、尝试、FCM 接收和失败。`alerts.jsonl` 的新行含可恢复 `initialTrack`（包括首次信号快照）；这是通过模型准入的机会，不保证已推送。`outcomes.jsonl` 仍是参考路径，`userExitStatusScope=LEGACY_SIMULATION_EVENTS_ONLY`，不代表实际账户持仓。

`user_actions.jsonl` 新行含 `eventId`、`payloadHash`、客户端 `actedAtMs`、服务端 `receivedAtMs` 和来源。新的 `PHONE_OPENED` 与前台 `PHONE_RECEIVED` 区分；`ENTRY_REJECTED` 保存入场复核原因。事件幂等写入后才确认；旧无事件号请求生成内容摘要编号以兼容旧客户端。

`MANUAL_FILL.fill`：`fillId`、`positionId`、`side`、`price`、扣费前 `quantity`、`executedAtMs`、`timeApproximate`、`commission`、`commissionAsset`、`commissionAssetUsdtRate`、`referencePrice`、`referenceAtMs`、`source=MANUAL`、可选 `exchangeTradeId`。未知数值使用 JSON null，不以 0 替代。`replacesEventId` 指向要更正的事件，保留所有版本但有效成交只计一次。

`executionSummary` 是收到该事件时的快照，不可将不同事件快照相加。使用受保护的 `GET /model-library/records?alertId=...` 获取原始档案及按当前有效成交重算的 `executionReports`，包含净收益、剩余库存、费用、执行价差、延迟、入场是否符合原时价区间。`GET /model-library/opportunities` 返回最近 100 次机会索引。手机 POST 前检查 `/model-library/capabilities` 的 `userActionProtocol=2`，不向旧接口盲目重试。

成交成本采用移动加权成本；BTC 手续费通过库存数量变化体现，不能再次从收益扣其折算值。其他币种费用按当时汇率计入；缺少费用或汇率时净收益为 null。模拟退出另外保存 `simulatedAccounting` 并明确成本假设；手工成交、模拟和行情参考路径不能混合成胜率。
