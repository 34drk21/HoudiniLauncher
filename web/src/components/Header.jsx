import React from 'react';
import { Box, Sparkles, FolderPlus, FolderOpen, RefreshCw, Search } from 'lucide-react';

export default function Header({ searchTerm, setSearchTerm, onNewProject, onAddExisting, onRefresh }) {
  return (
    <header className="header">
      <div className="brand">
        <div className="brand-icon">
          <Box size={22} color="#000" />
        </div>
        <div>
          <h1 className="brand-title">
            HouD<span>2</span> Launcher
          </h1>
          <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
            Houdini Project & Scene File Management
          </span>
        </div>
        <span className="badge-tag">v0.4.3</span>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
        {/* Global Search */}
        <div style={{ position: 'relative', width: '280px' }}>
          <Search 
            size={16} 
            color="var(--text-muted)" 
            style={{ position: 'absolute', left: '12px', top: '50%', transform: 'translateY(-50%)' }} 
          />
          <input
            type="text"
            className="form-input"
            style={{ paddingLeft: '36px', height: '38px', borderRadius: '20px' }}
            placeholder="Search projects, tasks, .hip files..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
          />
        </div>

        {/* Action Buttons */}
        <button className="btn btn-secondary" onClick={onAddExisting}>
          <FolderOpen size={16} color="var(--gold-primary)" />
          Add Existing
        </button>

        <button className="btn btn-primary" onClick={onNewProject}>
          <FolderPlus size={16} />
          New Project
        </button>

        <button className="btn btn-icon" title="Refresh Indexes" onClick={onRefresh}>
          <RefreshCw size={18} />
        </button>
      </div>
    </header>
  );
}
