import React, { Component } from 'react';
import type { ErrorInfo, ReactNode } from 'react';

interface Props {
  children: ReactNode;
  fallbackTitle?: string;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  public state: State = {
    hasError: false,
    error: null,
  };

  public static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  public componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('Uncaught error inside component:', error, errorInfo);
  }

  public render() {
    if (this.state.hasError) {
      return (
        <div style={{
          padding: '2rem',
          margin: '1.5rem',
          background: 'rgba(255, 59, 48, 0.08)',
          border: '1px solid rgba(255, 59, 48, 0.3)',
          borderRadius: '12px',
          color: '#f87171'
        }}>
          <h3 style={{ margin: '0 0 0.5rem 0', color: '#ff4d4f', fontSize: '1.1rem' }}>
            ⚠️ {this.props.fallbackTitle || '模块加载异常 / Module failed to load'}
          </h3>
          <p style={{ margin: '0 0 1rem 0', fontSize: '0.85rem', color: '#ccc' }}>
            {this.state.error?.message || '组件渲染遇到未预期的数据异常，已阻止整屏崩溃。 / Unexpected data prevented this panel from rendering; the rest of the page remains available.'}
          </p>
          <button
            onClick={() => this.setState({ hasError: false, error: null })}
            style={{
              background: '#2563eb',
              color: '#fff',
              border: 'none',
              padding: '6px 14px',
              borderRadius: '6px',
              fontSize: '0.8rem',
              fontWeight: 600,
              cursor: 'pointer'
            }}
          >
            重试加载 / Retry
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}
