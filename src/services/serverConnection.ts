const KEY = 'cryptog_device_connection_v1';
export interface ServerConnection { url: string; token: string; cacheScope?: string }
export function validateConnection(value: ServerConnection): ServerConnection {
  const url = new URL(value.url);
  if (url.protocol !== 'https:' || url.username || url.password || url.search || url.hash || url.pathname !== '/') throw new Error('请填写可信 HTTPS 服务器地址，不含路径或查询参数');
  if (!/^[A-Za-z0-9_-]{32,256}$/.test(value.token)) throw new Error('请填写独立设备访问凭据');
  return {url:url.origin, token:value.token};
}
export function saveConnection(value: ServerConnection) {
  localStorage.setItem(KEY, JSON.stringify({...validateConnection(value), cacheScope: crypto.randomUUID()}));
}
export function connection(): ServerConnection {
  const raw = localStorage.getItem(KEY);
  if (!raw) throw new Error('尚未配置安全服务器连接；补录仍保存在本机');
  const saved = JSON.parse(raw);
  const valid = validateConnection(saved);
  const cacheScope = saved.cacheScope || crypto.randomUUID();
  if (!saved.cacheScope) {
    try { localStorage.setItem(KEY, JSON.stringify({...valid, cacheScope})); } catch {}
  }
  return {...valid, cacheScope};
}
export function clearConnection() { localStorage.removeItem(KEY); }

export function editedConnection(url:string, token:string):ServerConnection {
  if(token.trim())return validateConnection({url:url.trim(),token:token.trim()});
  const saved=connection();
  if(new URL(url.trim()).origin!==saved.url)throw new Error('更换服务器时请重新输入设备凭据');
  return validateConnection({url:url.trim(),token:saved.token});
}
