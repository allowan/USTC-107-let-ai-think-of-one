import { useState, useEffect, useRef } from 'react';
import { Outlet, useNavigate, useLocation } from 'react-router-dom';
import { Layout, Menu, Button, Typography, App, Spin, Popconfirm, Input } from 'antd';
import {
  MessageOutlined,
  NotificationOutlined,
  DatabaseOutlined,
  SettingOutlined,
  SyncOutlined,
  PlusOutlined,
  DeleteOutlined,
  CommentOutlined,
  CalendarOutlined,
} from '@ant-design/icons';
import { useTopicStore } from '@/stores/topicStore';
import SettingsModal from './SettingsModal';

const { Header, Sider, Content } = Layout;
const { Text } = Typography;

export default function AppLayout() {
  const navigate = useNavigate();
  const location = useLocation();
  const {
    topics, activeTopicId, loading: topicsLoading, loadError,
    fetchTopics, createTopic, deleteTopic, renameTopic, setActiveTopicId,
  } = useTopicStore();

  const [settingsModalVisible, setSettingsModalVisible] = useState(false);
  const [editingTopicId, setEditingTopicId] = useState<string | null>(null);
  const [editTopicName, setEditTopicName] = useState('');
  // Enter 与 blur 可能先后触发提交，同步置位的 ref 标志去重，避免同一话题双 PUT
  const renameBusyRef = useRef(false);
  const { message } = App.useApp();

  useEffect(() => {
    fetchTopics();
  }, []);

  const menuItems = [
    { key: '/chat', icon: <MessageOutlined />, label: '对话' },
    { key: '/personal-data', icon: <DatabaseOutlined />, label: '个人数据' },
    { key: '/schedule', icon: <CalendarOutlined />, label: '我的课表' },
    { key: '/news', icon: <NotificationOutlined />, label: '最新消息' },
    { key: '/sync', icon: <SyncOutlined />, label: '数据同步' },
  ];

  const handleCreateTopic = async () => {
    try {
      await createTopic();
    } catch {
      message.error('创建话题失败');
    }
  };

  const handleDeleteTopic = async (topicId: string) => {
    try {
      await deleteTopic(topicId);
    } catch {
      message.error('删除话题失败');
    }
  };

  const handleStartRename = (topicId: string, currentName: string) => {
    setEditingTopicId(topicId);
    setEditTopicName(currentName);
  };

  const handleFinishRename = async () => {
    if (renameBusyRef.current) return;
    const topicId = editingTopicId;
    const name = editTopicName.trim();
    setEditingTopicId(null);
    setEditTopicName('');
    if (!topicId || !name) return;
    renameBusyRef.current = true;
    try {
      await renameTopic(topicId, name);
    } catch {
      message.error('重命名失败');
    } finally {
      renameBusyRef.current = false;
    }
  };

  const handleSelectTopic = (topicId: string) => {
    setActiveTopicId(topicId);
    if (location.pathname !== '/chat') {
      navigate('/chat');
    }
  };

  return (
    <Layout style={{ height: '100vh', overflow: 'hidden' }}>
      <Sider
        breakpoint="md"
        collapsedWidth={0}
        width={240}
        style={{ background: '#fff', height: '100vh', position: 'sticky', top: 0, overflow: 'hidden' }}
      >
        <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
        <div
          style={{
            height: 64,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontWeight: 700,
            fontSize: 18,
            borderBottom: '1px solid #f0f0f0',
            flexShrink: 0,
          }}
        >
          USTC AI
        </div>
        <Menu
          mode="inline"
          selectedKeys={[location.pathname]}
          items={menuItems}
          onClick={({ key }) => navigate(key)}
          style={{ border: 'none', flexShrink: 0 }}
        />

        {/* Topic section */}
        <div style={{
          borderTop: '1px solid #f0f0f0',
          padding: '8px 12px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexShrink: 0,
        }}>
          <Text type="secondary" style={{ fontSize: 12 }}>话题</Text>
          <Button type="text" size="small" icon={<PlusOutlined />} onClick={handleCreateTopic} />
        </div>

        <div style={{ flex: 1, overflow: 'auto', padding: '0 4px' }}>
          {loadError ? (
            <div
              onClick={() => fetchTopics()}
              style={{ textAlign: 'center', padding: 16, color: '#ff4d4f', fontSize: 12, lineHeight: 1.6, cursor: 'pointer' }}
            >
              后端连接失败，请确认已运行 python server.py
              <br />
              <span style={{ color: '#1677ff' }}>点击重试</span>
            </div>
          ) : topicsLoading ? (
            <div style={{ textAlign: 'center', padding: 16 }}><Spin size="small" /></div>
          ) : topics.length === 0 ? (
            <div style={{ textAlign: 'center', padding: 16, color: '#999', fontSize: 12 }}>
              暂无话题，点击 + 创建
            </div>
          ) : (
            topics.map((t) => (
              <div
                key={t.id}
                onClick={() => handleSelectTopic(t.id)}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  padding: '6px 8px',
                  margin: '2px 4px',
                  borderRadius: 8,
                  cursor: 'pointer',
                  background: t.id === activeTopicId ? '#e6f4ff' : 'transparent',
                  transition: 'background 0.2s',
                }}
                onMouseEnter={(e) => (e.currentTarget.style.background = t.id === activeTopicId ? '#e6f4ff' : '#f5f5f5')}
                onMouseLeave={(e) => (e.currentTarget.style.background = t.id === activeTopicId ? '#e6f4ff' : 'transparent')}
              >
                <CommentOutlined style={{ color: '#1677ff', marginRight: 8, flexShrink: 0 }} />
                {editingTopicId === t.id ? (
                  <Input
                    size="small"
                    value={editTopicName}
                    onChange={(e) => setEditTopicName(e.target.value)}
                    onPressEnter={handleFinishRename}
                    onBlur={handleFinishRename}
                    autoFocus
                    onClick={(e) => e.stopPropagation()}
                    style={{ flex: 1 }}
                  />
                ) : (
                  <Text
                    ellipsis
                    style={{ flex: 1, fontSize: 13 }}
                    onDoubleClick={(e) => { e.stopPropagation(); handleStartRename(t.id, t.name); }}
                  >
                    {t.name}
                  </Text>
                )}
                <Popconfirm
                  title="确定删除此话题及其对话记录？"
                  onConfirm={(e) => { e?.stopPropagation(); handleDeleteTopic(t.id); }}
                  onCancel={(e) => e?.stopPropagation()}
                >
                  <Button
                    type="text"
                    size="small"
                    danger
                    icon={<DeleteOutlined />}
                    onClick={(e) => e.stopPropagation()}
                    style={{ flexShrink: 0, opacity: 0.5 }}
                  />
                </Popconfirm>
              </div>
            ))
          )}
        </div>
        </div>
      </Sider>

      <Layout style={{ display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        <Header
          style={{
            background: '#fff',
            padding: '0 24px',
            display: 'flex',
            justifyContent: 'flex-end',
            alignItems: 'center',
            borderBottom: '1px solid #f0f0f0',
            flexShrink: 0,
          }}
        >
          <Button
            type="text"
            icon={<SettingOutlined />}
            onClick={() => setSettingsModalVisible(true)}
            style={{ display: 'flex', alignItems: 'center', gap: 8 }}
          >
            设置
          </Button>
        </Header>
        <Content style={{ padding: 24, overflow: 'auto', flex: 1 }}>
          <Outlet />
        </Content>
      </Layout>

      <SettingsModal
        visible={settingsModalVisible}
        onClose={() => setSettingsModalVisible(false)}
      />
    </Layout>
  );
}
