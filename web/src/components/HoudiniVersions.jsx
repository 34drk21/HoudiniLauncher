import React from 'react';
import { Cpu, Package, Check, Star } from 'lucide-react';

export default function HoudiniVersions({ houdiniVersions, hdas }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '16px', marginBottom: '20px' }}>
      {/* Houdini Installations */}
      <div className="card">
        <h3 style={{ fontSize: '0.95rem', fontWeight: 700, fontFamily: 'var(--font-display)', marginBottom: '12px', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <Cpu size={16} color="var(--sky-blue)" />
          Houdini Installations
        </h3>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          {houdiniVersions.map((v, i) => (
            <div key={i} style={{ background: 'var(--bg-base)', border: v.is_default ? '1px solid var(--border-gold)' : '1px solid var(--border-subtle)', borderRadius: 'var(--radius-sm)', padding: '10px 12px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <div>
                <div style={{ fontSize: '0.875rem', fontWeight: 700, fontFamily: 'var(--font-mono)', color: v.is_default ? 'var(--gold-hover)' : 'var(--text-primary)' }}>
                  Houdini {v.version} {v.is_default && <span style={{ fontSize: '0.7rem', background: 'var(--gold-dim)', color: 'var(--gold-hover)', padding: '2px 6px', borderRadius: '4px', marginLeft: '6px' }}>DEFAULT</span>}
                </div>
                <div style={{ fontSize: '0.725rem', color: 'var(--text-muted)' }}>
                  {v.variant} • {v.build_type}
                </div>
              </div>
              <span style={{ fontSize: '0.75rem', color: 'var(--emerald-green)', fontWeight: 600 }}>{v.status}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Installed HDAs */}
      <div className="card">
        <h3 style={{ fontSize: '0.95rem', fontWeight: 700, fontFamily: 'var(--font-display)', marginBottom: '12px', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <Package size={16} color="var(--gold-primary)" />
          Installed HDA Packages
        </h3>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          {hdas.map((hda, i) => (
            <div key={i} style={{ background: 'var(--bg-base)', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-sm)', padding: '10px 12px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <div>
                <div style={{ fontSize: '0.85rem', fontWeight: 600, fontFamily: 'var(--font-mono)', color: 'var(--text-primary)' }}>
                  {hda.name}
                </div>
                <div style={{ fontSize: '0.725rem', color: 'var(--text-muted)' }}>
                  v{hda.version} • {hda.type}
                </div>
              </div>
              <span style={{ fontSize: '0.7rem', background: 'var(--emerald-bg)', color: 'var(--emerald-green)', padding: '2px 8px', borderRadius: '10px', fontWeight: 600 }}>
                {hda.status}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
