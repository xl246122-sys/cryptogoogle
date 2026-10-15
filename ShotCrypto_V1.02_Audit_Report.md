# ShotCrypto V1.02 全系统只读代码与生产环境深度审计报告

> **审计执行原则声明**：本报告基于对本地工作区代码（`D:\Crypto-Google`）与腾讯云东京生产服务器（`43.163.203.127`）现有运行环境的**纯只读（READ-ONLY）**实证排查。无任何代码改动、无文件覆盖、无依赖更新、未重启任何生产进程、未触发任何真实/模拟交易与网络写操作。所有结论均附带真实文件路径、函数名、行号与生产日志证据。

---

## 一、 审计摘要

| 审计维度 | 审计结论 | 核心事实依据 |
|---|---|---|
| **当前真实版本号** | **多处版本割裂 (V1.02 / 1.05 / 0.00)** | `package.json` 为 `0.0.0`；`android/app/build.gradle` 为 `versionName "1.05"` (Code `105`)；服务器进程 User-Agent 为 `CryptoG-QuantEngine/1.03`；用户指令业务标识为 `V1.02` |
| **实际审计范围** | **全链路覆盖** | 前端 React/TS、Android 原生/Capacitor 容器、东京生产节点 Python Daemon、Systemd 服务、Firebase FCM 推送链路、历史运行日志 |
| **生产环境访问状态** | **VERIFIED (已只读连通核验)** | 成功通过 SSH 授权读取 `43.163.203.127`，获取 `shotcrypto.service` (PID `183990`) 实时运行状态与 `/opt/shotcrypto/logs/scanner.log` 完整日志 |
| **已确认模块** | **VERIFIED** | 1H 宏观趋势判定、瀑布通道拦截、5 重微波段止跌门禁、动态分位波动率分级、机构摩擦门禁、FCM 广播通道 |
| **未确认/缺陷模块** | **UNVERIFIED / DEFECT** | **历史回测系统 (全项目无任何回测脚本与交易样本，胜率纯硬编码)**、统一入场决策状态机缺失、未收盘 K 线假突破风险 |
| **全系统总体风险评级** | **P1 (高风险)** | 虽核心风控门禁已落地，但存在“未收盘 K 线实时漂移触发”、“回测数据完全失真”、“双端引擎独立决策无全局排他锁”三大高危风险 |

---

## 二、 当前系统架构与调用链路

经过对代码与进程的静态推演与日志核对，当前系统**并非传统的 Client-Server REST/FastAPI 架构**，而是**双端独立并行扫描引擎架构**：

```mermaid
flowchart TD
    subgraph Cloud_Server["【云端生产环境】腾讯云东京节点 (43.163.203.127)"]
        A[Binance REST API] -->|GET /ticker /klines /depth 每2秒| B["Python 守护进程 (scanner_daemon.py - PID 183990)"]
        B --> C["diagnose_macro_trend() (1H MA20/50, EMA7/25, RSI)"]
        C --> D{"is_bearish 空头趋势?"}
        D -->|是| E["硬门禁: 累计跌幅 ≥ 5.0%?"]
        E -->|未达到| F[强制静默 / 全面拦截]
        E -->|已达到| G[暴跌极值超卖 / RSI底背离]
        D -->|否 (震荡/多头)| H["5重微波段止跌门禁 + 滚动分位三级波动模型"]
        H --> I["机构交易摩擦门禁 (净TP1≥0.4%, 净RR≥1.1:1)"]
        G --> I
        I -->|通过| J["Firebase Admin SDK (send_fcm_alert)"]
        J -->|Topic: shot_crypto_signals| K[(Firebase Cloud Messaging)]
    end

    subgraph Android_Client["【终端运行环境】Android 客户端 (Crypto-G V1.05)"]
        K -.->|推送抵达通知栏| L[Capacitor PushNotifications 插件]
        M[Binance WebSocket / REST] -->|独立轮询 2000ms| N["前端独立量化引擎 (src/services/quantEngine.ts)"]
        N --> O["本地决策: 声音播报 + 弹窗 (SignalAlertModal.tsx)"]
    end
```

### 真实模块清单表

