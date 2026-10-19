package com.lu.cryptogoolge;

import android.content.Context;
import android.content.SharedPreferences;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

/** Device-bound authenticated encryption. Never logs credentials or exception details. */
@CapacitorPlugin(name = "CredentialVault")
public class CredentialVaultPlugin extends Plugin {
    private static final String ALIAS = "cryptog_device_connection_v2";
    private SharedPreferences prefs() {
        return getContext().getSharedPreferences(ALIAS, Context.MODE_PRIVATE);
    }
    private SecretKey key() throws Exception {
        KeyStore store = KeyStore.getInstance("AndroidKeyStore");
        store.load(null);
        if (!store.containsAlias(ALIAS)) {
            KeyGenerator generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
            generator.init(new KeyGenParameterSpec.Builder(ALIAS,
                KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build());
            generator.generateKey();
        }
        return ((KeyStore.SecretKeyEntry) store.getEntry(ALIAS, null)).getSecretKey();
    }
    @PluginMethod public synchronized void get(PluginCall call) {
        try {
            String encrypted = prefs().getString("ciphertext", null);
            JSObject result = new JSObject();
            if (encrypted != null) {
                String iv = prefs().getString("iv", null);
                if (iv == null) throw new IllegalStateException();
                Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
                cipher.init(Cipher.DECRYPT_MODE, key(), new GCMParameterSpec(128, Base64.decode(iv, Base64.NO_WRAP)));
                result.put("value", new String(cipher.doFinal(Base64.decode(encrypted, Base64.NO_WRAP)), StandardCharsets.UTF_8));
            }
            call.resolve(result);
        } catch (Exception ignored) { call.reject("安全存储读取失败，请重新核对连接"); }
    }
    @PluginMethod public synchronized void set(PluginCall call) {
        try {
            String value = call.getString("value");
            if (value == null || value.length() > 8192) throw new IllegalArgumentException();
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.ENCRYPT_MODE, key());
            String encrypted = Base64.encodeToString(cipher.doFinal(value.getBytes(StandardCharsets.UTF_8)), Base64.NO_WRAP);
            if (!prefs().edit().putString("ciphertext", encrypted)
                    .putString("iv", Base64.encodeToString(cipher.getIV(), Base64.NO_WRAP)).commit()) throw new IllegalStateException();
            call.resolve();
        } catch (Exception ignored) { call.reject("安全存储写入失败，原连接未移除"); }
    }
    @PluginMethod public synchronized void clear(PluginCall call) {
        try {
            if (!prefs().edit().clear().commit()) throw new IllegalStateException();
            KeyStore store = KeyStore.getInstance("AndroidKeyStore"); store.load(null);
            if (store.containsAlias(ALIAS)) store.deleteEntry(ALIAS);
            call.resolve();
        } catch (Exception ignored) { call.reject("安全存储清除失败，请重试"); }
    }
}
