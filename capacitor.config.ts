import type { CapacitorConfig } from '@capacitor/cli';

const config: CapacitorConfig = {
  appId: 'com.lu.cryptogoolge',
  appName: 'Crypto-G',
  webDir: 'dist',
  plugins: {
    PushNotifications: {
      presentationOptions: ['badge', 'sound', 'alert']
    }
  },
  server: {
    androidScheme: 'https',
    cleartext: false
  }
};

export default config;