| 模块名称 | 文件路径 | 主要职责 | 当前状态 | 证据支持 |
|---|---|---|---|---|
| **前端主程序** | `src/App.tsx` | UI 状态机、前端定时扫描循环、弹窗与声音调度 | **VERIFIED** | `App.tsx:201-243` `runScanner()` 独立运行 |
| **前端量化引擎** | `src/services/quantEngine.ts` | 浏览器端 7 大策略、宏观趋势、5 重止跌、三级分位波动率 | **VERIFIED** | 1,155 行完整 TypeScript 类，支持 pure BTC 过滤 |
| **行情接入服务** | `src/services/binanceService.ts` | Binance REST/WS 行情直连，多级 Fallback (Finnhub) | **VERIFIED** | `binanceService.ts:42` `INITIAL_WATCHLIST_SYMBOLS=['BTCUSDT']` |
| **Android 宿主工程** | `android/app/` | 基于 Capacitor 8.5 的 Android 原生封装层 | **VERIFIED** | `build.gradle:10` (`versionCode 105`, `versionName "1.05"`) |
| **云端守护脚本** | `/opt/shotcrypto/scanner_daemon.py` | 24/7 Linux 后台无间断高频扫描，直通 FCM 广播 | **VERIFIED** | 服务器 PID `183990` 正在执行该脚本，大小 `34,505 字节` |
| **Systemd 守护** | `/etc/systemd/system/shotcrypto.service` | Linux 服务自启与崩溃拉起 | **VERIFIED** | `systemctl status` 确认 `active (running)`，开机自启 |
| **FastAPI 后端** | *无* | 供客户端请求的 Python Web API | **NOT_FOUND** | 全盘无 FastAPI/Uvicorn 代码，服务器无 8000/8080 监听端口 |
| **回测与测试系统** | *无* | 策略历史验证、样本内外检验、滑点撮合回测脚本 | **NOT_FOUND** | 全项目除模板测试类外无任何量化回测代码 |

---

## 三、 多币种残留检查 (SUI / LINK / 其他币种)

### 3.1 多币种残留分类矩阵

| 文件/模块 | 涉及币种 | 残留分类 | 生产执行状态 | 对 BTC Only 的影响 | 风险等级 | 后续建议 |
|---|---|---|---|---|---|---|
| `src/components/SuiPositionDashboard.tsx` | `SUIUSDT` | **DORMANT** | 代码存在，但未被任何组件 `import` | 增加包体积 (~28KB)，无运行时逻辑影响 | **P3** | 安全移除或归档 |
| `public/manifest.json` | `SUI` | **UI_ONLY** | PWA 描述信息文案残留 | 仅影响安装提示文案，无业务逻辑影响 | **P3** | 修改文案为纯 BTC |
| `scratch/deploy_updated_daemon.py` | `SUIUSDT`, `LINKUSDT` | **HISTORICAL** | 历史部署脚本残留，包含早期多币种扫描数组 | 若被再次执行会覆盖云端生产，将云端退回多币种状态 | **P1** | 标记废弃或更新 |
| `/opt/shotcrypto/logs/scanner.log` | `SUIUSDT`, `LINKUSDT` | **HISTORICAL** | 历史运行日志（08:49 前曾产生预警） | 仅为日志记录，不影响当前运行 | **P3** | 日志滚动归档 |
| `src/services/binanceService.ts` | 无 (仅BTC) | **CLEAN** | 已纯化为 `BTCUSDT` | 100% 聚焦 BTC | **PASS** | 保持 |
| `src/services/quantEngine.ts` | 无 (仅BTC) | **CLEAN** | 行 698 强制拦截非 `BTCUSDT` 标的 | 100% 聚焦 BTC | **PASS** | 保持 |
| `/opt/shotcrypto/scanner_daemon.py` (在线) | 无 (仅BTC) | **ACTIVE** | 行 48 `TARGET_SYMBOLS = ["BTCUSDT"]`，行 563 仅放行 BTC | 生产守护进程当前仅扫描 BTC | **PASS** | 保持 |

### 3.2 核心疑问核实结果

