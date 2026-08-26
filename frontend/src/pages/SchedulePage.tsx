import { ChangeEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Alert, App, Button, Empty, Select, Space, Spin, Tag, Typography } from 'antd';
import { CloudDownloadOutlined, FileAddOutlined, ReloadOutlined } from '@ant-design/icons';
import { scheduleApi } from '@/services/api';
import type { ScheduleData, ScheduleImportPayload } from '@/types';
import UstcScheduleImportModal from '@/components/Schedule/UstcScheduleImportModal';

const { Text, Title } = Typography;
const weekdays = ['星期一', '星期二', '星期三', '星期四', '星期五', '星期六', '星期日'];

function parseCsv(text: string): ScheduleImportPayload {
  const lines = text.split(/\r?\n/).map(line => line.trim()).filter(Boolean);
  if (lines.length < 2) throw new Error('CSV 至少需要表头和一行课程');
  const headers = lines[0].split(',').map(value => value.trim());
  const index = (name: string) => headers.indexOf(name);
  const value = (cells: string[], name: string) => {
    const position = index(name);
    return position >= 0 ? cells[position]?.trim() || '' : '';
  };
  const courses = lines.slice(1).map(line => {
    const cells = line.split(',').map(value => value.trim());
    const sections = value(cells, 'sections').split(/[-~]/).map(Number).filter(Number.isFinite);
    const weeks = value(cells, 'weeks').split(/[;，,]/).map(Number).filter(Number.isFinite);
    return {
      course_code: value(cells, 'course_code'),
      name: value(cells, 'name'),
      teachers: value(cells, 'teachers').split(/[;，]/).map(item => item.trim()).filter(Boolean),
      credits: Number(value(cells, 'credits')) || null,
      raw_schedule: value(cells, 'raw_schedule'),
      meetings: [{
        weekday: Number(value(cells, 'weekday')) || null,
        sections,
        weeks,
        location: value(cells, 'location'),
        start_time: value(cells, 'start_time') || null,
        end_time: value(cells, 'end_time') || null,
      }],
    };
  }).filter(course => course.name);
  return { semester: '导入课表', courses };
}

async function readScheduleFile(file: File): Promise<ScheduleImportPayload> {
  const content = await file.text();
  if (file.name.toLowerCase().endsWith('.csv')) return parseCsv(content);
  const payload = JSON.parse(content) as ScheduleImportPayload;
  if (!payload.semester || !Array.isArray(payload.courses)) throw new Error('JSON 需要包含 semester 和 courses');
  return payload;
}

