import { useState } from 'react';
import { Tabs, Table, Button, Card, Statistic, Row, Col, Input, Modal, Popconfirm, App, Tag, Spin } from 'antd';
import { DeleteOutlined, PlusOutlined, UserOutlined, FileTextOutlined, CheckCircleOutlined, CloseCircleOutlined } from '@ant-design/icons';
import { adminApi } from '@/services/api';

export default function AdminPage() {
  const { message } = App.useApp();

  const [users, setUsers] = useState<Array<{ username: string; is_admin: boolean; index_size: number }>>([]);
  const [notices, setNotices] = useState<Array<{ source: string; preview: string }>>([]);
  const [stats, setStats] = useState<{ user_count: number; public_doc_count: number; user_collections_count: number; agent_ready: boolean } | null>(null);
  const [addNoticeVisible, setAddNoticeVisible] = useState(false);
  const [noticeContent, setNoticeContent] = useState('');
  const [loading, setLoading] = useState({ users: false, notices: false, stats: false });

  const fetchUsers = async () => {
    setLoading((prev) => ({ ...prev, users: true }));
    try {
      const { data } = await adminApi.getUsers();
      setUsers(data.users);
    } catch {
      message.error('获取用户列表失败');
    } finally {
      setLoading((prev) => ({ ...prev, users: false }));
    }
  };

  const fetchNotices = async () => {
    setLoading((prev) => ({ ...prev, notices: true }));
    try {
      const { data } = await adminApi.getNotices();
      setNotices(data.notices);
    } catch {
      message.error('获取通知列表失败');
    } finally {
      setLoading((prev) => ({ ...prev, notices: false }));
    }
  };

  const fetchStats = async () => {
    setLoading((prev) => ({ ...prev, stats: true }));
    try {
      const { data } = await adminApi.getStats();
      setStats(data);
    } catch {
      message.error('获取系统状态失败');
    } finally {
      setLoading((prev) => ({ ...prev, stats: false }));
    }
  };

  const onTabChange = (key: string) => {
    if (key === 'users') fetchUsers();
    else if (key === 'notices') fetchNotices();
    else if (key === 'stats') fetchStats();
  };

  const handleDeleteUser = async (username: string) => {
    try {
      await adminApi.deleteUser(username);
      message.success(`用户 ${username} 已删除`);
      fetchUsers();
    } catch {
      message.error('删除用户失败');
    }
  };

  const handleAddNotice = async () => {
    if (!noticeContent.trim()) return;
    try {
      await adminApi.addNotice(noticeContent);
      message.success('通知已添加');
      setAddNoticeVisible(false);
      setNoticeContent('');
      fetchNotices();
    } catch {
      message.error('添加通知失败');
    }
  };

  const handleDeleteNotice = async (source: string) => {
    try {
      await adminApi.deleteNotice(source);
      message.success('通知已删除');
      fetchNotices();
    } catch {
      message.error('删除通知失败');
    }
  };

  const userColumns = [
    { title: '用户名', dataIndex: 'username', key: 'username' },
    {
      title: '管理员', dataIndex: 'is_admin', key: 'is_admin',
      render: (v: boolean) => v ? <Tag color="red">是</Tag> : <Tag>否</Tag>,
    },
    { title: '索引文档数', dataIndex: 'index_size', key: 'index_size' },
    {
      title: '操作', key: 'actions',
      render: (_: unknown, record: { username: string; is_admin: boolean }) => (
        !record.is_admin ? (
          <Popconfirm
            title={`确定删除用户 "${record.username}"？`}
            onConfirm={() => handleDeleteUser(record.username)}
          >
            <Button type="link" danger icon={<DeleteOutlined />}>删除</Button>
          </Popconfirm>
        ) : (
          <span style={{ color: '#999' }}>保护账户</span>
        )
      ),
    },
  ];

  const noticeColumns = [
    { title: '来源', dataIndex: 'source', key: 'source', width: 200 },
    { title: '内容预览', dataIndex: 'preview', key: 'preview', ellipsis: true },
    {
      title: '操作', key: 'actions', width: 80,
      render: (_: unknown, record: { source: string }) => (
        <Popconfirm title="确定删除此通知及其所有分块？" onConfirm={() => handleDeleteNotice(record.source)}>
          <Button type="link" danger icon={<DeleteOutlined />} />
        </Popconfirm>
      ),
    },
  ];

  return (
    <div>
      <h2 style={{ marginBottom: 24 }}>管理面板</h2>
      <Tabs
        defaultActiveKey="users"
        onChange={onTabChange}
        items={[
          {
            key: 'users',
            label: '用户管理',
            children: (
              <Table
                columns={userColumns}
                dataSource={users.map((u) => ({ ...u, key: u.username }))}
                loading={loading.users}
                pagination={{ pageSize: 20 }}
                size="middle"
              />
            ),
          },
          {
            key: 'notices',
            label: '知识库管理',
            children: (
              <div>
                <Button
                  type="primary"
                  icon={<PlusOutlined />}
                  onClick={() => setAddNoticeVisible(true)}
                  style={{ marginBottom: 16 }}
                >
                  添加通知
                </Button>
                <Table
                  columns={noticeColumns}
                  dataSource={notices.map((n) => ({ ...n, key: n.source }))}
                  loading={loading.notices}
                  pagination={{ pageSize: 10 }}
                  size="middle"
                />
                <Modal
                  title="添加通知"
                  open={addNoticeVisible}
                  onOk={handleAddNotice}
                  onCancel={() => { setAddNoticeVisible(false); setNoticeContent(''); }}
                  okText="添加"
                  cancelText="取消"
                >
                  <Input.TextArea
                    value={noticeContent}
                    onChange={(e) => setNoticeContent(e.target.value)}
                    rows={6}
                    placeholder="输入通知内容..."
                  />
                </Modal>
              </div>
            ),
          },
          {
            key: 'stats',
            label: '系统状态',
            children: (
              <div>
                {loading.stats && !stats ? (
                  <div style={{ textAlign: 'center', padding: 60 }}><Spin size="large" /></div>
                ) : stats ? (
                  <Row gutter={[24, 24]}>
                    <Col xs={24} sm={12} lg={6}>
                      <Card>
                        <Statistic title="用户总数" value={stats.user_count} prefix={<UserOutlined />} />
                      </Card>
                    </Col>
                    <Col xs={24} sm={12} lg={6}>
                      <Card>
                        <Statistic title="公共文档数" value={stats.public_doc_count} prefix={<FileTextOutlined />} />
                      </Card>
                    </Col>
                    <Col xs={24} sm={12} lg={6}>
                      <Card>
                        <Statistic title="用户集合数" value={stats.user_collections_count} prefix={<UserOutlined />} />
                      </Card>
                    </Col>
                    <Col xs={24} sm={12} lg={6}>
                      <Card>
                        <Statistic
                          title="Agent 状态"
                          value={stats.agent_ready ? '运行中' : '未就绪'}
                          valueStyle={{ color: stats.agent_ready ? '#52c41a' : '#ff4d4f' }}
                          prefix={stats.agent_ready ? <CheckCircleOutlined /> : <CloseCircleOutlined />}
                        />
                      </Card>
                    </Col>
                  </Row>
                ) : null}
              </div>
            ),
          },
        ]}
      />
    </div>
  );
}
