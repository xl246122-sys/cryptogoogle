import {Capacitor,registerPlugin} from '@capacitor/core';
import {migrateCredential,type CredentialVault} from './credentialMigration';
const KEY = 'cryptog_device_connection_v1';
const vault=registerPlugin<CredentialVault>('CredentialVault');
let nativeSaved:ServerConnection|null=null;
let nativeReady=false;
let storageIssue='';
const native=()=>Capacitor.isNativePlatform();
function normalized(raw:string) {
  const saved=JSON.parse(raw);
  return JSON.stringify({...validateConnection(saved),cacheScope:typeof saved.cacheScope==='string' && saved.cacheScope?saved.cacheScope:crypto.randomUUID()});
}
export async function initializeConnectionStorage() {
  if(!native())return;
  try {
    const saved=await migrateCredential(localStorage,KEY,vault,normalized);
    nativeSaved=saved?JSON.parse(saved):null;nativeReady=true;storageIssue='';
  } catch {nativeReady=false;storageIssue='Android 安全存储未就绪，旧连接已保留；请重启后重试或重新核对设备连接。';}
}
export function credentialStorageStatus(){return native()?(storageIssue||'Android Keystore 加密保存'):'浏览器本地保存（非 Android 安全存储）';}
export interface ServerConnection { url: string; token: string; cacheScope?: string }
export function validateConnection(value: ServerConnection): ServerConnection {
  const url = new URL(value.url);
  if (url.protocol !== 'https:' || url.username || url.password || url.search || url.hash || url.pathname !== '/') throw new Error('请填写可信 HTTPS 服务器地址，不含路径或查询参数');
  if (!/^[A-Za-z0-9_-]{32,256}$/.test(value.token)) throw new Error('请填写独立设备访问凭据');
  return {url:url.origin, token:value.token};
}
export function saveConnection(value: ServerConnection) {
  const next={...validateConnection(value),cacheScope:crypto.randomUUID()};
  if(native())return (async()=>{
    const text=JSON.stringify(next);await vault.set({value:text});
    if((await vault.get()).value!==text)throw new Error('安全存储核验失败');
    localStorage.removeItem(KEY);nativeSaved=next;nativeReady=true;storageIssue='';
  })();
  localStorage.setItem(KEY, JSON.stringify(next));
}
export function connection(): ServerConnection {
  if(native()){
    if(!nativeReady)throw new Error(storageIssue||'等待安全存储初始化');
    if(!nativeSaved)throw new Error('尚未配置安全服务器连接；补录仍保存在本机');
    const cacheScope = nativeSaved.cacheScope || `native_${nativeSaved.url.replace(/[^a-zA-Z0-9]/g, '_')}`;
    return {...nativeSaved, cacheScope};
  }
  const raw = localStorage.getItem(KEY);
  if (!raw) throw new Error('尚未配置安全服务器连接；补录仍保存在本机');
  const saved = JSON.parse(raw);
  const valid = validateConnection(saved);
  const cacheScope = saved.cacheScope || `local_${valid.url.replace(/[^a-zA-Z0-9]/g, '_')}`;
  if (!saved.cacheScope) {
    try { localStorage.setItem(KEY, JSON.stringify({...valid, cacheScope})); } catch {}
  }
  return {...valid, cacheScope};
}
export function clearConnection() {
  if(native())return (async()=>{await vault.clear();if((await vault.get()).value)throw new Error('安全存储清除尚未确认');localStorage.removeItem(KEY);nativeSaved=null;})();
  localStorage.removeItem(KEY);
}

export function editedConnection(url:string, token:string):ServerConnection {
  if(token.trim())return validateConnection({url:url.trim(),token:token.trim()});
  const saved=connection();
  if(new URL(url.trim()).origin!==saved.url)throw new Error('更换服务器时请重新输入设备凭据');
  return validateConnection({url:url.trim(),token:saved.token});
}
