import React from 'react';
import { Folder, CheckSquare, FileCode, HardDrive, Cpu } from 'lucide-react';

export default function Metrics({ projects, tasks, houdiniVersions }) {
  const activeProjects = projects.filter(p => !p.archived).length;
  const totalTasks = tasks.length;
  
  let totalHips = 0;
  let totalCacheGB = 0;
  
  tasks.forEach(t => {
    totalHips += t.hips ? t.hips.length : 0;
    if (t.caches) {
      t.caches.forEach(c => totalCacheGB += c.size_gb || 0);
    }
  });

  const cards = [
    {
      title: "Registered Projects",
      value: activeProjects,
      subtitle: `${projects.length - activeProjects} Archived`,
      icon: Folder,
      color: "var(--gold-primary)"
    },
    {
      title: "Active Tasks",
      value: totalTasks,
      subtitle: "Across registered projects",
      icon: CheckSquare,
      color: "var(--gold-hover)"
    },
    {
      title: "HIP Scene Files",
      value: totalHips,
      subtitle: "Tracked file versions",
      icon: FileCode,
      color: "var(--gold-muted)"
    },
    {
      title: "Cache Disk Usage",
      value: `${totalCacheGB.toFixed(1)} GB`,
      subtitle: "VDB & BGEO.SC caches",
      icon: HardDrive,
      color: "var(--emerald-green)"
    },
    {
      title: "Houdini Installs",
      value: houdiniVersions.length,
      subtitle: "Default: 20.5.410",
      icon: Cpu,
      color: "var(--sky-blue)"
    }
  ];

  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
      gap: '16px',
      marginBottom: '20px'
    }}>
      {cards.map((c, i) => {
        const IconComponent = c.icon;
        return (
          <div key={i} className="card card-gold" style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
            <div style={{
              width: '42px',
              height: '42px',
              borderRadius: '10px',
              background: 'var(--bg-surface-elevated)',
              border: '1px solid var(--border-medium)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: c.color
            }}>
              <IconComponent size={22} />
            </div>
            <div>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                {c.title}
              </div>
              <div style={{ fontSize: '1.4rem', fontWeight: 700, fontFamily: 'var(--font-display)', color: 'var(--text-primary)' }}>
                {c.value}
              </div>
              <div style={{ fontSize: '0.725rem', color: 'var(--text-muted)' }}>
                {c.subtitle}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
