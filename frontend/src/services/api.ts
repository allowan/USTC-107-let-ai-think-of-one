import axios from 'axios';

const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
});

export const topicApi = {
  list: () =>
    api.get<{ topics: import('@/types').TopicInfo[] }>('/topics'),

  create: (name: string) =>
    api.post<import('@/types').TopicInfo>('/topics', { name }),

  delete: (topicId: string) =>
    api.delete<{ message: string }>(`/topics/${topicId}`),

  rename: (topicId: string, name: string) =>
    api.put<{ message: string; name: string }>(`/topics/${topicId}`, { name }),

  summarize: (topicId: string, userMessage: string, aiMessage: string) =>
    api.post<{ name: string }>(`/topics/${topicId}/summarize`, {
      user_message: userMessage,
      ai_message: aiMessage,
    }),

  getHistory: (topicId: string) =>
    api.get<{ messages: Array<{ role: 'user' | 'assistant'; content: string }> }>(`/topics/${topicId}/history`),
};

export const settingsApi = {
  getGlobal: () =>
    api.get<import('@/types').GlobalSettings>('/settings'),

  updateGlobal: (data: { api_key?: string; base_url?: string; api_type?: string }) =>
    api.put<{ message: string }>('/settings', data),

  switchModel: (group: string, model: string) =>
    api.post<{ message: string; model: string }>('/settings/model', { group, model }),

  getTools: () =>
    api.get<{ tools: import('@/types').ToolSetting[] }>('/settings/tools'),

  updateTools: (tools: Record<string, boolean>) =>
    api.put<{ message: string }>('/settings/tools', { tools }),
};

export const syncApi = {
  getStatus: () =>
    api.get<import('@/types').SyncStatus>('/sync/status'),

  // 全量同步包含逐篇嵌入写入，耗时可能远超全局 30s 超时；
  // 若前端提前断开会误报"同步失败"而后端实际继续完成，造成状态认知错乱。
  syncNow: () =>
    api.post<import('@/types').SyncResult>('/sync/now', {}, { timeout: 0 }),
};

export const personalDataApi = {
  list: () =>
    api.get<{ items: import('@/types').PersonalDataItem[] }>('/personal-data'),

  add: (content: string, source?: string) =>
    api.post<{ message: string }>('/personal-data', { content, source }),

  update: (source: string, content: string) =>
    api.put<{ message: string }>(`/personal-data/${encodeURIComponent(source)}`, { content }),

  delete: (source: string) =>
    api.delete<{ message: string }>(`/personal-data/${encodeURIComponent(source)}`),

  importExistingSchedule: (semester?: string) =>
    api.post<{
      message: string;
      semester: string;
      source: string;
      course_count: number;
      meeting_count: number;
    }>('/personal-data/import-schedule', { semester: semester || '' }),
};

export const scheduleApi = {
  list: (semester?: string) =>
    api.get<import('@/types').ScheduleData>('/schedule', { params: semester ? { semester } : {} }),
  import: (payload: import('@/types').ScheduleImportPayload) =>
    api.post<{ message: string; semester: string; meeting_count: number }>('/schedule/import', payload),
  importUstc: (content: string, filename?: string) =>
    api.post<{
      message: string;
      semester: string;
      course_count: number;
      meeting_count: number;
    }>('/schedule/import-ustc', { content, filename: filename || '' }),
};

export const digestApi = {
  get: (days = 7) =>
    api.get<import('@/types').DigestData>('/digest', { params: { days } }),
};

export const trackApi = {
  list: () =>
    api.get<{ items: import('@/types').TrackedEvent[] }>('/digest/tracked'),
  add: (event: {
    source: string;
    title?: string | null;
    category?: string | null;
    date_kind: 'deadline' | 'start';
    date_value?: string | null;
    url?: string | null;
  }) => api.post<import('@/types').TrackedEvent>('/digest/tracked', event),
  remove: (source: string) =>
    api.delete<{ message: string }>(`/digest/tracked/${encodeURIComponent(source)}`),
};

export default api;
