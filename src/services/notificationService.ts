import { ingestMessage, focusMessage } from './inbox';
import { Capacitor } from '@capacitor/core';
import { PushNotifications, Channel } from '@capacitor/push-notifications';
import {refreshExitDevice} from './exitPush';

/**
 * Hybrid Notification service supporting:
 * 1. Native Android Firebase Cloud Messaging (via @capacitor/push-notifications)
 * 2. Web / PWA browser notifications (via standard Notification & ServiceWorker API)
 */
class NotificationService {
  public async clearDelivered() {
    if (Capacitor.isNativePlatform()) await PushNotifications.removeAllDeliveredNotifications();
  }
  private hasPermission: boolean = false;
  private isNative: boolean = false;
  private initialized = false;
  private deviceToken: string | null = null;
    public getDeviceToken() { return this.deviceToken; }
    public async refreshPermission():Promise<boolean> {
      if(this.isNative)this.hasPermission=(await PushNotifications.checkPermissions()).receive==='granted';
      return this.isGranted();
    }
  public async ensureDeviceToken():Promise<string> {
    if(!this.isNative)throw new Error('请在 Android APP 内绑定手机通知');
    await this.initNativePush();
    if(!await this.requestPermission())throw new Error('请在手机设置中允许 Crypto-G 发送通知');
    const until=Date.now()+10000;
    while(!this.deviceToken && Date.now()<until)await new Promise(resolve=>setTimeout(resolve,200));
    if(!this.deviceToken)throw new Error('推送注册尚未完成，请检查网络后重试绑定');
    return this.deviceToken;
  }

  constructor() {
    try {
      this.isNative = Capacitor.isNativePlatform();
      if (!this.isNative && typeof window !== 'undefined' && 'Notification' in window) {
        this.hasPermission = Notification.permission === 'granted';
      }
    } catch {
      this.isNative = false;
      this.hasPermission = false;
    }
  }

  public async initNativePush(): Promise<void> {
    if (!this.isNative || this.initialized) return;
    this.initialized = true;

    try {
      if (!Capacitor.isPluginAvailable('PushNotifications')) {
        return;
      }
      // 1. Create high-importance Android Notification Channel
      const highChannel: Channel = {
        id: 'shot_crypto_signals_v2',
        name: 'Crypto-G 买入候选',
        description: '高频量化雷达 BUY 买入极值信号推送',
        importance: 5, // High importance (heads-up notification)
        visibility: 1, // Public
        sound: 'default',
        vibration: true,
        lights: true,
        lightColor: '#10B981',
      };
      await PushNotifications.createChannel(highChannel);
      await PushNotifications.createChannel({...highChannel,id:'cryptog_position_exits_v1',name:'Crypto-G 持仓退出事件',description:'打开核对实际持仓退出记录；不代表已成交',visibility:0});

      // 2. Request permission
      let permStatus = await PushNotifications.checkPermissions();
      if (permStatus.receive === 'prompt') {
        permStatus = await PushNotifications.requestPermissions();
      }

      // 3. Register push listeners
      await PushNotifications.addListener('registration', (token) => {
        this.deviceToken=token.value;
        void refreshExitDevice(token.value).catch(()=>{ /* UI binding can be retried explicitly. */ });
      });

      await PushNotifications.addListener('registrationError', (error) => {
        console.error('>>> [FCM Registration Error]:', error);
      });

      await PushNotifications.addListener('pushNotificationReceived', (notification) => {
        const notif = notification || ({} as any);
        const data = notif.data || {};
        const title = notif.title || data.title || data.strategyNameZh || data.scenarioNameZh || '';
        const body = notif.body || data.body || data.summaryZh || data.message || data.reasonZh || '';
        ingestMessage({ ...data, title, body });
        if (this.signalCallback && data) {
          this.signalCallback(data, 'received');
        }
      });

      await PushNotifications.addListener('pushNotificationActionPerformed', (action) => {
        const notif = action?.notification || ({} as any);
        const data = notif.data || {};
        const title = notif.title || data.title || data.strategyNameZh || data.scenarioNameZh || '';
        const body = notif.body || data.body || data.summaryZh || data.message || data.reasonZh || '';
        const msgId = data.eventId || data.id || data.testId || data.deliveryId || notif.id || ('push_' + Date.now());
        ingestMessage({ ...data, id: msgId, title, body });
        focusMessage(String(msgId));
        if (this.signalCallback && data) {
          this.signalCallback(data, 'opened');
        }
      });
      if (permStatus.receive === 'granted') {
        this.hasPermission = true;
        await PushNotifications.register();
      }
    } catch (err) {
      this.initialized = false;
      console.warn('Native push initialization note:', err);
    }
  }

  private signalCallback: ((payload: any, origin?: 'received' | 'opened') => void) | null = null;

  public onSignalReceived(callback: (payload: any, origin?: 'received' | 'opened') => void) {
    this.signalCallback = callback;
    return () => { if (this.signalCallback === callback) this.signalCallback = null; };
  }

  public async requestPermission(): Promise<boolean> {
    if (this.isNative) {
      try {
        if (!Capacitor.isPluginAvailable('PushNotifications')) return false;
        const result = await PushNotifications.requestPermissions();
        this.hasPermission = result.receive === 'granted';
        if (this.hasPermission) {
          await PushNotifications.register();
        }
        return this.hasPermission;
      } catch {
        return false;
      }
    }

    if (typeof window === 'undefined' || !('Notification' in window)) {
      return false;
    }

    try {
      const permission = await Notification.requestPermission();
      this.hasPermission = permission === 'granted';
      return this.hasPermission;
    } catch {
      return false;
    }
  }

  public isGranted(): boolean {
    if (this.isNative) {
      return this.hasPermission;
    }
    if (typeof window === 'undefined' || !('Notification' in window)) {
      return false;
    }
    return Notification.permission === 'granted';
  }

  public sendPushNotification(title: string, body: string, icon = '/icon.svg') {
    if (typeof window === 'undefined') return;

    if (this.isNative) {
      // In native environment, remote FCM pushes from the server daemon handle background alerts.
      return;
    }

    if (Notification.permission === 'granted') {
      try {
        if ('serviceWorker' in navigator && navigator.serviceWorker.controller) {
          navigator.serviceWorker.ready.then((registration) => {
            registration.showNotification(title, {
              body,
              icon,
              badge: icon,
              tag: 'shot-crypto-signal',
              renotify: true,
            } as NotificationOptions);
          });
        } else {
          new Notification(title, {
            body,
            icon,
          });
        }
      } catch {
        // Fallback or permission blocked
      }
    }
  }
}

export const notificationService = new NotificationService();
