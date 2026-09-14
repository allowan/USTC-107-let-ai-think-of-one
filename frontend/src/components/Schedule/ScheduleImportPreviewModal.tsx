import { Alert, Modal, Table } from 'antd';
import type { ScheduleImportPreview } from '@/types';

interface Props {
  preview: ScheduleImportPreview | null;
  saving: boolean;
  error: string | null;
  onConfirm: () => void;
  onCancel: () => void;
}

export default function ScheduleImportPreviewModal({ preview, saving, error, onConfirm, onCancel }: Props) {
  const weekdays = ['星期一', '星期二', '星期三', '星期四', '星期五', '星期六', '星期日'];
  const rows = !preview || preview.errors.length ? [] : preview.payload.courses.flatMap((course, index) =>
    (course.meetings?.length ? course.meetings : [{}]).map((meeting, meetingIndex) => ({
      key: `${index}-${meetingIndex}`,
      name: course.name,
      weekday: meeting.weekday ? weekdays[Number(meeting.weekday) - 1] : '星期待定',
      sections: meeting.sections?.length ? `第 ${meeting.sections.join('、')} 节` : '节次待定',
      weeks: meeting.weeks?.length ? `第 ${meeting.weeks.join('、')} 周` : '全部周次',
      time: meeting.start_time && meeting.end_time ? `${meeting.start_time}–${meeting.end_time}` : '未提供',
      location: meeting.location || '地点待定',
    })),
  );
  return (
    <Modal
      title="确认课表导入"
      open={preview !== null}
      onCancel={() => { if (!saving) onCancel(); }}
      onOk={onConfirm}
      okText={preview?.existing_meeting_count ? '确认覆盖该学期课表' : '确认导入'}
      okButtonProps={{ disabled: !preview || preview.errors.length > 0 }}
      cancelButtonProps={{ disabled: saving }}
      cancelText="返回修改"
      confirmLoading={saving}
      closable={!saving}
      maskClosable={!saving}
      width={1000}
    >
      {preview && <>
        <Alert
          showIcon
          type={preview.existing_meeting_count ? 'warning' : 'info'}
          message={`学期：${preview.payload.semester} · ${preview.course_count} 门课程 · ${preview.meeting_count} 个安排`}
          description={preview.existing_meeting_count
            ? `确认后将替换该学期已有的 ${preview.existing_meeting_count} 个安排，其他学期和校历保持不变。当前预览尚未保存。`
            : '当前预览尚未保存，请核对学期与课程安排后确认。'}
          style={{ marginBottom: 12 }}
        />
        {preview.errors.length > 0 && <Alert type="error" showIcon message="请修正以下问题后重新预览，原有课表未修改"
          description={<ul style={{ maxHeight: 220, overflowY: 'auto', paddingLeft: 20 }}>{preview.errors.map((item, index) => <li key={index}>{item}</li>)}</ul>}
          style={{ marginBottom: 12 }} />}
        {preview.warnings.length > 0 && <Alert type="warning" showIcon message="以下安排需要留意，不影响确认导入"
          description={<ul style={{ maxHeight: 160, overflowY: 'auto', paddingLeft: 20 }}>{preview.warnings.map((item, index) => <li key={index}>{item}</li>)}</ul>}
          style={{ marginBottom: 12 }} />}
        {error && <Alert type="error" showIcon message={error} style={{ marginBottom: 12 }} />}
        {rows.length > 0 && <Table size="small" dataSource={rows} pagination={{ pageSize: 10, showSizeChanger: false }} scroll={{ x: 850 }}
          columns={[
            { title: '课程', dataIndex: 'name', width: 180 },
            { title: '星期', dataIndex: 'weekday', width: 90 },
            { title: '节次', dataIndex: 'sections', width: 120 },
            { title: '具体时间', dataIndex: 'time', width: 120 },
            { title: '周次', dataIndex: 'weeks', width: 200 },
            { title: '地点', dataIndex: 'location', width: 140 },
          ]} />}
      </>}
    </Modal>
  );
}