1. **当前系统到底监控几个币种？**
   - **前端**：**1 个**（`BTCUSDT`，见 `App.tsx:42` 与 `binanceService.ts:42`）。
   - **云端生产**：**1 个**（`BTCUSDT`，见生产环境 `scanner_daemon.py:48`）。
2. **哪些币种能够产生买入信号？**
   - 当前代码与运行进程中，**仅 `BTCUSDT`** 能够产生信号。
3. **哪些币种能够发送 FCM？**
   - 当前仅 `BTCUSDT` 会触发 `send_fcm_alert`。
4. **BTC 是否能够独立产生买入预警？**
   - **完全可以**。BTC 自身既作为宏观风向标（1H K线），又作为微观交易标的（1m K线 + 深度盘口），在生产环境已多次独立触发预警（见生产日志实证）。
5. **跨币种联动依赖是否已彻底解耦？**
   - **已完全解耦**。代码中已不存在“BTC 趋势用于过滤 SUI”的跨币混用，所有指标（ATR、VWAP、Bollinger Bands、RSI、OrderBook）计算对象均为 BTC 自身。

---

## 四、 三级波动率自适应引擎审计

### 4.1 真实计算公式与实现核对

在 `src/services/quantEngine.ts:112-250` 与云端 `scanner_daemon.py:266-362` 中均实现了该引擎：

1. **观察窗口基准**：
   - 明确定义为 **15m $\times$ 48 根 K 线**（12小时滚动会话窗口，见 `quantEngine.ts:136`）。
   - 计算 12H 窗口内每根 K 线的局部振幅序列 $R_i = \frac{High_i - Low_i}{Low_i} \times 100\%$。
2. **滚动历史分位数**：
   - 严格采用插值分位公式计算当前 12H 会话的动态分位数：$P_{25}, P_{50}, P_{75}$（`quantEngine.ts:90-99`）。
3. **经验分位排位 ($Q_{vol}$)**：
   - 统计最近 24 根 K 线的活跃振幅 $Swing = \frac{\max(H_{24}) - \min(L_{24})}{\min(L_{24})} \times 100\%$ 在 12H 历史序列中的百分位排位：$Q_{vol} = \frac{\text{count}(R_i \le Swing)}{48} \times 100\%$。
4. **三级划分逻辑**：
   - **LOW (小幅度波动)**：$(Q_{vol} \le 30\% \land Swing < 1.1\%) \lor (Swing < \max(0.70, P_{25}) \land Bandwidth < 1.05\%)$。
   - **HIGH (大幅度波动)**：$(Q_{vol} \ge 75\% \land Swing \ge 1.6\%) \lor Swing \ge \max(1.95, P_{75}) \lor Bandwidth \ge 2.25\%$。
   - **MEDIUM (中度波动)**：介于两者之间。

### 4.2 趋势与波动独立性核验 (Decoupling)

- **是否将单边拉升误判为大幅震荡？**
  - **不会**。在 `quantEngine.ts:602-605` 与 `scanner_daemon.py:492-495` 中，显式设置了趋势解耦过滤器：
    当 4小时价格漂移 $>+0.8\%$ 且站稳 EMA7 时，强制判定为 `TRENDING_BULL`。在多头顺势态下，震荡策略分支直接短路，仅放行 `TREND_PULLBACK_BUY` 与 `BURST_BREAKOUT`，**绝不进入宽幅震荡抄底模式**。
- **是否将持续下跌误判为小幅震荡？**
  - **不会**。单边瀑布下行通道有 `diagnoseCascadeDowntrend` 拦截；大盘空头下行时有“5% 跌幅门槛”拦截。

### 4.3 三级策略门禁与参数审计

