package com.lu.cryptogoolge;

import android.os.Bundle;
import android.webkit.WebView;
import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        registerPlugin(CredentialVaultPlugin.class);
        super.onCreate(savedInstanceState);
        try {
            WebView.setWebContentsDebuggingEnabled((getApplicationInfo().flags & android.content.pm.ApplicationInfo.FLAG_DEBUGGABLE) != 0);
        } catch (Exception ignored) {}
        try {
            Class<?> firebaseMessaging = Class.forName("com.google.firebase.messaging.FirebaseMessaging");
            Object instance = firebaseMessaging.getMethod("getInstance").invoke(null);
            firebaseMessaging.getMethod("subscribeToTopic", String.class).invoke(instance, "shot_crypto_signals");
        } catch (Throwable ignored) {}
    }
}
