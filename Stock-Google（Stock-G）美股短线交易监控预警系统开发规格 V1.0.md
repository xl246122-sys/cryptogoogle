# Stock-Google（Stock-G）美股短线交易监控预警系统开发规格 V1.0

> 日期：2026-10-17。目标市场：美股（NYSE/Nasdaq），非A股。交易类型：以普通股票、ETF做多为主；持仓窗口30分钟至5个交易日；用户手工买卖。本文为研发设计与验收规格，不保证任何交易胜率或回报。

## 1. 一句话任务
开发云端常驻监控 + Android 实时预警的美股短线辅助系统。量化引擎负责可复算交易条件，DeepSeek AI负责新闻风险、解释、复盘和离线优化建议；云端风控具有最高优先级；不允许AI直接下单、卖出、改写生产策略。支持真实交易镜像仓与独立策略模拟仓的完整闭环。

## 2. 范围与不可违反的规则
- 主市场美股；产品名称 Stock-Google / Stock-G。A股未来另做独立市场适配，不复用交易时段及资金规则。
- 关注1m、10m、30m、1h、2h、4h、1D；30m用于主信号，1m/10m用于入场优化，日线和4h/2h用于大趋势。
- 三策略：开盘区间突破 ORB，暴跌确认反弹 Rebound，区间震荡 Range。
- 先判断市场状态 TREND_UP / TREND_DOWN / RANGE / TRANSITION / HIGH_VOL，再分配策略；HIGH_VOL默认禁止新增多头买入。
- 所有正式 BUY 必须由云端统一批准，验证实时行情/时区/数据质量/事件风险；离线本地只能显示缓存并标注过期。
- 风险监控独立于买入信号：无新买入时仍要监视已持仓止损、结构失效、新闻、停牌。
- 禁止自动下单、禁止使用模拟行情触发生产交易通知、禁止无人工审批的生产参数自动改变。
- 券商买卖均由用户手动执行；用户可自行录入成交记录、同步镜像仓，保留数据来源标记。

## 3. AMD 六周期样本（仅截图，不是实时交易指令）
2026-10-16截图报收约528.75美元，日内低点524.97美元，另有527.08的图表标价，待核对行情时间与盘后属性。EMA7/25/99：日线576.72/581.08/508.36，4h542.39/567.30/590.50，2h535.36/551.94/585.50，1h530.55/542.73/568.07，30m527.72/535.92/552.95，10m526.51/528.43/538.92。高周期明显偏空，适合训练趋势压制与反弹确认，不得凭RSI超卖直接买入。截图不含可验证的实时订单簿与新闻，不生成实际入场目标。

## 4. 行情数据模块
- 评估 Alpaca IEX基础实时与付费SIP全市场，或 Massive 行情，必须核对API权益、实时性和展示/存储/再分发条款。
- WebSocket采集 + REST回补 + 断线重连 + 乱序去重 + 行情源切换和差异告警。
- 一分钟基础K线，按美东交易所实际日历、夏令时和常规会话定义合成多周期K线；盘前/盘后独立计算指标。
- K线字段：symbol, venue/feed, session, open/high/low/close/volume, bar_start/end, event_time, ingested_at, is_final, adjustment_version, quality_flags。
- 处理拆股/分红/停牌/交易条件/修正成交/空缺bar。数据过期时不得发布新BUY；风险提醒可使用最后已知价但必须标注陈旧。
- 定期核对与行情基准的OHLCV偏差并生成对账报告。

