export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: number;
}

export interface TopicInfo {
  id: string;
  name: string;
  thread_id: string;
}

export interface ToolSetting {
  name: string;
  label: string;
  description: string;
  enabled: boolean;
}

export interface ModelInfo {
  request_id: string;
  show_id: string;
  toolCalling: boolean;
  vision: boolean;
}

export interface ModelGroup {
  group_name: string;
  vendor: string;
  api_key?: string;
  api_type?: string;
  base_url?: string;
  models: ModelInfo[];
}

export interface GlobalSettings {
  env: {
    api_key: string;
    base_url: string;
    model: string;
    api_type: string;
  };
  groups: ModelGroup[];
}

export interface PersonalDataItem {
  source: string;
  preview: string;
  full_content: string;
  chunks: number;
}

export interface SyncStatus {
  local_version: number;
  remote_version: number;
  needs_sync: boolean;
  server_online: boolean;
}

export interface SyncResult {
  status: 'ok' | 'error';
  message: string;
  version?: number;
  upserted?: number;
  deleted?: number;
  document_count?: number;
}
