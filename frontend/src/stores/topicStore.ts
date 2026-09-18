import { create } from 'zustand';
import type { NoticeContext, TopicInfo } from '@/types';
import { topicApi } from '@/services/api';
import { buildNoticePrompt } from '@/utils/noticeAssistant';

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
  noticeCreating: boolean;
  noticeContexts: Record<string, NoticeContext>;
  noticeDraft: { topicId: string; content: string } | null;
  createNoticeTopic: (notice: NoticeContext) => Promise<string>;
  consumeNoticeDraft: (topicId: string) => void;
}

export const useTopicStore = create<TopicState>((set, get) => ({
  topics: [],
  activeTopicId: '',
  loading: false,
  loaded: false,
  loadError: false,
  noticeCreating: false,
  noticeContexts: {},
  noticeDraft: null,

  createNoticeTopic: async (notice) => {
    if (get().noticeCreating) throw new Error('正在创建通知话题，请稍候');
    const content = buildNoticePrompt(notice);
    set({ noticeCreating: true });
    try {
      const { data } = await topicApi.create(`办理：${notice.title}`.slice(0, 80));
      set(state => ({ topics: [data, ...state.topics], activeTopicId: data.id,
        noticeContexts: { ...state.noticeContexts, [data.id]: { ...notice } },
        noticeDraft: { topicId: data.id, content } }));
      return data.id;
    } finally {
      set({ noticeCreating: false });
    }
  },

  consumeNoticeDraft: (topicId) => {
    if (get().noticeDraft?.topicId === topicId) set({ noticeDraft: null });
  },

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
