"""Render the observed stage-D status without promoting or changing any rules."""
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CST = timezone(timedelta(hours=8))


def read(path):
    return json.loads((ROOT/path).read_text(encoding='utf-8-sig'))


def date(ms):
    return datetime.fromtimestamp(ms/1000, CST).strftime('%Y-%m-%d %H:%M:%S')


def number(value, percentage=False):
    if value is None:
        return '不可判定'
    return f'{value*100:.2f}%' if percentage else f'{value:.4f}'


def main():
    directory = ROOT/'model_library/stage-d/D-20261018-002'
    protocol = read('model_library/stage-d/D-20261018-002/protocol.json')
    coverage = read('audit/stage-d-diagnostic-data.json')
    live = read('audit/stage-d-live-acceptance.json')
    tool_status = read('audit/stage-d-final-tool-status.json')
    tests = sum(map(int, re.findall(r'Ran (\d+) tests?', (ROOT/'audit/stage-d-tests.txt').read_text(encoding='utf-8-sig'))))
    results = [(path.stem, json.loads(path.read_text(encoding='utf-8'))) for path in sorted((directory/'trials').glob('*.reviewed.json'))]
    attempts = list((ROOT/'model_library/stage-d').rglob('*.trial.json'))
    aborted = list((ROOT/'model_library/stage-d').rglob('*.aborted.json'))
    lines = ['# D 阶段实施记录 · 独立验证准备与晋级防护', '',
             '日期：2026-10-18（北京时间）。状态：D 阶段已进入，数据补齐、研究准备和晋级防护已交付；独立验证与交易级晋级尚未完成。', '',
             'S1–S5 参数、成本下限、止损约束、持有上限和熔断规则未调整。APK 保持 V1.53 / 153，本次没有 APP 发布。', '',
             '## 已完成', '',
             '- 分别只读核查本地与生产研究库，并将本地历史复制为独立 SQLite 诊断库；原库和线上数据未被回补覆盖。',
             '- 历史分钟线补齐至旧报告截止时点；每周期内部缺口与数据校验异常均为 0。尾部不延伸至现在，不能描述为实时库。',
             '- 历史诊断使用生产 evaluate、冻结输入窗口、1 分钟结算、候选去重、单模块重叠限制和共享 500 USDT 资金预算。',
             '- 交易总收益统计包含亏损、保本和时间退出；路径不确定样本另列，加入按北京时间入场日分块 bootstrap 敏感性。',
             '- 登记每次运行，保留失败/中止记录与代码归档；已看过的历史不重新成为独立样本外。',
             '- 晋级阶段到期后重新要求独立试验、数据质量、唯一有效成交、实际试验矩阵和统计门槛；缺失则延长原阶段。',
             '- 重复扫描同一候选不再增加影子阶段记录数。NaN/无效 PBO 不能通过；完全相同的收益列不产生 PBO=0 的通过证据。', '',
             '## 数据覆盖', '',
             '| 周期 | 根数 | 首根开盘（北京时间） | 末根开盘 | 内部缺口 | 异常 |',
             '| --- | ---: | --- | --- | ---: | ---: |']
    for tf, row in coverage['coverage'].items():
        lines.append(f"| {tf} | {row['count']:,} | {date(row['startMs'])} | {date(row['endMs'])} | {row['internalMissing']} | {row['invalid']} |")
    lines += ['', '数据文件：`data/stage-d-diagnostic.sqlite3`；逐周期内容哈希见 `audit/stage-d-diagnostic-data.json` 和冻结目录。衍生品历史未补造，历史回放没有真实盘口、真实推送或人工操作延迟。', '',
              '## 修正后的历史诊断', '',
              '下表不是独立样本外结果。固定 5 分钟采样判定可能遗漏分钟内机会；成交采用延迟后分钟开盘落入入场带的假设，不把 K 线触碰当作真实排队成交。基础 60 秒、压力 120 秒均为情景值，尚非实测。', '',
              '全部本金保留至最终退出，半仓退出所得不提前复用；资金曲线为现金/占用曲线，不是逐时盯市回撤。单模块行是组合中被选中交易的归因，不是四个独立模块账户。', '',
              '| 情景 | 模块 | 模拟完整交易 | 路径可统计 | 排除 | 整笔≥0.8% | 净胜率 | 净期望% | 日分块95%下限% |',
              '| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for name, report in results:
        for module, row in report['modules'].items():
            stats = row['diagnosticStatistics']
            lines.append(f"| {name} | {module} | {row['total']} | {row['eligible']} | {row['excluded']} | {number(row['achievementRate'],True)} | {number(stats['winRate'],True)} | {number(stats['expectancyPct'])} | {number(row['blockBootstrapLower95'])} |")
    lines += ['', f'登记运行 {len(attempts)} 次，其中 {len(aborted)} 次因 SQLite 查询性能问题中止并保留记录，完成报告 {len(results)} 份。中止后仅增加索引时间边界，没有按收益选参数。两次源码冻结目录 D-20261018-001 / 002 均保留。',
              '不同压力场景和代码重试不冒充互相独立的策略参数组。历史全部试验清单仍未完整恢复，总 nTrials 保持未知；不因本次只跑三组就重置为 3。PBO、正式 DSR 证据均不可判定，晋级不通过。',
              '原始 result.json 保留；reviewed.json 仅纠正旧统计助手默认 nTrials=1/DSR 字段，改为未知，并关联原始文件 SHA256。成交、收益和全部其他统计未改动。003 源码归档保留这项报告元数据修正，不新增参数试验。', '']
    for name, report in results:
        lines.append(f"- {name}：{date(report['startMs'])} 至 {date(report['endMs'])}；计数 {json.dumps(report['counters'],ensure_ascii=False)}；资金情景终值 {report['capital']['finalScenarioCash']:.4f} USDT。所有原始交易腿及候选保存在对应 JSON。")
    future = protocol['prospective']
    lines += ['', '## 独立观察协议与未完成项', '',
              f"独立未来区间已封存为 {date(future['startMs'])} 至 {date(future['endMs'])}。训练标签最晚须于 {date(future['trainingLabelsMustEndByMs'])} 结束，保留 6 小时禁区。该区间尚未发生；任何后续规则或执行模型实质变动须另行登记，不能继承未污染的资格。", '',
              '- 未来生产数据持续由 C 阶段采集，但目前候选/影子/标签/真实成交仍为 0。冻结文件不是已经取得独立结果，也没有设置后台自动研究任务。',
              '- 需完成逐分钟/真实事件的完整重放、独立模块账户与组合盯市资金曲线、波段早期召回及可成交召回，并按事件分组检查泄漏。当前诊断不能代替这些验收。',
              '- 需补齐实测通知/人工操作延迟、成交可实现性证据和真实成本压力核对；假设延迟不能当作测量值。',
              '- 需恢复所有真实试验及失败结果，构建同时间轴收益矩阵并复核 PBO/DSR 估计。不能编造配置补数，也不能将缺失 PBO 当通过。',
              '- 独立门槛全部满足后，才开始规定的 14 天影子、14 天试运行；届时仍须复核有效样本和质量，到期不会自动放行。',
              '- AI 否决效果无足够真实样本，仍未验证；E 阶段真机送达、真实成交及账户核对未完成。', '',
              '## 测试与上线', '',
              f'- 本地 {tests} 项 Python unittest 通过；新增 8 项 D 阶段测试。服务器部署前 20 项针对性测试通过。',
              f"- 部署前 120 条真实输入完整回放差异 0；部署后 {live['reconstructedInputs']} 条回放差异 {live['replayMismatches']}。研究库 quick_check={live['researchQuickCheck']}。", 
              '- 用户明确授权后，于北京时间 2026-10-18 12:58:01 完成生产重启；active/running、NRestarts=0、错误级日志为空。',
              '- 部署 5 个 Python 文件，清单 `audit/stage-d-manifest.json`；研究测试工具不参与生产信号生成。备份 `/opt/shotcrypto/backups/audit-stage-d-20261018-045800`，SQLite 备份已校验。',
              '- 首次自动审批要求明确生产部署授权后已获得用户授权，随后部署及上线验证成功。',
              '- 回滚应恢复兼容代码并保留新增记录；不要用旧研究库覆盖上线后数据。release_candidates 是新增去重表，不删除旧表或历史记录。', '',
              '主要证据：`audit/stage-d-tests.txt`、`stage-d-deploy.txt`、`stage-d-live-acceptance.json`、`stage-d-service.txt`、`model_library/stage-d/`。audit 被 Git 忽略，须保留本地副本。', '']
    if tool_status['status'] != 'DEPLOYED':
        lines += ['补充状态：晋级防护已上线；本地 003 版本的离线报告试验数字段修正尚未同步生产。第二次部署被自动审批要求单独授权，等待用户选择。当前实际线上清单仍为 stage-d-manifest.json，拟同步清单另存 stage-d-manifest-final-pending.json。该差异不参与生产信号或晋级判断。', '']
    else:
        lines += ['补充状态：003 版本的离线报告元数据修正也已获得用户单独授权，于北京时间 13:06:10 同步上线。最终备份 `/opt/shotcrypto/backups/audit-stage-d-20261018-050610`；20 项服务器测试、120 条切换前回放再次通过，切换后 200 条抽样回放差异 0，服务正常且错误日志为空。详见 stage-d-deploy-final.txt、stage-d-live-acceptance-final.json、stage-d-service-final.txt 和 stage-d-final-tool-status.json。实际最终清单为 stage-d-manifest.json，首次清单另存 stage-d-manifest-initial.json。', '']
    dest = ROOT/'开发方案资料 Opus5.5/第四阶段实施记录-D阶段-2026-10-18.md'
    dest.write_text('\n'.join(lines), encoding='utf-8')
    print('Stage D report written.')


if __name__ == '__main__':
    main()