## 5. 策略与信号规则（初始参数为研发假设）
### ORB
- 美东9:30开盘，前15m或30m定义opening range；30m/1h趋势不明显看空；有效收盘突破区间上沿；VWAP上方；同期RVOL建议>=1.5；QQQ/SPY风险过滤。
- 一分钟提前观察，10m/30m确认；避免高开过大后的高位追单；入场需回踩确认或明确的连续收盘突破。
- 若价差异常、低流动性、突发负面新闻、事件/熔断或风险收益比低于要求，禁止发布。
### Rebound
- ATR归一化跌幅、RSI、均线偏离仅构成WATCH，非BUY；检查重大负面事件；10m higher low、局部压力收复、30m卖压减弱、成交量回升才进入候选。
- 一轮下跌中连续失败需冷却期；如新低/结构失效则候选撤销。
### Range
- 用ADX、布林带宽、ATR、支撑阻力接触次数分类；ADX<20仅是候选，不能单独判定；支撑带反转确认入场；中线/上沿逐步退出；趋势突破后停用。
### 统一信号
- WATCH -> NEAR_TRIGGER -> BUY_CANDIDATE -> EXPIRED/INVALIDATED 或用户标记 FILLED -> POSITION_RISK -> CLOSED。
- S/A/B/C为配置评分层级，分数不是胜率。硬性风控比评分和AI优先。
- 信号包含signal_id, strategy_id/version, feature_snapshot_hash, source_bars, provider, timestamp, expire_at, entry_range, stop, target1/2, RR, rationale, invalidation, confidence_quality, news_event_ids。
- 止盈止损由结构/ATR与风险预算决定，初始试验1.5R及2R；已录入真实成交价后按风险重新检查；不得声称止损保证成交。

## 6. 风控配置
- 起始单笔账户风险0.25%-0.5%，计划日亏上限1%，整体风险暴露与相关性另限；均为可调研发初始建议，不是收益承诺。
- 阻断条件：行情陈旧、低质量源、超出交易时间策略限制、停牌/LULD、点差异常、新闻风险高、持仓冲突、净盈亏比不足、仓位预算超限、信号过期、AI关键事件未完成核验。
- 若当前已有持仓，必须继续运行止损/结构/跳空风险监测，即使新BUY全部被禁用。
- FINRA于2026-06-04生效新日内保证金标准，券商有过渡期至2027-10-20。交易资格按券商、现金/保证金账户和实际实施状态核验。美股大多数适用股票T+1交收。资金账户余额不可凭估算放大交易能力。

## 7. AI新闻及DeepSeek
- 权威源：SEC EDGAR公司披露、发行人IR、交易所公告、Fed/BLS/BEA；授权新闻可接入Alpaca实时新闻等。
- 消息处理：发布/抓取时间 ->去重 ->股票映射 ->原始来源证据 ->DeepSeek结构化分类 ->保守风险规则 ->推送及审计。
- AI输出事件ID、分类、利好/利空/不确定、影响范围、严重程度、事实证据、发布时间、置信与未知项；不把文章/网页文本作为系统指令。
- 2026-10官方可参考 model=deepseek-flash 和 deepseek-v4-pro，base_url=https://api.deepseek.com；不可把用户口头的V3永久写死；模型名可配置、需版本兼容测试。
- AI允许提出假设、解释量化信号、标记风险和建议拒绝；不能无规则凭空产出BUY、不能直接改生产配置。
- 密钥只在云端，超时可降级但不能绕过安全决策。

## 8. 交易记录/模拟仓
- 真实镜像仓：用户录入fill时间、方向、股数、价格、费用、关联信号；支持分批、补录、纠错审计，忠实反映实际成交（不是默认验证券商）。
- 独立策略模拟仓：对所有候选信号按统一成交模拟器跟踪，包括用户未买的信号；纳入点差、滑点、时延、不可成交、跳空和分批成交。
- 不将镜像仓盈利等同于策略成功；所有被拒绝、过期、放弃的候选必须归档，用于消除样本选择偏差。
- 交易事件模型：trade_id, account_kind, signal_id, symbol, fill_id, timestamp, side, price, qty, fee, reason_code, source, correction_of，写入幂等键，保证至少一次消息投递也不会重复记账。

## 9. 回测与自学习
- 争取3-5年合规许可分钟数据，跨股票、ETF、牛熊震荡、财报与宏观新闻日；样本外按时间隔离，5D标签重叠需要purge/embargo。
- 绩效报表：扣成本胜率和置信区间、样本数、avg win/loss、expectancy、profit factor、max drawdown、PnL_R、MFE/MAE、信号质量和滑点。
- 研发参考门槛：扣成本胜率>=60%、Profit Factor>=1.3、均盈亏比>=1.5、样本外期望>0；不达标标示未验证，不能夸称高胜率。单策略初期至少约200独立交易供评估，但仍需置信区间与市场状态分层。
- L0只采集，L1自动诊断，L2离线优化且人工审批，L3影子+灰度+回滚。生产风险边界不可由AI更改。
- 机器学习先选Logistic/LightGBM/XGBoost、概率校准和Optuna；测试多重参数搜索过拟合，胜率不能直接当作置信概率。

