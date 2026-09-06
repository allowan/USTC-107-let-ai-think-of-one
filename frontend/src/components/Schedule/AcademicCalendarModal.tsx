import { CalendarOutlined, MinusCircleOutlined, PlusOutlined } from '@ant-design/icons';
import { Alert, App, Button, Divider, Form, Input, InputNumber, Modal, Select, Space } from 'antd';
import { ChangeEvent, useEffect, useRef, useState } from 'react';
import axios from 'axios';
import { scheduleApi } from '@/services/api';
import type { AcademicCalendar, AcademicCalendarUpdate } from '@/types';

interface AcademicCalendarModalProps {
  open: boolean;
  semester: string;
  calendar: AcademicCalendar | null;
  onCancel: () => void;
  onSaved: (calendar: AcademicCalendar) => void;
}

const kindOptions = [
  { value: 'holiday', label: '节假日' },
  { value: 'no_class', label: '停课' },
  { value: 'makeup', label: '调课/补课' },
  { value: 'note', label: '其他提醒' },
];

export default function AcademicCalendarModal({
  open, semester, calendar, onCancel, onSaved,
}: AcademicCalendarModalProps) {
  const { message } = App.useApp();
  const [form] = Form.useForm<AcademicCalendarUpdate>();
  const [saving, setSaving] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  const useImportedCalendar = (items: Array<AcademicCalendar & { warnings?: string[] }>) => {
    const matched = items.find(item => item.semester === semester) || items[0];
    if (!matched) return;
    form.setFieldsValue({
      semester: matched.semester,
      start_date: matched.start_date,
      total_weeks: matched.total_weeks,
      special_dates: matched.special_dates,
    });
    if (matched.semester !== semester) {
      message.warning(`文件识别为 ${matched.semester}，保存后将配置该学期`);
    }
    matched.warnings?.forEach(warning => message.warning(warning));
  };

  const importIcs = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    setSaving(true);
    try {
      const response = await scheduleApi.importCalendarIcs(file, semester);
      useImportedCalendar(response.data.calendars);
      if (response.data.already_exists) {
        message.info(response.data.message);
      } else {
        message.success('已解析并保存校历 iCalendar，可继续核对和调整');
      }
      const imported = response.data.calendars.find(item => item.semester === semester) || response.data.calendars[0];
      if (imported?.semester === semester) onSaved(imported);
    } catch (error) {
      const detail = axios.isAxiosError(error) ? error.response?.data?.detail : undefined;
      message.error(typeof detail === 'string' ? detail : '校历导入失败，请检查后端连接后重试');
    } finally {
      setSaving(false);
    }
  };

  useEffect(() => {
    if (!open) return;
    form.setFieldsValue({
      semester,
      start_date: calendar?.start_date || '',
      total_weeks: calendar?.total_weeks,
      special_dates: calendar?.special_dates || [],
    });
  }, [calendar, form, open, semester]);

  const save = async () => {
    try {
      const values = await form.validateFields();
      setSaving(true);
      const response = await scheduleApi.saveCalendar({
        ...values,
        start_date: values.start_date || undefined,
        total_weeks: values.total_weeks || undefined,
      });
      message.success('校历已保存');
      onSaved(response.data.calendar);
      onCancel();
    } catch (error) {
      if (error && typeof error === 'object' && 'errorFields' in error) return;
      message.error('校历保存失败，请检查日期和特殊安排');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      title={`配置校历 · ${semester}`}
      open={open}
      onCancel={onCancel}
      onOk={() => void save()}
      confirmLoading={saving}
      okButtonProps={{ disabled: !calendar }}
      okText={calendar ? '保存校正' : '请先导入校历'}
      width={720}
    >
      <Alert
        type="info"
        showIcon
        message="上传中国科大教学日历 iCalendar"
        description="选择已下载的 .ics 文件，仅导入当前课表学期；文件可包含多年日历，导入后可校正日期与教学周数。"
        style={{ marginBottom: 16 }}
      />
      <Space wrap>
        <Button type="primary" icon={<CalendarOutlined />} onClick={() => fileInput.current?.click()} loading={saving}>导入校历 iCalendar</Button>
        <input ref={fileInput} hidden type="file" accept=".ics,.ical,text/calendar" onChange={importIcs} />
      </Space>
      <Divider />
      <Form form={form} layout="vertical">
        <Form.Item name="semester" hidden><Input /></Form.Item>
        <Space align="start" size="large">
          <Form.Item label="第一周周一日期（可选校正）" name="start_date">
            <Input type="date" allowClear style={{ width: 210 }} />
          </Form.Item>
          <Form.Item label="教学周数（可选校正）" name="total_weeks">
            <InputNumber min={1} max={30} precision={0} />
          </Form.Item>
        </Space>
        <Form.Item label="特殊日期（用于当周提醒）">
          <Form.List name="special_dates">
            {(fields, { add, remove }) => (
              <Space direction="vertical" style={{ width: '100%' }}>
                {fields.map(field => (
                  <Space key={field.key} align="baseline" wrap>
                    <Form.Item name={[field.name, 'date']} rules={[{ required: true, message: '请选择日期' }]}>
                      <Input type="date" style={{ width: 150 }} />
                    </Form.Item>
                    <Form.Item name={[field.name, 'kind']} rules={[{ required: true, message: '请选择类型' }]}>
                      <Select options={kindOptions} placeholder="类型" style={{ width: 120 }} />
                    </Form.Item>
                    <Form.Item name={[field.name, 'label']} rules={[{ required: true, message: '请输入提醒内容' }]}>
                      <Input placeholder="如：国庆节放假" style={{ width: 230 }} maxLength={100} />
                    </Form.Item>
                    <Form.Item name={[field.name, 'course_weekday']}>
                      <Select allowClear placeholder="按星期几上课" style={{ width: 140 }} options={Array.from({ length: 7 }, (_, index) => ({ value: index + 1, label: `星期${'一二三四五六日'[index]}` }))} />
                    </Form.Item>
                    <MinusCircleOutlined aria-label="删除该特殊日期" onClick={() => remove(field.name)} />
                  </Space>
                ))}
                <Button type="dashed" icon={<PlusOutlined />} onClick={() => add({ kind: 'note', course_weekday: null })}>添加特殊日期</Button>
              </Space>
            )}
          </Form.List>
        </Form.Item>
      </Form>
    </Modal>
  );
}