| 模式 | 理论参数 | 真实代码实现参数 | 5重止跌门禁依赖 | 缺陷与风险分析 |
|---|---|---|---|---|
| **小幅震荡 (RANGE_MICRO)** | TP1: +0.8%, TP2: +1.6%, SL: 0.55% | 动态 ATR 挂钩：$TP1 = \max(0.65\%, ATR\% \times 1.6)$；$SL = \min(0.65\%, \max(0.38\%, ATR\% \times 1.1))$ | **必须全部通过** | 真实参数针对 BTC 波动自适应，**优于固定百分比**；但门禁计算基于未收盘 K 线，盘中微小跳价可瞬时满足门禁 |
| **中型震荡 (RANGE_MEDIUM)** | TP1: +1.4%, TP2: +3.0%, SL: 0.85% | 动态 ATR 挂钩：$TP1 = \max(1.20\%, ATR\% \times 2.1)$；$SL = \min(0.95\%, \max(0.60\%, ATR\% \times 1.3))$ | **必须全部通过** | 结构止损锚定箱体底部下探 $0.3 \times ATR$，具备物理支撑依据 |
| **大幅震荡 (RANGE_WIDE)** | TP1: +2.2%, TP2: +4.5%, SL: 1.2% | 动态 ATR 挂钩：$TP1 = \max(1.85\%, ATR\% \times 2.6)$；$SL = \min(1.40\%, \max(0.85\%, ATR\% \times 1.6))$ | **必须全部通过** | 要求 RSI $\le 38$ 且击穿布林下轨，具有较强弹性偏离保护 |

---

## 五、 统一风险门禁审计

### 5.1 真实风控决策链与拦截能力评估

完整追踪代码调用流程：

```
K线与行情数据摄取 
  └── [门禁 0] 瀑布通道拦截器 (diagnoseCascadeDowntrend) ──> 发现单边连跌，直接 return null (阻断)
  └── [门禁 1] 宏观趋势诊断 (diagnoseMacroTrend)
        └── 若判定为 BEARISH (空头下行)
              └── [门禁 2] 空头 5% 跌幅硬指标 ──> effectiveDropPct < 5.0% 直接 return null (阻断)
  └── [门禁 3] 5重微波段止跌企稳门禁 (verifyMicroRangeReversal - 仅震荡模式)
        ├── 局部低点不再创新低 (Lt >= Lt-1 * 0.9995) ──> 不满足直接阻断
        ├── 实体微阳突破站稳 EMA7 并收复前K中轴 ──> 不满足直接阻断
        ├── 下杀缩量且盘口买卖比 Imbalance >= +0.02 ──> 不满足直接阻断
        └── 买卖点差 Spread <= 0.02% ──> 不满足直接阻断
  └── [门禁 4] 机构交易摩擦门禁 (Friction Gate)
        ├── 扣除 0.11% 双向手续费与预估滑点
        └── 校验净收益 Net TP1 >= 0.40% 且 Net RR >= 1.10 : 1 ──> 达不到直接 return null (阻断)
```

### 5.2 关键风控项对照核实表

| 风控检查项 | 是否存在 | 真实代码位置 | 是否为硬性阻断 | 是否覆盖所有策略 | 是否存在绕过风险 |
|---|---|---|---|---|---|
| **单边瀑布下杀拦截** | **存在** | `quantEngine.ts:733`, `scanner:582` | **是**（直接返回 null） | **是**（位于策略循环最前置） | 无绕过路径 |
| **空头5%跌幅硬门槛** | **存在** | `quantEngine.ts:762`, `scanner:595` | **是**（未达5%全面静默） | **覆盖空头态所有买入** | 仅多头/震荡态不走此分支 |
| **局部低点不创新低** | **存在** | `quantEngine.ts:364`, `scanner:425` | **是**（不通过直接 return） | **覆盖所有 RANGE 震荡模型** | 多头放量突破模型不走此门禁 |
| **结构位站稳(EMA7/前K中轴)** | **存在** | `quantEngine.ts:382`, `scanner:434` | **是**（不通过直接 return） | **覆盖所有 RANGE 震荡模型** | 多头放量突破模型不走此门禁 |
| **卖压衰减与盘口买量深度** | **存在** | `quantEngine.ts:399`, `scanner:444` | **是**（深度 < +2% 阻断） | **覆盖所有 RANGE 震荡模型** | 无绕过路径 |
| **交易摩擦门禁(0.11%扣费)** | **存在** | `quantEngine.ts:1095`, `scanner:739` | **是**（净盈亏比<1.1直接作废） | **覆盖全部 7 种买入策略** | 无绕过路径 |
| **冷却时间过滤** | **存在** | `App.tsx:153`, `scanner:799` | **是**（45s / 60s 冷却） | **全部策略** | **有风险**（见下文：策略切换会绕过） |
| **K线未收盘假突破保护** | **缺失** | 使用 `candles[-1]` 最新未收盘 K 线 | **否** | **全部策略受影响** | **高危绕过风险 (P1)** |

