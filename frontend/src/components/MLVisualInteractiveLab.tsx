import React, { useState, useEffect, useRef } from 'react';

interface MLCardProps {
  title: string;
  subtitle: string;
  tags: string[];
  description: string;
  children: React.ReactNode;
}

const MLCard: React.FC<MLCardProps> = ({ title, subtitle, tags, description, children }) => {
  return (
    <div style={{
      background: '#0f172a',
      border: '1px solid rgba(255, 255, 255, 0.1)',
      borderRadius: '12px',
      padding: '16px',
      display: 'flex',
      flexDirection: 'column',
      boxShadow: '0 8px 24px rgba(0,0,0,0.3)',
      transition: 'all 0.2s ease',
    }}>
      {/* Visual Canvas Area */}
      <div style={{
        background: '#020617',
        borderRadius: '8px',
        border: '1px solid rgba(255, 255, 255, 0.05)',
        minHeight: '220px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        overflow: 'hidden',
        position: 'relative'
      }}>
        {children}
      </div>

      {/* Info Header */}
      <div style={{ marginTop: '14px' }}>
        <h3 style={{ margin: '0 0 4px 0', fontSize: '1.1rem', fontWeight: 800, color: '#f8fafc' }}>
          {title}
        </h3>
        <p style={{ margin: '0 0 10px 0', fontSize: '0.8rem', color: '#94a3b8', lineHeight: '1.4' }}>
          {subtitle}
        </p>
        <div style={{ fontSize: '0.75rem', color: '#cbd5e1', background: 'rgba(255,255,255,0.03)', padding: '8px', borderRadius: '6px', marginBottom: '12px', borderLeft: '3px solid #38bdf8' }}>
          {description}
        </div>

        {/* Tags */}
        <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
          {tags.map((tag, idx) => (
            <span
              key={idx}
              style={{
                fontSize: '0.68rem',
                fontWeight: 700,
                padding: '2px 8px',
                borderRadius: '4px',
                background: idx === 0 ? 'rgba(239, 68, 68, 0.15)' : idx === 1 ? 'rgba(59, 130, 246, 0.15)' : 'rgba(168, 85, 247, 0.15)',
                color: idx === 0 ? '#f87171' : idx === 1 ? '#60a5fa' : '#c084fc',
                border: '1px solid rgba(255,255,255,0.08)'
              }}
            >
              {tag}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
};

export const MLVisualInteractiveLab: React.FC = () => {
  const [epoch, setEpoch] = useState<number>(25);
  const [learningRate, setLearningRate] = useState<number>(0.05);
  const [selectedOptimizer, setSelectedOptimizer] = useState<'Adam' | 'SGD' | 'RMSprop'>('Adam');
  const [kClusters, setKClusters] = useState<number>(3);
  const [activeLayer, setActiveLayer] = useState<number>(2);

  // Auto animation for interactive demo
  useEffect(() => {
    const interval = setInterval(() => {
      setEpoch((prev) => (prev >= 100 ? 1 : prev + 1));
    }, 150);
    return () => clearInterval(interval);
  }, []);

  return (
    <div style={{ padding: '24px', background: '#090d16', color: '#f8fafc', minHeight: '100vh', fontFamily: 'Inter, system-ui, sans-serif' }}>
      {/* Top Banner */}
      <div style={{
        background: 'linear-gradient(135deg, rgba(30, 41, 59, 0.8) 0%, rgba(15, 23, 42, 0.95) 100%)',
        border: '1px solid rgba(56, 189, 248, 0.25)',
        borderRadius: '16px',
        padding: '24px',
        marginBottom: '28px',
        boxShadow: '0 12px 32px rgba(0,0,0,0.4)',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        flexWrap: 'wrap',
        gap: '16px'
      }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '8px' }}>
            <span style={{ fontSize: '1.8rem' }}>🧠</span>
            <h1 style={{ margin: 0, fontSize: '1.6rem', fontWeight: 900, color: '#f8fafc', letterSpacing: '-0.02em' }}>
              Quant.ai 机器学习全景可视化实验室 (ML Visual Interactive Lab)
            </h1>
          </div>
          <p style={{ margin: 0, fontSize: '0.9rem', color: '#94a3b8', maxWidth: '800px', lineHeight: '1.5' }}>
            将抽象的数学公式与黑盒模型转化为<strong>直观、生动、可交互的 2D/3D 几何演化图景</strong>。亲眼见证模型如何从杂乱无章的盘口噪声中学习出清晰的盈利决策边界！
          </p>
        </div>

        {/* Global Control Widget */}
        <div style={{
          display: 'flex',
          gap: '14px',
          alignItems: 'center',
          background: '#020617',
          padding: '12px 18px',
          borderRadius: '10px',
          border: '1px solid rgba(255,255,255,0.1)'
        }}>
          <div>
            <div style={{ fontSize: '0.7rem', color: '#94a3b8', fontWeight: 700 }}>动态训练迭代 (Epoch)</div>
            <div style={{ fontSize: '1.2rem', fontWeight: 900, color: '#38bdf8' }}>#{epoch} / 100</div>
          </div>
          <button
            onClick={() => setEpoch(1)}
            style={{
              background: '#2563eb',
              color: '#fff',
              border: 'none',
              padding: '6px 12px',
              borderRadius: '6px',
              fontSize: '0.75rem',
              fontWeight: 700,
              cursor: 'pointer'
            }}
          >
            🔄 重置训练
          </button>
        </div>
      </div>

      {/* Grid of ML Visualizations (Matching User Reference Image) */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(360px, 1fr))',
        gap: '24px'
      }}>

        {/* 1. Deep Neural Network */}
        <MLCard
          title="Deep Neural Network (深度神经网络)"
          subtitle="Implementation and visualization of universal function approximator"
          tags={['Python', 'NumPy', 'Matplotlib']}
          description="量化应用：用于拟合多资产复杂微观结构非线性映射，逼近真实市场分布。"
        >
          <svg width="100%" height="220" viewBox="0 0 320 200">
            {/* Left: MSE Error Curve */}
            <g transform="translate(20, 20)">
              <text x="0" y="0" fill="#94a3b8" fontSize="8" fontWeight="700">Mean Squared Error (MSE)</text>
              <line x1="0" y1="140" x2="110" y2="140" stroke="#334155" strokeWidth="1" />
              <line x1="0" y1="10" x2="0" y2="140" stroke="#334155" strokeWidth="1" />
              <path
                d={`M 0,20 Q 30,${60 + (100 - epoch) * 0.5} 110,${130 - epoch * 0.1}`}
                fill="none"
                stroke="#ef4444"
                strokeWidth="2"
              />
              <circle cx={Math.min(110, epoch * 1.1)} cy={Math.max(20, 130 - epoch * 0.8)} r="3" fill="#ef4444" />
              <text x="50" y="152" fill="#64748b" fontSize="7">Epoch</text>
            </g>

            {/* Right: 3D Surface Approximation */}
            <g transform="translate(160, 20)">
              <text x="10" y="0" fill="#94a3b8" fontSize="8" fontWeight="700">3D Function Approximation</text>
              {/* Wireframe surface */}
              {[-30, -15, 0, 15, 30].map((offset, i) => (
                <path
                  key={i}
                  d={`M ${30 + offset},${90 + i * 8} Q ${75 + offset},${40 + Math.sin((epoch + i) * 0.2) * 15} ${120 + offset},${100 + i * 8}`}
                  fill="none"
                  stroke={i % 2 === 0 ? '#38bdf8' : '#a855f7'}
                  strokeWidth="1.5"
                  opacity={0.7}
                />
              ))}
              <circle cx="75" cy={55 + Math.sin(epoch * 0.2) * 10} r="4" fill="#22c55e" />
              <text x="85" y={58 + Math.sin(epoch * 0.2) * 10} fill="#22c55e" fontSize="7" fontWeight="700">w* Optimal</text>
            </g>
          </svg>
        </MLCard>

        {/* 2. Backpropagation & Gradient Descent */}
        <MLCard
          title="Backpropagation (反向传播与梯度下降)"
          subtitle="Optimization of neural network weights with gradient descent"
          tags={['Python', 'NumPy', 'Matplotlib']}
          description="量化应用：通过链式法则将盘口预测误差反向传播，秒级校正因子权重。"
        >
          <svg width="100%" height="220" viewBox="0 0 320 200">
            {/* 3D Loss Bowl */}
            <g transform="translate(40, 20)">
              <text x="50" y="0" fill="#94a3b8" fontSize="8" fontWeight="700">3D Loss Bowl L(w₁, w₂)</text>
              {/* Elliptical Contours of Loss Basin */}
              <ellipse cx="120" cy="85" rx="90" ry="45" fill="none" stroke="#1e293b" strokeWidth="1.5" />
              <ellipse cx="120" cy="85" rx="65" ry="32" fill="none" stroke="#334155" strokeWidth="1.5" />
              <ellipse cx="120" cy="85" rx="40" ry="20" fill="none" stroke="#475569" strokeWidth="1.5" />
              <ellipse cx="120" cy="85" rx="18" ry="9" fill="rgba(34, 197, 94, 0.15)" stroke="#22c55e" strokeWidth="1.5" />

              {/* Gradient Descent Step Path */}
              <path
                d={`M 40,55 Q ${70 + epoch * 0.4},${65 + epoch * 0.1} ${120 - Math.max(0, 30 - epoch * 0.5)},${85 - Math.max(0, 15 - epoch * 0.25)}`}
                fill="none"
                stroke="#f59e0b"
                strokeWidth="2"
                strokeDasharray="3,3"
              />
              <circle
                cx={Math.min(120, 40 + epoch * 0.8)}
                cy={Math.min(85, 55 + epoch * 0.3)}
                r="4"
                fill="#ef4444"
              />
              <text x="120" y="90" fill="#22c55e" fontSize="7" fontWeight="900" textAnchor="middle">MIN</text>
            </g>
          </svg>
        </MLCard>

        {/* 3. Neural Network Transforms (Latent Space) */}
        <MLCard
          title="Neural Network Transforms (隐层空间投影变换)"
          subtitle="Visualization of neural network internal transformations"
          tags={['Python', 'NumPy', 'Matplotlib']}
          description="量化应用：将线性不可分的混乱行情，在多层隐空间投影为清晰的多空两类。"
        >
          <div style={{ display: 'flex', width: '100%', height: '200px', padding: '10px', gap: '8px' }}>
            {/* Layer 0: Entangled */}
            <div style={{ flex: 1, background: '#0f172a', borderRadius: '6px', padding: '6px', border: '1px solid rgba(255,255,255,0.05)', textAlign: 'center' }}>
              <div style={{ fontSize: '0.65rem', color: '#94a3b8', fontWeight: 700 }}>Layer 0 (原始盘口)</div>
              <svg width="100%" height="130" viewBox="0 0 100 100">
                {/* Randomly mixed red and blue dots */}
                {[...Array(15)].map((_, i) => (
                  <circle key={`r${i}`} cx={20 + (i * 17) % 65} cy={20 + (i * 23) % 65} r="2.5" fill="#ef4444" />
                ))}
                {[...Array(15)].map((_, i) => (
                  <circle key={`b${i}`} cx={30 + (i * 19) % 60} cy={25 + (i * 29) % 60} r="2.5" fill="#3b82f6" />
                ))}
              </svg>
              <div style={{ fontSize: '0.6rem', color: '#ef4444' }}>❌ 线性不可分 (混沌)</div>
            </div>

            {/* Layer 2: Separated */}
            <div style={{ flex: 1, background: '#0f172a', borderRadius: '6px', padding: '6px', border: '1px solid rgba(34, 197, 94, 0.3)', textAlign: 'center' }}>
              <div style={{ fontSize: '0.65rem', color: '#22c55e', fontWeight: 700 }}>Layer 2 (ML 隐空间)</div>
              <svg width="100%" height="130" viewBox="0 0 100 100">
                {/* Cleanly separated clusters */}
                <line x1="10" y1="90" x2="90" y2="10" stroke="#f59e0b" strokeWidth="1.5" strokeDasharray="2,2" />
                {[...Array(15)].map((_, i) => (
                  <circle key={`r${i}`} cx={20 + (i * 5) % 30} cy={20 + (i * 7) % 30} r="2.5" fill="#ef4444" />
                ))}
                {[...Array(15)].map((_, i) => (
                  <circle key={`b${i}`} cx={60 + (i * 5) % 30} cy={60 + (i * 7) % 30} r="2.5" fill="#3b82f6" />
                ))}
              </svg>
              <div style={{ fontSize: '0.6rem', color: '#22c55e' }}>✅ 完美线性可分 (清晰)</div>
            </div>
          </div>
        </MLCard>

        {/* 4. Logistic Regression & Classification Boundary */}
        <MLCard
          title="Logistic Regression (逻辑回归与 Sigmoid 概率)"
          subtitle="Binary classification using maximum likelihood estimation"
          tags={['Python', 'NumPy', 'Matplotlib']}
          description="量化应用：LightGBM 与概率引擎通过 Sigmoid 将特征得分校准为真实胜率 P_win。"
        >
          <svg width="100%" height="220" viewBox="0 0 320 200">
            {/* Left: Cross Entropy Loss */}
            <g transform="translate(20, 20)">
              <text x="0" y="0" fill="#94a3b8" fontSize="8" fontWeight="700">Binary Cross Entropy</text>
              <line x1="0" y1="140" x2="100" y2="140" stroke="#334155" strokeWidth="1" />
              <line x1="0" y1="10" x2="0" y2="140" stroke="#334155" strokeWidth="1" />
              <path d="M 5,20 Q 20,80 100,135" fill="none" stroke="#ef4444" strokeWidth="2" />
              <text x="40" y="152" fill="#64748b" fontSize="7">Iterations</text>
            </g>

            {/* Right: S-Curve Probability */}
            <g transform="translate(150, 20)">
              <text x="20" y="0" fill="#94a3b8" fontSize="8" fontWeight="700">Prediction Probabilities (P_win)</text>
              <line x1="10" y1="140" x2="150" y2="140" stroke="#334155" strokeWidth="1" />
              <line x1="80" y1="10" x2="80" y2="140" stroke="#475569" strokeWidth="1" strokeDasharray="2,2" />

              {/* Sigmoid S-Curve */}
              <path
                d="M 10,130 C 50,130 65,130 80,75 C 95,20 110,20 150,20"
                fill="none"
                stroke="#38bdf8"
                strokeWidth="2.5"
              />

              {/* Trade Points */}
              <circle cx="40" cy="130" r="3" fill="#ef4444" />
              <circle cx="55" cy="128" r="3" fill="#ef4444" />
              <circle cx="115" cy="22" r="3" fill="#22c55e" />
              <circle cx="135" cy="20" r="3" fill="#22c55e" />

              <text x="80" y="152" fill="#f59e0b" fontSize="7" textAnchor="middle">门槛 P=50%</text>
            </g>
          </svg>
        </MLCard>

        {/* 5. Perceptron & Hyperplane Decision Boundary */}
        <MLCard
          title="Perceptron (感知机超平面决策边界)"
          subtitle="Linear model using hyperplane decision boundary"
          tags={['Python', 'NumPy', 'Matplotlib']}
          description="量化应用：在 OFI（订单流）与微观拉升速度空间切分多空决策超平面。"
        >
          <svg width="100%" height="220" viewBox="0 0 320 200">
            <g transform="translate(30, 20)">
              {/* Feature Space X1 (OFI) vs X2 (Micro Velocity) */}
              <line x1="20" y1="140" x2="260" y2="140" stroke="#334155" strokeWidth="1" />
              <line x1="20" y1="10" x2="20" y2="140" stroke="#334155" strokeWidth="1" />
              <text x="220" y="155" fill="#64748b" fontSize="8">X₁: 订单流失衡 (OFI)</text>
              <text x="0" y="10" fill="#64748b" fontSize="8" transform="rotate(-90 10,20)">X₂: 微观拉升速度</text>

              {/* Dynamic Hyperplane w·x + b = 0 */}
              <line
                x1="40"
                y1={130 - Math.min(100, epoch)}
                x2="240"
                y2={30 + Math.max(0, 100 - epoch) * 0.5}
                stroke="#f59e0b"
                strokeWidth="2.5"
              />

              {/* Short Zone (Red Points) */}
              <circle cx="60" cy="110" r="3.5" fill="#ef4444" />
              <circle cx="90" cy="120" r="3.5" fill="#ef4444" />
              <circle cx="50" cy="80" r="3.5" fill="#ef4444" />
              <text x="60" y="130" fill="#ef4444" fontSize="7" fontWeight="700">做空区 (SHORT)</text>

              {/* Long Zone (Green Points) */}
              <circle cx="180" cy="40" r="3.5" fill="#22c55e" />
              <circle cx="210" cy="50" r="3.5" fill="#22c55e" />
              <circle cx="190" cy="70" r="3.5" fill="#22c55e" />
              <text x="180" y="30" fill="#22c55e" fontSize="7" fontWeight="700">做多区 (LONG)</text>
            </g>
          </svg>
        </MLCard>

        {/* 6. PCA (Principal Component Analysis) */}
        <MLCard
          title="PCA (主成分分析降维)"
          subtitle="Linear dimensionality reduction to capture variance"
          tags={['Python', 'NumPy', 'Matplotlib']}
          description="量化应用：从数十个高相关性市场指标中提取出最大方差的第一、第二主成分因子。"
        >
          <svg width="100%" height="220" viewBox="0 0 320 200">
            {/* 3D Point Cloud on Left */}
            <g transform="translate(20, 20)">
              <text x="10" y="0" fill="#94a3b8" fontSize="8" fontWeight="700">3D 多重因子空间</text>
              <polygon points="20,130 110,140 130,90 40,80" fill="rgba(56, 189, 248, 0.05)" stroke="#334155" />
              {[...Array(20)].map((_, i) => (
                <circle key={i} cx={45 + (i * 13) % 60} cy={95 + (i * 17) % 35} r="2.5" fill="#38bdf8" />
              ))}
              <line x1="30" y1="120" x2="115" y2="90" stroke="#f59e0b" strokeWidth="2" />
              <text x="100" y="85" fill="#f59e0b" fontSize="7" fontWeight="700">PC1 (82% Var)</text>
            </g>

            {/* Projected 2D Subspace on Right */}
            <g transform="translate(170, 20)">
              <text x="10" y="0" fill="#94a3b8" fontSize="8" fontWeight="700">2D 正交主成分投影</text>
              <line x1="20" y1="80" x2="130" y2="80" stroke="#475569" strokeWidth="1" />
              <line x1="75" y1="20" x2="75" y2="140" stroke="#475569" strokeWidth="1" />
              {[...Array(20)].map((_, i) => (
                <circle key={i} cx={35 + (i * 13) % 80} cy={40 + (i * 17) % 80} r="2.5" fill="#a855f7" />
              ))}
              <text x="110" y="92" fill="#64748b" fontSize="7">PC1</text>
              <text x="80" y="28" fill="#64748b" fontSize="7">PC2</text>
            </g>
          </svg>
        </MLCard>

        {/* 7. K-Means Clustering & Market Regimes */}
        <MLCard
          title="K-Means Clustering (无监督聚类与市场体制)"
          subtitle="Implementation of unsupervised clustering algorithm"
          tags={['Python', 'NumPy', 'Matplotlib']}
          description="量化应用：Stage-1 市场体制分类器将盘面自适应聚类为单边牛市、震荡箱体、恐慌暴跌。"
        >
          <svg width="100%" height="220" viewBox="0 0 320 200">
            {/* Left: Elbow Method */}
            <g transform="translate(15, 20)">
              <text x="0" y="0" fill="#94a3b8" fontSize="8" fontWeight="700">Elbow Method (K-Selection)</text>
              <line x1="0" y1="140" x2="90" y2="140" stroke="#334155" strokeWidth="1" />
              <line x1="0" y1="10" x2="0" y2="140" stroke="#334155" strokeWidth="1" />
              <path d="M 5,20 Q 25,110 90,130" fill="none" stroke="#ef4444" strokeWidth="2" />
              <circle cx="28" cy="110" r="3.5" fill="#f59e0b" />
              <text x="32" y="105" fill="#f59e0b" fontSize="7" fontWeight="700">K=3 最佳</text>
            </g>

            {/* Right: 3 Voronoi Cluster Regions */}
            <g transform="translate(130, 20)">
              <text x="15" y="0" fill="#94a3b8" fontSize="8" fontWeight="700">Regime Voronoi Clusters</text>

              {/* Cluster 1: Trend Bull */}
              <polygon points="10,10 90,10 60,70 10,70" fill="rgba(34, 197, 94, 0.1)" stroke="rgba(34, 197, 94, 0.3)" />
              <circle cx="45" cy="35" r="4" fill="#22c55e" />
              <text x="30" y="50" fill="#22c55e" fontSize="6.5" fontWeight="700">牛市主升 (Bull)</text>

              {/* Cluster 2: Chop Range */}
              <polygon points="90,10 170,10 170,80 60,70" fill="rgba(245, 158, 11, 0.1)" stroke="rgba(245, 158, 11, 0.3)" />
              <circle cx="120" cy="40" r="4" fill="#f59e0b" />
              <text x="105" y="55" fill="#f59e0b" fontSize="6.5" fontWeight="700">震荡箱体 (Chop)</text>

              {/* Cluster 3: Panic Crash */}
              <polygon points="10,70 170,80 170,140 10,140" fill="rgba(239, 68, 68, 0.1)" stroke="rgba(239, 68, 68, 0.3)" />
              <circle cx="85" cy="110" r="4" fill="#ef4444" />
              <text x="70" y="125" fill="#ef4444" fontSize="6.5" fontWeight="700">恐慌跳水 (Panic)</text>
            </g>
          </svg>
        </MLCard>

        {/* 8. Optimizers Trajectory Comparison */}
        <MLCard
          title="Optimizers (优化器收敛轨迹对比)"
          subtitle="Optimization algorithms to find global minima"
          tags={['Python', 'NumPy', 'Matplotlib']}
          description="量化应用：对比 Adam、SGD、RMSprop 在复杂非凸损失曲面上的逃离鞍点与收敛速度。"
        >
          <svg width="100%" height="220" viewBox="0 0 320 200">
            {/* Left: Loss vs Epoch */}
            <g transform="translate(20, 20)">
              <text x="0" y="0" fill="#94a3b8" fontSize="8" fontWeight="700">Convergence Curves</text>
              <line x1="0" y1="140" x2="100" y2="140" stroke="#334155" strokeWidth="1" />
              <line x1="0" y1="10" x2="0" y2="140" stroke="#334155" strokeWidth="1" />

              {/* SGD (Slow) */}
              <path d="M 5,25 Q 30,50 100,100" fill="none" stroke="#60a5fa" strokeWidth="1.5" />
              <text x="70" y="95" fill="#60a5fa" fontSize="6">SGD</text>

              {/* RMSprop (Medium) */}
              <path d="M 5,25 Q 30,90 100,120" fill="none" stroke="#c084fc" strokeWidth="1.5" />
              <text x="70" y="115" fill="#c084fc" fontSize="6">RMSprop</text>

              {/* Adam (Fastest) */}
              <path d="M 5,25 Q 20,120 100,135" fill="none" stroke="#22c55e" strokeWidth="2" />
              <text x="70" y="138" fill="#22c55e" fontSize="6" fontWeight="700">Adam (最优)</text>
            </g>

            {/* Right: 2D Contour Optimization Path */}
            <g transform="translate(150, 20)">
              <text x="10" y="0" fill="#94a3b8" fontSize="8" fontWeight="700">Loss Contour Optimization Path</text>
              <ellipse cx="80" cy="80" rx="65" ry="45" fill="none" stroke="#1e293b" />
              <ellipse cx="80" cy="80" rx="40" ry="25" fill="none" stroke="#334155" />
              <ellipse cx="80" cy="80" rx="15" ry="10" fill="none" stroke="#475569" />

              {/* SGD Oscillations */}
              <path d="M 30,30 L 45,50 L 50,40 L 65,70" fill="none" stroke="#60a5fa" strokeWidth="1" strokeDasharray="1,1" />

              {/* Adam Smooth Trajectory */}
              <path
                d={`M 30,30 Q ${50 + Math.min(20, epoch * 0.3)},${60 + Math.min(15, epoch * 0.2)} 80,80`}
                fill="none"
                stroke="#22c55e"
                strokeWidth="2"
              />
              <circle cx="80" cy="80" r="3.5" fill="#22c55e" />
              <text x="80" y="93" fill="#22c55e" fontSize="7" textAnchor="middle" fontWeight="900">GLOBAL MIN</text>
            </g>
          </svg>
        </MLCard>

      </div>
    </div>
  );
};
