import { create } from 'zustand';
import type { Conversation, Message } from '@/types';

interface ConversationState {
  /* Active conversation */
  activeConversationId: string | null;
  conversations: Conversation[];
  messages: Message[];
  streamingContent: string;

  /* Actions */
  setActiveConversation: (id: string | null) => void;
  setConversations: (conversations: Conversation[]) => void;
  addConversation: (conversation: Conversation) => void;
  removeConversation: (id: string) => void;
  renameConversation: (id: string, title: string) => void;
  setMessages: (messages: Message[]) => void;
  appendMessage: (message: Message) => void;
  updateStreamingContent: (content: string) => void;
  clearStreamingContent: () => void;
}

export const useConversationStore = create<ConversationState>((set) => ({
  activeConversationId: null,
  conversations: [],
  messages: [],
  streamingContent: '',

  setActiveConversation: (id) => set({ activeConversationId: id }),

  setConversations: (conversations) => set({ conversations }),

  addConversation: (conversation) =>
    set((state) => ({ conversations: [conversation, ...state.conversations] })),

  removeConversation: (id) =>
    set((state) => ({
      conversations: state.conversations.filter((c) => c.id !== id),
      activeConversationId:
        state.activeConversationId === id ? null : state.activeConversationId,
      messages: state.activeConversationId === id ? [] : state.messages,
    })),

  renameConversation: (id, title) =>
    set((state) => ({
      conversations: state.conversations.map((c) =>
        c.id === id ? { ...c, title } : c,
      ),
    })),

  setMessages: (messages) => set({ messages }),

  appendMessage: (message) =>
    set((state) => ({ messages: [...state.messages, message] })),

  updateStreamingContent: (content) => set({ streamingContent: content }),

  clearStreamingContent: () => set({ streamingContent: '' }),
}));