---

## 六、 FCM 预警系统审计与历史日志追溯

### 6.1 历史预警日志确证事实

审计工程师调取了东京生产服务器 `/opt/shotcrypto/logs/scanner.log` 的历史真实日志，**完整复现并确认了用户指出的关键事件**：

```log
2026-10-14 08:49:01,476 [INFO] >>> DETECTED SIGNAL: SUIUSDT Strategy=RANGE_MICRO Price=1.0601
2026-10-14 08:49:01,954 [INFO] >>> FCM PUSH BROADCAST SUCCESS! MsgID: projects/crypto-49cb0/messages/-250049164921888627 | Title: ⚡ [区间震荡 · 小波段低吸预警] SUIUSDT

2026-10-14 08:49:03,999 [INFO] >>> DETECTED SIGNAL: LINKUSDT Strategy=RANGE_MICRO Price=12.987
2026-10-14 08:49:04,343 [INFO] >>> FCM PUSH BROADCAST SUCCESS! MsgID: projects/crypto-49cb0/messages/9062807749740167402 | Title: ⚡ [区间震荡 · 小波段低吸预警] LINKUSDT
```

### 6.2 日志证据分析与定性结论

1. **该信号是否真实发生过？**
   - **完全确证**。北京时间 2026-10-14 08:49:01（SUI）与 08:49:03（LINK）确实由当时的 Python 扫描引擎生成。
2. **发生的原因**：
   - 当时服务器运行的代码中 `TARGET_SYMBOLS = ["SUIUSDT", "BTCUSDT", "LINKUSDT"]`，扫描循环遍历所有目标，导致 2 秒内先后对 SUI 和 LINK 发送了预警。
3. **推送生命周期的严格定性**：
   - 日志中的 `FCM PUSH BROADCAST SUCCESS! MsgID: ...` 仅证明 **Google Firebase FCM 服务器成功接收了该消息进队 (`FCM_ACCEPTED`)**；
   - **无法证明**用户的 Android 手机实际亮屏收到了弹窗（`DEVICE_RECEIVED` / `USER_NOTIFIED`）。若手机断网、杀后台或无 Google Play 服务，该消息可能未送达。
4. **当前生产状态**：
   - 09:16:10 守护进程更新后，多币种循环已被切断，09:18 之后的日志证明已**仅向 BTCUSDT 单币种推送**。

---

## 七、 回测与胜率可信度审计

### 审查结论：**`UNVERIFIED PERFORMANCE CLAIM` (全量未验证/纯演示数据)**

在整个代码库及生产服务器中，针对此前宣传的 `87.4% ~ 94.6%` 胜率及 `90.2%` 综合回测成绩进行了地毯式追溯：

1. **数据来源真相**：
   - 所有的胜率字段（如 `StrategyEngineView.tsx:77` `winRate: '88.5%'`，`105行` `winRate: '93.2%'`，`161行` `winRate: '94.6%'`）均为**前端视图静态常量（Hardcoded String）**。
   - 信号中的 `confidence = 93%` 均为人工设定的数值插值公式（例如：`confidence = Math.min(96, Math.round(91 + bounceFromBottomPct * 3.2))`），**并非由统计机器学习或历史回测得出**。
2. **缺失核心资产**：
   - 项目中**不存在任何历史回测脚本**（无 Backtest runner、无历史数据清洗脚本、无订单撮合模拟器）。
   - **未考虑滑点实测分布**（0.03% 仅为主观静态假设，未经过暴跌极端流动性检验）。
   - **未统计最大历史回撤 (Max Drawdown)**。
   - **未区分样本内 (In-Sample) 与样本外 (Out-of-Sample) 验证**。

---

## 八、 Android 端与云端一致性审计

