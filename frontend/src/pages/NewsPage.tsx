import { useEffect, useState } from 'react';
import { Alert, Button, Card, Empty, Input, List, Select, Space, Tag, Typography } from 'antd';
import { ReloadOutlined, ExportOutlined } from '@ant-design/icons';
import api from '@/services/api';

type NewsItem = { title: string; url: string; source_id: string; source_name: string; source_url: string; published_at: string | null; date_label: string };
type NewsSource = { id: string; name: string; url: string; status: 'ok' | 'stale' | 'error'; updated_at: string | null };
type NewsData = { items: NewsItem[]; sources: NewsSource[] };

export default function NewsPage() {
  const [data, setData] = useState<NewsData>({ items: [], sources: [] });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [source, setSource] = useState('all');
  const [query, setQuery] = useState('');
  async function load(refresh = false) {
    setLoading(true);
    setError('');
    try {
      const response = await api.get<NewsData>('/news', { params: { refresh } });
      setData(response.data);
    } catch {
      setError('消息加载失败，请稍后重试。已有内容仍保留。');
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => { void load(); }, []);
  const items = data.items.filter(item => (source === 'all' || item.source_id === source) && item.title.toLowerCase().includes(query.trim().toLowerCase()));
  const failed = data.sources.filter(s => s.status !== 'ok');
  return (
    <div style={{ maxWidth: 1120, margin: '0 auto' }}>
      <Space style={{ width: '100%', justifyContent: 'space-between', marginBottom: 8 }} wrap>
        <Typography.Title level={2} style={{ margin: 0 }}>最新消息</Typography.Title>
        <Button icon={<ReloadOutlined />} loading={loading} onClick={() => void load(true)}>刷新消息</Button>
      </Space>
      <Typography.Paragraph type="secondary">汇集科大各平台公开消息。按发布日期倒序展示，每个平台最多 20 条；完整日期未知的消息置后。消息以来源原文为准。</Typography.Paragraph>
      {error && <Alert type="error" showIcon message={error} style={{ marginBottom: 16 }} />}
      {failed.length > 0 && <Alert type="warning" showIcon message="部分平台暂时无法更新" description={failed.map(s => `${s.name}：${s.status === 'stale' ? '显示上次成功获取的缓存' : '暂未获取到消息'}`).join('；')} style={{ marginBottom: 16 }} />}
      <Space wrap style={{ marginBottom: 20 }}>
        <Select aria-label="筛选消息平台" value={source} onChange={setSource} style={{ width: 220 }} options={[{ value: 'all', label: '全部平台' }, ...data.sources.map(s => ({ value: s.id, label: s.name }))]} />
        <Input.Search aria-label="搜索消息标题" placeholder="搜索消息标题" allowClear value={query} onChange={e => setQuery(e.target.value)} style={{ width: 260, maxWidth: '100%' }} />
        <Typography.Text type="secondary">共 {items.length} 条消息</Typography.Text>
      </Space>
      <Card styles={{ body: { padding: '0 24px' } }}>
        <List loading={loading} dataSource={items} pagination={items.length > 15 ? { pageSize: 15, showSizeChanger: false, hideOnSinglePage: true } : false} locale={{ emptyText: <Empty description={query || source !== 'all' ? '没有符合筛选条件的消息' : '暂无消息，请点击刷新消息重试'} /> }} renderItem={item => {
          const status = data.sources.find(s => s.id === item.source_id);
          return <List.Item key={item.url} style={{ padding: '20px 0' }}>
            <div style={{ width: '100%' }}>
              <a href={item.url} target="_blank" rel="noopener noreferrer" style={{ fontSize: 16, fontWeight: 500, lineHeight: 1.7 }}>{item.title} <ExportOutlined style={{ fontSize: 12 }} /></a>
              <Space wrap size={[12, 4]} style={{ display: 'flex', marginTop: 9, fontSize: 12 }}>
                <Typography.Text type="secondary">来源：<a href={item.source_url} target="_blank" rel="noopener noreferrer">{item.source_name}</a></Typography.Text>
                <Typography.Text type="secondary">发布：{item.date_label}</Typography.Text>
                {status?.status === 'stale' && <Tag color="orange">缓存消息</Tag>}
              </Space>
            </div>
          </List.Item>;
        }} />
      </Card>
      <div style={{ marginTop: 24 }}>
        <Typography.Text strong>来源与获取状态</Typography.Text>
        <Typography.Paragraph type="secondary" style={{ marginTop: 6 }}>页面缓存 5 分钟，点击刷新可重新获取。仅包含公开栏目，需登录的平台消息暂未接入。</Typography.Paragraph>
        <Space direction="vertical" size={8}>
          {data.sources.map(s => <Space key={s.id} wrap><a href={s.url} target="_blank" rel="noopener noreferrer">{s.name}</a><Tag color={s.status === 'ok' ? 'green' : 'orange'}>{s.status === 'ok' ? '已获取' : s.status === 'stale' ? '缓存' : '获取失败'}</Tag><Typography.Text type="secondary">{s.updated_at ? `最近成功获取：${new Date(s.updated_at).toLocaleString('zh-CN')}` : '尚无成功获取记录'}</Typography.Text></Space>)}
        </Space>
      </div>
    </div>
  );
}
