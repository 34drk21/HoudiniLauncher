import React from 'react';
import { Layers, FileCode, Play, Clock, User, HardDrive, Plus, CheckCircle2 } from 'lucide-react';

export default function TaskInspector({ selectedProject, tasks, onNewHip, onOpenHip, onVersionUp }) {
  if (!selectedProject) {
    return (
      <div className="card" style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)' }}>
        Select a project from the left panel to inspect tasks and scene files.
      </div>
    );
  }

  const projectTasks = tasks.filter(t => t.project_id === selectedProject.project_id);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      {/* Project Header Info */}
      <div className="card card-gold" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <h2 style={{ fontSize: '1.2rem', fontWeight: 700, fontFamily: 'var(--font-display)', color: 'var(--text-primary)' }}>
              {selectedProject.name}
            </h2>
            <span className="badge-tag">
              Default Range: {selectedProject.default_frames.start}-{selectedProject.default_frames.end} ({selectedProject.default_frames.fps} FPS)
            </span>
          </div>
          <p style={{ fontSize: '0.8rem', fontFamily: 'var(--font-mono)', color: 'var(--text-muted)', marginTop: '4px' }}>
            {selectedProject.project_root}
          </p>
        </div>
      </div>

      {/* Tasks List & HIP Files */}
      {projectTasks.length === 0 ? (
        <div className="card" style={{ padding: '40px', textAlign: 'center', color: 'var(--text-muted)' }}>
          No tasks found in this project. Click <strong>New Task</strong> or add an existing task folder.
        </div>
      ) : (
        projectTasks.map(task => (
          <div key={task.task_id} className="card" style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
            {/* Task Info Header */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderBottom: '1px solid var(--border-subtle)', paddingBottom: '12px' }}>
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                  <Layers size={20} color="var(--gold-primary)" />
                  <h3 style={{ fontSize: '1.1rem', fontWeight: 600, color: 'var(--text-primary)' }}>
                    {task.name}
                  </h3>
                  <span style={{
                    padding: '2px 10px',
                    borderRadius: '12px',
                    fontSize: '0.75rem',
                    fontWeight: 600,
                    background: 'var(--gold-dim)',
                    color: 'var(--gold-hover)',
                    border: '1px solid var(--border-gold)'
                  }}>
                    {task.status}
                  </span>
                </div>
                <div style={{ display: 'flex', gap: '16px', fontSize: '0.775rem', color: 'var(--text-secondary)', marginTop: '6px' }}>
                  <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                    <User size={13} color="var(--gold-muted)" /> Owner: {task.owner}
                  </span>
                  <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                    <Clock size={13} color="var(--gold-muted)" /> Frame Range: {task.frames.start} - {task.frames.end}
                  </span>
                </div>
              </div>

              <div style={{ display: 'flex', gap: '8px' }}>
                <button className="btn btn-secondary" style={{ fontSize: '0.8rem' }} onClick={() => onNewHip(task)}>
                  <Plus size={14} color="var(--gold-primary)" />
                  New HIP Version
                </button>
              </div>
            </div>

            {/* HIP Scene Files Version Timeline */}
            <div>
              <h4 style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: '10px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                <FileCode size={14} color="var(--gold-primary)" />
                Scene Files (.hip) Version Timeline
              </h4>

              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                {task.hips && task.hips.map((hip, idx) => (
                  <div
                    key={idx}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justify: 'space-between',
                      padding: '10px 14px',
                      borderRadius: 'var(--radius-sm)',
                      background: idx === 0 ? 'var(--bg-surface-elevated)' : 'var(--bg-base)',
                      border: idx === 0 ? '1px solid var(--border-gold)' : '1px solid var(--border-subtle)',
                      transition: 'var(--transition)'
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                      <span style={{
                        padding: '3px 8px',
                        borderRadius: '4px',
                        fontSize: '0.75rem',
                        fontWeight: 700,
                        fontFamily: 'var(--font-mono)',
                        background: idx === 0 ? 'var(--gold-primary)' : 'var(--border-medium)',
                        color: idx === 0 ? '#000' : 'var(--text-primary)'
                      }}>
                        v{String(hip.version).padStart(3, '0')}
                      </span>

                      <div>
                        <div style={{ fontSize: '0.875rem', fontWeight: 600, fontFamily: 'var(--font-mono)', color: idx === 0 ? 'var(--gold-hover)' : 'var(--text-primary)' }}>
                          {hip.hip_file}
                        </div>
                        <div style={{ fontSize: '0.725rem', color: 'var(--text-muted)' }}>
                          Saved by {hip.user_name} • {hip.size_mb} MB • {hip.modified_at}
                        </div>
                      </div>
                    </div>

                    <div style={{ display: 'flex', gap: '8px' }}>
                      {idx === 0 && (
                        <button className="btn btn-secondary" style={{ padding: '6px 10px', fontSize: '0.75rem' }} onClick={() => onVersionUp(task)}>
                          Version Up
                        </button>
                      )}
                      <button className="btn btn-primary" style={{ padding: '6px 14px', fontSize: '0.75rem' }} onClick={() => onOpenHip(hip)}>
                        <Play size={13} />
                        Launch Houdini
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Caches Summary */}
            {task.caches && task.caches.length > 0 && (
              <div style={{ marginTop: '6px', paddingTop: '10px', borderTop: '1px dashed var(--border-subtle)' }}>
                <h5 style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '6px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <HardDrive size={13} color="var(--emerald-green)" />
                  Task Disk Caches
                </h5>
                <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
                  {task.caches.map((c, i) => (
                    <div key={i} style={{ background: 'var(--bg-base)', border: '1px solid var(--border-subtle)', borderRadius: '6px', padding: '6px 10px', fontSize: '0.75rem', display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{c.name}</span>
                      <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--gold-muted)' }}>{c.format}</span>
                      <span style={{ color: 'var(--emerald-green)' }}>{c.size_gb} GB</span>
                      {c.missing_count > 0 && (
                        <span style={{ color: 'var(--coral-red)', fontWeight: 600 }}>({c.missing_count} frames missing)</span>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        ))
      )}
    </div>
  );
}
