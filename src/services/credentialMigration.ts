export interface CredentialVault { get():Promise<{value?:string}>; set(input:{value:string}):Promise<void>; clear():Promise<void> }
/** Delete legacy plaintext only after a persisted read-back succeeds. Preserve scope. */
export async function migrateCredential(storage:Pick<Storage,'getItem'|'removeItem'>, key:string,
  vault:CredentialVault, normalize:(raw:string)=>string):Promise<string|null> {
  const stored=(await vault.get()).value;
  if(stored!==undefined && stored!==null){
    const valid=normalize(stored);
    if(valid!==stored){await vault.set({value:valid});if((await vault.get()).value!==valid)throw new Error('安全存储核验失败');}
    storage.removeItem(key); return valid;
  }
  const legacy=storage.getItem(key);
  if(!legacy)return null;
  const normalized=normalize(legacy);
  await vault.set({value:normalized});
  if((await vault.get()).value!==normalized)throw new Error('安全存储核验失败，旧连接已保留');
  storage.removeItem(key);
  return normalized;
}
