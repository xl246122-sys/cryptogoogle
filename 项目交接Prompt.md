# Crypto-G 项目完整交接与继续开发 Prompt（2026-10-20 最新版）

> **使用说明**：
> 本文档是开启新对话时的**唯一权威交接基准**。在新的对话窗口中，直接复制本文档全部内容发送给 AI 助手，即可无缝承接所有上下文、工程环境与核心铁律，避免重复开发与模型幻觉。

---

## 1. 项目基本信息与运行环境

### 1.1 标的与交易定位
- **唯一监控标的**：`BTCUSDT` 币安现货，**只做多单（BUY Only，严禁做空或对冲）**。
- **持仓周期**：短线波段（5 分钟至 6 小时）。
- **量化引擎版本**：`short-horizon-v2`（引擎 A：`scratch/cryptog/engine_v2.py`，配置参数：`scratch/cryptog/config.py` 中的 `V2_*`）。
- **硬性风控门禁（不可突破）**：
  - **摩擦成本地板**：双向吃单 `0.24%`（0.10% taker/边 + 0.02% 滑点/边；BNB 抵扣地板 `0.19%`）。
  - **净目标利润**：$TP1_{net} \ge 0.50\%$（毛利 $\ge 0.74\%$），在入场区间最差价格检验。
  - **净盈亏比**：$RR_{net} \ge 1.0$。
  - **结构性止损**：$0.35\% \sim 1.20\%$，结构止损只可外扩缓冲（$+0.15 \times ATR15$），严禁为了凑盈亏比而收窄。
  - **单笔风险**：账户总净值的 $0.5\%$；模拟账本单笔基准 `$500 USDT`。
  - **信号有效期**：触发周期 2 根 K 线；价格高出进场区 $0.25\%$ 自动作废。
  - **出场机制**：TP1 止盈 50% 并将止损移至保本+成本位；90 分钟未达 $+0.3R$ 离场，360 分钟（6小时）硬性止损。
  - **形态分级**：S1~S4 目前均为 `观察级·未验证`（WATCH 级），S5 仅用于研究；熔断仅暂停交易级，观察级继续推送。

