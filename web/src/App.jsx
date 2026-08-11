import React, { useState } from 'react';
import Header from './components/Header';
import Metrics from './components/Metrics';
import ProjectGrid from './components/ProjectGrid';
import TaskInspector from './components/TaskInspector';
import CacheVisualizer from './components/CacheVisualizer';
import HoudiniVersions from './components/HoudiniVersions';
import ActivityLog from './components/ActivityLog';
import { NewProjectModal, AddExistingModal, JsonViewerModal } from './components/Modals';

import {
  initialProjects,
  initialTasks,
  initialHoudiniVersions,
  initialHdas,
  initialActivityLog
} from './data/mockData';

export default function App() {
  const [projects, setProjects] = useState(initialProjects);
  const [tasks, setTasks] = useState(initialTasks);
  const [selectedProject, setSelectedProject] = useState(initialProjects[0]);
  const [searchTerm, setSearchTerm] = useState('');
  const [activeTab, setActiveTab] = useState('tasks'); // tasks, caches, versions

  // Modals
  const [isNewProjectOpen, setIsNewProjectOpen] = useState(false);
  const [isAddExistingOpen, setIsAddExistingOpen] = useState(false);
  const [jsonProject, setJsonProject] = useState(null);

  // Activities
  const [activities, setActivities] = useState(initialActivityLog);

  // Filter projects by search
  const filteredProjects = projects.filter(p =>
    p.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
    p.project_root.toLowerCase().includes(searchTerm.toLowerCase())
  );

  const handleSelectProject = (project) => {
    setSelectedProject(project);
  };

  const handleToggleFavorite = (projectId) => {
    setProjects(prev => prev.map(p => {
      if (p.project_id === projectId) {
        const updated = !p.favorite;
        logActivity(updated ? `Marked '${p.name}' as Favorite (★)` : `Unmarked Favorite for '${p.name}'`);
        return { ...p, favorite: updated };
      }
      return p;
    }));
  };

  const handleToggleArchive = (projectId) => {
    setProjects(prev => prev.map(p => {
      if (p.project_id === projectId) {
        const updated = !p.archived;
        logActivity(updated ? `Archived project '${p.name}'` : `Unarchived project '${p.name}'`);
        return { ...p, archived: updated };
      }
      return p;
    }));
  };

  const handleCreateProject = (newProj) => {
    setProjects([newProj, ...projects]);
    setSelectedProject(newProj);
    logActivity(`Created new project '${newProj.name}'`);
  };

  const handleAddExisting = (existingProj) => {
    setProjects([existingProj, ...projects]);
    setSelectedProject(existingProj);
    logActivity(`Added existing project '${existingProj.name}'`);
  };

  const handleNewHip = (task) => {
    const nextVer = (task.hips?.length || 0) + 1;
    const newHipName = `${task.name}_v${String(nextVer).padStart(3, '0')}_Shota.hip`;
    const newHip = {
      hip_file: newHipName,
      version: nextVer,
      user_name: 'Shota TD',
      size_mb: 31.5,
      modified_at: new Date().toISOString().replace('T', ' ').substring(0, 16)
    };

    setTasks(prev => prev.map(t => {
      if (t.task_id === task.task_id) {
        return { ...t, hips: [newHip, ...(t.hips || [])] };
      }
      return t;
    }));
    logActivity(`Created new HIP version v${String(nextVer).padStart(3, '0')} for task '${task.name}'`);
  };

  const handleOpenHip = (hip) => {
    logActivity(`Launched Houdini 20.5.410 with file '${hip.hip_file}'`);
    alert(`Opening scene file '${hip.hip_file}' in SideFX Houdini 20.5.410...`);
  };

  const logActivity = (details) => {
    const newAct = {
      id: Date.now(),
      details,
      created_at: new Date().toISOString().replace('T', ' ').substring(0, 16)
    };
    setActivities([newAct, ...activities]);
  };

  return (
    <div className="app-container">
      <Header
        searchTerm={searchTerm}
        setSearchTerm={setSearchTerm}
        onNewProject={() => setIsNewProjectOpen(true)}
        onAddExisting={() => setIsAddExistingOpen(true)}
        onRefresh={() => logActivity("Refreshed filesystem indexes")}
      />

      <div className="main-content">
        {/* Left Side: Projects Grid */}
        <div>
          <ProjectGrid
            projects={filteredProjects}
            selectedProject={selectedProject}
            onSelectProject={handleSelectProject}
            onToggleFavorite={handleToggleFavorite}
            onToggleArchive={handleToggleArchive}
            onOpenJson={(proj) => setJsonProject(proj)}
            onNewTask={() => alert("Creating a new task inside selected project...")}
          />
        </div>

        {/* Right Side: Dynamic Dashboard & Tabs */}
        <div>
          <Metrics
            projects={projects}
            tasks={tasks}
            houdiniVersions={initialHoudiniVersions}
          />

          {/* Navigation Tabs */}
          <div className="tabs-nav">
            <button
              className={`tab-btn ${activeTab === 'tasks' ? 'active' : ''}`}
              onClick={() => setActiveTab('tasks')}
            >
              Tasks & HIP Versions
            </button>
            <button
              className={`tab-btn ${activeTab === 'caches' ? 'active' : ''}`}
              onClick={() => setActiveTab('caches')}
            >
              Caches & Disk Inspection
            </button>
            <button
              className={`tab-btn ${activeTab === 'versions' ? 'active' : ''}`}
              onClick={() => setActiveTab('versions')}
            >
              Houdini & HDAs
            </button>
          </div>

          {/* Tab Views */}
          {activeTab === 'tasks' && (
            <TaskInspector
              selectedProject={selectedProject}
              tasks={tasks}
              onNewHip={handleNewHip}
              onOpenHip={handleOpenHip}
              onVersionUp={handleNewHip}
            />
          )}

          {activeTab === 'caches' && (
            <CacheVisualizer tasks={tasks} />
          )}

          {activeTab === 'versions' && (
            <HoudiniVersions
              houdiniVersions={initialHoudiniVersions}
              hdas={initialHdas}
            />
          )}

          <ActivityLog activities={activities} />
        </div>
      </div>

      {/* Modals */}
      <NewProjectModal
        isOpen={isNewProjectOpen}
        onClose={() => setIsNewProjectOpen(false)}
        onCreate={handleCreateProject}
      />

      <AddExistingModal
        isOpen={isAddExistingOpen}
        onClose={() => setIsAddExistingOpen(false)}
        onAdd={handleAddExisting}
      />

      <JsonViewerModal
        isOpen={Boolean(jsonProject)}
        onClose={() => setJsonProject(null)}
        project={jsonProject}
      />
    </div>
  );
}