export default function SchedulePage() {
  const { message } = App.useApp();
  const [data, setData] = useState<ScheduleData>({ semester: null, semesters: [], courses: [] });
  const [loading, setLoading] = useState(true);
  const [importing, setImporting] = useState(false);
  const [ustcImportVisible, setUstcImportVisible] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  const load = useCallback(async (semester?: string) => {
    setLoading(true);
    try {
      const response = await scheduleApi.list(semester);
      setData(response.data);
    } catch {
      message.error('读取本地课表失败');
    } finally {
      setLoading(false);
    }
  }, [message]);

  useEffect(() => { void load(); }, [load]);

  const importFile = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    setImporting(true);
    try {
      const payload = await readScheduleFile(file);
      if (!payload.courses.length) throw new Error('文件中没有课程');
      await scheduleApi.import(payload);
      message.success(`已导入 ${payload.courses.length} 门课程`);
      await load(payload.semester);
    } catch (error) {
      message.error(error instanceof Error ? error.message : '课表文件导入失败');
    } finally {
      setImporting(false);
    }
  };

  const sectionCount = useMemo(() => Math.max(
    13,
    ...data.courses.map(course => course.end_section || course.start_section || 0),
  ), [data.courses]);
  const sectionGroups = [
    { label: '上午', start: 1, end: 5 },
    { label: '下午', start: 6, end: 10 },
    { label: '晚上', start: 11, end: sectionCount },
  ].filter(group => group.start <= sectionCount);
  const courseCount = new Set(data.courses.map(course => course.course_code || course.name)).size;

  return (
    <div style={{ maxWidth: 1200, margin: '0 auto' }}>
      <Space style={{ width: '100%', justifyContent: 'space-between', marginBottom: 20 }}>
        <div>
          <Title level={4} style={{ margin: 0 }}>我的课表</Title>
        </div>
        <Space>
          {data.semesters.length > 0 && (
            <Select
              value={data.semester || undefined}
              options={data.semesters.map(value => ({ value, label: value }))}
              onChange={value => void load(value)}
              style={{ minWidth: 180 }}
            />
          )}
          <Button icon={<ReloadOutlined />} loading={loading} onClick={() => void load(data.semester || undefined)}>
            刷新本地课表
          </Button>
          <Button icon={<CloudDownloadOutlined />} onClick={() => setUstcImportVisible(true)}>
            获取课表
          </Button>
          <Button type="primary" icon={<FileAddOutlined />} loading={importing} onClick={() => fileInput.current?.click()}>
            导入课表文件
          </Button>
          <input ref={fileInput} type="file" accept=".json,.csv,application/json,text/csv" hidden onChange={importFile} />
        </Space>
      </Space>

      {data.courses.length === 0 && (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message="导入课表后即可离线查看"
          description="可从中国科大教务系统复制加载完成后的页面内容导入，也支持项目结构化 JSON/CSV。导入完成后不需要保持浏览器或教务系统登录。"
        />
      )}

      {loading ? <div style={{ textAlign: 'center', padding: 48 }}><Spin /></div> : data.courses.length === 0 ? (
        <Empty description="暂无本地课表，请点击“获取课表”手动导入，或导入 JSON/CSV 文件" />
      ) : (
        <>
          <div className="schedule-summary">
            <Tag color="blue">{data.semester}</Tag>
            <Text type="secondary">共 {courseCount} 门课程 · {data.courses.length} 个上课安排</Text>
          </div>
          <div className="schedule-scroll">
            <div
              className="schedule-grid"
              style={{
                gridTemplateColumns: '72px 44px repeat(7, minmax(145px, 1fr))',
                gridTemplateRows: `48px repeat(${sectionCount}, 70px)`,
              }}
            >
              <div className="schedule-corner">时间 / 节次</div>
              <div className="schedule-section-header">节次</div>
              {weekdays.map(label => <div className="schedule-day-header" key={label}>{label}</div>)}

              {sectionGroups.map(group => (
                <div
                  className={`schedule-period-label ${group.label === '下午' ? 'afternoon' : group.label === '晚上' ? 'evening' : ''}`}
                  key={group.label}
                  style={{ gridColumn: 1, gridRow: `${group.start + 1} / span ${group.end - group.start + 1}` }}
                >
                  {group.label}
                </div>
              ))}
              {Array.from({ length: sectionCount }, (_, index) => index + 1).map(section => (
                <div className="schedule-section-number" key={`section-${section}`} style={{ gridColumn: 2, gridRow: section + 1 }}>
                  {section}
                </div>
              ))}
              {Array.from({ length: sectionCount }, (_, row) =>
                weekdays.map((_, day) => (
                  <div
                    className="schedule-cell"
                    key={`cell-${row + 1}-${day + 1}`}
                    style={{ gridColumn: day + 3, gridRow: row + 2 }}
                  />
                )),
              )}
              {data.courses.filter(course => course.weekday && course.start_section).map(course => {
                const start = course.start_section || 1;
                const span = Math.max(1, (course.end_section || start) - start + 1);
                const time = course.start_time && course.end_time ? `${course.start_time}-${course.end_time}` : '';
                return (
                  <div
                    className="schedule-course-block"
                    key={course.id}
                    style={{ gridColumn: course.weekday! + 2, gridRow: `${start + 1} / span ${span}` }}
                  >
                    {time && <div className="schedule-course-time">{time}</div>}
                    <div className="schedule-course-name">{course.name}</div>
                    <div className="schedule-course-meta">{course.teachers.join('、')}</div>
                    <div className="schedule-course-meta">{course.location || '地点待定'}</div>
                    {course.weeks.length > 0 && <div className="schedule-course-meta">第 {Math.min(...course.weeks)}-{Math.max(...course.weeks)} 周</div>}
                  </div>
                );
              })}
            </div>
          </div>
        </>
      )}
      <UstcScheduleImportModal
        open={ustcImportVisible}
        onCancel={() => setUstcImportVisible(false)}
        onImported={(result) => void load(result.semester)}
      />
    </div>
  );
}
