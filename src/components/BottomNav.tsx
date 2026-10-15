import React from 'react';
import { Radar, Bell, BookmarkCheck, Cpu, Server } from 'lucide-react';

export type TabType = 'radar' | 'signals' | 'watchlist' | 'strategy' | 'server';

interface BottomNavProps {
  activeTab: TabType;
  onChangeTab: (tab: TabType) => void;
  unreadSignalsCount: number;
}

export const BottomNav: React.FC<BottomNavProps> = ({
  activeTab,
  onChangeTab,
  unreadSignalsCount,
}) => {
  const tabs: { id: TabType; label: string; icon: React.ReactNode; badge?: number }[] = [
    {
      id: 'radar',
      label: '实时雷达',
      icon: <Radar className="w-5 h-5" />,
    },
    {
      id: 'signals',
      label: '预警买入',
      icon: <Bell className="w-5 h-5" />,
      badge: unreadSignalsCount,
    },
    {
      id: 'watchlist',
      label: '自选持仓',
      icon: <BookmarkCheck className="w-5 h-5" />,
    },
    {
      id: 'strategy',
      label: '量化模型',
      icon: <Cpu className="w-5 h-5" />,
    },
    {
      id: 'server',
      label: '云端守护',
      icon: <Server className="w-5 h-5" />,
    },
  ];

  return (
    <nav className="fixed bottom-0 left-0 right-0 z-40 bg-[#13161c]/98 backdrop-blur-xl border-t border-[#282d38] pb-safe select-none shadow-[0_-4px_16px_rgba(0,0,0,0.3)]">
      <div className="max-w-md mx-auto grid grid-cols-5 items-center h-16 px-1.5">
        {tabs.map((tab) => {
          const isActive = activeTab === tab.id;
          return (
            <button
              key={tab.id}
              onClick={() => onChangeTab(tab.id)}
              className="flex flex-col items-center justify-center py-1 transition-all group active:scale-95"
            >
              {/* Material 3 Active Pill Indicator */}
              <div
                className={`relative px-4 py-1 rounded-full transition-all flex items-center justify-center ${
                  isActive
                    ? 'bg-[#1a3258] text-[#8ab4f8] shadow-sm'
                    : 'text-[#9aa0a6] group-hover:text-[#e2e2e8]'
                }`}
              >
                {tab.icon}
                {tab.badge && tab.badge > 0 ? (
                  <span className="absolute -top-1 -right-1 px-1.5 py-0.2 bg-[#ea4335] text-white text-[10px] font-bold rounded-full min-w-[16px] text-center leading-tight shadow-sm">
                    {tab.badge > 9 ? '9+' : tab.badge}
                  </span>
                ) : null}
              </div>

              {/* Label */}
              <span
                className={`text-[10.5px] tracking-tight mt-0.5 font-medium transition-colors ${
                  isActive ? 'text-[#8ab4f8] font-bold' : 'text-[#9aa0a6]'
                }`}
              >
                {tab.label}
              </span>
            </button>
          );
        })}
      </div>
    </nav>
  );
};
