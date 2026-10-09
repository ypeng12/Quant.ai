import React, { useEffect, useState } from 'react';
import { API_BASE } from '../config';

type Post = { post_id: string; title: string; excerpt: string; published_at: string | null };
type Snapshot = { symbol: string; posts: Post[]; source: { status: string; last_success: string | null } | null };

export const CommunityMonitorPanel: React.FC<{ symbol: string }> = ({ symbol }) => {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    let active = true;
    const load = async () => {
      try {
        const response = await fetch(`${API_BASE}/api/community/${encodeURIComponent(symbol)}?limit=20`);
        if (!response.ok) throw new Error('Community source unavailable');
        const data = await response.json() as Snapshot;
        if (active) { setSnapshot(data); setError(false); }
      } catch { if (active) setError(true); }
    };
    void load();
    const timer = window.setInterval(() => { void load(); }, 60_000);
    return () => { active = false; window.clearInterval(timer); };
  }, [symbol]);

  return <section style={{ padding: '18px', marginBottom: '18px', background: '#101826', border: '1px solid #2c3b50', borderRadius: '12px' }} aria-label="Community posts">
    <h2 style={{ margin: '0 0 6px' }}>Futu Community · {symbol}</h2>
    <p style={{ color: '#a5b4c8', margin: '0 0 12px' }}>Saved public-post snapshot. Continuous collection has not been verified. No sentiment model or contrarian signal is applied.</p>
    {error && <p role="alert">Community source unavailable.</p>}
    {!error && snapshot && <>
      <p style={{ color: '#a5b4c8' }}>Source: {snapshot.source?.status || 'waiting'} · Last successful collection: {snapshot.source?.last_success ? new Date(snapshot.source.last_success).toLocaleString('en-US') : 'Pending'}</p>
      {snapshot.posts.length === 0 && <p>No posts saved in this app's collection database yet.</p>}
      {snapshot.posts.map(post => <article key={post.post_id} style={{ padding: '12px 0', borderTop: '1px solid #2c3b50' }}>
        <strong>{post.title || 'Community post'}</strong>
        <p style={{ color: '#b9c6d8', margin: '6px 0' }}>{post.excerpt}</p>
        <small>{post.published_at ? new Date(post.published_at).toLocaleString('en-US') : 'Time unavailable'} · Futu public feed</small>
      </article>)}
    </>}
    <p style={{ color: '#8d9db2', fontSize: '12px' }}>Post quality and sentiment have not been validated against subsequent returns.</p>
  </section>;
};
