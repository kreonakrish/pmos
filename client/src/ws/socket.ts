import { useWSStore } from '@/store/wsStore';
import { useConversationStore } from '@/store/conversationStore';
import type { WSEvent } from '@/types';

/**
 * The gateway uses a raw WebSocket server (ws library) at /v1/ws/chat,
 * not socket.io. This module wraps a native WebSocket connection that
 * connects on demand when streaming a conversation.
 */

let ws: WebSocket | null = null;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

export function getSocket(): WebSocket | null {
  return ws;
}

/**
 * initSocket is called on app mount. It marks the store as ready but does
 * NOT open a persistent connection — the WS is only needed during chat
 * streaming. This avoids console errors from constant reconnect attempts.
 */
export function initSocket(): void {
  // Nothing to do on mount — connection is opened by connectForStream()
}

/**
 * Open a WebSocket to the gateway for streaming a conversation.
 * Called when the user sends a chat message that needs streaming.
 */
export function connectForStream(onMessage?: (event: WSEvent) => void): WebSocket | null {
  if (ws && ws.readyState === WebSocket.OPEN) return ws;

  const token = localStorage.getItem('pmos_token');
  if (!token) return null;

  const runtimeCfg = (window as any).__PMOS_CONFIG__ || {};
  let base: string = runtimeCfg.wsBaseUrl || '';
  if (!base) {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    base = `${protocol}//${window.location.host}`;
  }
  const url = `${base.replace(/\/$/, '')}/v1/ws/chat?token=${encodeURIComponent(token)}`;

  const wsStore = useWSStore.getState();

  try {
    ws = new WebSocket(url);
  } catch {
    return null;
  }

  ws.onopen = () => {
    wsStore.setConnected(true);
    wsStore.setReconnecting(false);
  };

  ws.onmessage = (evt) => {
    try {
      const event: WSEvent = JSON.parse(evt.data as string);
      wsStore.setLastEvent(event);

      if (event.type === 'stream_chunk' || event.type === 'step') {
        const convStore = useConversationStore.getState();
        convStore.updateStreamingContent(
          convStore.streamingContent + event.content,
        );
      }

      if (event.type === 'complete' || event.type === 'stream_complete') {
        wsStore.setStreaming(false);
        useConversationStore.getState().clearStreamingContent();
      }

      if (onMessage) onMessage(event);
    } catch {
      // Non-JSON message — ignore
    }
  };

  ws.onclose = () => {
    wsStore.setConnected(false);
    ws = null;
  };

  ws.onerror = () => {
    // Silently handle — onclose will fire after this
  };

  return ws;
}

export function disconnectSocket(): void {
  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
  if (ws) {
    ws.close();
    ws = null;
    useWSStore.getState().setConnected(false);
  }
}
