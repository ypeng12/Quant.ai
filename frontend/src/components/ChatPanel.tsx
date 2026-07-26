// frontend/src/components/ChatPanel.tsx

import React, { useState, useRef, useEffect } from 'react';
import { API_BASE } from '../config';

interface ChatMessage {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: Date;
  strategyConfig?: Record<string, unknown>;
  executionPlan?: Array<{ step: number; tool: string; desc: string }>;
  riskReport?: RiskReport | null;
}

interface RiskReport {
  ticker: string;
  strategy: string;
  interval: string;
  risk_score: number;
  sections: Array<{
    title: string;
    icon: string;
    insights: string[];
    severity: string;
  }>;
}

interface ChatPanelProps {
  onRunBacktest: (config: Record<string, unknown>) => void;
  isLoading: boolean;
  activeTicker: string;
}

const EXAMPLE_PROMPTS = [
  "Backtest TSLA with dynamic routing strategy on daily bars",
  "Test NVDA with EMA crossover on 5-minute bars, ATR stop 1.5x",
  "Run mean reversion on SPY with RSI oversold at 10",
  "用日线回测 AAPL 的突破策略，ATR 止损 2.5 倍",
  "Compare Donchian breakout on AMD with 2x ATR trailing stop",
];

export const ChatPanel: React.FC<ChatPanelProps> = ({ onRunBacktest, isLoading, activeTicker }) => {
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: 'welcome',
      role: 'system',
      content: `Welcome to Quant.ai Research Agent. Describe your trading research in natural language — I'll parse it into a strategy config, run the backtest, and generate a risk analysis report.\n\nTry: "Backtest TSLA with dynamic routing strategy on daily bars"`,
      timestamp: new Date()
    }
  ]);
  const [input, setInput] = useState('');
  const [reportLoading, setReportLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSend = async () => {
    const trimmed = input.trim();
    if (!trimmed || isLoading) return;

    const userMsg: ChatMessage = {
      id: Date.now().toString(),
      role: 'user',
      content: trimmed,
      timestamp: new Date()
    };
    setMessages(prev => [...prev, userMsg]);
    setInput('');

    try {
      // Step 1: Parse prompt → strategy config
      const parseRes = await fetch(`${API_BASE}/api/agent/research`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: trimmed })
      });
      const parseData = await parseRes.json();

      if (!parseData.success) {
        setMessages(prev => [...prev, {
          id: Date.now().toString(),
          role: 'assistant',
          content: `❌ Failed to parse: ${parseData.error}`,
          timestamp: new Date()
        }]);
        return;
      }

      const config = parseData.strategy_config;
      const plan = parseData.execution_plan;

      // Step 2: Show parsed config and plan
      const configMsg: ChatMessage = {
        id: (Date.now() + 1).toString(),
        role: 'assistant',
        content: `**${parseData.parsed_intent}**\n\nI've parsed your request into the following configuration. Click "Run Backtest" to execute, or modify the parameters in the settings panel.`,
        timestamp: new Date(),
        strategyConfig: config,
        executionPlan: plan
      };
      setMessages(prev => [...prev, configMsg]);

      // Step 3: Auto-run backtest
      onRunBacktest(config);

      // Step 4: Generate risk report
      setReportLoading(true);
      try {
        const reportRes = await fetch(`${API_BASE}/api/report/generate`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(config)
        });
        const reportData = await reportRes.json();

        if (reportData.success && reportData.report) {
          const reportMsg: ChatMessage = {
            id: (Date.now() + 2).toString(),
            role: 'assistant',
            content: '',
            timestamp: new Date(),
            riskReport: reportData.report
          };
          setMessages(prev => [...prev, reportMsg]);
        }
      } catch {
        // Risk report is optional — backtest still succeeded
      } finally {
        setReportLoading(false);
      }

    } catch (e) {
      setMessages(prev => [...prev, {
        id: Date.now().toString(),
        role: 'assistant',
        content: `❌ Connection failed: ${e}. Make sure the backend is running on ${API_BASE}`,
        timestamp: new Date()
      }]);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const renderRiskScore = (score: number) => {
    const color = score >= 70 ? 'var(--color-green)' : score >= 40 ? '#f5a623' : 'var(--color-red)';
    const label = score >= 70 ? 'Low Risk' : score >= 40 ? 'Moderate Risk' : 'High Risk';
    return (
      <div className="risk-score-badge" style={{ borderColor: color }}>
        <div className="risk-score-value" style={{ color }}>{score}</div>
        <div className="risk-score-label" style={{ color }}>{label}</div>
      </div>
    );
  };

  return (
    <div className="chat-panel">
      <div className="chat-header">
        <div className="chat-header-title">
          <span className="chat-icon">🤖</span>
          <span>AI Research Agent</span>
        </div>
        <span className="chat-status">{isLoading || reportLoading ? '● Analyzing...' : '● Ready'}</span>
      </div>

      <div className="chat-messages">
        {messages.map(msg => (
          <div key={msg.id} className={`chat-msg chat-msg-${msg.role}`}>
            {msg.role === 'user' && (
              <div className="chat-msg-bubble chat-msg-user-bubble">
                {msg.content}
              </div>
            )}
            {msg.role === 'system' && (
              <div className="chat-msg-bubble chat-msg-system-bubble">
                {msg.content.split('\n').map((line, i) => (
                  <span key={i}>{line}<br /></span>
                ))}
              </div>
            )}
            {msg.role === 'assistant' && (
              <div className="chat-msg-bubble chat-msg-assistant-bubble">
                {msg.content && msg.content.split('\n').map((line, i) => (
                  <span key={i}>
                    {line.startsWith('**') && line.endsWith('**')
                      ? <strong>{line.replace(/\*\*/g, '')}</strong>
                      : line}
                    <br />
                  </span>
                ))}

                {msg.strategyConfig && (
                  <div className="chat-config-preview">
                    <div className="chat-config-title">📋 Strategy Configuration</div>
                    <div className="chat-config-grid">
                      {Object.entries(msg.strategyConfig).map(([key, val]) => (
                        <div key={key} className="chat-config-item">
                          <span className="chat-config-key">{key}</span>
                          <span className="chat-config-val">{String(val)}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {msg.executionPlan && (
                  <div className="chat-plan">
                    <div className="chat-config-title">🔧 Execution Plan</div>
                    {msg.executionPlan.map(step => (
                      <div key={step.step} className="chat-plan-step">
                        <span className="chat-plan-step-num">{step.step}</span>
                        <div>
                          <span className="chat-plan-tool">{step.tool}</span>
                          <span className="chat-plan-desc">{step.desc}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                )}

                {msg.riskReport && (
                  <div className="chat-risk-report">
                    <div className="chat-risk-header">
                      <div className="chat-config-title">📊 AI Risk Analysis Report</div>
                      {renderRiskScore(msg.riskReport.risk_score)}
                    </div>
                    {msg.riskReport.sections.map((section, i) => (
                      <div key={i} className={`chat-risk-section chat-risk-${section.severity}`}>
                        <div className="chat-risk-section-title">
                          {section.icon} {section.title}
                        </div>
                        <ul className="chat-risk-insights">
                          {section.insights.map((insight, j) => (
                            <li key={j} dangerouslySetInnerHTML={{
                              __html: insight
                                .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
                                .replace(/`(.*?)`/g, '<code>$1</code>')
                            }} />
                          ))}
                        </ul>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        ))}
        {(isLoading || reportLoading) && (
          <div className="chat-msg chat-msg-assistant">
            <div className="chat-msg-bubble chat-msg-assistant-bubble chat-typing">
              <span className="dot"></span>
              <span className="dot"></span>
              <span className="dot"></span>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Example prompts */}
      {messages.length <= 1 && (
        <div className="chat-examples">
          {EXAMPLE_PROMPTS.map((prompt, i) => (
            <button
              key={i}
              className="chat-example-btn"
              onClick={() => setInput(prompt)}
            >
              {prompt}
            </button>
          ))}
        </div>
      )}

      <div className="chat-input-area">
        <textarea
          className="chat-input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={`Describe your research goal... e.g. "Backtest ${activeTicker} with dynamic strategy on daily bars"`}
          rows={1}
          disabled={isLoading}
        />
        <button
          className="chat-send-btn"
          onClick={handleSend}
          disabled={!input.trim() || isLoading}
        >
          {isLoading ? '⏳' : '▶'}
        </button>
      </div>
    </div>
  );
};
