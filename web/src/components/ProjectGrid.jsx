import React, { useState } from 'react';
import { Star, Archive, Folder, FolderCheck, AlertTriangle, Code, Plus } from 'lucide-react';

export default function ProjectGrid({
  projects,
  selectedProject,
  onSelectProject,
  onToggleFavorite,
  onToggleArchive,
  onOpenJson,
  onNewTask
}) {
  const [filter, setFilter] = useState('all'); // all, favorites, archived

  const filteredProjects = projects.filter(p => {
    if (filter === 'favorites') return p.favorite && !p.archived;
    if (filter === 'archived') return p.archived;
    return !p.archived;
  });

  return (
    <div className="card" style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '14px' }}>
        <h2 style={{ fontSize: '1rem', fontWeight: 700, fontFamily: 'var(--font-display)', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <Folder size={18} color="var(--gold-primary)" />
          Projects
        </h2>

        <div style={{ display: 'flex', gap: '4px', background: 'var(--bg-base)', padding: '2px', borderRadius: '6px', border: '1px solid var(--border-subtle)' }}>
          <button
            style={{
              padding: '4px 10px',
              fontSize: '0.75rem',
              borderRadius: '4px',
              border: 'none',
              cursor: 'pointer',
              background: filter === 'all' ? 'var(--gold-dim)' : 'transparent',
              color: filter === 'all' ? 'var(--gold-hover)' : 'var(--text-secondary)',
              fontWeight: filter === 'all' ? 600 : 400
            }}
            onClick={() => setFilter('all')}
          >
            All
          </button>
          <button
            style={{
              padding: '4px 10px',
              fontSize: '0.75rem',
              borderRadius: '4px',
              border: 'none',
              cursor: 'pointer',
              background: filter === 'favorites' ? 'var(--gold-dim)' : 'transparent',
              color: filter === 'favorites' ? 'var(--gold-hover)' : 'var(--text-secondary)',
              fontWeight: filter === 'favorites' ? 600 : 400
            }}
            onClick={() => setFilter('favorites')}
          >
            ★ Favorites
          </button>
          <button
            style={{
              padding: '4px 10px',
              fontSize: '0.75rem',
              borderRadius: '4px',
              border: 'none',
              cursor: 'pointer',
              background: filter === 'archived' ? 'var(--gold-dim)' : 'transparent',
              color: filter === 'archived' ? 'var(--gold-hover)' : 'var(--text-secondary)',
              fontWeight: filter === 'archived' ? 600 : 400
            }}
            onClick={() => setFilter('archived')}
          >
            Archived
          </button>
        </div>
      </div>

      {/* Project List */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', overflowY: 'auto', flex: 1, paddingRight: '4px' }}>
        {filteredProjects.length === 0 ? (
          <div style={{ padding: '30px 10px', textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.875rem' }}>
            No projects found in this category.
          </div>
        ) : (
          filteredProjects.map(proj => {
            const isSelected = selectedProject && selectedProject.project_id === proj.project_id;
            return (
              <div
                key={proj.project_id}
                onClick={() => onSelectProject(proj)}
                style={{
                  padding: '14px',
                  borderRadius: 'var(--radius-md)',
                  background: isSelected ? 'var(--bg-surface-elevated)' : 'var(--bg-base)',
                  border: isSelected ? '1px solid var(--border-gold)' : '1px solid var(--border-subtle)',
                  boxShadow: isSelected ? 'var(--shadow-gold)' : 'none',
                  cursor: 'pointer',
                  transition: 'var(--transition)'
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '6px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <FolderCheck size={18} color={isSelected ? 'var(--gold-primary)' : 'var(--text-secondary)'} />
                    <span style={{ fontWeight: 600, fontSize: '0.95rem', color: isSelected ? 'var(--gold-hover)' : 'var(--text-primary)' }}>
                      {proj.name}
                    </span>
                  </div>

                  <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }} onClick={(e) => e.stopPropagation()}>
                    <button
                      className="btn-icon"
                      style={{ color: proj.favorite ? 'var(--gold-primary)' : 'var(--text-muted)' }}
                      title="Favorite Project"
                      onClick={() => onToggleFavorite(proj.project_id)}
                    >
                      <Star size={16} fill={proj.favorite ? 'var(--gold-primary)' : 'none'} />
                    </button>
                    <button
                      className="btn-icon"
                      style={{ color: proj.archived ? 'var(--coral-red)' : 'var(--text-muted)' }}
                      title="Archive Project"
                      onClick={() => onToggleArchive(proj.project_id)}
                    >
                      <Archive size={16} />
                    </button>
                  </div>
                </div>

                <div style={{ fontSize: '0.75rem', fontFamily: 'var(--font-mono)', color: 'var(--text-muted)', marginBottom: '8px', wordBreak: 'break-all' }}>
                  {proj.project_root}
                </div>

                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                  <span>{proj.tasks_count} Tasks • {proj.hip_count} HIP Files</span>
                  <span style={{
                    padding: '2px 6px',
                    borderRadius: '4px',
                    fontSize: '0.7rem',
                    fontWeight: 600,
                    background: proj.missing ? 'var(--coral-bg)' : 'var(--emerald-bg)',
                    color: proj.missing ? 'var(--coral-red)' : 'var(--emerald-green)'
                  }}>
                    {proj.missing ? 'Missing' : 'Available'}
                  </span>
                </div>
              </div>
            );
          })
        )}
      </div>

      {/* Footer Info / JSON View Button */}
      {selectedProject && (
        <div style={{ marginTop: '14px', paddingTop: '14px', borderTop: '1px solid var(--border-subtle)', display: 'flex', gap: '8px' }}>
          <button className="btn btn-secondary" style={{ flex: 1, fontSize: '0.8rem' }} onClick={() => onOpenJson(selectedProject)}>
            <Code size={14} color="var(--gold-primary)" />
            View project.json
          </button>
          <button className="btn btn-primary" style={{ flex: 1, fontSize: '0.8rem' }} onClick={onNewTask}>
            <Plus size={14} />
            New Task
          </button>
        </div>
      )}
    </div>
  );
}
