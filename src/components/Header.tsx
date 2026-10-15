import React from 'react';
import { Volume2, VolumeX, Zap, Download, Radio, ShieldCheck, Activity } from 'lucide-react';
interface HeaderProps {
  soundEnabled: boolean;
  onToggleSound: () => void;
  scanIntervalSec: number;
  onTriggerTestSignal: () => void;
  onOpenInstallModal: () => void;
  isInstallable: boolean;
}

export const Header: React.FC<HeaderProps> = ({
  soundEnabled,
  onToggleSound,
  scanIntervalSec,
  onTriggerTestSignal,
  onOpenInstallModal,
  isInstallable,
}) => {
  return (
    <header className="sticky top-0 z-30 flex items-center justify-between px-3.5 pt-safe pb-2.5 bg-[#13161c]/98 backdrop-blur-md border-b border-[#282d38] transition-all select-none shadow-sm">
      {/* Zone 1: Material 3 App Branding */}
      <div className="flex items-center gap-2.5 shrink-0">
        <div className="relative w-9 h-9 rounded-xl bg-gradient-to-br from-[#1a73e8] via-[#1557b0] to-[#0d3c7d] flex items-center justify-center shadow-[0_2px_8px_rgba(26,115,232,0.3)] text-white border border-[#4285f4]/30">
          {/* Subtle radar circle indicator */}
          <div className="absolute inset-0 rounded-xl border border-white/20 animate-pulse pointer-events-none" />
          <Zap className="w-4.5 h-4.5 fill-[#fbbc04] text-[#fbbc04] drop-shadow-sm" />
        </div>
        <div className="flex flex-col justify-center">
          <div className="flex items-center gap-1.5 leading-none">
            <span className="text-[16px] font-black tracking-tight text-white font-sans">
              Crypto-G
            </span>
            <span className="text-[9.5px] font-mono px-1.5 py-0.5 rounded-full bg-[#1e4620] text-[#81c995] font-semibold border border-[#2a6831]/60">
              BTC 量化雷达
            </span>
          </div>
          <span className="text-[10px] text-[#9aa0a6] mt-1 font-medium tracking-tight">
            BTC 超短线自适应 · 买入专属
          </span>
        </div>
      </div>

      {/* Zone 2: Engine Status & M3 Action Controls */}
      <div className="flex items-center gap-1.5 shrink-0">
        {/* Realtime Stream Ping Pill */}
        <div className="hidden xs:flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-[#1c2029] border border-[#2b313f] text-[11px] font-mono text-[#9aa0a6]">
          <span className="relative flex h-1.5 w-1.5">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-[#81c995] opacity-75"></span>
            <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-[#81c995]"></span>
          </span>
          <span>币安 {scanIntervalSec}s</span>
        </div>

        {/* Audio Alert Toggle Button (M3 Icon Toggle) */}
        <button
          onClick={onToggleSound}
          className={`h-8.5 w-8.5 rounded-full flex items-center justify-center transition-all active:scale-95 ${
            soundEnabled
              ? 'bg-[#143820] text-[#81c995] border border-[#2a6831] shadow-[0_0_10px_rgba(52,168,83,0.15)]'
              : 'bg-[#1c2029] text-[#9aa0a6] hover:text-white border border-[#282d38]'
          }`}
          title={soundEnabled ? '买入提示音已开启' : '静音模式'}
          aria-label="切换预警声音"
        >
          {soundEnabled ? <Volume2 className="w-4 h-4" /> : <VolumeX className="w-4 h-4" />}
        </button>

        {/* Test Signal Trigger Button (Google Blue Tonal Pill) */}
        <button
          onClick={onTriggerTestSignal}
          className="flex items-center gap-1 px-3 py-1.5 text-xs font-semibold text-[#8ab4f8] bg-[#1a3258] hover:bg-[#204070] active:scale-95 border border-[#3b6bb0]/60 rounded-full transition-all shadow-sm whitespace-nowrap"
          title="只试听提示音，不会生成买入信号"
        >
          <Zap className="w-3.5 h-3.5 text-[#8ab4f8] fill-[#8ab4f8]" />
          <span>试听</span>
        </button>

        {/* Optional Install APP Chip */}
        {isInstallable && (
          <button
            onClick={onOpenInstallModal}
            className="flex items-center gap-1 px-2.5 py-1.5 text-xs font-medium text-[#e2e2e8] bg-[#232834] hover:bg-[#2c3342] border border-[#383e4c] rounded-full transition-all active:scale-95"
            title="安装到桌面"
          >
            <Download className="w-3.5 h-3.5 text-[#81c995]" />
          </button>
        )}
      </div>
    </header>
  );
};
