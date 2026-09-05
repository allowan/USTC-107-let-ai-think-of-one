import { useState, useEffect } from 'react';
import { Button, Input, Modal, Popconfirm, App, Empty, Card, Space, Typography, Segmented, Upload, Alert } from 'antd';
import { InboxOutlined, CalendarOutlined, PlusOutlined, EditOutlined, DeleteOutlined, DatabaseOutlined } from '@ant-design/icons';
import { personalDataApi } from '@/services/api';
import type { PersonalDataItem } from '@/types';
import ImportExistingScheduleModal from '@/components/Schedule/ImportExistingScheduleModal';

const { TextArea } = Input;
const { Text, Paragraph } = Typography;

// 后端 detail（如嵌入服务不可用的 503 守卫说明）是可操作信息，
// 一律优先展示而非吞成通用文案；非 axios 错误回退默认文案。
const errDetail = (e: unknown, fallback: string): string => {
  if (e && typeof e === 'object' && 'response' in e) {
    const detail = (e as { response?: { data?: { detail?: string } } }).response?.data?.detail;
    if (detail) return String(detail);
  }
  return fallback;
};

export default function PersonalDataPage() {
  const { message } = App.useApp();
  const [items, setItems] = useState<PersonalDataItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [addVisible, setAddVisible] = useState(false);
  const [editVisible, setEditVisible] = useState(false);
  const [newContent, setNewContent] = useState('');
  const [newSource, setNewSource] = useState('');
  const [editSource, setEditSource] = useState('');
  const [editContent, setEditContent] = useState('');
  const [saving, setSaving] = useState(false);
  const [addMode, setAddMode] = useState<'text' | 'file'>('text');
  const [parsing, setParsing] = useState(false);
  const [fileName, setFileName] = useState('');
  const [fileError, setFileError] = useState('');

  const resetAdd = () => {
    setAddVisible(false);
    setNewContent('');
    setNewSource('');
    setFileName('');
    setFileError('');
    setAddMode('text');
  };

  const parseFile = async (file: File) => {
    if (file.size > 10 * 1024 * 1024) {
      setFileError('文件不能超过 10 MB');
      return false;
    }
    setParsing(true);
    setFileError('');
    try {
      const { data } = await personalDataApi.parseFile(file);
      setNewContent(data.content);
      setNewSource(data.source);
      setFileName(data.filename);
    } catch (e) {
      setFileError(errDetail(e, '文件解析失败，请检查文件后重试'));
    } finally {
      setParsing(false);
    }
    return false;
  };
  const [scheduleImportVisible, setScheduleImportVisible] = useState(false);

  const fetchData = () => {
    setLoading(true);
    personalDataApi.list()
      .then(({ data }) => setItems(data.items))
      .catch(() => message.error('获取个人数据失败'))
      .finally(() => setLoading(false));
  };

  useEffect(() => { fetchData(); }, []);

  const handleAdd = async () => {
    if (!newContent.trim()) {
      message.warning('请输入内容');
      return;
    }
    setSaving(true);
    try {
      await personalDataApi.add(newContent, newSource.trim() || undefined);
      message.success('数据已添加');
      resetAdd();
      fetchData();
    } catch (e) {
      message.error(errDetail(e, '添加失败'));
    } finally {
      setSaving(false);
    }
  };

  const handleEdit = async () => {
    if (!editContent.trim()) {
      message.warning('请输入内容');
      return;
    }
    setSaving(true);
    try {
      await personalDataApi.update(editSource, editContent);
      message.success('数据已更新');
      setEditVisible(false);
      fetchData();
    } catch (e) {
      message.error(errDetail(e, '更新失败'));
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (source: string) => {
    try {
      await personalDataApi.delete(source);
      message.success('数据已删除');
      fetchData();
    } catch {
      message.error('删除失败');
    }
  };

  const openEdit = (item: PersonalDataItem) => {
    setEditSource(item.source);
    setEditContent(item.full_content);
    setEditVisible(true);
  };

  return (
    <div style={{ maxWidth: 800, margin: '0 auto' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <Text strong style={{ fontSize: 18 }}>个人数据</Text>
        <Space>
          <Button icon={<CalendarOutlined />} onClick={() => setScheduleImportVisible(true)}>
            导入已有课表
          </Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setAddVisible(true)}>
            添加数据
          </Button>
        </Space>
      </div>

      {items.length === 0 && !loading ? (
        <Empty description="暂无个人数据，点击上方按钮添加" />
      ) : (
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          {items.map((item) => (
            <Card
              key={item.source}
              size="small"
              title={
                <Space>
                  <DatabaseOutlined />
                  <Text strong>{item.source}</Text>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    ({item.chunks} 个片段)
                  </Text>
                </Space>
              }
              extra={
                <Space>
                  <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(item)}>
                    编辑
                  </Button>
                  <Popconfirm
                    title="确定删除此数据？"
                    onConfirm={() => handleDelete(item.source)}
                  >
                    <Button size="small" danger icon={<DeleteOutlined />}>
                      删除
                    </Button>
                  </Popconfirm>
                </Space>
              }
            >
              <Paragraph ellipsis={{ rows: 4, expandable: true, symbol: '展开' }} style={{ margin: 0, whiteSpace: 'pre-wrap' }}>
                {item.full_content}
              </Paragraph>
            </Card>
          ))}
        </Space>
      )}

      {/* Add modal */}
      <Modal
        title="添加个人数据"
        open={addVisible}
        onOk={handleAdd}
        onCancel={() => { if (!saving && !parsing) resetAdd(); }}
        closable={!saving && !parsing}
        maskClosable={!saving && !parsing}
        keyboard={!saving && !parsing}
        cancelButtonProps={{ disabled: saving || parsing }}
        okButtonProps={{ disabled: parsing || !newContent.trim() }}
        styles={{ body: { maxHeight: '65vh', overflowY: 'auto' } }}
        width={640}
        confirmLoading={saving}
        okText="添加"
        cancelText="取消"
        destroyOnClose
      >
        <Segmented
          aria-label="添加方式"
          options={[{ label: '输入文本', value: 'text' }, { label: '上传文件', value: 'file' }]}
          value={addMode}
          onChange={value => setAddMode(value as 'text' | 'file')}
          disabled={saving || parsing}
          style={{ marginBottom: 16 }}
        />
        {addMode === 'file' && <div style={{ marginBottom: 16 }}>
          <Upload.Dragger
            accept=".txt,.md,.markdown,.csv,.json,.pdf,.docx"
            multiple={false}
            showUploadList={false}
            beforeUpload={parseFile}
            disabled={saving || parsing}
          >
            <p className="ant-upload-drag-icon"><InboxOutlined /></p>
            <p className="ant-upload-text">{parsing ? '正在解析文件…' : '点击或拖拽文件到这里'}</p>
            <p className="ant-upload-hint">TXT、Markdown、CSV、JSON、PDF、DOCX；单个文件不超过 10 MB</p>
          </Upload.Dragger>
          <Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 8 }}>解析后可检查并修改下方内容，点击“添加”才会存入个人知识库。仅导入文本，不保存原始附件；暂不支持图片和扫描件文字识别。</Paragraph>
          {fileName && <Text>已解析：{fileName}（当前 {newContent.length} 字符）</Text>}
          {fileError && <Alert type="error" showIcon message={fileError} style={{ marginTop: 8 }} />}
        </div>}
        <Input
          aria-label="数据来源"
          disabled={saving || parsing}
          value={newSource}
          onChange={(e) => setNewSource(e.target.value)}
          placeholder="数据来源（可选，如：课表、成绩单）"
          style={{ marginBottom: 12 }}
        />
        <TextArea
          aria-label="个人数据内容"
          disabled={saving || parsing}
          value={newContent}
          onChange={(e) => setNewContent(e.target.value)}
          placeholder="输入要存储的数据内容..."
          rows={8}
        />
      </Modal>

      {/* Edit modal */}
      <Modal
        title={`编辑 — ${editSource}`}
        open={editVisible}
        onOk={handleEdit}
        onCancel={() => setEditVisible(false)}
        confirmLoading={saving}
        okText="保存"
        cancelText="取消"
        destroyOnClose
        width={640}
      >
        <TextArea
          value={editContent}
          onChange={(e) => setEditContent(e.target.value)}
          placeholder="编辑数据内容..."
          rows={12}
        />
      </Modal>

      <ImportExistingScheduleModal
        open={scheduleImportVisible}
        onCancel={() => setScheduleImportVisible(false)}
        onImported={() => fetchData()}
      />
    </div>
  );
}
