// src/store/chatStore.ts
import { create } from 'zustand';
import type { ChatMessage } from '../types/chat';
import { mockMessages } from '../mocks/mockChat';

interface ChatState {
  messages: ChatMessage[];
  addMessage: (message: ChatMessage) => void;
}

export const useChatStore = create<ChatState>((set) => ({
  messages: mockMessages,
  addMessage: (message) =>
    set((state) => ({ messages: [...state.messages, message] })),
}));