import { create } from 'zustand';
import type { TopicInfo } from '@/types';
import { topicApi } from '@/services/api';

interface TopicState {
  topics: TopicInfo[];
  activeTopicId: string;
  loading: boolean;
  loaded: boolean;
  loadError: boolean;
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
  loadError: false,

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
        loadError: false,
      });
    } catch {
      // 后端离线时不能置 loaded：否则 ChatPage 会触发自动建话题产生
      // 未处理的 rejection，且用户看不到任何失败信号。保留 loaded: false
      // 表示"尚未成功加载"，并用 loadError 驱动 UI 提示后端不可达。
      set({ loading: false, loadError: true });
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
