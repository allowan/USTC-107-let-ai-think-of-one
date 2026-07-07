import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Card, Form, Input, Button, Tabs, App } from 'antd';
import { UserOutlined, LockOutlined } from '@ant-design/icons';
import { authApi } from '@/services/api';
import { useUserStore } from '@/stores/userStore';
import type { LoginForm } from '@/types';

export default function LoginPage() {
  const [loading, setLoading] = useState(false);
  const { setAuth } = useUserStore();
  const navigate = useNavigate();
  const { message } = App.useApp();

  const handleSubmit = async (values: LoginForm, isRegister: boolean) => {
    setLoading(true);
    try {
      const api = isRegister ? authApi.register : authApi.login;
      const { data } = await api(values.username, values.password);
      setAuth(
        { user_id: data.user_id, username: data.username, is_admin: data.is_admin },
        data.token,
      );
      message.success(isRegister ? '注册成功' : '登录成功');
      navigate('/chat', { replace: true });
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        '操作失败，请重试';
      message.error(msg);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      style={{
        height: '100vh',
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
      }}
    >
      <Card style={{ width: 400, boxShadow: '0 8px 24px rgba(0,0,0,0.15)' }}>
        <h1 style={{ textAlign: 'center', marginBottom: 32, fontSize: 24 }}>
          USTC AI 助手
        </h1>
        <Tabs
          centered
          items={[
            {
              key: 'login',
              label: '登录',
              children: (
                <AuthForm
                  loading={loading}
                  onSubmit={(v) => handleSubmit(v, false)}
                  submitText="登录"
                />
              ),
            },
            {
              key: 'register',
              label: '注册',
              children: (
                <AuthForm
                  loading={loading}
                  onSubmit={(v) => handleSubmit(v, true)}
                  submitText="注册"
                />
              ),
            },
          ]}
        />
      </Card>
    </div>
  );
}

function AuthForm({
  loading,
  onSubmit,
  submitText,
}: {
  loading: boolean;
  onSubmit: (v: LoginForm) => void;
  submitText: string;
}) {
  return (
    <Form onFinish={onSubmit} size="large">
      <Form.Item
        name="username"
        rules={[{ required: true, message: '请输入用户名' }]}
      >
        <Input prefix={<UserOutlined />} placeholder="用户名" />
      </Form.Item>
      <Form.Item
        name="password"
        rules={[{ required: true, message: '请输入密码' }]}
      >
        <Input.Password prefix={<LockOutlined />} placeholder="密码" />
      </Form.Item>
      <Form.Item>
        <Button type="primary" htmlType="submit" loading={loading} block>
          {submitText}
        </Button>
      </Form.Item>
    </Form>
  );
}
