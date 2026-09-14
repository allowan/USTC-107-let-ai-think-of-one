import { useRef, useState } from 'react';
import { Alert, App, Button, Input, Modal, Space, Typography } from 'antd';
import { ExportOutlined, FileTextOutlined } from '@ant-design/icons';
import { scheduleImportError } from '@/utils/scheduleImport';
import { scheduleApi } from '@/services/api';
import type { ScheduleImportPreview } from '@/types';
import ScheduleImportPreviewModal from '@/components/Schedule/ScheduleImportPreviewModal';

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

export default function UstcScheduleImportModal({ open, onCancel, onImported }: Props) {
  const { message } = App.useApp();
  const [content, setContent] = useState('');
  const [filename, setFilename] = useState('');
  const [loading, setLoading] = useState(false);
  const [preview, setPreview] = useState<ScheduleImportPreview | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const reset = () => {
    setContent('');
    setFilename('');
    setPreview(null);
    setSaveError(null);
  };

  const close = () => {
    if (loading) return;
    reset();
    onCancel();
  };

  const readFile = async (file: File) => {
    if (file.size > 5_000_000) {
      message.error('课表文件不能超过 5 MB');
      return;
    }
    setLoading(true);
    try {
      setContent(await file.text());
      setFilename(file.name);
    } catch {
      message.error('读取课表文件失败');
    } finally {
      setLoading(false);
    }
  };

  const submit = async () => {
    if (!content.trim()) {
      message.warning('请先选择课表 HTML/JSON 文件，或粘贴课表内容');
      return;
    }
    setLoading(true);
    try {
      const response = await scheduleApi.previewUstc(content, filename);
      setSaveError(null);
      setPreview(response.data);
    } catch (error) {
      message.error(scheduleImportError(error, '教务课表解析失败'));
    } finally {
      setLoading(false);
    }
  };

  const confirmImport = async () => {
    if (!preview || preview.errors.length || loading) return;
    setLoading(true);
    setSaveError(null);
    try {
      const response = await scheduleApi.import(preview.payload);
      message.success(`已导入 ${preview.course_count} 门课程`);
      onImported({ ...response.data, course_count: preview.course_count });
      reset();
      onCancel();
    } catch (error) {
      setSaveError(scheduleImportError(error, '课表保存失败，请重试'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
    <Modal
      title="获取并导入教务课表"
      open={open && preview === null}
      onCancel={close}
      onOk={() => void submit()}
      okText="解析并预览"
      okButtonProps={{ disabled: !content.trim() }}
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
        <Button icon={<FileTextOutlined />} disabled={loading} onClick={() => fileInput.current?.click()}>
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
        disabled={loading}
        onChange={(event) => setContent(event.target.value)}
        placeholder="将教务课表页面 HTML 或结构化 JSON 粘贴到这里"
        rows={12}
        spellCheck={false}
      />
      <Text type="secondary" style={{ display: 'block', marginTop: 8 }}>
        只读取你主动选择或粘贴的内容；本地应用不会保存教务系统账号、密码或浏览器 Cookie。
      </Text>
    </Modal>
    <ScheduleImportPreviewModal
      preview={open ? preview : null}
      saving={loading}
      error={saveError}
      onConfirm={() => void confirmImport()}
      onCancel={() => { setPreview(null); setSaveError(null); }}
    />
    </>
  );
}
