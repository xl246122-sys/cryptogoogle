import React, { useState } from 'react';
import { ServerConnectionPanel } from '../ServerConnectionPanel';
import { PositionMonitor } from '../PositionMonitor';
import {
  PYTHON_DAEMON_SCRIPT,
  SYSTEMD_SERVICE_FILE,
  UBUNTU_DEPLOY_GUIDE,
} from '../../services/exportService';
import {
  Server,
  Download,
  Copy,
  Check,
  Terminal,
  HardDrive,
  Zap,
} from 'lucide-react';

export const ServerDaemonView: React.FC = () => {
  const [activeCodeTab, setActiveCodeTab] = useState<'python' | 'service' | 'guide'>('python');
  const [copiedKey, setCopiedKey] = useState<string | null>(null);

  const handleCopy = (text: string, key: string) => {
    navigator.clipboard.writeText(text);
    setCopiedKey(key);
    setTimeout(() => setCopiedKey(null), 2000);
  };

  const handleDownload = (filename: string, content: string) => {
    const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-3 pb-20">
      <ServerConnectionPanel />
      <PositionMonitor />
      {/* Header */}
      <div className="px-1">
        <h2 className="text-sm font-semibold text-white flex items-center gap-1.5">
          <Server className="w-4 h-4 text-[#81c995]" />
          <span>腾讯云日本服务器 24/7 后台常驻守护</span>
        </h2>
        <p className="text-[10px] text-[#9aa0a6] mt-0.5">
          独立运行 Python 高频扫描引擎，结合 Firebase 消息推送直达 Android 手机，连接与推送状态需要实际监测
        </p>
      </div>

      {/* Target Infrastructure Summary */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        {/* Ubuntu Server Card */}
        <div className="p-3 rounded-2xl bg-[#1c2029] border border-[#2b313f] space-y-1.5">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1.5">
              <Server className="w-3.5 h-3.5 text-[#81c995]" />
              <span className="text-xs font-semibold text-white">云端生产服务器</span>
            </div>
            <span className="text-[10px] font-mono px-1.5 py-0.2 rounded-full bg-[#143820] text-[#81c995] border border-[#2a6831]/60">
              Ubuntu 26.04LTS
            </span>
          </div>

          <div className="text-[11px] font-mono text-[#c4c7c5] space-y-1 pt-1">
            <div className="flex justify-between">
              <span className="text-[#9aa0a6]">主机 IP:</span>
              <span className="text-[#fdd663] font-medium">43.163.203.127 (日本)</span>
            </div>
            <div className="flex justify-between">
              <span className="text-[#9aa0a6]">配置规格:</span>
              <span>以服务器实际配置为准</span>
            </div>
            <div className="flex justify-between">
              <span className="text-[#9aa0a6]">登录账号:</span>
              <span>ubuntu</span>
            </div>
            <div className="flex justify-between">
              <span className="text-[#9aa0a6]">带宽延迟:</span>
              <span>网络延迟需实际测量</span>
            </div>
          </div>
        </div>

        {/* Local Dev & Firebase Card */}
        <div className="p-3 rounded-2xl bg-[#1c2029] border border-[#2b313f] space-y-1.5">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1.5">
              <HardDrive className="w-3.5 h-3.5 text-[#8ab4f8]" />
              <span className="text-xs font-semibold text-white">本地环境与证书</span>
            </div>
            <span className="text-[10px] font-mono px-1.5 py-0.2 rounded-full bg-[#1a3258] text-[#8ab4f8] border border-[#3b6bb0]/60">
              Android 11
            </span>
          </div>

          <div className="text-[11px] font-mono text-[#c4c7c5] space-y-1 pt-1">
            <div className="flex justify-between">
              <span className="text-[#9aa0a6]">本地开发目录:</span>
              <span className="text-[#fdd663]">D:\Shot-Crypto</span>
            </div>
            <div className="flex justify-between">
              <span className="text-[#9aa0a6]">应用标识:</span>
              <span>shot-crypto</span>
            </div>
            <div className="flex justify-between">
              <span className="text-[#9aa0a6]">推送密钥:</span>
              <span className="text-[#81c995] truncate max-w-[140px]">
                stockscanner-ab380...json
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-[#9aa0a6]">常驻守护:</span>
              <span className="text-[#81c995]">Systemd 杀进程自动拉起</span>
            </div>
          </div>
        </div>
      </div>

      {/* 1-Click Export & Download Ribbon */}
      <div className="p-3 rounded-2xl bg-[#1c2029] border border-[#2b313f] flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="text-xs font-semibold text-white flex items-center gap-1.5">
            <Zap className="w-3.5 h-3.5 text-[#fdd663]" />
            <span>独立守护脚本包</span>
          </div>
          <div className="text-[10px] text-[#9aa0a6] mt-0.5">
            直接放入 D:\Shot-Crypto 或上传至云服务器运行
          </div>
        </div>

        <div className="flex items-center gap-1.5">
          <button
            onClick={() => handleDownload('shot_crypto_daemon.py', PYTHON_DAEMON_SCRIPT)}
            className="flex items-center gap-1 px-3 py-1.5 text-xs font-medium text-white bg-[#1a73e8] hover:bg-[#1558b0] rounded-full transition-all active:scale-95 shadow-sm"
          >
            <Download className="w-3.5 h-3.5" />
            <span>下载 Python 脚本</span>
          </button>

          <button
            onClick={() => handleDownload('shot-crypto.service', SYSTEMD_SERVICE_FILE)}
            className="flex items-center gap-1 px-3 py-1.5 text-xs font-medium text-[#c4c7c5] bg-[#232834] hover:bg-[#2b313f] border border-[#383e4c] rounded-full transition-all active:scale-95"
          >
            <Download className="w-3.5 h-3.5" />
            <span>Systemd 配置</span>
          </button>
        </div>
      </div>

      {/* Code Viewer & Deployment Tabs */}
      <div className="rounded-2xl bg-[#171a21] border border-[#282d38] overflow-hidden">
        {/* Tab Headers */}
        <div className="flex items-center justify-between p-2 bg-[#1c2029] border-b border-[#282d38]">
          <div className="flex items-center gap-1 overflow-x-auto pb-0.5">
            <button
              onClick={() => setActiveCodeTab('python')}
              className={`px-2.5 py-1 rounded-full text-[11px] font-medium transition-colors whitespace-nowrap ${
                activeCodeTab === 'python'
                  ? 'bg-[#1a3258] text-[#8ab4f8] font-semibold border border-[#3b6bb0]/60'
                  : 'text-[#9aa0a6] hover:text-white'
              }`}
            >
              daemon.py
            </button>
            <button
              onClick={() => setActiveCodeTab('service')}
              className={`px-2.5 py-1 rounded-full text-[11px] font-medium transition-colors whitespace-nowrap ${
                activeCodeTab === 'service'
                  ? 'bg-[#1a3258] text-[#8ab4f8] font-semibold border border-[#3b6bb0]/60'
                  : 'text-[#9aa0a6] hover:text-white'
              }`}
            >
              systemd.service
            </button>
            <button
              onClick={() => setActiveCodeTab('guide')}
              className={`px-2.5 py-1 rounded-full text-[11px] font-medium transition-colors whitespace-nowrap ${
                activeCodeTab === 'guide'
                  ? 'bg-[#1a3258] text-[#8ab4f8] font-semibold border border-[#3b6bb0]/60'
                  : 'text-[#9aa0a6] hover:text-white'
              }`}
            >
              Ubuntu 部署指令
            </button>
          </div>

          <button
            onClick={() => {
              const content =
                activeCodeTab === 'python'
                  ? PYTHON_DAEMON_SCRIPT
                  : activeCodeTab === 'service'
                  ? SYSTEMD_SERVICE_FILE
                  : UBUNTU_DEPLOY_GUIDE;
              handleCopy(content, activeCodeTab);
            }}
            className="flex items-center gap-1 px-2.5 py-1 text-[11px] font-medium text-[#8ab4f8] bg-[#232834] hover:bg-[#2b313f] rounded-full transition-colors border border-[#383e4c] shrink-0"
          >
            {copiedKey === activeCodeTab ? (
              <Check className="w-3.5 h-3.5 text-[#81c995]" />
            ) : (
              <Copy className="w-3.5 h-3.5" />
            )}
            <span>{copiedKey === activeCodeTab ? '已复制' : '复制全文'}</span>
          </button>
        </div>

        {/* Code Content */}
        <div className="p-3 overflow-x-auto max-h-[350px] font-mono text-[11px] text-[#c4c7c5] leading-relaxed">
          <pre className="whitespace-pre">
            {activeCodeTab === 'python' && PYTHON_DAEMON_SCRIPT}
            {activeCodeTab === 'service' && SYSTEMD_SERVICE_FILE}
            {activeCodeTab === 'guide' && UBUNTU_DEPLOY_GUIDE}
          </pre>
        </div>
      </div>
    </div>
  );
};
