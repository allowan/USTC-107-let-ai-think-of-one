import { useCallback, useEffect, useRef, useState } from 'react';
import { Alert, Button, Card, Checkbox, Empty, Modal, Space, Spin, Typography } from 'antd';
import { DownloadOutlined, ReloadOutlined, UploadOutlined } from '@ant-design/icons';
import axios from 'axios';
import { backupApi } from '@/services/api';
import type { BackupCatalog, BackupRestorePreview, BackupRestoreResult } from '@/types';
import { useTopicStore } from '@/stores/topicStore';

async function errorMessage(error: unknown): Promise<string> {
  if (axios.isAxiosError(error)) {
    let data = error.response?.data;
    if (data instanceof Blob) {
      try { data = JSON.parse(await data.text()); }
      catch { return '备份请求失败，请重启后端后重试'; }
    }
    if (typeof data?.detail === 'string') return data.detail;
  }
  return '备份操作失败，请确认后端可用后重试';
}

function download(content: Blob): void {
  const url = URL.createObjectURL(content);
  const link = document.createElement('a');
  link.href = url;
  link.download = `campus-backup-${new Date().toISOString().replace(/[:.]/g, '-')}.json`;
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export default function BackupPage() {
  const [catalog, setCatalog] = useState<BackupCatalog>({ topics: [], documents: [], errors: [] });
  const [topicIds, setTopicIds] = useState<string[]>([]);
  const [documentIds, setDocumentIds] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [backupFile, setBackupFile] = useState<File | null>(null);
  const [restorePreview, setRestorePreview] = useState<BackupRestorePreview | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [restoring, setRestoring] = useState(false);
  const [restoreError, setRestoreError] = useState<string | null>(null);
  const [restoreResult, setRestoreResult] = useState<BackupRestoreResult | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const busy = loading || exporting || previewing || restoring;
  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await backupApi.catalog();
      setCatalog(response.data);
      setTopicIds([]);
      setDocumentIds([]);
    } catch (reason) { setError(await errorMessage(reason)); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const exportData = async () => {
    setExporting(true);
    setError(null);
    setSuccess(false);
    try {
      const response = await backupApi.export(topicIds, documentIds);
      download(response.data);
      setSuccess(true);
    } catch (reason) { setError(await errorMessage(reason)); }
    finally { setExporting(false); }
  };

  const previewFile = async (file: File) => {
    setBackupFile(null);
    setRestorePreview(null);
    setRestoreError(null);
    setRestoreResult(null);
    if (file.size > 20 * 1024 * 1024) {
      setRestoreError('备份文件不能超过20 MB');
      return;
    }
    setPreviewing(true);
    try {
      const response = await backupApi.preview(file);
      setBackupFile(file);
      setRestorePreview(response.data);
    } catch (reason) { setRestoreError(await errorMessage(reason)); }
    finally { setPreviewing(false); }
  };

  const restoreData = async () => {
    if (!backupFile || !restorePreview || restoring) return;
    setRestoring(true);
    setRestoreError(null);
    try {
      const response = await backupApi.restore(backupFile, restorePreview.checksum);
      setRestoreResult(response.data);
      if (!response.data.failed) { setRestorePreview(null); setBackupFile(null); }
      await useTopicStore.getState().fetchTopics();
      await load();
    } catch (reason) { setRestoreError(await errorMessage(reason)); }
    finally { setRestoring(false); }
  };

  const resultSummary = restoreResult ? <Alert showIcon type={restoreResult.failed ? 'warning' : 'success'}
    message={`已恢复 ${restoreResult.restored} 项，跳过已存在 ${restoreResult.skipped} 项，失败 ${restoreResult.failed} 项`}
    description={restoreResult.failed > 0 ? <ul>{restoreResult.results.filter(item => item.status === 'failed').map((item, index) =>
      <li key={index}>{item.name}：{item.message}</li>)}</ul> : '原有对话和资料保持不变。'} style={{ marginBottom: 12 }} /> : null;

  return <div style={{ maxWidth: 1000, margin: '0 auto' }}>
    <Typography.Title level={4}>个人备份</Typography.Title>
    <Alert showIcon type="info" message="只备份你选择的对话和文字资料"
      description="包含话题名称、用户与助手的可见文本、个人资料文字。配置、密钥文件、工具内部记录、向量索引和原始附件不进入备份。正文中的已配置凭据及常见密钥格式会脱敏；未标识的私人信息仍需你核对。" style={{ marginBottom: 16 }} />
    <Card title="从备份恢复" style={{ marginBottom: 16 }}>
      <Space direction="vertical" style={{ width: '100%' }}>
        <Typography.Text>选择本应用导出的 JSON，先核对内容，再恢复为新副本。重复恢复会跳过已有副本。</Typography.Text>
        <Button icon={<UploadOutlined />} loading={previewing} disabled={busy} onClick={() => fileInput.current?.click()}>选择备份文件</Button>
        <input type="file" accept=".json,application/json" hidden ref={fileInput} disabled={busy} onChange={event => {
          const file = event.target.files?.[0];
          event.target.value = '';
          if (file) void previewFile(file);
        }} />
        {restoreError && <Alert type="error" showIcon message={restoreError} />}
        {resultSummary}
      </Space>
    </Card>
    {error && <Alert showIcon type="error" message={error} style={{ marginBottom: 12 }} />}
    {success && <Alert showIcon type="success" message="备份文件已生成，请在浏览器下载列表确认保存成功" style={{ marginBottom: 12 }} />}
    {catalog.errors.map(item => <Alert showIcon type="warning" key={item} message={item} style={{ marginBottom: 12 }} />)}
    <Space wrap style={{ marginBottom: 16 }}>
      <Button icon={<ReloadOutlined />} loading={loading} disabled={exporting || previewing || restoring} onClick={() => void load()}>刷新列表</Button>
      <Button type="primary" icon={<DownloadOutlined />} loading={exporting}
        disabled={busy || topicIds.length + documentIds.length === 0} onClick={() => void exportData()}>导出所选内容</Button>
      <Typography.Text type="secondary">已选 {topicIds.length} 个话题、{documentIds.length} 份资料</Typography.Text>
    </Space>
    <Spin spinning={loading}>
      <Card title={`对话（${catalog.topics.length}）`} style={{ marginBottom: 16 }}
        extra={<Button type="link" disabled={busy} onClick={() => setTopicIds(topicIds.length === catalog.topics.length ? [] : catalog.topics.map(item => item.id))}>全选 / 清空</Button>}>
        {catalog.topics.length === 0 ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无可导出的对话" /> :
          <Checkbox.Group value={topicIds} disabled={busy} onChange={setTopicIds} style={{ display: 'flex', flexDirection: 'column', gap: 12 }}
            options={catalog.topics.map(item => ({ value: item.id, label: item.name }))} />}
      </Card>
      <Card title={`个人资料（${catalog.documents.length}）`}
        extra={<Button type="link" disabled={busy} onClick={() => setDocumentIds(documentIds.length === catalog.documents.length ? [] : catalog.documents.map(item => item.id))}>全选 / 清空</Button>}>
        {catalog.documents.length === 0 ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无可导出的资料" /> :
          <Checkbox.Group value={documentIds} disabled={busy} onChange={setDocumentIds} style={{ display: 'flex', flexDirection: 'column', gap: 12 }}
            options={catalog.documents.map(item => ({ value: item.id, label: `${item.name}（${item.characters} 字符）` }))} />}
      </Card>
    </Spin>
    <Modal title="确认恢复为新副本" open={restorePreview !== null}
      onCancel={() => { if (!restoring) { setRestorePreview(null); setBackupFile(null); } }}
      onOk={() => void restoreData()} okText={restoreResult?.failed ? '重试失败项' : '确认恢复'}
      confirmLoading={restoring} cancelButtonProps={{ disabled: restoring }} closable={!restoring} maskClosable={!restoring} width={720}>
      {restorePreview && <>
        <Alert showIcon type="info" message={`备份包含 ${restorePreview.topics.length} 个话题、${restorePreview.documents.length} 份资料`}
          description="恢复会新建副本，保留已有内容；已恢复项不会被重复写入。" style={{ marginBottom: 12 }} />
        {restorePreview.documents.length > 0 && <Alert showIcon type="warning" message="资料恢复会调用当前配置的嵌入服务"
          description="如果使用远程嵌入服务，资料文字会发送至该服务。资料失败项可重试；对话恢复不需要模型服务。" style={{ marginBottom: 12 }} />}
        <div style={{ maxHeight: 280, overflowY: 'auto' }}>
          <ul>{restorePreview.topics.map((item, index) => <li key={`topic-${index}`}>对话：{item.name}（{item.message_count} 条消息）</li>)}
            {restorePreview.documents.map((item, index) => <li key={`doc-${index}`}>资料：{item.source}（{item.characters} 字符）</li>)}</ul>
        </div>
        {restoreError && <Alert type="error" showIcon message={restoreError} style={{ marginBottom: 12 }} />}
        {resultSummary}
      </>}
    </Modal>
  </div>;
}