## 10. 工程实现
- Android: React/TypeScript/Vite/Tailwind/Capacitor + FCM；云端Python FastAPI、asyncio/WebSocket、PostgreSQL/TimescaleDB、Redis消息队列、Docker Compose。
- 前端六页：市场雷达、多周期K线、预警中心、真实/策略模拟双仓、AI统计学习、设置及健康状态。
- 服务端域：market_data/candles/indicators/regime/strategies/risk/signals/news/ai/portfolios/paper_trading/backtesting/learning/notifications/database。
- API版本v1: GET /market/quotes, /market/candles, /market/regime, /signals, /signals/{id}, /news/events, /portfolios/real, /portfolios/paper, /analytics/performance, /learning/reports, /system/health；POST /trades/fills。
- 核心数据都需要source_id、版本号、时间戳、审计字段；服务重启可重放，Push去重，FCM状态落库。
- TLS、访问控制、服务端密钥、数据库备份、审计日志、通知验收，开发/模拟/生产环境物理或逻辑隔离。

## 11. 分期与上线验收
- P0（周1-3）：行情/WebSocket/K线/Android/FCM/健康；成功上线真实数据WATCH。
- P1（周4-6）：三策略、趋势分类、信号状态机、风控；AMD空头例必须拒绝仅RSI抄底。
- P2（周7-9）：官方新闻/DeepSeek、真实镜像仓与模拟仓、推送。
- P3（周10-12）：历史/样本外/影子回测、绩效面板和版本化。
- P4（周13-16）：受控学习、灰度、回滚、压力/断线/安全/推送测试。进度是估算，需以数据接口可用性为准。
- P0至P4每阶段都输出：代码、自动化测试、API合约、日志、截图、真实设备验收、部署步骤、失败回滚步骤和里程碑报告。

## 12. MVP明确不做
不自动下单/卖出，不做期权/杠杆/卖空，不承诺固定盈利，不展示无样本胜率，不让AI自行修改线上生产策略，不用未经授权的延迟行情生成真实买入提示，不把新闻情绪当唯一入场依据。

## 13. 关键外部官方研究与文档
- FINRA 2026规则：https://www.finra.org/rules-guidance/notices/26-10
- FINRA 投资者解释：https://www.finra.org/investors/insights/intraday-margin-requirements
- SEC T+1：https://www.sec.gov/oiea/investor-alerts-and-bulletins/new-t1-settlement-cycle-what-investors-need-know-investor
- NYSE交易时段：https://www.nyse.com/trade/trading-information
- Alpaca数据套餐：https://docs.alpaca.markets/us/docs/about-market-data-api
- Alpaca新闻流：https://docs.alpaca.markets/us/docs/streaming-real-time-news
- Massive股票WebSocket：https://massive.com/docs/websocket/stocks/overview
- SEC EDGAR：https://www.sec.gov/search-filings/edgar-application-programming-interfaces
- DeepSeek模型：https://api-docs.deepseek.com/quick_start/pricing/
- Market intraday momentum (2018): https://ideas.repec.org/a/eee/jfinec/v129y2018i2p394-414.html
- Assessing profitability of ORB strategies (2013): https://www.sciencedirect.com/science/article/pii/S1544612312000438
- The cross-section of speculator skill (2014): https://escholarship.org/uc/item/7k75v0qx
- Deflated Sharpe Ratio (2014): https://doi.org/10.2139/ssrn.2460551

## 14. 给开发代理的第一条执行指令
先生成需求追踪矩阵、架构决策记录和P0执行清单，明确数据服务选择、配额、行情授权、盘前盘后、时区规则、延迟阈值、Android推送测试方式。先实现单只AMD的真实行情采集 + 多周期K线 + 市场状态 + 无买入WATCH预警 + Android FCM全链路，验证后扩大自选池。P0不得提前实现自动交易或声称模型有实测高胜率。
