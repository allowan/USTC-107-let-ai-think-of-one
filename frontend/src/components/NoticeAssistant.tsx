import { useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Alert, App, Button, Input, Modal, Select, Space, Typography } from 'antd';
import { useTopicStore } from '@/stores/topicStore';
import { trackApi } from '@/services/api';
import type { NoticeContext, TrackedEvent } from '@/types';
import { isCalendarDate } from '@/utils/calendarExport';
import { noticeUrl } from '@/utils/noticeAssistant';

interface NoticeProps {
  notice: NoticeContext;
}

export function NoticeAssistantButton({ notice }: NoticeProps) {
  const navigate = useNavigate();
  const { message } = App.useApp();
  const { createNoticeTopic, noticeCreating } = useTopicStore();
  const open = async () => {
    try {
      await createNoticeTopic(notice);
      navigate('/chat');
    } catch {
      message.error('创建通知话题失败，请稍后重试；当前通知仍保留。');
    }
  };
  return <Button size="small" loading={noticeCreating} onClick={() => void open()}>整理办理清单</Button>;
}

export function NoticeContextPanel({ notice }: NoticeProps) {
  const { message } = App.useApp();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [existing, setExisting] = useState<TrackedEvent | null>(null);
  const [dateKind, setDateKind] = useState<'deadline' | 'start'>(notice.dateKind || 'deadline');
  const [dateValue, setDateValue] = useState(isCalendarDate(notice.dateValue || null) ? notice.dateValue! : '');
  const saving = useRef(false);
  const url = noticeUrl(notice.url);
  const preview = async () => {
    if (saving.current) return;
    saving.current = true;
    setBusy(true);
    setError('');
    try {
      const { data } = await trackApi.list();
      setExisting(data.items.find(item => item.source === notice.source) || null);
      setOpen(true);
    } catch {
      setError('无法读取现有追踪，请重试后再确认，避免覆盖未知状态。');
    } finally {
      saving.current = false;
      setBusy(false);
    }
  };
  const confirm = async () => {
    if (!open || saving.current || !isCalendarDate(dateValue)) return;
    saving.current = true;
    setBusy(true);
    setError('');
    try {
      await trackApi.add({ source: notice.source, title: notice.title, category: notice.category,
        date_kind: dateKind, date_value: dateValue, url });
      setOpen(false);
      message.success('追踪已保存，可在今日面板查看');
    } catch {
      setError('保存失败，请核对今日面板中的实际结果后重试。');
    } finally {
      saving.current = false;
      setBusy(false);
    }
  };
  return <div style={{ borderBottom: '1px solid #eee', padding: '12px 8px' }}>
    <Space wrap>
      <Typography.Text strong>正在整理：{notice.title}</Typography.Text>
      {url && <a href={url} target="_blank" rel="noopener noreferrer">核对原文</a>}
      <Button size="small" loading={busy} onClick={() => void preview()}>追踪这则通知</Button>
    </Space>
    <div><Typography.Text type="secondary">通知只读模式：点击发送后整理，不提供资料写入或课表导入工具。日期核对后单独确认追踪。</Typography.Text></div>
    {error && !open && <Alert type="error" showIcon message={error} />}
    <Modal title="核对后保存追踪" open={open} onCancel={() => { if (!saving.current) setOpen(false); }}
      onOk={() => void confirm()} confirmLoading={busy} okText={existing ? '确认更新追踪' : '确认加入追踪'} cancelText="取消"
      okButtonProps={{ disabled: !isCalendarDate(dateValue) }} cancelButtonProps={{ disabled: busy }}>
      <Typography.Paragraph>{notice.title}</Typography.Paragraph>
      <Alert type="info" showIcon message="请从原文核对日期，不能把发布日期当作截止日；没有具体时刻时只保存全天日期。" />
      {existing && <Alert type="warning" showIcon style={{ marginTop: 12 }} message="同一来源已有追踪，确认将更新该记录"
        description={`原记录：${existing.date_kind === 'deadline' ? '截止' : '开始'} ${existing.date_value || '日期未知'}`} />}
      <Space wrap style={{ marginTop: 16 }}>
        <Select aria-label="追踪日期类型" value={dateKind} onChange={setDateKind} disabled={busy}
          options={[{ value: 'deadline', label: '截止日期' }, { value: 'start', label: '开始日期' }]} />
        <Input aria-label="核对后的追踪日期" type="date" value={dateValue} disabled={busy} onChange={event => setDateValue(event.target.value)} />
      </Space>
      {error && <Alert type="error" showIcon message={error} style={{ marginTop: 12 }} />}
    </Modal>
  </div>;
}
