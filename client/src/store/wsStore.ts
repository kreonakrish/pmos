import { create } from 'zustand';
import type { WSEvent } from '@/types';

interface WSState {
  isConnected: boolean;
  isStreaming: boolean;
  reconnecting: boolean;
  lastEvent: WSEvent | null;
  abortController: AbortController | null;

  setConnected: (connected: boolean) => void;
  setStreaming: (streaming: boolean) => void;
  setReconnecting: (v: boolean) => void;
  setLastEvent: (e: WSEvent) => void;
  setAbortController: (controller: AbortController | null) => void;
  abort: () => void;
}

export const useWSStore = create<WSState>((set, get) => ({
  isConnected: false,
  isStreaming: false,
  reconnecting: false,
  lastEvent: null,
  abortController: null,

  setConnected: (connected) => set({ isConnected: connected, reconnecting: false }),
  setStreaming: (streaming) => set({ isStreaming: streaming }),
  setReconnecting: (v) => set({ reconnecting: v }),
  setLastEvent: (e) => set({ lastEvent: e }),
  setAbortController: (controller) => set({ abortController: controller }),

  abort: () => {
    const { abortController } = get();
    if (abortController) {
      abortController.abort();
    }
    set({ isStreaming: false, abortController: null });
  },
}));
