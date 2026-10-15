import React from 'react';
import { Download, X, Smartphone, CheckCircle } from 'lucide-react';

interface PWAInstallModalProps {
  isOpen: boolean;
  onClose: () => void;
  onInstall: () => void;
  isInstallable: boolean;
}

export const PWAInstallModal: React.FC<PWAInstallModalProps> = ({
  isOpen,
  onClose,
  onInstall,
  isInstallable,
}) => {
  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center p-0 sm:p-4 bg-black/75 backdrop-blur-sm animate-fadeIn">
      <div className="w-full max-w-md bg-[#171a21] border border-[#2b313f] rounded-t-3xl sm:rounded-2xl p-4 space-y-3 shadow-2xl">
        {/* Top Sheet Drag Indicator */}
        <div className="pt-1 pb-1 flex justify-center sm:hidden">
          <div className="w-9 h-1 rounded-full bg-[#383e4c]"></div>
        </div>

        <div className="flex items-center justify-between pb-2 border-b border-[#282d38]">
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 rounded-lg bg-[#1a3258] text-[#8ab4f8] flex items-center justify-center">
              <Smartphone className="w-4 h-4" />
            </div>
            <h3 className="text-sm font-semibold text-white">
              安装 Crypto-G 到 Android 手机
            </h3>
          </div>
          <button
            onClick={onClose}
            className="w-7 h-7 rounded-full bg-[#232834] text-[#9aa0a6] hover:text-white flex items-center justify-center"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <p className="text-[11px] text-[#c4c7c5] leading-relaxed">
          安装后应用脱离浏览器全屏独立运行，支持常驻 Android 11 后台进程、极速音频警报与即时震动预警。
        </p>

        {isInstallable ? (
          <button
            onClick={() => {
              onInstall();
              onClose();
            }}
            className="w-full py-2.5 rounded-full bg-[#1a73e8] hover:bg-[#1558b0] text-white font-medium text-xs shadow-md transition-all flex items-center justify-center gap-1.5"
          >
            <Download className="w-4 h-4" />
            <span>立即添加到 Android 桌面</span>
          </button>
        ) : (
          <div className="p-3 rounded-xl bg-[#1c2029] border border-[#282d38] space-y-1.5 text-[11px] text-[#c4c7c5]">
            <div className="font-medium text-[#fdd663]">
              Android Chrome 添加指引：
            </div>
            <div className="flex items-start gap-1.5 text-[#9aa0a6]">
              <span className="font-mono text-[#8ab4f8]">1.</span>
              <span>点击 Chrome 浏览器右上角三个点菜单 <strong>(⋮)</strong></span>
            </div>
            <div className="flex items-start gap-1.5 text-[#9aa0a6]">
              <span className="font-mono text-[#8ab4f8]">2.</span>
              <span>选择 <strong>“安装应用”</strong> 或 <strong>“添加到主屏幕”</strong></span>
            </div>
            <div className="flex items-start gap-1.5 text-[#9aa0a6]">
              <span className="font-mono text-[#8ab4f8]">3.</span>
              <span>Crypto-G 将作为原生独立 APP 运行在手机中</span>
            </div>
          </div>
        )}

        <div className="pt-1 flex justify-end">
          <button
            onClick={onClose}
            className="px-3 py-1 text-xs text-[#9aa0a6] hover:text-white"
          >
            关闭
          </button>
        </div>
      </div>
    </div>
  );
};
