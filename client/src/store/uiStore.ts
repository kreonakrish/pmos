import { create } from 'zustand';

interface UIState {
  sidebarOpen: boolean;
  sidebarCollapsed: boolean;
  graphDetailPanelOpen: boolean;
  themeMode: 'light' | 'dark';
  selectedAgentId: string | null;

  toggleSidebar: () => void;
  setSidebarOpen: (open: boolean) => void;
  setGraphDetailPanelOpen: (open: boolean) => void;
  setThemeMode: (mode: 'light' | 'dark') => void;
  toggleTheme: () => void;
  setSelectedAgent: (id: string | null) => void;
}

export const useUIStore = create<UIState>((set) => ({
  sidebarOpen: true,
  sidebarCollapsed: false,
  graphDetailPanelOpen: false,
  themeMode: 'dark',
  selectedAgentId: null,

  toggleSidebar: () =>
    set((state) => ({
      sidebarOpen: !state.sidebarOpen,
      sidebarCollapsed: !state.sidebarCollapsed,
    })),
  setSidebarOpen: (open) => set({ sidebarOpen: open }),
  setGraphDetailPanelOpen: (open) => set({ graphDetailPanelOpen: open }),
  setThemeMode: (mode) => set({ themeMode: mode }),
  toggleTheme: () =>
    set((state) => ({
      themeMode: state.themeMode === 'dark' ? 'light' : 'dark',
    })),
  setSelectedAgent: (id) => set({ selectedAgentId: id }),
}));
