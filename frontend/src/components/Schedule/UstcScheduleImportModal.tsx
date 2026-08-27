import { useRef, useState } from 'react';
import { Alert, App, Button, Input, Modal, Space, Typography } from 'antd';
import { ExportOutlined, FileTextOutlined } from '@ant-design/icons';
import axios from 'axios';
import { scheduleApi } from '@/services/api';

const { Text, Paragraph } = Typography;
const { TextArea } = Input;
const USTC_ORIGIN = 'https://jw.ustc.edu.cn';

export interface UstcScheduleImportResult {
  semester: string;
  course_count: number;
  meeting_count: number;
}

interface Props {
  open: boolean;
  onCancel: () => void;
  onImported: (result: UstcScheduleImportResult) => void;
}

function getErrorMessage(error: unknown, fallback: string): string {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    if (typeof detail === 'string' && detail) return detail;
  }
  return error instanceof Error ? error.message : fallback;
}

export default function UstcScheduleImportModal({ open, onCancel, onImported }: Props) {
  const { message } = App.useApp();
  const [content, setContent] = useState('');
  const [filename, setFilename] = useState('');
  const [loading, setLoading] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const reset = () => {
    setContent('');
    setFilename('');
  };

  const close = () => {
    if (loading) return;
    reset();
    onCancel();
  };

  const readFile = async (file: File) => {
    try {
      setContent(await file.text());
      setFilename(file.name);
    } catch {
      message.error('读取课表文件失败');
    }
  };

  const submit = async () => {
    if (!content.trim()) {
      message.warning('请先选择课表 HTML/JSON 文件，或粘贴课表内容');
      return;
    }
    setLoading(true);
    try {
      const response = await scheduleApi.importUstc(content, filename);
      const result = response.data;
      message.success(`已导入 ${result.course_count} 门课程`);
      onImported(result);
      reset();
      onCancel();
    } catch (error) {
      message.error(getErrorMessage(error, '教务课表解析失败'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <Modal
      title="获取并导入教务课表"
      open={open}
      onCancel={close}
      onOk={() => void submit()}
      okText="解析并导入"
      cancelText="取消"
      confirmLoading={loading}
      destroyOnClose
      width={720}
    >
      <Alert
        type="info"
        showIcon
        message="使用中国科大教务系统的课表页面"
        description={(
          <Paragraph style={{ margin: 0 }}>
            在教务系统打开“我的课表”（页面地址为 <Text code>/for-std/course-table</Text>），
            等待课表加载完成后，在开发者工具 Console 执行 <Text code>copy(document.documentElement.outerHTML)</Text>，
            再将内容粘贴到这里；也可以选择 HTML/JSON 文件。
          </Paragraph>
        )}
        style={{ marginBottom: 16 }}
      />
      <Space wrap style={{ marginBottom: 12 }}>
        <Button icon={<ExportOutlined />} onClick={() => window.open(`${USTC_ORIGIN}/for-std/course-table`, '_blank')}>
          打开教务课表
        </Button>
        <Button icon={<FileTextOutlined />} onClick={() => fileInput.current?.click()}>
          选择 HTML/JSON 文件
        </Button>
        {filename && <Text type="secondary">已选择：{filename}</Text>}
        <input
          ref={fileInput}
          type="file"
          accept=".html,.htm,.json,text/html,application/json"
          hidden
          onChange={(event) => {
            const file = event.target.files?.[0];
            event.target.value = '';
            if (file) void readFile(file);
          }}
        />
      </Space>
      <TextArea
        value={content}
        onChange={(event) => setContent(event.target.value)}
        placeholder="将教务课表页面 HTML 或结构化 JSON 粘贴到这里"
        rows={12}
        spellCheck={false}
      />
      <Text type="secondary" style={{ display: 'block', marginTop: 8 }}>
        只读取你主动选择或粘贴的内容；本地应用不会保存教务系统账号、密码或浏览器 Cookie。
      </Text>
    </Modal>
  );
}
