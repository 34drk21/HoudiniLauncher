import React from 'react';
import { History, Activity } from 'lucide-react';

export default function ActivityLog({ activities }) {
  return (
    <div className="card">
      <h3 style={{ fontSize: '0.95rem', fontWeight: 700, fontFamily: 'var(--font-display)', marginBottom: '12px', display: 'flex', alignItems: 'center', gap: '8px' }}>
        <Activity size={16} color="var(--gold-primary)" />
        Recent Activity History
      </h3>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', maxHeight: '200px', overflowY: 'auto' }}>
        {activities.map(act => (
          <div key={act.id} style={{ fontSize: '0.8rem', padding: '8px 12px', background: 'var(--bg-base)', borderLeft: '3px solid var(--gold-primary)', borderRadius: '4px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ color: 'var(--text-primary)' }}>{act.details}</span>
            <span style={{ fontSize: '0.725rem', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>{act.created_at}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
