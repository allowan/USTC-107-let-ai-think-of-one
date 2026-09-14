import { ChangeEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Alert, App, Button, Empty, Select, Space, Spin, Tag, Typography } from 'antd';
import { CalendarOutlined, CloudDownloadOutlined, FileAddOutlined, InfoCircleOutlined, ReloadOutlined } from '@ant-design/icons';
import axios from 'axios';
import { scheduleApi } from '@/services/api';
import { readScheduleFile, scheduleImportError } from '@/utils/scheduleImport';
import type { AcademicCalendar, ScheduleCourse, ScheduleData, ScheduleImportPreview } from '@/types';
import AcademicCalendarModal from '@/components/Schedule/AcademicCalendarModal';
import UstcScheduleImportModal from '@/components/Schedule/UstcScheduleImportModal';
import ScheduleImportPreviewModal from '@/components/Schedule/ScheduleImportPreviewModal';

const { Text, Title } = Typography;
const weekdays = ['星期一', '星期二', '星期三', '星期四', '星期五', '星期六', '星期日'];
const sectionCount = 13;

function hasValidGridPosition(course: ScheduleCourse): boolean {
  const { weekday, start_section: start } = course;
  const end = course.end_section ?? start;
  // 异常导入数据不能通过 CSS Grid 隐式行列扩展课表。
  return weekday !== null && Number.isInteger(weekday) && weekday >= 1 && weekday <= 7
    && start !== null && Number.isInteger(start) && start >= 1
    && end !== null && Number.isInteger(end) && end >= start && end <= sectionCount;
}

function addDays(value: string, days: number): Date {
  const result = new Date(`${value}T00:00:00`);
  result.setDate(result.getDate() + days);
  return result;
}

