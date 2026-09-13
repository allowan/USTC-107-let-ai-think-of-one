import { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import { Alert, Modal, Tabs, Form, Input, Switch, Button, App, Spin, Space, Typography, Card, Empty, Popconfirm, Select, Divider, Tag } from 'antd';
import { SaveOutlined, PlusOutlined, EditOutlined, DeleteOutlined, MinusCircleOutlined, ApiOutlined } from '@ant-design/icons';
import { settingsApi } from '@/services/api';
import type { ModelGroup, ToolSetting } from '@/types';

const { Text } = Typography;

interface Props {
  visible: boolean;
  onClose: () => void;
}

export default function SettingsModal({ visible, onClose }: Props) {
  const [activeTab, setActiveTab] = useState('providers');

  useEffect(() => {
    if (visible) {
      setActiveTab('providers');
    }
  }, [visible]);

  const tabItems = [
    {
      key: 'providers',
      label: '模型供应商',
      children: <ProviderGroupsTab />,
    },
    {
      key: 'tools',
      label: '工具设置',
      children: <ToolSettingsTab />,
    },
    { key: 'diagnostics', label: '连接诊断', children: <DiagnosticsTab /> },
  ];

  return (
    <Modal
      className="settings-modal"
      title="设置"
      open={visible}
      onCancel={onClose}
      footer={null}
      width={640}
      destroyOnClose
      centered
      styles={{ body: { maxHeight: '62vh', overflowY: 'auto', paddingRight: 8 } }}
    >
      <Tabs activeKey={activeTab} onChange={setActiveTab} items={tabItems} />
    </Modal>
  );
}

function errorDetail(error: unknown, fallback: string) {
  return axios.isAxiosError(error) ? error.response?.data?.detail || fallback : fallback;
}

function DiagnosticsTab() {
  const [loading, setLoading] = useState(false);
  const [checks, setChecks] = useState<{ llm: boolean; chromadb: boolean } | null>(null);
  const [error, setError] = useState(false);
  const active = useRef(true);
  useEffect(() => { active.current = true; return () => { active.current = false; }; }, []);
  const diagnose = async () => {
    if (loading) return;
    setLoading(true);
    setError(false);
    setChecks(null);
    try {
      const { data } = await settingsApi.diagnose();
      if (active.current) setChecks(data.checks);
    } catch {
      if (active.current) setError(true);
    } finally {
      if (active.current) setLoading(false);
    }
  };
  return <Space direction="vertical" style={{ width: '100%' }}>
    <Text>点击后检查模型连接和本地资料库。模型检查会向当前供应商发送一次简短请求，可能产生少量费用；不会发送个人资料。</Text>
    <Button onClick={() => void diagnose()} loading={loading}>开始诊断</Button>
    {error && <Alert type="error" message="诊断请求失败，请检查本地后端后重试。" />}
    {checks && <>
      <Alert type={checks.llm ? 'success' : 'warning'} message={checks.llm ? '模型连接正常' : '模型不可用或检查超时，请核对模型配置与网络。'} />
      <Alert type={checks.chromadb ? 'success' : 'warning'} message={checks.chromadb ? '本地资料库可访问' : '资料库不可用或检查超时，请核对存储状态。'} />
      <Text type="secondary">本次检查不验证嵌入、重排序或同步服务。正在执行的探测不会因等待超时而重复启动。</Text>
    </>}
  </Space>;
}

function ProviderGroupsTab() {
  const { message } = App.useApp();
  const [groups, setGroups] = useState<ModelGroup[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [editorOpen, setEditorOpen] = useState(false);
  const [modelOptions, setModelOptions] = useState<string[]>([]);
  const [modelsLoading, setModelsLoading] = useState(false);
  const [editingName, setEditingName] = useState<string | null>(null);
  const [editorValues, setEditorValues] = useState<ModelGroup | null>(null);
  const [form] = Form.useForm<ModelGroup>();

  const refresh = () => {
    setLoading(true);
    settingsApi.getGlobal()
      .then(({ data }) => setGroups(data.groups || []))
      .catch((error) => message.error(errorDetail(error, '获取供应商分组失败')))
      .finally(() => setLoading(false));
  };

  useEffect(() => { refresh(); }, []);

  const openCreate = () => {
    setEditingName(null);
    setEditorValues({
      group_name: '',
      vendor: 'customendpoint',
      api_key: '',
      base_url: '',
      api_type: 'chat-completions',
      models: [{ request_id: '', show_id: '', toolCalling: true, vision: false }],
    });
    setModelOptions([]);
    setEditorOpen(true);
  };

  const openEdit = (group: ModelGroup) => {
    setEditingName(group.group_name);
    setEditorValues(JSON.parse(JSON.stringify(group)));
    setModelOptions([]);
    setEditorOpen(true);
  };

  const loadAvailableModels = async () => {
    try {
      const { base_url: baseUrl, api_key: apiKey } = await form.validateFields(['base_url', 'api_key']);
      setModelsLoading(true);
      const { data } = await settingsApi.getAvailableModels({ base_url: baseUrl, api_key: apiKey });
      setModelOptions(data.models);
      if (data.models.length) message.success(`已查询到 ${data.models.length} 个模型`);
      else message.warning('接口返回的模型列表为空');
    } catch (error) {
      message.error(errorDetail(error, '获取模型列表失败'));
    } finally {
      setModelsLoading(false);
    }
  };

  const saveGroup = async () => {
    try {
      const values = await form.validateFields();
      setSaving(true);
      if (editingName) {
        await settingsApi.updateGroup(editingName, values);
        message.success('供应商分组已更新');
      } else {
        await settingsApi.addGroup(values);
        message.success('供应商分组已添加');
      }
      setEditorOpen(false);
      refresh();
      window.dispatchEvent(new Event('model-settings-changed'));
    } catch (error) {
      if (axios.isAxiosError(error)) message.error(errorDetail(error, '保存供应商分组失败'));
    } finally {
      setSaving(false);
    }
  };

  const deleteGroup = async (groupName: string) => {
    try {
      await settingsApi.deleteGroup(groupName);
      setGroups((current) => current.filter((group) => group.group_name !== groupName));
      message.success('供应商分组已删除');
      window.dispatchEvent(new Event('model-settings-changed'));
    } catch (error) {
      message.error(errorDetail(error, '删除供应商分组失败'));
    }
  };

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <div>
          <Text strong>模型供应商</Text><br />
          <Text type="secondary" style={{ fontSize: 12 }}>管理兼容接口及其可切换模型</Text>
        </div>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>添加分组</Button>
      </div>

      {loading ? <div style={{ textAlign: 'center', padding: 32 }}><Spin /></div> : groups.length === 0 ? (
        <Empty description="暂无供应商分组" />
      ) : (
        <Space direction="vertical" style={{ width: '100%' }} size={12}>
          {groups.map((group) => (
            <Card
              key={group.group_name}
              size="small"
              title={<Space><ApiOutlined /><span>{group.group_name}</span><Tag>{group.models.length} 个模型</Tag></Space>}
              extra={<Space>
                <Button type="text" size="small" icon={<EditOutlined />} onClick={() => openEdit(group)}>编辑</Button>
                <Popconfirm title="删除此供应商分组？" description="当前使用的模型所在分组不能删除。" onConfirm={() => deleteGroup(group.group_name)}>
                  <Button type="text" danger size="small" icon={<DeleteOutlined />}>删除</Button>
                </Popconfirm>
              </Space>}
            >
              <Text type="secondary">{group.base_url || '沿用全局 Base URL'}</Text>
              <div style={{ marginTop: 8 }}>
                {group.models.map((model) => <Tag key={model.request_id}>{model.show_id || model.request_id}</Tag>)}
              </div>
            </Card>
          ))}
        </Space>
      )}

      <Modal
        className="provider-editor-modal"
        title={editingName ? '编辑供应商分组' : '添加供应商分组'}
        open={editorOpen}
        onCancel={() => setEditorOpen(false)}
        onOk={() => { void saveGroup(); }}
        confirmLoading={saving}
        okText="保存"
        cancelText="取消"
        width={600}
        destroyOnClose
        centered
        styles={{ body: { maxHeight: '64vh', overflowY: 'auto', paddingRight: 8 } }}
      >
        <Form form={form} layout="vertical" preserve={false} initialValues={editorValues || undefined}>
          <Form.Item name="group_name" label="分组名称" rules={[{ required: true, whitespace: true, message: '请输入分组名称' }]}>
            <Input placeholder="例如：DeepSeek、科大 LLM 网关" />
          </Form.Item>
          <Form.Item name="vendor" label="供应商标识" rules={[{ required: true, whitespace: true }]}>
            <Input placeholder="customendpoint" />
          </Form.Item>
          <Form.Item
            name="base_url"
            label="Base URL"
            rules={[
              { required: true, whitespace: true, message: '请输入 Base URL' },
              { type: 'url', message: '请输入有效的 URL' },
            ]}
          >
            <Input placeholder="https://api.example.com/v1" />
          </Form.Item>
          <Form.Item name="api_key" label="API Key" rules={[{ required: true, whitespace: true, message: '请输入 API Key' }]}>
            <Input.Password placeholder="请输入 API Key" autoComplete="new-password" />
          </Form.Item>
          <Form.Item name="api_type" label="API Type">
            <Select placeholder="请选择 API Type" options={[
              { label: 'Chat Completions', value: 'chat-completions' },
              { label: 'Responses', value: 'responses' },
            ]} />
          </Form.Item>

          <Divider orientation="left">分组模型</Divider>
          <Button
            block
            icon={<ApiOutlined />}
            loading={modelsLoading}
            onClick={() => { void loadAvailableModels(); }}
            style={{ marginBottom: 12 }}
          >
            通过 Base URL 查询可用模型
          </Button>
          <Form.List name="models">
            {(fields, { add, remove }) => (
              <Space direction="vertical" style={{ width: '100%' }} size={12}>
                {fields.map((field, index) => (
                  <Card
                    key={field.key}
                    size="small"
                    title={`模型 ${index + 1}`}
                    extra={fields.length > 1 ? <Button type="text" danger icon={<MinusCircleOutlined />} onClick={() => remove(field.name)}>移除</Button> : null}
                  >
                    <Form.Item name={[field.name, 'request_id']} label="模型 ID" rules={[{ required: true, whitespace: true, message: '请输入模型 ID' }]}>
                      {modelOptions.length > 0 ? (
                        <Select
                          showSearch
                          placeholder="请选择接口返回的模型"
                          optionFilterProp="label"
                          options={modelOptions.map((model) => ({ label: model, value: model }))}
                        />
                      ) : <Input placeholder="例如：deepseek-chat；也可先查询模型列表" />}
                    </Form.Item>
                    <Form.Item name={[field.name, 'show_id']} label="显示名称">
                      <Input placeholder="例如：DeepSeek Chat" />
                    </Form.Item>
                    <Space size="large">
                      <Form.Item name={[field.name, 'toolCalling']} valuePropName="checked" initialValue>
                        <Switch checkedChildren="工具调用" unCheckedChildren="无工具调用" />
                      </Form.Item>
                      <Form.Item name={[field.name, 'vision']} valuePropName="checked">
                        <Switch checkedChildren="视觉" unCheckedChildren="纯文本" />
                      </Form.Item>
                    </Space>
                  </Card>
                ))}
                <Button block type="dashed" icon={<PlusOutlined />} onClick={() => add({ request_id: '', show_id: '', toolCalling: true, vision: false })}>
                  添加模型
                </Button>
              </Space>
            )}
          </Form.List>
        </Form>
      </Modal>
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