| 比较维度 | 本地 Android 客户端 (V1.05) | 腾讯云生产环境 (43.163.203.127) | 一致性定性与差异说明 |
|---|---|---|---|
| **代码实现语言** | TypeScript (React 19) | Python 3.12 (原生脚本) | **算法逻辑双端独立维护** |
| **量化风控算法** | `quantEngine.ts` (1,155 行) | `/opt/shotcrypto/scanner_daemon.py` (825 行) | **一致**（均已同步 5% 空头门槛、5重止跌、3级分位波动率、0.11%摩擦门禁） |
| **监控交易标的** | `BTCUSDT` (唯一) | `BTCUSDT` (唯一，自 09:16 起生效) | **一致** |
| **行情数据来源** | Binance REST + Binance Vision + Finnhub 备用 | Binance REST (`data-api.binance.vision`) 轮询 | **基本一致** |
| **预警通知机制** | 客户端本地声音 (Web Audio API) + 页面弹窗 Modal | 云端 Python 通过 Firebase Admin SDK 推送 FCM Topic | **分工明确**：云端负责熄屏后台广播，前端负责前台沉浸弹窗 |
| **决策冲突隐患** | 本地根据 WebSocket 独立计算并弹窗 | 云端根据 REST 独立计算并推送 FCM | **存在双重报警风险**：网络延迟差异可能导致手机收到 FCM 与前台弹窗出现几秒时间差 |

---

## 九、 静态边界测试分析 (12项边界场景)

| 场景 | 当前代码的实际处理逻辑 | 证据路径与行号 | 是否符合预期 | 潜在风险 | 建议后续测试 |
|---|---|---|---|---|---|
| **1. BTC窄幅横盘，RSI 44** | 进入震荡分支，调用 `verifyMicroRangeReversal` 校验低点不破、微阳站稳 EMA7 等 5 重门禁 | `quantEngine.ts:992-1014` | **符合** | 未收盘 K 线若瞬时微阳站上 EMA7，会瞬时放行 | 注入瞬时脉冲假阳线测试 |
| **2. BTC持续暴跌，RSI 25** | 先触发瀑布通道拦截；若非瀑布但处于空头，校验跌幅是否 $\ge 5\%$。未达 5% 彻底拦截，达到 5% 且企稳才允许抄底 | `quantEngine.ts:733`, `762` | **符合** | 暴跌中途若出现 2 根缩量假阴线使瀑布判定失效，跌幅达标时可能抄在半山腰 | 模拟 5% 连续大阴线下杀行情 |
| **3. BTC单边上涨2.5%** | 4小时漂移 $>+0.8\%$ 且站稳均线，强制识别为 `TRENDING_BULL`，短路震荡模型，仅允许放量起爆与顺势回踩 | `quantEngine.ts:602-641` | **符合** | 无，趋势与波动已严格解耦 | 模拟单边主升浪 K 线序列 |
| **4. BTC振幅恰好0.95%** | 采用经验分位数 $Q_{vol} \le 30\%$ 综合判定，不再单纯依赖 0.95% 硬跳变 | `quantEngine.ts:174-177` | **符合** | 临界点跳变风险已被平滑消除 | 构造 0.95% 边界行情数据集 |
| **5. BTC振幅恰好2.0%** | 若 $Q_{vol} \ge 75\%$ 或大于 12H 的 $P_{75}$ 分位数，平滑划入大幅波动 | `quantEngine.ts:179-183` | **符合** | 无边界断层问题 | 构造 2.0% 边界行情数据集 |
| **6. ATR为0或NaN** | ATR 为 0 时 `adaptiveTp1` 被钳位在 0.65%，仍能计算出 1.10:1 净盈亏比 | `quantEngine.ts:189-191` | **不符合** | **数据异常时依然可能发出买入信号** | 增加前置 `!atr14` 空值断言 |
| **7. 1H趋势数据延迟** | `diagnoseMacroTrend` 未校验 `hourlyCandles[-1].time` 时戳时效性 | `quantEngine.ts:548` | **不符合** | 网络假死或缓存超时时，基于过时大盘趋势误判 | 注入过期 3 小时的 K 线测试 |
| **8. 两个策略同时BUY** | 采用 `if ... else if` 互斥链，单次扫描仅输出最高优先级单一策略 | `quantEngine.ts:808-1073` | **符合** | 单次扫描无冲突；但下一次扫描可能因价格微变切换策略 | 多模型竞争压测 |
| **9. BTC触发BUY，SUI也触发BUY** | 前端与云端最新代码均设置了 `symbol !== 'BTCUSDT'` 强制拦截 | `quantEngine.ts:698`, `scanner:563` | **符合** | 历史残留脚本若误启动会再次触发 SUI | 持续封锁非 BTC 代码 |
| **10. FCM发送失败** | `send_fcm_alert` 捕获异常打印 error 并返回 `False`，主循环记录报警日志 | `scanner:75-101`, `815` | **部分符合** | 未检查返回值，未重试，未在监控系统登记失败指标 | 模拟断网注入 FCM 故障测试 |
| **11. 2秒内连续触发相同信号** | 内存字典 `RECENT_ALERT_MEMORY` 实施 60s (云端) / 45s (前端) 物理防抖 | `scanner:798-800`, `App.tsx:153` | **符合** | 仅单端内生效，两端并发时可能在短时间内先后各报一次 | 双端并发压力测试 |
| **12. 未收盘K线出现假突破** | 取 `candles[-1]`，K 线每 2 秒变化，未收盘前若价格短暂冲过 EMA7 即触发 | `quantEngine.ts:351`, `scanner:413` | **不符合** | **最具隐蔽性的盘中骗线风险 (P1)** | 注入长上影线假突破形态测试 |

