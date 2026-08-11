import React, { useState } from 'react';
import { X, FolderPlus, FolderOpen, Plus, Code } from 'lucide-react';

export function NewProjectModal({ isOpen, onClose, onCreate }) {
  const [name, setName] = useState('');
  const [root, setRoot] = useState('C:/Projects/');
  const [startFrame, setStartFrame] = useState(1001);
  const [endFrame, setEndFrame] = useState(1100);

  if (!isOpen) return null;

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!name) return;
    onCreate({
      project_id: `proj_${Date.now()}`,
      name,
      project_root: `${root.endsWith('/') ? root : root + '/'}${name}`,
      favorite: false,
      archived: false,
      missing: false,
      default_frames: { start: Number(startFrame), end: Number(endFrame), fps: 24.0 },
      created_at: new Date().toISOString().replace('T', ' ').substring(0, 16),
      tasks_count: 0,
      hip_count: 0,
      cache_size_gb: 0
    });
    setName('');
    onClose();
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <h3 style={{ fontSize: '1.05rem', fontWeight: 700, display: 'flex', alignItems: 'center', gap: '8px' }}>
            <FolderPlus size={18} color="var(--gold-primary)" />
            Create New HouD2 Project
          </h3>
          <button className="btn-icon" onClick={onClose}><X size={18} /></button>
        </div>
        <form onSubmit={handleSubmit}>
          <div className="modal-body">
            <div className="form-group">
              <label className="form-label">Project Name</label>
              <input
                className="form-input"
                placeholder="e.g. Commercial_Shot01"
                value={name}
                onChange={e => setName(e.target.value)}
                required
              />
            </div>
            <div className="form-group">
              <label className="form-label">Root Directory</label>
              <input
                className="form-input"
                value={root}
                onChange={e => setRoot(e.target.value)}
                required
              />
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
              <div className="form-group">
                <label className="form-label">Start Frame</label>
                <input
                  type="number"
                  className="form-input"
                  value={startFrame}
                  onChange={e => setStartFrame(e.target.value)}
                />
              </div>
              <div className="form-group">
                <label className="form-label">End Frame</label>
                <input
                  type="number"
                  className="form-input"
                  value={endFrame}
                  onChange={e => setEndFrame(e.target.value)}
                />
              </div>
            </div>
          </div>
          <div className="modal-footer">
            <button type="button" className="btn btn-secondary" onClick={onClose}>Cancel</button>
            <button type="submit" className="btn btn-primary">Create Project</button>
          </div>
        </form>
      </div>
    </div>
  );
}

export function AddExistingModal({ isOpen, onClose, onAdd }) {
  const [path, setPath] = useState('C:/Projects/MyExistingHoudiniProject');

  if (!isOpen) return null;

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!path) return;
    const folderName = path.split('/').filter(Boolean).pop() || 'Existing_Project';
    onAdd({
      project_id: `proj_${Date.now()}`,
      name: folderName,
      project_root: path,
      favorite: false,
      archived: false,
      missing: false,
      default_frames: { start: 1001, end: 1100, fps: 24.0 },
      created_at: new Date().toISOString().replace('T', ' ').substring(0, 16),
      tasks_count: 1,
      hip_count: 2,
      cache_size_gb: 12.4
    });
    onClose();
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <h3 style={{ fontSize: '1.05rem', fontWeight: 700, display: 'flex', alignItems: 'center', gap: '8px' }}>
            <FolderOpen size={18} color="var(--gold-primary)" />
            Add Existing HouD2 Project
          </h3>
          <button className="btn-icon" onClick={onClose}><X size={18} /></button>
        </div>
        <form onSubmit={handleSubmit}>
          <div className="modal-body">
            <div className="form-group">
              <label className="form-label">Select Existing Project Folder Path</label>
              <input
                className="form-input"
                placeholder="C:/Projects/YourProjectFolder"
                value={path}
                onChange={e => setPath(e.target.value)}
                required
              />
              <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '4px', display: 'block' }}>
                If .houd2/project.json or existing tasks/HIP files exist, they will be automatically reconciled and loaded.
              </span>
            </div>
          </div>
          <div className="modal-footer">
            <button type="button" className="btn btn-secondary" onClick={onClose}>Cancel</button>
            <button type="submit" className="btn btn-primary">Add Project</button>
          </div>
        </form>
      </div>
    </div>
  );
}

export function JsonViewerModal({ isOpen, onClose, project }) {
  if (!isOpen || !project) return null;

  const jsonContent = JSON.stringify({
    format: "houd2.project_settings",
    schema_version: 1,
    project_id: project.project_id,
    name: project.name,
    project_root: project.project_root,
    default_frames: project.default_frames,
    created_at: project.created_at
  }, null, 2);

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: '640px' }}>
        <div className="modal-header">
          <h3 style={{ fontSize: '1.05rem', fontWeight: 700, display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Code size={18} color="var(--gold-primary)" />
            Canonical .houd2/project.json Preview
          </h3>
          <button className="btn-icon" onClick={onClose}><X size={18} /></button>
        </div>
        <div className="modal-body">
          <pre className="code-block">{jsonContent}</pre>
        </div>
        <div className="modal-footer">
          <button type="button" className="btn btn-secondary" onClick={onClose}>Close</button>
        </div>
      </div>
    </div>
  );
}
