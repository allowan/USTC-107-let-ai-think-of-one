import { useState, useEffect } from 'react';
import {
  Table,
  Button,
  Breadcrumb,
  Upload,
  Modal,
  Input,
  Space,
  App,
} from 'antd';
import {
  FolderOutlined,
  FileOutlined,
  UploadOutlined,
  DeleteOutlined,
  FolderAddOutlined,
  EyeOutlined,
} from '@ant-design/icons';
import { fileApi } from '@/services/api';
import type { FileInfo } from '@/types';

export default function FilesPage() {
  const [files, setFiles] = useState<FileInfo[]>([]);
  const [currentPath, setCurrentPath] = useState('');
  const [loading, setLoading] = useState(false);
  const [mkdirVisible, setMkdirVisible] = useState(false);
  const [mkdirName, setMkdirName] = useState('');
  const [previewVisible, setPreviewVisible] = useState(false);
  const [previewContent, setPreviewContent] = useState('');
  const { message } = App.useApp();

  const fetchFiles = async (path?: string) => {
    setLoading(true);
    try {
      const { data } = await fileApi.list(path);
      setFiles(data.files);
    } catch {
      message.error('获取文件列表失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchFiles(currentPath);
  }, [currentPath]);

  const enterDir = (dirName: string) => {
    setCurrentPath((prev) => (prev ? `${prev}/${dirName}` : dirName));
  };

  const handleDelete = async (filePath: string) => {
    try {
      await fileApi.delete(filePath);
      message.success('删除成功');
      fetchFiles(currentPath);
    } catch {
      message.error('删除失败');
    }
  };

  const handlePreview = async (filePath: string) => {
    try {
      const { data } = await fileApi.read(filePath);
      setPreviewContent(data.content);
      setPreviewVisible(true);
    } catch {
      message.error('读取文件失败');
    }
  };

  const handleMkdir = async () => {
    if (!mkdirName.trim()) return;
    const fullPath = currentPath ? `${currentPath}/${mkdirName.trim()}` : mkdirName.trim();
    try {
      await fileApi.write(fullPath + '/.gitkeep', '');
      message.success('目录创建成功');
      setMkdirVisible(false);
      setMkdirName('');
      fetchFiles(currentPath);
    } catch {
      message.error('创建目录失败');
    }
  };

  const handleUpload = async (file: File) => {
    try {
      await fileApi.upload(file, currentPath || undefined);
      message.success('上传成功');
      fetchFiles(currentPath);
    } catch {
      message.error('上传失败');
    }
    return false; // prevent default upload
  };

  const pathParts = currentPath ? currentPath.split('/') : [];

  const columns = [
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      render: (name: string, record: FileInfo) => (
        <a
          onClick={() => record.type === 'directory' && enterDir(name)}
          style={{ cursor: record.type === 'directory' ? 'pointer' : 'default' }}
        >
          {record.type === 'directory' ? <FolderOutlined style={{ marginRight: 8 }} /> : <FileOutlined style={{ marginRight: 8 }} />}
          {name}
        </a>
      ),
    },
    {
      title: '大小',
      dataIndex: 'size',
      key: 'size',
      width: 120,
      render: (size?: number) => (size != null ? `${(size / 1024).toFixed(1)} KB` : '-'),
    },
    {
      title: '操作',
      key: 'actions',
      width: 160,
      render: (_: unknown, record: FileInfo) => (
        <Space>
          {record.type === 'file' && (
            <Button
              type="link"
              size="small"
              icon={<EyeOutlined />}
              onClick={() => handlePreview(currentPath ? `${currentPath}/${record.name}` : record.name)}
            >
              查看
            </Button>
          )}
          <Button
            type="link"
            danger
            size="small"
            icon={<DeleteOutlined />}
            onClick={() =>
              handleDelete(currentPath ? `${currentPath}/${record.name}` : record.name)
            }
          />
        </Space>
      ),
    },
  ];

  return (
    <div>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: 16,
        }}
      >
        <Breadcrumb
          items={[
            { title: <a onClick={() => setCurrentPath('')}>根目录</a> },
            ...pathParts.map((part, i) => ({
              title: (
                <a onClick={() => setCurrentPath(pathParts.slice(0, i + 1).join('/'))}>
                  {part}
                </a>
              ),
            })),
          ]}
        />
        <Space>
          <Upload
            showUploadList={false}
            beforeUpload={(file) => {
              handleUpload(file);
              return false;
            }}
          >
            <Button icon={<UploadOutlined />}>上传</Button>
          </Upload>
          <Button icon={<FolderAddOutlined />} onClick={() => setMkdirVisible(true)}>
            新建目录
          </Button>
        </Space>
      </div>

      <Table
        columns={columns}
        dataSource={files.map((f) => ({ ...f, key: f.name }))}
        loading={loading}
        pagination={false}
        size="middle"
      />

      <Modal
        title="新建目录"
        open={mkdirVisible}
        onOk={handleMkdir}
        onCancel={() => setMkdirVisible(false)}
      >
        <Input
          value={mkdirName}
          onChange={(e) => setMkdirName(e.target.value)}
          placeholder="目录名称"
        />
      </Modal>

      <Modal
        title="文件预览"
        open={previewVisible}
        onCancel={() => setPreviewVisible(false)}
        footer={null}
        width={700}
      >
        <pre
          style={{
            maxHeight: 400,
            overflow: 'auto',
            background: '#f5f5f5',
            padding: 16,
            borderRadius: 8,
            whiteSpace: 'pre-wrap',
          }}
        >
          {previewContent}
        </pre>
      </Modal>
    </div>
  );
}
