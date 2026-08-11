import React from 'react';
import { HardDrive, AlertTriangle, CheckCircle, PieChart } from 'lucide-react';

export default function CacheVisualizer({ tasks }) {
  const allCaches = [];
  tasks.forEach(t => {
    if (t.caches) {
      t.caches.forEach(c => {
        allCaches.push({ ...c, taskName: t.name });
      });
    }
  });

  return (
    <div className="card" style={{ marginBottom: '20px' }}>
      <h3 style={{ fontSize: '1rem', fontWeight: 700, fontFamily: 'var(--font-display)', marginBottom: '14px', display: 'flex', alignItems: 'center', gap: '8px' }}>
        <HardDrive size={18} color="var(--emerald-green)" />
        Cache & Disk Usage Inspection
      </h3>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '12px' }}>
        {allCaches.length === 0 ? (
          <div style={{ color: 'var(--text-muted)', fontSize: '0.875rem' }}>No cache files found.</div>
        ) : (
          allCaches.map((cache, i) => (
            <div key={i} style={{ background: 'var(--bg-base)', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-sm)', padding: '12px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
                <span style={{ fontWeight: 600, fontSize: '0.875rem', color: 'var(--text-primary)' }}>{cache.name}</span>
                <span style={{ fontSize: '0.75rem', fontFamily: 'var(--font-mono)', padding: '2px 6px', background: 'var(--bg-surface-elevated)', borderRadius: '4px', color: 'var(--gold-muted)' }}>
                  {cache.format}
                </span>
              </div>

              <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginBottom: '8px' }}>
                Task: <strong>{cache.taskName}</strong> • Range: {cache.start_frame}-{cache.end_frame} ({cache.total_frames} frames)
              </div>

              {/* Cache Progress Bar */}
              <div style={{ height: '6px', background: 'var(--bg-surface-elevated)', borderRadius: '3px', overflow: 'hidden', marginBottom: '8px', display: 'flex' }}>
                <div style={{
                  width: `${((cache.total_frames - cache.missing_count) / cache.total_frames) * 100}%`,
                  background: cache.missing_count > 0 ? 'var(--gold-primary)' : 'var(--emerald-green)'
                }} />
                {cache.missing_count > 0 && (
                  <div style={{ width: `${(cache.missing_count / cache.total_frames) * 100}%`, background: 'var(--coral-red)' }} />
                )}
              </div>

              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '0.75rem' }}>
                <span style={{ color: 'var(--text-muted)' }}>Size: <strong style={{ color: 'var(--text-primary)' }}>{cache.size_gb} GB</strong></span>
                {cache.missing_count > 0 ? (
                  <span style={{ color: 'var(--coral-red)', display: 'flex', alignItems: 'center', gap: '4px', fontWeight: 600 }}>
                    <AlertTriangle size={12} /> {cache.missing_count} Missing Frames
                  </span>
                ) : (
                  <span style={{ color: 'var(--emerald-green)', display: 'flex', alignItems: 'center', gap: '4px' }}>
                    <CheckCircle size={12} /> Complete
                  </span>
                )}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