function localDate(value: Date): string {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, '0');
  const day = String(value.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

export default function SchedulePage() {
  const { message } = App.useApp();
  const [data, setData] = useState<ScheduleData>({ semester: null, semesters: [], courses: [] });
  const [loading, setLoading] = useState(true);
  const [importing, setImporting] = useState(false);
  const [importPreview, setImportPreview] = useState<ScheduleImportPreview | null>(null);
  const [importError, setImportError] = useState<string | null>(null);
  const [ustcImportVisible, setUstcImportVisible] = useState(false);
  const [calendarVisible, setCalendarVisible] = useState(false);
  const [calendar, setCalendar] = useState<AcademicCalendar | null>(null);
  const [selectedWeek, setSelectedWeek] = useState<number | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const load = useCallback(async (semester?: string) => {
    setLoading(true);
    try {
      const response = await scheduleApi.list(semester);
      setData({ ...response.data, courses: response.data.courses.filter(course => course.semester === response.data.semester) });
      const selectedSemester = response.data.semester;
      if (selectedSemester) {
        try {
          const calendarResponse = await scheduleApi.getCalendar(selectedSemester);
          setCalendar(calendarResponse.data);
          setSelectedWeek(calendarResponse.data.current_week || 1);
        } catch (error) {
          setCalendar(null);
          setSelectedWeek(null);
          if (!axios.isAxiosError(error) || error.response?.status !== 404) {
            message.error('读取校历失败，暂时显示全部周次课程');
          }
        }
      } else {
        setCalendar(null);
        setSelectedWeek(null);
      }
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
      const response = await scheduleApi.preview(payload);
      setImportError(null);
      setImportPreview(response.data);
    } catch (error) {
      message.error(scheduleImportError(error, '课表文件导入失败'));
    } finally {
      setImporting(false);
    }
  };

  const confirmImport = async () => {
    if (!importPreview || importPreview.errors.length || importing) return;
    setImporting(true);
    setImportError(null);
    try {
      await scheduleApi.import(importPreview.payload);
      message.success(`已导入 ${importPreview.course_count} 门课程`);
      setImportPreview(null);
      await load(importPreview.payload.semester);
    } catch (error) {
      setImportError(scheduleImportError(error, '课表保存失败，请重试'));
    } finally {
      setImporting(false);
    }
  };

  const visibleCourses = useMemo(
    () => selectedWeek === null
      ? data.courses
      : data.courses.filter(course => course.weeks.length === 0 || course.weeks.includes(selectedWeek)),
    [data.courses, selectedWeek],
  );
  const unplacedCourses = visibleCourses.filter(course => !hasValidGridPosition(course));
  const selectedWeekStart = calendar && selectedWeek
    ? addDays(calendar.start_date, (selectedWeek - 1) * 7)
    : null;
  const selectedWeekEnd = selectedWeekStart ? addDays(localDate(selectedWeekStart), 6) : null;
  const weekSpecialDates = calendar && selectedWeekStart && selectedWeekEnd
    ? calendar.special_dates.filter(item => item.date >= localDate(selectedWeekStart) && item.date <= localDate(selectedWeekEnd))
    : [];
  const today = new Date();
  const todayWeekday = today.getDay() === 0 ? 7 : today.getDay();
  const tomorrow = new Date(today);
  tomorrow.setDate(today.getDate() + 1);
  const tomorrowWeekday = tomorrow.getDay() === 0 ? 7 : tomorrow.getDay();
  const tomorrowWeek = calendar?.current_week
    ? calendar.current_week + (todayWeekday === 7 ? 1 : 0)
    : null;
  const todaySpecial = calendar?.special_dates.filter(item => item.date === localDate(today)) || [];
  const tomorrowSpecial = calendar?.special_dates.filter(item => item.date === localDate(tomorrow)) || [];
  const coursesForDate = (weekday: number, week: number | null, specials: typeof todaySpecial) => {
    if (!week || specials.some(item => item.kind === 'holiday' || item.kind === 'no_class')) return [];
    const makeup = specials.find(item => item.kind === 'makeup' && item.course_weekday);
    const courseWeekday = makeup?.course_weekday || weekday;
    return data.courses.filter(course =>
      (course.weeks.length === 0 || course.weeks.includes(week)) && course.weekday === courseWeekday);
  };
  const todayCourses = coursesForDate(todayWeekday, calendar?.current_week || null, todaySpecial);
  const tomorrowCourses = tomorrowWeek && tomorrowWeek <= (calendar?.total_weeks || 0)
    ? coursesForDate(tomorrowWeekday, tomorrowWeek, tomorrowSpecial)
    : [];
  const currentReminder = calendar?.current_week === selectedWeek
    ? [
      `今天${todayCourses.length ? `有 ${todayCourses.length} 个上课安排：${todayCourses.map(course => course.name).join('、')}` : '没有课程安排'}`,
      ...todaySpecial.map(item => `今日提醒：${item.label}`),
      `明天${tomorrowCourses.length ? `有 ${tomorrowCourses.length} 个上课安排：${tomorrowCourses.map(course => course.name).join('、')}` : '没有课程安排'}`,
      ...tomorrowSpecial.map(item => `明日提醒：${item.label}`),
    ].join('；')
    : '本周没有特殊校历提醒。';
  const sectionGroups = [
    { label: '上午', start: 1, end: 5 },
    { label: '下午', start: 6, end: 10 },
    { label: '晚上', start: 11, end: sectionCount },
  ];
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
          {data.semester && (
            <Button icon={<CalendarOutlined />} onClick={() => setCalendarVisible(true)}>
              配置校历
            </Button>
          )}
          <Button icon={<ReloadOutlined />} loading={loading} onClick={() => void load(data.semester || undefined)}>
            刷新本地课表
          </Button>
          <Button icon={<CloudDownloadOutlined />} onClick={() => setUstcImportVisible(true)}>
            获取课表
          </Button>
          <Button type="primary" icon={<FileAddOutlined />} loading={importing} disabled={importPreview !== null} onClick={() => fileInput.current?.click()}>
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
            {calendar && (
              <Select
                value={selectedWeek || undefined}
                placeholder="选择周次"
                options={Array.from({ length: calendar.total_weeks }, (_, index) => ({ value: index + 1, label: `第 ${index + 1} 周` }))}
                onChange={setSelectedWeek}
                style={{ width: 110 }}
              />
            )}
            <Button type={selectedWeek === null ? 'primary' : 'default'} onClick={() => setSelectedWeek(null)}>全部周次</Button>
          </div>
          {!calendar && <Alert type="warning" showIcon style={{ marginBottom: 12 }} message="尚未配置校历，当前显示全部周次课程" description="导入校历 iCalendar 后，可自动定位教学周并获得按周提醒。" />}
          {calendar?.status !== 'active' && calendar && (
            <Alert
              type="warning"
              showIcon
              style={{ marginBottom: 12 }}
              message={calendar.status === 'not_started' ? '学期尚未开始' : '本学期教学周已经结束'}
              description={calendar.status === 'not_started' ? `第一周从 ${calendar.start_date} 开始。` : '仍可手动选择周次查看历史课表。'}
            />
          )}
          {calendar && selectedWeekStart && selectedWeekEnd && (
            <Alert
              type={weekSpecialDates.length ? 'warning' : 'info'}
              showIcon
              style={{ marginBottom: 12 }}
              message={`第 ${selectedWeek} 周 · ${localDate(selectedWeekStart)} 至 ${localDate(selectedWeekEnd)}`}
              description={[
                calendar.current_week === selectedWeek ? currentReminder : '',
                ...weekSpecialDates
                  .filter(item => item.date !== localDate(today) && item.date !== localDate(tomorrow))
                  .map(item => `${item.date}：${item.label}${item.course_weekday ? `（按${weekdays[item.course_weekday - 1]}课程安排）` : ''}`),
              ].filter(Boolean).join('；') || '本周没有特殊校历提醒。'}
            />
          )}
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
              {visibleCourses.filter(hasValidGridPosition).map(course => {
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
                    {selectedWeek === null && course.weeks.length > 0 && <div className="schedule-course-meta">第 {course.weeks.join('、')} 周</div>}
                  </div>
                );
              })}
            </div>
          </div>
          {unplacedCourses.length > 0 && (
            <section className="schedule-review" aria-labelledby="schedule-review-title">
              <div className="schedule-review-heading">
                <span className="schedule-review-icon"><InfoCircleOutlined /></span>
                <div>
                  <div className="schedule-review-title-row">
                    <h2 id="schedule-review-title">待核对的安排</h2>
                    <Tag color="gold">{unplacedCourses.length} 项</Tag>
                  </div>
                  <p>以下安排已保留，核对星期或节次后可重新导入。每天支持第 1–13 节。</p>
                </div>
              </div>
              <ul className="schedule-review-list">
                {unplacedCourses.map(course => {
                  const weekdayValid = course.weekday !== null && Number.isInteger(course.weekday)
                    && course.weekday >= 1 && course.weekday <= 7;
                  const end = course.end_section ?? course.start_section;
                  const sectionValid = course.start_section !== null && Number.isInteger(course.start_section)
                    && course.start_section >= 1 && end !== null && Number.isInteger(end)
                    && end >= course.start_section && end <= sectionCount;
                  return (
                    <li className="schedule-review-card" key={course.id}>
                      <div className="schedule-review-card-heading">
                        <h3>{course.name}</h3>
                        <Space size={[0, 4]} wrap>
                          {!weekdayValid && <Tag color="gold">{course.weekday === null ? '星期待定' : '星期异常'}</Tag>}
                          {!sectionValid && <Tag color="gold">{course.start_section === null ? '节次待定' : '节次异常'}</Tag>}
                        </Space>
                      </div>
                      <dl className="schedule-review-meta">
                        <div><dt>地点</dt><dd>{course.location || '地点待定'}</dd></div>
                        <div><dt>教师</dt><dd>{course.teachers.join('、') || '教师待定'}</dd></div>
                        <div><dt>星期</dt><dd>{weekdayValid ? weekdays[course.weekday! - 1] : course.weekday === null ? '待定' : `原始值：${course.weekday}`}</dd></div>
                        <div><dt>节次</dt><dd>{course.start_section === null ? '待定' : `第 ${course.start_section}${end === course.start_section ? '' : `–${end}`} 节`}</dd></div>
                        <div className="schedule-review-meta-wide"><dt>周次</dt><dd>{course.weeks.length ? `第 ${course.weeks.join('、')} 周` : '全部周次'}</dd></div>
                        {(course.start_time || course.end_time) && <div className="schedule-review-meta-wide"><dt>时间</dt><dd>{course.start_time || '待定'}–{course.end_time || '待定'}</dd></div>}
                      </dl>
                      {course.raw_schedule && (
                        <details className="schedule-review-original">
                          <summary>查看原始安排</summary>
                          <p>{course.raw_schedule}</p>
                        </details>
                      )}
                    </li>
                  );
                })}
              </ul>
            </section>
          )}
        </>
      )}
      <ScheduleImportPreviewModal
        preview={importPreview}
        saving={importing}
        error={importError}
        onConfirm={() => void confirmImport()}
        onCancel={() => setImportPreview(null)}
      />
      <UstcScheduleImportModal
        open={ustcImportVisible}
        onCancel={() => setUstcImportVisible(false)}
        onImported={(result) => void load(result.semester)}
      />
      {data.semester && (
        <AcademicCalendarModal
          open={calendarVisible}
          semester={data.semester}
          calendar={calendar}
          onCancel={() => setCalendarVisible(false)}
          onSaved={(value) => {
            setCalendar(value);
            setSelectedWeek(value.current_week || 1);
          }}
        />
      )}
    </div>
  );
}
