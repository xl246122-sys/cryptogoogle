"""Package reviewed E-stage APK and rollback patch without private configuration."""
import difflib
import hashlib
import json
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parents[1]
release=ROOT/'release'
apk=release/'Crypto-G V1.59.apk'
expected='154988af3b5ca9239c61f8f5ce1293349c2ba1c1f7fa05f4047c15124c9a1b28'
assert hashlib.sha256(apk.read_bytes()).hexdigest()==expected
with zipfile.ZipFile(apk) as archive:
    for path in (ROOT/'dist').rglob('*'):
        if path.is_file():
            name='assets/public/'+path.relative_to(ROOT/'dist').as_posix()
            assert archive.read(name)==path.read_bytes(),name

patch=[]
name='src/services/notificationService.ts'
current=(ROOT/name).read_text(encoding='utf-8')
old=current.replace("import {NotificationRelay,recordNotificationEvidence} from './notificationEvidence';\n",'')
for origin in ['received','opened']:
    old=old.replace(f"        recordNotificationEvidence(data,'{origin}');\n        this.signalRelay.emit(data,'{origin}');",
        f"        if (this.signalCallback && data) {{\n          this.signalCallback(data, '{origin}');\n        }}")
old=old.replace('  private signalRelay = new NotificationRelay();',
    "  private signalCallback: ((payload: any, origin?: 'received' | 'opened') => void) | null = null;")
old=old.replace('    return this.signalRelay.subscribe(callback);',
    '    this.signalCallback = callback;\n    return () => { if (this.signalCallback === callback) this.signalCallback = null; };')
assert 'signalRelay' not in old and 'recordNotificationEvidence' not in old
patch.extend(difflib.unified_diff(current.splitlines(True),old.splitlines(True),fromfile='a/'+name,tofile='b/'+name))
for name,replacements in {
    'src/components/views/SystemGuardView.tsx':[
        ("import {NotificationEvidencePanel} from '../NotificationEvidencePanel';\n",''),
        ('      <NotificationEvidencePanel />\n','')],
    'package.json':[(' tests/notificationEvidence.test.tsx','')]
}.items():
    current=(ROOT/name).read_text(encoding='utf-8');old=current
    for before,after in replacements:
        assert before in old
        old=old.replace(before,after)
    patch.extend(difflib.unified_diff(current.splitlines(True),old.splitlines(True),fromfile='a/'+name,tofile='b/'+name))
rollback=release/'V1.59-E回退代码.patch'
rollback.write_bytes(''.join(patch).encode())
note=release/'V1.59-E阶段交付说明.md'
note.write_text('''# V1.59 E阶段交付

新增系统守护页的本机通知验收记录，分别留存前台接收和点击；不把两者当成锁屏展示或单向送达。修复原生回调早于React订阅时漏处理跳转的问题。最近300条记录可复制，不包含凭据或消息正文。

已通过通知记录/冷启动缓冲、四阶段消息集成、10项相关测试及TypeScript检查。网页构建、Capacitor同步和Gradle assembleDebug成功。首次默认JDK25与Gradle不兼容，最终使用项目JDK21构建。APK内容与dist逐文件核对通过。

versionName 1.59 / versionCode 159；签名与V1.58一致，使用项目既有debug签名。可覆盖安装，保留应用数据。服务器、研究等级和交易级开关未修改；本次未发送测试通知。

按用户选择，先交付安装包与验收表，所有手机实测保持待验收。新四阶段实际手机发送器仍未接入生产；本版展示能力及本机记录不能替代该链路。

## 回退资料

`V1.59-E回退代码.patch`仅还原本次通知缓冲/验收面板接入及测试命令，保留本地数据；新加文件会成为未引用文件，不删除它们。应用前先运行git apply --check并审阅，不能重置整个工作区。后续代码如已变化，必须重新核对补丁。

补丁故意不降低Android版本号。若需要发布回退包，应将当前版本再递增（下一版至少1.60/160），重新测试、构建并核验签名后覆盖安装。此处提供的是源码回退资料，不是已安装验证的回退APK；不要卸载APP来强行降级。
''',encoding='utf-8')
files=['src/services/notificationService.ts','src/services/notificationEvidence.ts',
    'src/components/NotificationEvidencePanel.tsx','src/components/views/SystemGuardView.tsx',
    'tests/notificationEvidence.test.tsx','android/app/build.gradle']
status=dict(versionName='1.59',versionCode=159,apkSha256=expected,apkBytes=apk.stat().st_size,
    signerSha256='72f972b0c7126b9b12eabb0047ead015934c87aedbd484831945f495b9de9998',
    signatureMatchesV158=True,signingType='EXISTING_DEBUG',apkAssetsMatchDist=True,
    phoneAcceptance='PENDING_USER_INSTALL_AND_DEVICE_TEST',backendModified=False,testPushesSent=0,
    newWaveSenderConnected=False,tradeTierEnabled=False,
    validation=['notificationEvidence assertions','waveIntegration assertions','10 related tests','tsc --noEmit','vite build','cap sync android','Gradle assembleDebug','APK version/signature/assets'],
    sources={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in files})
manifest=release/'V1.59-release-status.json'
manifest.write_text(json.dumps(status,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
target=release/'Crypto-G V1.59 E阶段交付包.zip'
with zipfile.ZipFile(target,'x',zipfile.ZIP_DEFLATED) as archive:
    for path in [apk,manifest,note,rollback,release/'E阶段-V1.59-三星S24+验收表.md']:
        archive.write(path,path.name)
print(json.dumps(dict(apk=str(apk),package=str(target),packageSha256=hashlib.sha256(target.read_bytes()).hexdigest()),ensure_ascii=True))