### 1.2 本地与移动端环境
- **本地代码仓库**：`D:\Crypto-Google`（Windows PowerShell 环境）。
- **技术栈**：Ionic React + TypeScript + Vite + Tailwind CSS + Capacitor Android Native。
- **APK 交付规范（必须严格遵守）**：
  - 交付路径：`D:\Crypto-Google\release\Crypto-G V{versionName}.apk`。
  - 自动归档：`android/app/build.gradle` 配置了 `copyApkToRelease` 任务，执行 `./gradlew assembleDebug` 会自动将产物复制到 `release/` 目录。
  - 版本递增：每次迭代发版，`android/app/build.gradle` 中的 `versionName` 必须 **+0.01**，`versionCode` 必须 **+1**。
  - **当前最新交付产物**：[`D:\Crypto-Google\release\Crypto-G V1.63.apk`](file:///D:/Crypto-Google/release/Crypto-G%20V1.63.apk)（versionName `1.63`，versionCode `163`，大小约 6.36 MB）。

### 1.3 远端云服务器信息
- **服务器节点**：腾讯云东京节点（直连币安撮合中心），公网 IP：`43.163.203.127`。
- **操作系统**：Ubuntu 26.04 LTS。
- **登录凭据**：账户 `ubuntu`，密码 `Maxence2468;`，具备完整的 `sudo root` 提权能力。
- **云端服务与守护进程**：
  1. `shotcrypto.service`：核心量化扫描与模型库守护进程（端口 `8788` HTTPS，脚本路径 `/opt/shotcrypto/scanner_daemon.py`）。
  2. `cryptog-wave-observe-push.service`：波段观察与预警推送服务（脚本路径 `/opt/shotcrypto/wave_observe_push_service.py`）。

---

## 2. 刚刚完成的关键修复与成果（2026-10-20 最新）

在上一轮开发迭代中，团队集中攻克了四大核心问题，并完成了 V1.60 至 V1.63 的连续交付：

### 2.1 页面 2s–5s 加载延迟与数据空白闪烁彻底根治（V1.63 核心成果）
- **现象回顾**：用户打开 App、锁屏唤醒或切屏回来时，顶部 1H 趋势卡、布林带和三层环境频发 2~5 秒数据空白（显示 `—`、`待更新`、`等待行情`），但底部现价秒出。
- **排查出的 5 个底层根因与修复措施**：
  1. **消除了唤醒破坏性清空**：[`src/App.tsx`](file:///d:/Crypto-Google/src/App.tsx) 移除了 `resume()` 中的 `setMacroTrend(getInitialMarketState())`，切屏/亮屏时绝不抹除已有数据。
  2. **全面落地 SWR（Stale-While-Revalidate）架构**：网络短暂抖动或遇到 4 秒超时时，前端自动保持上一刻渲染数据并打上 `CACHE · 同步中` 标识，后台静默重试，视觉上实现零空白过渡。
  3. **HTTP `Date` 响应头绝对时间校准**：[`src/services/marketState.ts`](file:///d:/Crypto-Google/src/services/marketState.ts) 从服务端响应头获取精准东京时间基准 `serverNow`，彻底根除了手机本地时钟与服务器时钟漂移（误差 3-5s）导致的“超过 10s 误判为数据过期并全屏变空白”的重大缺陷。
  4. **Native 安全存储 Scope 兜底**：[`src/services/serverConnection.ts`](file:///d:/Crypto-Google/src/services/serverConnection.ts) 为 Android Keystore 增加了确定性 URL 哈希兜底，确保冷启动 100% 命中首屏快照缓存。
  5. **雷达图与布林组件 CACHE 支持**：[`src/components/views/RadarView.tsx`](file:///d:/Crypto-Google/src/components/views/RadarView.tsx) 优化了渲染判断，在 `CACHE` 状态下立即可视化布林上下轨与多空状态。

### 2.2 “观察：...”预警机制修复与推送流控优化（V1.61 - V1.62）
- **现象回顾**：观察预警在修改为 10 分钟间隔后 10 小时未收到一条；此前曾出现 1 分钟内同时发“下跌行情预警”又发“研究候选已撤销”的逻辑矛盾。
- **根因与修复**：
  1. **修复云端服务闪退**：`/opt/shotcrypto/manifest.json` 的 SHA256 校验与部署脚本不匹配，触发 `SOURCE_HASH_MISMATCH` 导致 `cryptog-wave-observe-push.service` 崩溃停止。已修复校验并稳定运行。
  2. **修复未确认即撤销的逻辑缺陷**：在 `scratch/cryptog/wave_push.py` 中，修复了若从未发出过 `REBOUND_CONFIRMED`（反弹确认）就静默忽略 `INVALIDATED`（已撤销），杜绝无源撤销。
  3. **严格落地用户要求的双层流控**：
     - **同类内容**：执行 60 秒（1 分钟）严格冷却。
     - **跨类冲突**：同波段 180 秒（3 分钟）内抑制不同阶段推送，避免“边报下跌、边报撤销”。
     - **标题格式标准化**：统一使用 `观察：【...】`（如 `观察：【下跌行情预警】`、`观察：【反弹确认·研究候选】`）。

### 2.3 近 6 个月历史 BTC 现货量化基线审计与服务器运维
- **6 个月基线审计报告**：回测了 2026-04 至 2026-10 币安实盘 BTC 数据（180 天、17,305 根 15m K 线），出具完整报告存放在 `BTC_Spot_Quant_Audit_Report.md`，确认 S1~S4 在 0.24% 摩擦下表现稳健，继续维持 `观察级·未验证` 状态。
- **云端磁盘空间清理**：排查并清理了 `/opt/shotcrypto/backups/` 中累计的 16.32 GB 重复 SQLite 数据备份，服务器磁盘占用率从 70% 降至 35%（剩余 31 GB 可用空间）。
- **TLS 握手日志降噪**：在 `/opt/shotcrypto/scanner_daemon.py` 中静默了无害的 TLS 异常断开日志，轮转了日志文件，服务平稳运行。

---

## 3. 当前代码库与测试状态

- **Git 工作区状态**：干净稳定，所有修改已通过全量回归测试。
- **测试套件运行结果**：
  - 执行指令：`npm test`
  - 覆盖范围：包含 65 项 TypeScript 单元/UI 组件测试、18 项 Python 量化风控与五重门禁测试，以及模型库测试。
  - 运行结果：**全部 316/316 测试通过（100% Passed）**。
- **最新打包产物**：
  - 路径：[`D:\Crypto-Google\release\Crypto-G V1.63.apk`](file:///D:/Crypto-Google/release/Crypto-G%20V1.63.apk)
  - 校验大小：6,359,574 字节。

---

## 4. 关键文件与架构地图

| 模块 | 本地路径 | 说明 |
| :--- | :--- | :--- |
| **量化引擎 A** | `scratch/cryptog/engine_v2.py` | S1~S5 形态检测、15m 触发、5m 收复确认、摩擦门禁 |
| **策略参数配置** | `scratch/cryptog/config.py` | `V2_*` 硬性常量（0.24% 摩擦、0.5% 风险、1.0 净盈亏比） |
| **波段预警服务** | `scratch/cryptog/wave_push.py` | 观察波段预警、FCM 推送、60s 同类冷却、180s 跨类抑制 |
| **前端主程序** | `src/App.tsx` | 3 秒行情轮询、SWR 平滑数据保持、系统唤醒静默刷新 |
| **行情状态解析** | `src/services/marketState.ts` | 快照数据解析、HTTP `Date` 时间校准、冷热缓存恢复 |
| **原生凭据存储** | `src/services/serverConnection.ts` | Android Keystore 加密凭据与 `cacheScope` 确定性隔离 |
| **主雷达图视图** | `src/components/views/RadarView.tsx` | BTC 现价看板、1H MA20/布林带、三层多空环境指示 |
| **消息中心** | `src/components/MessagePanel.tsx` | 观察性预警与交易信号分级列表、滑动删除与标记已读 |
| **Android 构建** | `android/app/build.gradle` | 当前版本 1.63 / 163，集成 `copyApkToRelease` |

---

## 5. 常用研发与维护命令清单

### 5.1 自动化测试
```powershell
# 运行全部测试（包含 TS 与 Python 离线套件）
npm test

# 单独运行 Python 量化风控套件
python tests/run_python_offline.py
```

### 5.2 前端构建与 Android APK 打包
```powershell
# 1. 编译前端工程
npm run build

# 2. 同步静态资源到 Android 原生工程
npx cap sync android

# 3. 编译 Debug APK 并自动同步到 release 目录（注意版本号需 +0.01）
cd android
.\gradlew.bat assembleDebug
cd ..

# 4. 验证 APK 是否生成成功
Get-Item "D:\Crypto-Google\release\Crypto-G V1.63.apk"
```

### 5.3 云端服务器运维（通过 SSH 登录 `43.163.203.127`）
```bash
# 查看两大系统服务运行状态
sudo systemctl status shotcrypto.service
sudo systemctl status cryptog-wave-observe-push.service

# 查看服务实时日志
sudo journalctl -u shotcrypto.service -n 50 --no-pager
sudo journalctl -u cryptog-wave-observe-push.service -n 50 --no-pager

# 热更新重启服务
sudo systemctl restart shotcrypto.service
sudo systemctl restart cryptog-wave-observe-push.service
```

---

## 6. 后续任务指引与建议（下一步开发方向）

1. **观察 V1.63 客户端实测体验**：
   - 验证用户安装 `Crypto-G V1.63.apk` 后，在熄屏、切屏以及网络弱网环境下的加载平滑度，确认 2s-5s 空白卡顿已彻底消除。
2. **监控云端观察预警推送频率**：
   - 关注 `cryptog-wave-observe-push.service` 在实盘波动中的表现，验证 1 分钟同内容冷却与 3 分钟跨类别抑制是否精准执行。
3. **晋级流程准备**：
   - 当前所有形态均在 `观察级·未验证` 状态。未来如果用户提出“晋级进入交易级”，需严格根据方案第七节，检查累计样本外实盘样本是否满足 60 笔、胜率 $\ge 52\%$、净期望 $\ge +0.10\%$ 的晋级硬门槛。

---
*交接文档生成时间：2026-10-20。已全量同步至本地根目录：`D:\Crypto-Google\项目交接Prompt.md`。*
