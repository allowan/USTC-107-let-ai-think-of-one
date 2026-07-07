export interface UserInfo {
  user_id: string;
  username: string;
  is_admin?: boolean;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: number;
}

export interface FileInfo {
  name: string;
  path: string;
  type: 'file' | 'directory';
  size?: number;
}

export interface LoginForm {
  username: string;
  password: string;
}
