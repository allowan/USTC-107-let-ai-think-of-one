import { useCallback, useEffect, useState } from 'react';
import { Alert, Button, Card, Checkbox, Empty, Space, Spin, Typography } from 'antd';
import { DownloadOutlined, ReloadOutlined } from '@ant-design/icons';
import axios from 'axios';
import { backupApi } from '@/services/api';
import type { BackupCatalog } from '@/types';

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

  return <div style={{ maxWidth: 1000, margin: '0 auto' }}>
    <Typography.Title level={4}>个人备份</Typography.Title>
    <Alert showIcon type="info" message="只备份你选择的对话和文字资料"
      description="包含话题名称、用户与助手的可见文本、个人资料文字。配置、密钥文件、工具内部记录、向量索引和原始附件不进入备份。正文中的已配置凭据及常见密钥格式会脱敏；未标识的私人信息仍需你核对。" style={{ marginBottom: 16 }} />
    {error && <Alert showIcon type="error" message={error} style={{ marginBottom: 12 }} />}
    {success && <Alert showIcon type="success" message="备份文件已生成，请在浏览器下载列表确认保存成功" style={{ marginBottom: 12 }} />}
    {catalog.errors.map(item => <Alert showIcon type="warning" key={item} message={item} style={{ marginBottom: 12 }} />)}
    <Space wrap style={{ marginBottom: 16 }}>
      <Button icon={<ReloadOutlined />} loading={loading} disabled={exporting} onClick={() => void load()}>刷新列表</Button>
      <Button type="primary" icon={<DownloadOutlined />} loading={exporting}
        disabled={loading || topicIds.length + documentIds.length === 0} onClick={() => void exportData()}>导出所选内容</Button>
      <Typography.Text type="secondary">已选 {topicIds.length} 个话题、{documentIds.length} 份资料</Typography.Text>
    </Space>
    <Spin spinning={loading}>
      <Card title={`对话（${catalog.topics.length}）`} style={{ marginBottom: 16 }}
        extra={<Button type="link" disabled={loading || exporting} onClick={() => setTopicIds(topicIds.length === catalog.topics.length ? [] : catalog.topics.map(item => item.id))}>全选 / 清空</Button>}>
        {catalog.topics.length === 0 ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无可导出的对话" /> :
          <Checkbox.Group value={topicIds} disabled={exporting} onChange={setTopicIds} style={{ display: 'flex', flexDirection: 'column', gap: 12 }}
            options={catalog.topics.map(item => ({ value: item.id, label: item.name }))} />}
      </Card>
      <Card title={`个人资料（${catalog.documents.length}）`}
        extra={<Button type="link" disabled={loading || exporting} onClick={() => setDocumentIds(documentIds.length === catalog.documents.length ? [] : catalog.documents.map(item => item.id))}>全选 / 清空</Button>}>
        {catalog.documents.length === 0 ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无可导出的资料" /> :
          <Checkbox.Group value={documentIds} disabled={exporting} onChange={setDocumentIds} style={{ display: 'flex', flexDirection: 'column', gap: 12 }}
            options={catalog.documents.map(item => ({ value: item.id, label: `${item.name}（${item.characters} 字符）` }))} />}
      </Card>
    </Spin>
  </div>;
}
