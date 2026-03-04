import { create } from 'zustand';
import * as projectApi from '../api/projects';
import type { Artifact, Project, ProjectDetail } from '../types/project';

interface ProjectState {
  projects: Project[];
  currentProject: ProjectDetail | null;
  selectedArtifact: Artifact | null;
  loading: boolean;
  fetchProjects: () => Promise<void>;
  fetchProject: (id: string) => Promise<void>;
  createProject: (name: string, description: string | null, content: string) => Promise<string>;
  deleteProject: (id: string) => Promise<void>;
  fetchArtifact: (id: string) => Promise<void>;
  updateArtifact: (id: string, content: string) => Promise<void>;
  clearSelection: () => void;
}

export const useProjectStore = create<ProjectState>((set) => ({
  projects: [],
  currentProject: null,
  selectedArtifact: null,
  loading: false,

  fetchProjects: async () => {
    set({ loading: true });
    const projects = await projectApi.listProjects();
    set({ projects, loading: false });
  },

  fetchProject: async (id) => {
    set({ loading: true });
    const project = await projectApi.getProject(id);
    set({ currentProject: project, loading: false });
  },

  createProject: async (name, description, content) => {
    const project = await projectApi.createProject(name, description, content);
    set((state) => ({ projects: [project, ...state.projects] }));
    return project.id;
  },

  deleteProject: async (id) => {
    await projectApi.deleteProject(id);
    set((state) => ({
      projects: state.projects.filter((p) => p.id !== id),
      currentProject: state.currentProject?.id === id ? null : state.currentProject,
    }));
  },

  fetchArtifact: async (id) => {
    const artifact = await projectApi.getArtifact(id);
    set({ selectedArtifact: artifact });
  },

  updateArtifact: async (id, content) => {
    const artifact = await projectApi.updateArtifact(id, content);
    set({ selectedArtifact: artifact });
  },

  clearSelection: () => set({ selectedArtifact: null }),
}));
