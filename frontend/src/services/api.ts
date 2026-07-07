import axios from 'axios';

const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      localStorage.removeItem('token');
      localStorage.removeItem('user');
      window.location.href = '/login';
    }
    return Promise.reject(err);
  },
);

export const authApi = {
  login: (username: string, password: string) =>
    api.post<{ token: string; user_id: string; username: string; is_admin?: boolean }>('/auth/login', { username, password }),

  register: (username: string, password: string) =>
    api.post<{ token: string; user_id: string; username: string; is_admin?: boolean }>('/auth/register', { username, password }),
};

export const chatApi = {
  getWebSocketUrl: () => {
    const token = localStorage.getItem('token');
    const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
    return `${protocol}://${window.location.host}/ws/chat?token=${token}`;
  },
};

export const fileApi = {
  list: (dirPath?: string) =>
    api.get<{ files: import('@/types').FileInfo[] }>('/files/list', { params: { path: dirPath } }),

  read: (filePath: string) =>
    api.get<{ content: string; path: string }>('/files/read', { params: { path: filePath } }),

  write: (filePath: string, content: string) =>
    api.post<{ message: string }>('/files/write', { path: filePath, content }),

  delete: (filePath: string) =>
    api.delete<{ message: string }>('/files/delete', { params: { path: filePath } }),

  upload: (file: File, destDir?: string) => {
    const form = new FormData();
    form.append('file', file);
    const params = destDir ? `?dest_dir=${encodeURIComponent(destDir)}` : '';
    return api.post<{ message: string; path: string }>(`/files/upload${params}`, form);
  },
};

export const searchApi = {
  notices: (query: string) =>
    api.get<{ query: string; results: string }>('/search/notices', { params: { q: query } }),
};

export const adminApi = {
  getUsers: () =>
    api.get<{ users: Array<{ username: string; is_admin: boolean; index_size: number }> }>('/admin/users'),

  deleteUser: (username: string) =>
    api.delete<{ message: string }>(`/admin/users/${encodeURIComponent(username)}`),

  getNotices: () =>
    api.get<{ notices: Array<{ source: string; preview: string }> }>('/admin/notices'),

  addNotice: (content: string, source?: string) =>
    api.post<{ message: string }>('/admin/notices', { content, source }),

  deleteNotice: (source: string) =>
    api.delete<{ message: string }>(`/admin/notices/${encodeURIComponent(source)}`),

  getStats: () =>
    api.get<{ user_count: number; public_doc_count: number; user_collections_count: number; agent_ready: boolean }>('/admin/stats'),
};

export default api;
