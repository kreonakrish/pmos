import { create } from 'zustand';

interface StudioState {
  dirtyTool: boolean;
  dirtyAgent: boolean;
  dirtyTeam: boolean;
  selectedToolId: string | null;
  selectedAgentId: string | null;
  selectedTeamId: string | null;
  setDirtyTool: (v: boolean) => void;
  setDirtyAgent: (v: boolean) => void;
  setDirtyTeam: (v: boolean) => void;
  setSelectedTool: (id: string | null) => void;
  setSelectedAgent: (id: string | null) => void;
  setSelectedTeam: (id: string | null) => void;
}

export const useStudioStore = create<StudioState>((set) => ({
  dirtyTool: false,
  dirtyAgent: false,
  dirtyTeam: false,
  selectedToolId: null,
  selectedAgentId: null,
  selectedTeamId: null,

  setDirtyTool: (v) => set({ dirtyTool: v }),
  setDirtyAgent: (v) => set({ dirtyAgent: v }),
  setDirtyTeam: (v) => set({ dirtyTeam: v }),
  setSelectedTool: (id) => set({ selectedToolId: id }),
  setSelectedAgent: (id) => set({ selectedAgentId: id }),
  setSelectedTeam: (id) => set({ selectedTeamId: id }),
}));
