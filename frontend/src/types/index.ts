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
  runtime?: {
    effective_model: string;
    model_source: 'settings' | 'environment';
    model_locked: boolean;
  };
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

export interface ScheduleCourse {
  id: number;
  semester: string;
  course_code: string;
  name: string;
  teachers: string[];
  weekday: number | null;
  start_section: number | null;
  end_section: number | null;
  weeks: number[];
  location: string;
  credits: number | null;
  start_time: string | null;
  end_time: string | null;
  raw_schedule: string;
  updated_at: string;
}

export interface ScheduleData {
  semester: string | null;
  semesters: string[];
  courses: ScheduleCourse[];
}

export interface ScheduleMeetingInput {
  weekday?: number | null;
  sections?: number[];
  weeks?: number[];
  location?: string;
  start_time?: string | null;
  end_time?: string | null;
}

export interface ScheduleCourseInput {
  course_code?: string;
  name: string;
  teachers?: string[];
  credits?: number | null;
  raw_schedule?: string;
  meetings?: ScheduleMeetingInput[];
}

export interface ScheduleImportPayload {
  semester: string;
  courses: ScheduleCourseInput[];
}

export interface DigestEvent {
  source: string;
  title: string | null;
  category: string | null;
  audience: string | null;
  publish_date: string | null;
  deadline: string | null;
  deadline_text: string | null;
  event_start: string | null;
  event_end: string | null;
  location: string | null;
  url: string | null;
  kind?: 'deadline' | 'start';
  /** 开始型事件中，开始日已过、尚未结束的事件（展览/施工等长期事件） */
  ongoing?: boolean;
  days_left?: number;
  days_since?: number;
}

export interface DigestData {
  generated_on: string;
  days: number;
  upcoming: DigestEvent[];
  recent: DigestEvent[];
}

export interface TrackedEvent {
  source: string;
  title: string | null;
  category: string | null;
  date_kind: 'deadline' | 'start';
  date_value: string | null;
  url: string | null;
  created_at: string;
}
