import { Outlet, useNavigate, useLocation } from 'react-router-dom';
import { Layout, Menu, Button, Avatar, Dropdown } from 'antd';
import {
  MessageOutlined,
  FolderOutlined,
  SettingOutlined,
  LogoutOutlined,
  UserOutlined,
} from '@ant-design/icons';
import { useUserStore } from '@/stores/userStore';

const { Header, Sider, Content } = Layout;

export default function AppLayout() {
  const navigate = useNavigate();
  const location = useLocation();
  const { user, logout, isAdmin } = useUserStore();

  const menuItems = [
    { key: '/chat', icon: <MessageOutlined />, label: '对话' },
    { key: '/files', icon: <FolderOutlined />, label: '文件' },
    ...(isAdmin() ? [{ key: '/admin', icon: <SettingOutlined />, label: '管理' }] : []),
  ];

  const handleLogout = () => {
    logout();
    navigate('/login', { replace: true });
  };

  const dropdownItems = {
    items: [
      {
        key: 'logout',
        icon: <LogoutOutlined />,
        label: '退出登录',
        onClick: handleLogout,
      },
    ],
  };

  return (
    <Layout style={{ height: '100%' }}>
      <Sider
        breakpoint="md"
        collapsedWidth={0}
        width={200}
        style={{ background: '#fff' }}
      >
        <div
          style={{
            height: 64,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontWeight: 700,
            fontSize: 18,
            borderBottom: '1px solid #f0f0f0',
          }}
        >
          USTC AI
        </div>
        <Menu
          mode="inline"
          selectedKeys={[location.pathname]}
          items={menuItems}
          onClick={({ key }) => navigate(key)}
          style={{ border: 'none' }}
        />
      </Sider>
      <Layout>
        <Header
          style={{
            background: '#fff',
            padding: '0 24px',
            display: 'flex',
            justifyContent: 'flex-end',
            alignItems: 'center',
            borderBottom: '1px solid #f0f0f0',
          }}
        >
          <Dropdown menu={dropdownItems} placement="bottomRight">
            <Button type="text" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <Avatar size="small" icon={<UserOutlined />} />
              {user?.username}
            </Button>
          </Dropdown>
        </Header>
        <Content style={{ padding: 24, overflow: 'auto', height: 'calc(100% - 64px)' }}>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  );
}