---

## 十、 P0 至 P3 风险清单 (Risk Matrix)

| 编号 | 风险等级 | 问题描述 | 证据文件与行号 | 潜在影响与后果 | 修复与改造建议 |
|---|---|---|---|---|---|
| **R-01** | **P1 (高)** | **未收盘K线实时假突破误触发** | `quantEngine.ts:351`, `scanner:413` | 5重门禁基于 `candles[-1]` 最新跳动价。若 1m K线前 15 秒冲高突破 EMA7，随后跳水收长上影阴线，系统会在盘中冲高瞬间误发出买入预警 | 引入收盘确认机制（如判断当前秒数 $\ge 50s$）或在门禁中加入前一已收盘 K 线的形态要求 |
| **R-02** | **P1 (高)** | **策略类型突变绕过冷却时间** | `src/App.tsx:160-164` | 冷却判断中包含 `if (isStrategyChange) allow;`。当行情震荡在微阳与均线间摆动时，若策略由 `BOTTOM_REBOUND` 突变为 `RANGE_OSCILLATION`，会直接绕过 150 秒冷却连续弹窗 | 取消策略变更为白名单的逻辑，实行针对标的的全局绝对冷却倒计时 |
| **R-03** | **P1 (高)** | **回测系统完全缺位与虚假胜率宣称** | `StrategyEngineView.tsx:77-217` | 87%~94.6% 胜率全为写死的字符串，缺乏历史回测支撑，极易导致实盘交易者盲目加杠杆爆仓 | 明确标记为“策略理论置信度”，并立项开发离线 BTC 历史多周期回测流水线 |
| **R-04** | **P2 (中)** | **ATR 为 0 或 NaN 时的边界放行缺陷** | `quantEngine.ts:189-191` | 当 K 线数据不足或出现异常断线导致 ATR=0 时，`adaptiveTp1` 被 `Math.max(0.65)` 钳位，依然能计算出 1.10:1 净盈亏比并发出买入信号 | 增加数据完整性前置断言：`if (!atr14 || isNaN(atr14) || atr14 <= 0) return null;` |
| **R-05** | **P2 (中)** | **1小时大盘趋势行情缺乏时效性校验** | `quantEngine.ts:548`, `scanner:315` | 未校验 `hourlyCandles[-1].time` 与系统当前时间差。若大盘 1H K线因网络异常长时间未刷新（例如缓存停留在数小时前），系统仍会基于陈旧趋势放行买入 | 增加时钟防抖检验：1H 最新蜡烛时间差超过 2 小时判定为数据失效，拒绝出信号 |
| **R-06** | **P2 (中)** | **双端独立引擎无统一分布式仲裁锁** | `App.tsx:201` vs `scanner:631` | 本地前端与云端后台两套引擎各自轮询 Binance，若网络抖动会导致本地弹窗与手机系统通知时间不同步 | 架构演进为“云端唯一定位决策，前端仅做只读展示与监听 WebSocket/FCM” |
| **R-07** | **P3 (低)** | **SUI 废弃组件与文案代码残留** | `SuiPositionDashboard.tsx`, `manifest.json:5` | 代码未被引用但留在代码树中，增加包体积并引起维护歧义 | 下一阶段安全物理清理 |

