export const initialProjects = [
  {
    project_id: "proj_cyber_fx_2026",
    name: "Cyber_FX_Commercial",
    project_root: "C:/Projects/Cyber_FX_Commercial",
    favorite: true,
    archived: false,
    missing: false,
    default_frames: { start: 1001, end: 1150, fps: 24.0 },
    created_at: "2026-08-01 10:15",
    tasks_count: 3,
    hip_count: 8,
    cache_size_gb: 42.8
  },
  {
    project_id: "proj_destruct_movie",
    name: "Feature_Destruction_Shot42",
    project_root: "C:/Projects/Feature_Destruction_Shot42",
    favorite: true,
    archived: false,
    missing: false,
    default_frames: { start: 1001, end: 1240, fps: 24.0 },
    created_at: "2026-07-28 14:30",
    tasks_count: 4,
    hip_count: 14,
    cache_size_gb: 128.5
  },
  {
    project_id: "proj_creature_rig",
    name: "Dragon_Creature_FX",
    project_root: "D:/VFX_Projects/Dragon_Creature_FX",
    favorite: false,
    archived: false,
    missing: false,
    default_frames: { start: 1001, end: 1080, fps: 24.0 },
    created_at: "2026-08-04 09:45",
    tasks_count: 2,
    hip_count: 5,
    cache_size_gb: 18.2
  },
  {
    project_id: "proj_legacy_env",
    name: "Archived_Ocean_Sim_2025",
    project_root: "Z:/Archive/Archived_Ocean_Sim_2025",
    favorite: false,
    archived: true,
    missing: false,
    default_frames: { start: 1001, end: 1200, fps: 24.0 },
    created_at: "2025-11-12 18:20",
    tasks_count: 1,
    hip_count: 3,
    cache_size_gb: 86.0
  }
];

export const initialTasks = [
  {
    task_id: "task_pyro_explosion",
    project_id: "proj_cyber_fx_2026",
    name: "fx_pyro_explosion",
    owner: "Shota TD",
    status: "In Progress",
    modified_at: "2026-08-11 11:20",
    frames: { start: 1001, end: 1120, fps: 24.0 },
    hips: [
      { hip_file: "fx_pyro_explosion_v003_Shota.hip", version: 3, user_name: "Shota TD", size_mb: 28.4, modified_at: "2026-08-11 11:20" },
      { hip_file: "fx_pyro_explosion_v002_Shota.hip", version: 2, user_name: "Shota TD", size_mb: 26.1, modified_at: "2026-08-10 16:45" },
      { hip_file: "fx_pyro_explosion_v001_Alex.hip", version: 1, user_name: "Alex FX", size_mb: 22.0, modified_at: "2026-08-09 09:10" }
    ],
    caches: [
      { name: "sim_pyro_v003", format: ".vdb", start_frame: 1001, end_frame: 1120, total_frames: 120, missing_count: 0, size_gb: 24.5 },
      { name: "geo_colliders_v001", format: ".bgeo.sc", start_frame: 1001, end_frame: 1120, total_frames: 120, missing_count: 0, size_gb: 3.2 }
    ]
  },
  {
    task_id: "task_sparks_elect",
    project_id: "proj_cyber_fx_2026",
    name: "fx_sparks_electric",
    owner: "Alex FX",
    status: "Approved",
    modified_at: "2026-08-10 17:30",
    frames: { start: 1001, end: 1150, fps: 24.0 },
    hips: [
      { hip_file: "fx_sparks_electric_v002_Alex.hip", version: 2, user_name: "Alex FX", size_mb: 18.2, modified_at: "2026-08-10 17:30" },
      { hip_file: "fx_sparks_electric_v001_Alex.hip", version: 1, user_name: "Alex FX", size_mb: 15.8, modified_at: "2026-08-08 14:00" }
    ],
    caches: [
      { name: "particles_sparks_v002", format: ".bgeo.sc", start_frame: 1001, end_frame: 1150, total_frames: 150, missing_count: 2, size_gb: 8.4 }
    ]
  },
  {
    task_id: "task_building_collapse",
    project_id: "proj_destruct_movie",
    name: "fx_building_rbd",
    owner: "Shota TD",
    status: "In Review",
    modified_at: "2026-08-11 09:15",
    frames: { start: 1001, end: 1240, fps: 24.0 },
    hips: [
      { hip_file: "fx_building_rbd_v004_Shota.hip", version: 4, user_name: "Shota TD", size_mb: 45.6, modified_at: "2026-08-11 09:15" },
      { hip_file: "fx_building_rbd_v003_Shota.hip", version: 3, user_name: "Shota TD", size_mb: 42.1, modified_at: "2026-08-10 11:00" }
    ],
    caches: [
      { name: "rbd_packed_debris_v004", format: ".bgeo.sc", start_frame: 1001, end_frame: 1240, total_frames: 240, missing_count: 0, size_gb: 94.2 },
      { name: "dust_cloud_v004", format: ".vdb", start_frame: 1001, end_frame: 1240, total_frames: 240, missing_count: 0, size_gb: 34.3 }
    ]
  }
];

export const initialHoudiniVersions = [
  {
    version: "20.5.410",
    variant: "Python 3.11",
    build_type: "Production Build",
    path: "C:/Program Files/Side Effects Software/Houdini 20.5.410/bin/houdini.exe",
    is_default: true,
    status: "Active"
  },
  {
    version: "20.0.751",
    variant: "Python 3.10",
    build_type: "Production Build",
    path: "C:/Program Files/Side Effects Software/Houdini 20.0.751/bin/houdini.exe",
    is_default: false,
    status: "Active"
  },
  {
    version: "19.5.805",
    variant: "Python 3.9",
    build_type: "Legacy Archive Build",
    path: "C:/Program Files/Side Effects Software/Houdini 19.5.805/bin/houdini.exe",
    is_default: false,
    status: "Available"
  }
];

export const initialHdas = [
  { name: "HouD2_Pyro_Builder.hda", version: "1.4.0", type: "SOP / Pyro", status: "Installed" },
  { name: "HouD2_Cache_Exporter.hda", version: "2.1.0", type: "ROP / Output", status: "Installed" },
  { name: "HouD2_RBD_Debris_Gen.hda", version: "1.0.2", type: "SOP / RBD", status: "Installed" },
  { name: "HouD2_Camera_Rig.hda", version: "1.1.0", type: "OBJ / Camera", status: "Installed" }
];

export const initialActivityLog = [
  { id: 1, type: "task_adopted", details: "Adopted existing task 'fx_pyro_explosion' into Cyber_FX_Commercial", created_at: "2026-08-11 11:20" },
  { id: 2, type: "hip_version_up", details: "Saved version v003 of 'fx_pyro_explosion_v003_Shota.hip'", created_at: "2026-08-11 11:20" },
  { id: 3, type: "project_added", details: "Added existing project 'Feature_Destruction_Shot42' from C:/Projects", created_at: "2026-08-11 09:15" },
  { id: 4, type: "cache_verified", details: "Verified 240 cache frames for 'rbd_packed_debris_v004' (94.2 GB)", created_at: "2026-08-10 17:45" },
  { id: 5, type: "project_favorite", details: "Marked 'Cyber_FX_Commercial' as Favorite (★)", created_at: "2026-08-10 14:00" }
];
