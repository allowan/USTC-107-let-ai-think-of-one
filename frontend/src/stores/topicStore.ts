import { create } from 'zustand';
import type { TopicInfo } from '@/types';
import { topicApi } from '@/services/api';

interface TopicState {
  topics: TopicInfo[];
  activeTopicId: string;
  loading: boolean;
  loaded: boolean;
  fetchTopics: () => Promise<void>;
  createTopic: () => Promise<string>;
  deleteTopic: (topicId: string) => Promise<void>;
  renameTopic: (topicId: string, name: string) => Promise<void>;
  setActiveTopicId: (id: string) => void;
}

export const useTopicStore = create<TopicState>((set, get) => ({
  topics: [],
  activeTopicId: '',
  loading: false,
  loaded: false,

  fetchTopics: async () => {
    set({ loading: true });
    try {
      const { data } = await topicApi.list();
      const topics = data.topics;
      const activeTopicId = get().activeTopicId;
      set({
        topics,
        activeTopicId: topics.length > 0 && !activeTopicId ? topics[0].id : activeTopicId,
        loading: false,
        loaded: true,
      });
    } catch {
      set({ loading: false, loaded: true });
    }
  },

  createTopic: async () => {
    const { data } = await topicApi.create('默认话题');
    set((s) => ({
      topics: [data, ...s.topics],
      activeTopicId: data.id,
    }));
    return data.id;
  },

  deleteTopic: async (topicId: string) => {
    await topicApi.delete(topicId);
    set((s) => {
      const remaining = s.topics.filter((t) => t.id !== topicId);
      return {
        topics: remaining,
        activeTopicId: s.activeTopicId === topicId
          ? (remaining.length > 0 ? remaining[0].id : '')
          : s.activeTopicId,
      };
    });
  },

  renameTopic: async (topicId: string, name: string) => {
    await topicApi.rename(topicId, name);
    set((s) => ({
      topics: s.topics.map((t) => (t.id === topicId ? { ...t, name } : t)),
    }));
  },

  setActiveTopicId: (id: string) => set({ activeTopicId: id }),
}));
