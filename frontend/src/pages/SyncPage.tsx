import { useState, useEffect, useCallback } from 'react';
import { Card, Button, Statistic, Row, Col, Typography, App, Spin, Tag, Descriptions } from 'antd';
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

  const fetchStatus = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await syncApi.getStatus();
      setStatus(data);
    } catch {
      // 静默处理
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchStatus();
  }, [fetchStatus]);

  const handleSync = async () => {
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

      <Row gutter={[24, 24]}>
        <Col xs={24} sm={12} lg={8}>
          <Card>
            <Statistic
              title="服务端状态"
              value={status?.server_online ? '在线' : '离线'}
              valueStyle={{ color: status?.server_online ? '#52c41a' : '#ff4d4f' }}
              prefix={status?.server_online ? <CheckCircleOutlined /> : <CloseCircleOutlined />}
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
            {status?.needs_sync ? (
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
          disabled={!status?.server_online}
          size="large"
        >
          立即同步
        </Button>

        {!status?.server_online && (
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
