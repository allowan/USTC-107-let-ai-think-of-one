import { useEffect, useMemo, useState } from 'react';
import { Alert, App, Empty, Modal, Select, Space, Spin, Typography } from 'antd';
import axios from 'axios';
import { personalDataApi, scheduleApi } from '@/services/api';
import type { ScheduleData } from '@/types';

const { Text } = Typography;

interface Props {
  open: boolean;
  onCancel: () => void;
  onImported: () => void;
}

function getErrorMessage(error: unknown, fallback: string): string {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    if (typeof detail === 'string' && detail) return detail;
    if (Array.isArray(detail)) {
      const messages = detail.map((item) => {
        if (!item || typeof item !== 'object') return String(item);
        const record = item as { loc?: unknown[]; msg?: unknown };
        const location = Array.isArray(record.loc) ? record.loc.join('.') : '';
        const message = typeof record.msg === 'string' ? record.msg : '请求参数无效';
        return location ? `${location}: ${message}` : message;
      });
      if (messages.length > 0) return messages.join('；');
    }
  }
  return error instanceof Error ? error.message : fallback;
}

export default function ImportExistingScheduleModal({ open, onCancel, onImported }: Props) {
  const { message } = App.useApp();
  const [data, setData] = useState<ScheduleData>({ semester: null, semesters: [], courses: [] });
  const [selectedSemester, setSelectedSemester] = useState('');
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return undefined;
    let active = true;
    setLoading(true);
    scheduleApi.list()
      .then(({ data: schedule }) => {
        if (!active) return;
        setData(schedule);
        setSelectedSemester(schedule.semester || schedule.semesters[0] || '');
      })
      .catch((error) => {
        if (active) message.error(getErrorMessage(error, '读取已有课表失败'));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => { active = false; };
  }, [message, open]);

  const selectedCourses = useMemo(
    () => data.courses.filter(course => course.semester === selectedSemester),
    [data.courses, selectedSemester],
  );
  const courseCount = new Set(selectedCourses.map(course => course.course_code || course.name)).size;

  const submit = async () => {
    if (!selectedSemester || selectedCourses.length === 0) {
      message.warning('当前没有可导入的已有课表');
      return;
    }
    setSaving(true);
    try {
      const response = await personalDataApi.importExistingSchedule(selectedSemester);
      message.success(`已将 ${response.data.semester} 课表同步到个人数据`);
      onImported();
      onCancel();
    } catch (error) {
      message.error(getErrorMessage(error, '同步已有课表失败'));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      title="导入已有课表到个人数据"
      open={open}
      onCancel={() => { if (!saving) onCancel(); }}
      onOk={() => void submit()}
      okText="同步到个人数据"
      cancelText="取消"
      confirmLoading={saving}
      okButtonProps={{ disabled: loading || !selectedSemester || selectedCourses.length === 0 }}
      destroyOnClose
      width={560}
    >
      <Alert
        type="info"
        showIcon
        message="读取本地已有课表"
        description="本操作只读取“我的课表”中已经保存的本地数据，同步到个人知识库，不会重新访问教务系统，也不会修改课表。"
        style={{ marginBottom: 16 }}
      />
      {loading ? (
        <div style={{ textAlign: 'center', padding: 24 }}><Spin /></div>
      ) : data.semesters.length === 0 ? (
        <Empty description="暂无已导入课表，请先在“我的课表”中导入" />
      ) : (
        <Space direction="vertical" style={{ width: '100%' }}>
          <Text strong>选择学期</Text>
          <Select
            value={selectedSemester || undefined}
            options={data.semesters.map(semester => ({ value: semester, label: semester }))}
            onChange={setSelectedSemester}
            style={{ width: '100%' }}
          />
          <Text type="secondary">
            当前学期包含 {courseCount} 门课程、{selectedCourses.length} 个上课安排。
          </Text>
        </Space>
      )}
    </Modal>
  );
}
