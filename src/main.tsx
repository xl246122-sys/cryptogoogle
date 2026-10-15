import React, { Component, ErrorInfo, ReactNode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App.tsx';
import './index.css';

interface ErrorBoundaryProps {
  children: ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

class RootErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('Unhandled Root Error caught by ErrorBoundary:', error, errorInfo);
  }

  handleReload = () => {
    window.location.reload();
  };

  render() {
    if (this.state.hasError) {
      return (
        <div style={{
          minHeight: '100vh',
          backgroundColor: '#0f1115',
          color: '#e2e2e8',
          padding: '24px',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          fontFamily: 'system-ui, -apple-system, sans-serif',
          textAlign: 'center',
          boxSizing: 'border-box'
        }}>
          <div style={{
            width: '56px',
            height: '56px',
            borderRadius: '16px',
            backgroundColor: 'rgba(242, 139, 130, 0.15)',
            border: '1px solid rgba(242, 139, 130, 0.4)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: '28px',
            marginBottom: '16px'
          }}>
            ⚠️
          </div>
          <h2 style={{ fontSize: '20px', fontWeight: 'bold', color: '#f28b82', margin: '0 0 8px 0' }}>
            Crypto-G 运行保护
          </h2>
          <p style={{ fontSize: '13px', color: '#9aa0a6', maxWidth: '360px', margin: '0 0 20px 0', lineHeight: 1.5 }}>
            组件渲染时捕获到异常。已为您拦截该异常，请点击下方按钮重新恢复加载。
          </p>
          <div style={{
            backgroundColor: '#1c2029',
            border: '1px solid #2b313f',
            borderRadius: '8px',
            padding: '12px',
            maxWidth: '90%',
            textAlign: 'left',
            marginBottom: '24px',
            maxHeight: '160px',
            overflowY: 'auto'
          }}>
            <code style={{ fontSize: '11px', color: '#f28b82', fontFamily: 'monospace', wordBreak: 'break-all' }}>
              {this.state.error?.toString()}
            </code>
          </div>
          <button
            onClick={this.handleReload}
            style={{
              padding: '10px 24px',
              backgroundColor: '#8ab4f8',
              color: '#0f1115',
              border: 'none',
              borderRadius: '9999px',
              fontWeight: 600,
              fontSize: '14px',
              cursor: 'pointer'
            }}
          >
            重新加载雷达
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}

const rootEl = document.getElementById('root');
if (rootEl) {
  createRoot(rootEl).render(
    <RootErrorBoundary>
      <App />
    </RootErrorBoundary>
  );
}