---

## 十一、 BTC Only 最小改造实施方案建议 (仅规划，本次不执行)

若后续进入开发阶段，建议按以下严格依赖顺序执行最小化改造：

1. **第 1 阶段：物理清理多币种代码残余**
   - 涉及文件：`src/components/SuiPositionDashboard.tsx`（物理删除）、`public/manifest.json`（移除 SUI 描述文案）。
2. **第 2 阶段：加固未收盘 K 线防御机制**
   - 涉及文件：`src/services/quantEngine.ts` 与云端 `/opt/shotcrypto/scanner_daemon.py`。
   - 动作：在 `verifyMicroRangeReversal` 引入当前 1m K 线已走过时间判定（必须 $\ge 45s$），或以倒数第二根已定型 K 线 `candles[-2]` 作为主要反转判定源。
3. **第 3 阶段：封堵策略切换绕过冷却的漏洞**
   - 涉及文件：`src/App.tsx` 行 158-165。
   - 动作：移除 `isStrategyChange` 的放行特权，确保 BTC 在任意买入触发后，必须经历至少 90 秒的绝对物理冷却。
4. **第 4 阶段：补充数据完整性与时效断言**
   - 涉及文件：`src/services/quantEngine.ts`。
   - 动作：增加 `if (!atr14 || atr14 <= 0 || isNaN(atr14)) return null;` 以及 1H K线陈旧度检查（超 90 分钟未更新强制判定数据不足）。
5. **第 5 阶段：建立 BTC 历史量化回测基准工程**
   - 动作：编写离线 Python 回测套件，调取 Binance 2024-2026 年 BTC/USDT 1m 真实成交数据，计算真实盈亏比与胜率，取代界面的硬编码假数据。

---

## 十二、 最终审计裁决

| 核心审计项 | 审计裁定 | 核心事实依据 |
|---|---|---|
| **V1.02 三级波动引擎** | **PARTIAL** | 12H 48根K线滚动分位数（$P_{25}/P_{50}/P_{75}/Q_{vol}$）与趋势解耦**已真实落地**，优于原设计；但门禁计算受未收盘实时 K 线跳动影响，存在假突破风险 |
| **统一风险门禁** | **PARTIAL** | 空头 5% 跌幅门槛、单边瀑布拦截、0.11% 交易摩擦门禁**均已硬阻断生效**；但缺失数据时效性校验与 ATR 为 0 时的除零安全保护 |
| **FCM 推送链路** | **PASS** | 经生产日志核验，Firebase Admin SDK 链路完好，成功实现针对 Topic 的广播推送；已完成由多币种向单一 BTCUSDT 推送的收敛 |
| **回测可信度** | **FAIL** | 全系统**无任何量化回测代码、无历史撮合样本**，前端 87%~94.6% 胜率全为 Hardcoded 假数据，标记为 `UNVERIFIED PERFORMANCE CLAIM` |
| **Android 与云端一致性** | **PARTIAL** | 两端算法逻辑高度对应（双端均包含 5% 空头门槛、5重止跌门禁与 3 级波动模型）；但属于“双引擎并行自治”模式，存在推送与前台弹窗无全局锁的问题 |
| **BTC Only 就绪程度** | **PASS** | 生产守护进程与前端核心扫描入口均已收敛至 `BTCUSDT` 单一标的，残留 SUI 代码已处于孤立休眠状态，具备转为纯 BTC 运作的坚实基石 |
