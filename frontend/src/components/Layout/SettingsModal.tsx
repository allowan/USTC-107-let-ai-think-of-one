import { useState, useEffect } from 'react';
import { Modal, Tabs, Form, Input, Select, Switch, Button, App, Spin, Space, Typography } from 'antd';
import { SaveOutlined } from '@ant-design/icons';
import { settingsApi } from '@/services/api';
import type { GlobalSettings, ToolSetting } from '@/types';

const { Text } = Typography;

interface Props {
  visible: boolean;
  onClose: () => void;
}

export default function SettingsModal({ visible, onClose }: Props) {
  const [activeTab, setActiveTab] = useState('tools');

  useEffect(() => {
    if (visible) {
      setActiveTab('global');
    }
  }, [visible]);

  const tabItems = [
    {
      key: 'global',
      label: '全局设置',
      children: <GlobalSettingsTab />,
    },
    {
      key: 'tools',
      label: '工具设置',
      children: <ToolSettingsTab />,
    },
  ];

  return (
    <Modal
      title="设置"
      open={visible}
      onCancel={onClose}
      footer={null}
      width={560}
      destroyOnClose
    >
      <Tabs activeKey={activeTab} onChange={setActiveTab} items={tabItems} />
    </Modal>
  );
}

function GlobalSettingsTab() {
  const { message } = App.useApp();
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [savingModel, setSavingModel] = useState(false);
  const [settings, setSettings] = useState<GlobalSettings | null>(null);
  const [selectedGroup, setSelectedGroup] = useState('');
  const [selectedModel, setSelectedModel] = useState('');

  useEffect(() => {
    setLoading(true);
    settingsApi.getGlobal()
      .then(({ data }) => {
        setSettings(data);
        if (data.groups?.length > 0) {
          setSelectedGroup(data.groups[0].group_name);
          const currentModel = data.env?.model;
          for (const g of data.groups) {
            for (const m of g.models) {
              if (m.request_id === currentModel || m.show_id === currentModel) {
                setSelectedGroup(g.group_name);
                setSelectedModel(m.show_id);
              }
            }
          }
        }
      })
      .catch(() => message.error('获取全局设置失败'))
      .finally(() => setLoading(false));
  }, []);

  const handleSaveEnv = async () => {
    if (!settings) return;
    setSaving(true);
    try {
      await settingsApi.updateGlobal({
        api_key: settings.env.api_key,
        base_url: settings.env.base_url,
        api_type: settings.env.api_type,
      });
      message.success('全局设置已保存');
    } catch {
      message.error('保存全局设置失败');
    } finally {
      setSaving(false);
    }
  };

  const handleSwitchModel = async () => {
    if (!selectedGroup || !selectedModel) {
      message.warning('请选择分组和模型');
      return;
    }
    setSavingModel(true);
    try {
      await settingsApi.switchModel(selectedGroup, selectedModel);
      message.success(`模型已切换为 ${selectedModel}`);
    } catch {
      message.error('切换模型失败');
    } finally {
      setSavingModel(false);
    }
  };

  const currentGroup = settings?.groups?.find((g) => g.group_name === selectedGroup);
  const currentModels = currentGroup?.models || [];

  return loading ? (
    <div style={{ textAlign: 'center', padding: 32 }}><Spin /></div>
  ) : !settings ? null : (
    <div>
      <Form layout="vertical" size="middle">
        <Form.Item label="API Key">
          <Input.Password
            value={settings.env.api_key}
            onChange={(e) => setSettings({ ...settings, env: { ...settings.env, api_key: e.target.value } })}
            placeholder="sk-..."
          />
        </Form.Item>
        <Form.Item label="Base URL">
          <Input
            value={settings.env.base_url}
            onChange={(e) => setSettings({ ...settings, env: { ...settings.env, base_url: e.target.value } })}
            placeholder="https://api.deepseek.com"
          />
        </Form.Item>
        <Form.Item label="API Type">
          <Input
            value={settings.env.api_type}
            onChange={(e) => setSettings({ ...settings, env: { ...settings.env, api_type: e.target.value } })}
            placeholder="chat-completions"
          />
        </Form.Item>
        <Form.Item label="模型分组">
          <Select
            value={selectedGroup}
            onChange={(v) => { setSelectedGroup(v); setSelectedModel(''); }}
            options={settings.groups?.map((g) => ({ label: g.group_name, value: g.group_name })) || []}
          />
        </Form.Item>
        <Form.Item label="当前模型">
          <Select
            value={selectedModel}
            onChange={setSelectedModel}
            options={currentModels.map((m) => ({ label: m.show_id, value: m.show_id }))}
            notFoundContent="该分组下无可用模型"
          />
        </Form.Item>
      </Form>
      <Space style={{ width: '100%', justifyContent: 'flex-end' }}>
        <Button onClick={handleSaveEnv} loading={saving} icon={<SaveOutlined />}>
          保存环境配置
        </Button>
        <Button type="primary" onClick={handleSwitchModel} loading={savingModel}>
          切换模型
        </Button>
      </Space>
    </div>
  );
}

function ToolSettingsTab() {
  const { message } = App.useApp();
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [tools, setTools] = useState<ToolSetting[]>([]);

  useEffect(() => {
    setLoading(true);
    settingsApi.getTools()
      .then(({ data }) => setTools(data.tools))
      .catch(() => message.error('获取工具设置失败'))
      .finally(() => setLoading(false));
  }, []);

  const handleToggle = (name: string, enabled: boolean) => {
    setTools((prev) => prev.map((t) => (t.name === name ? { ...t, enabled } : t)));
  };

  const handleSave = async () => {
    setSaving(true);
    const prefs: Record<string, boolean> = {};
    tools.forEach((t) => { prefs[t.name] = t.enabled; });
    try {
      await settingsApi.updateTools(prefs);
      message.success('工具设置已保存');
    } catch {
      message.error('保存工具设置失败');
    } finally {
      setSaving(false);
    }
  };

  return loading ? (
    <div style={{ textAlign: 'center', padding: 32 }}><Spin /></div>
  ) : (
    <div>
      {tools.map((tool) => (
        <div
          key={tool.name}
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '10px 0',
            borderBottom: '1px solid #f0f0f0',
          }}
        >
          <div style={{ flex: 1 }}>
            <Text strong style={{ fontSize: 14 }}>{tool.label}</Text>
            <br />
            <Text type="secondary" style={{ fontSize: 12 }}>{tool.description}</Text>
          </div>
          <Switch
            checked={tool.enabled}
            onChange={(v) => handleToggle(tool.name, v)}
          />
        </div>
      ))}
      <div style={{ marginTop: 16, textAlign: 'right' }}>
        <Button type="primary" onClick={handleSave} loading={saving} icon={<SaveOutlined />}>
          保存工具设置
        </Button>
      </div>
    </div>
  );
}
