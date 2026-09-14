import { useState, useEffect, useCallback, useRef } from 'react';
import { Alert, Card, Button, Statistic, Row, Col, Typography, App, Spin, Tag, Descriptions } from 'antd';
import { SyncOutlined, CheckCircleOutlined, CloseCircleOutlined, CloudServerOutlined } from '@ant-design/icons';
import { syncApi } from '@/services/api';
import type { SyncStatus, SyncResult } from '@/types';

const { Text } = Typography;

export default function SyncPage() {
  const { message } = App.useApp();
  const [status, setStatus] = useState<SyncStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [result, setResult] = useState<SyncResult | null>(null);
  const [statusError, setStatusError] = useState(false);
  const mounted = useRef(false);
  const requestId = useRef(0);

  const fetchStatus = useCallback(async () => {
    const id = ++requestId.current;
    setLoading(true);
    try {
      const { data } = await syncApi.getStatus();
      if (!mounted.current || id !== requestId.current) return;
      setStatus(data);
      setStatusError(false);
    } catch {
      if (mounted.current && id === requestId.current) setStatusError(true);
    } finally {
      if (mounted.current && id === requestId.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    void fetchStatus();
    return () => { mounted.current = false; requestId.current++; };
  }, [fetchStatus]);

  const handleSync = async () => {
    if (statusError || loading || syncing || !status?.server_online) return;
    setSyncing(true);
    setResult(null);
    try {
      const { data } = await syncApi.syncNow();
      setResult(data);
      if (data.status === 'ok') {
        message.success(data.message);
      } else {
        message.error(data.message);
      }
      await fetchStatus();
    } catch {
      message.error('同步失败，请检查网络连接');
    } finally {
      setSyncing(false);
    }
  };

  if (loading && !status) {
    return (
      <div style={{ textAlign: 'center', padding: 60 }}>
        <Spin size="large" />
      </div>
    );
  }

  return (
    <div>
      <h2 style={{ marginBottom: 24 }}>数据同步</h2>
      {statusError && <Alert type="error" showIcon style={{ marginBottom: 16 }}
        message="状态获取失败"
        description={status ? '以下保留上次成功获取的状态，可能已过期。请重新获取后再同步。' : '无法获取同步状态，请检查本地后端并重试。'}
      />}
      <Button onClick={() => void fetchStatus()} loading={loading} disabled={syncing} style={{ marginBottom: 16 }}>
        重新获取状态
      </Button>

      <Row gutter={[24, 24]}>
        <Col xs={24} sm={12} lg={8}>
          <Card>
            <Statistic
              title={statusError && status ? '服务端状态（上次结果）' : '服务端状态'}
              value={!status ? '未知' : status.server_online ? '在线' : '离线'}
              valueStyle={{ color: !status || statusError ? '#888' : status.server_online ? '#52c41a' : '#ff4d4f' }}
              prefix={!status || statusError ? <CloudServerOutlined /> : status.server_online ? <CheckCircleOutlined /> : <CloseCircleOutlined />}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={8}>
          <Card>
            <Statistic
              title="本地版本"
              value={status?.local_version ?? '-'}
              prefix={<CloudServerOutlined />}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={8}>
          <Card>
            <Statistic
              title="远程版本"
              value={status?.server_online ? (status?.remote_version ?? '-') : 'N/A'}
              prefix={<CloudServerOutlined />}
            />
          </Card>
        </Col>
      </Row>

      <Card style={{ marginTop: 24 }}>
        <Descriptions column={1} size="small" style={{ marginBottom: 16 }}>
          <Descriptions.Item label="同步状态">
            {!status || statusError ? <Tag>等待获取最新状态</Tag> : status.needs_sync ? (
              <Tag color="orange">有待同步数据</Tag>
            ) : status?.server_online ? (
              <Tag color="green">已是最新</Tag>
            ) : (
              <Tag color="default">无法连接</Tag>
            )}
          </Descriptions.Item>
        </Descriptions>

        <Button
          type="primary"
          icon={<SyncOutlined spin={syncing} />}
          onClick={handleSync}
          loading={syncing}
          disabled={loading || statusError || !status?.server_online}
          size="large"
        >
          立即同步
        </Button>

        {status && !statusError && !status.server_online && (
          <div style={{ marginTop: 12 }}>
            <Text type="secondary">
              服务端离线时，应用使用本地缓存的公共数据正常运行。下次上线时自动同步。
            </Text>
          </div>
        )}
      </Card>

      {result && (
        <Card title="同步结果" style={{ marginTop: 16 }}>
          <Descriptions column={1} size="small">
            <Descriptions.Item label="状态">
              <Tag color={result.status === 'ok' ? 'green' : 'red'}>{result.message}</Tag>
            </Descriptions.Item>
            {result.version != null && (
              <Descriptions.Item label="当前版本">{result.version}</Descriptions.Item>
            )}
            {result.upserted != null && (
              <Descriptions.Item label="新增/更新文档">{result.upserted} 条</Descriptions.Item>
            )}
            {result.deleted != null && (
              <Descriptions.Item label="删除文档">{result.deleted} 条</Descriptions.Item>
            )}
            {result.document_count != null && (
              <Descriptions.Item label="文档总数">{result.document_count} 篇</Descriptions.Item>
            )}
          </Descriptions>
        </Card>
      )}
    </div>
  );
}
