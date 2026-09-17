import { useEffect, useState, useCallback, useRef } from 'react';
import { Alert, Checkbox, Modal, Card, Tag, Button, App, Spin, Empty, Space, Typography, Tooltip } from 'antd';
import {
  BellOutlined,
  ClockCircleOutlined,
  CalendarOutlined,
  StarOutlined,
  StarFilled,
  LinkOutlined,
  ReloadOutlined,
  EnvironmentOutlined,
} from '@ant-design/icons';
import { digestApi, scheduleApi, trackApi } from '@/services/api';
import type { CourseReminderData, CourseReminderDay, DigestData, DigestEvent, TrackedEvent } from '@/types';
import { buildTrackedCalendar, isCalendarDate } from '@/utils/calendarExport';
import { NoticeAssistantButton } from '@/components/NoticeAssistant';

const { Text, Link } = Typography;

// ── 日期徽章：左对齐的时间锚点，让用户 3 秒内定位"最要紧的事" ─────

interface Badge {
  dateText: string;
  leftText: string;
  cls: string;
}

function badgeOf(e: DigestEvent): Badge {
  // 最近发布：语义是"多久前"，不是倒计时
  if (e.days_since !== undefined) {
    return {
      dateText: e.publish_date?.slice(5) ?? '',
      leftText: e.days_since <= 0 ? '今天发布' : `${e.days_since} 天前`,
      cls: 'badge-recent',
    };
  }
  if (e.ongoing) {
    return {
      dateText: '进行中',
      leftText: e.event_end ? `至 ${e.event_end.slice(5)}` : '',
      cls: 'badge-ongoing',
    };
  }
  const when = (e.kind === 'start' ? e.event_start : e.deadline) ?? '';
  const d = e.days_left;
  if (d !== undefined && d < 0) {
    return { dateText: when.slice(5), leftText: `${e.kind === 'start' ? '已开始' : '已截止'} ${-d} 天`, cls: 'badge-recent' };
  }
  if (d === 0) {
    return { dateText: '今天', leftText: e.kind === 'start' ? '开始' : '截止', cls: 'badge-urgent' };
  }
  if (d !== undefined && d <= 3) {
    return { dateText: when.slice(5), leftText: `D-${d}`, cls: 'badge-urgent' };
  }
  return {
    dateText: when.slice(5),
    leftText: d !== undefined ? `D-${d}` : '',
    cls: e.kind === 'start' ? 'badge-start' : 'badge-soon',
  };
}

// ── 单条事件 ───────────────────────────────────────────────────────

interface EventRowProps {
  e: DigestEvent;
  tracked: boolean;
  onTrack: (e: DigestEvent) => void;
  onUntrack: (source: string) => void;
  trackingUnavailable: boolean;
}

function EventRow({ e, tracked, onTrack, onUntrack, trackingUnavailable }: EventRowProps) {
  const badge = badgeOf(e);
  const isRecent = e.days_since !== undefined;
  return (
    <div className="digest-event">
      <div className={`digest-date-badge ${badge.cls}`}>
        <div className="digest-badge-date">{badge.dateText}</div>
        {badge.leftText && <div className="digest-badge-left">{badge.leftText}</div>}
      </div>
      <div className="digest-event-body">
        <div className="digest-event-title">
          {e.category && <Tag className={`tag-kind-${e.kind ?? 'deadline'}`}>{e.category}</Tag>}
          <span>{e.title || e.source}</span>
        </div>
        <div className="digest-event-meta">
          {isRecent ? (
            <span>
              <CalendarOutlined /> 发布于 {e.publish_date}
            </span>
          ) : e.ongoing ? (
            <span>
              <ClockCircleOutlined /> {e.event_start} 起{e.event_end ? `，至 ${e.event_end} 结束` : '，进行中'}
            </span>
          ) : (
            <span>
              <ClockCircleOutlined /> {e.kind === 'start' ? '开始' : '截止'} {e.kind === 'start' ? e.event_start : e.deadline}
            </span>
          )}
          {e.location && (
            <span>
              <EnvironmentOutlined /> {e.location}
            </span>
          )}
          {e.url && (
            <Link href={e.url} target="_blank" rel="noopener noreferrer">
              <LinkOutlined /> 原文
            </Link>
          )}
          <NoticeAssistantButton notice={{ source: e.source, title: e.title || e.source, url: e.url,
            category: e.category, publishedAt: e.publish_date, dateKind: e.kind || 'deadline',
            dateValue: e.kind === 'start' ? e.event_start : e.deadline }} />
        </div>
      </div>
      <Tooltip title={tracked ? '取消追踪' : '追踪此事件'}>
        <Button
          type="text"
          disabled={trackingUnavailable}
          aria-label={tracked ? '取消追踪' : '追踪此事件'}
          className={`digest-track-btn${tracked ? ' is-tracked' : ''}`}
          icon={tracked ? <StarFilled /> : <StarOutlined />}
          onClick={() => (tracked ? onUntrack(e.source) : onTrack(e))}
        />
      </Tooltip>
    </div>
  );
}

interface SectionProps {
  title: string;
  icon: React.ReactNode;
  events: DigestEvent[];
  trackedSources: Set<string>;
  onTrack: (e: DigestEvent) => void;
  onUntrack: (source: string) => void;
  emptyHint: string;
  trackingUnavailable: boolean;
}

function EventSection({ title, icon, events, trackedSources, onTrack, onUntrack, emptyHint, trackingUnavailable }: SectionProps) {
  return (
    <Card size="small" className="digest-card" title={<Space>{icon}<span>{title}</span></Space>}>
      {events.length === 0 ? (
        <Empty description={emptyHint} image={Empty.PRESENTED_IMAGE_SIMPLE} style={{ margin: '12px 0' }} />
      ) : (
        events.map((e) => (
          <EventRow
            key={e.source}
            e={e}
            tracked={trackedSources.has(e.source)}
            onTrack={onTrack}
            onUntrack={onUntrack}
            trackingUnavailable={trackingUnavailable}
          />
        ))
      )}
    </Card>
  );
}

// ── 页面 ───────────────────────────────────────────────────────────

const WEEK_NAMES = ['日', '一', '二', '三', '四', '五', '六'];

export default function DigestPage() {
  const { message } = App.useApp();
  const [loading, setLoading] = useState(false);
  const [days, setDays] = useState(7);
  const [digest, setDigest] = useState<DigestData | null>(null);
  const [tracked, setTracked] = useState<TrackedEvent[] | null>(null);
  const [courseReminders, setCourseReminders] = useState<CourseReminderData | null>(null);
  const [loadErrors, setLoadErrors] = useState({ digest: false, tracked: false, courses: false });
  const [calendarPreview, setCalendarPreview] = useState<TrackedEvent[] | null>(null);
  const [calendarSelection, setCalendarSelection] = useState<string[]>([]);
  const [exporting, setExporting] = useState(false);
  const loadSequence = useRef(0);

  const exportCalendar = async () => {
    if (!calendarPreview || exporting || !calendarSelection.length) return;
    setExporting(true);
    try {
      const content = await buildTrackedCalendar(calendarPreview.filter(item => calendarSelection.includes(item.source)));
      const url = URL.createObjectURL(new Blob([content], { type: 'text/calendar;charset=utf-8' }));
      const link = document.createElement('a');
      link.href = url;
      link.download = 'campus-tracked-events.ics';
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      setCalendarPreview(null);
    } catch (error) {
      message.error(error instanceof Error ? error.message : '日历导出失败，请重试');
    } finally {
      setExporting(false);
    }
  };

  const load = useCallback(async () => {
    const sequence = ++loadSequence.current;
    setLoading(true);
    // 各区域独立提交结果，慢请求或失败不能挡住其余区域；迟到响应不能覆盖新范围。
    const refresh = async <T,>(key: keyof typeof loadErrors, request: Promise<{ data: T }>, apply: (data: T) => void) => {
      try {
        const { data } = await request;
        if (sequence !== loadSequence.current) return;
        apply(data);
        setLoadErrors(previous => ({ ...previous, [key]: false }));
      } catch {
        if (sequence === loadSequence.current) setLoadErrors(previous => ({ ...previous, [key]: true }));
      }
    };
    await Promise.all([
      refresh('digest', digestApi.get(days), setDigest),
      refresh('tracked', trackApi.list(), data => setTracked(data.items || [])),
      refresh('courses', scheduleApi.getReminders(), setCourseReminders),
    ]);
    if (sequence === loadSequence.current) setLoading(false);
  }, [days]);

  useEffect(() => { void load(); return () => { loadSequence.current++; }; }, [load]);

  const trackedSet = new Set((tracked || []).map((t) => t.source));
  const trackingUnavailable = tracked === null || loadErrors.tracked;

  const handleTrack = async (e: DigestEvent) => {
    const isStart = e.kind === 'start';
    try {
      await trackApi.add({
        source: e.source,
        title: e.title,
        category: e.category,
        date_kind: isStart ? 'start' : 'deadline',
        date_value: isStart ? e.event_start : e.deadline,
        url: e.url,
      });
      message.success('已加入追踪');
      const { data: t } = await trackApi.list();
      setTracked(t.items || []);
    } catch {
      message.error('追踪失败');
    }
  };

  const handleUntrack = async (source: string) => {
    try {
      await trackApi.remove(source);
      setTracked((prev) => (prev || []).filter((t) => t.source !== source));
    } catch {
      message.error('取消追踪失败');
    }
  };

  // 追踪事件渲染为顶部固定区；date_value 非法时跳过倒计时（NaN 防御）
  const trackedAsEvents: DigestEvent[] = (tracked || []).map((t) => {
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    let daysLeft: number | undefined;
    if (isCalendarDate(t.date_value)) {
      // 用本地日历日对应的 UTC 序号相减，避免时区偏移和夏令时改变全天倒计时。
      const todayOrdinal = Date.UTC(today.getFullYear(), today.getMonth(), today.getDate());
      daysLeft = (Date.parse(`${t.date_value}T00:00:00Z`) - todayOrdinal) / 86400000;
    }
    return {
      source: t.source,
      title: t.title,
      category: t.category,
      audience: null,
      publish_date: null,
      deadline: t.date_kind === 'deadline' ? t.date_value : null,
      deadline_text: null,
      event_start: t.date_kind === 'start' ? t.date_value : null,
      event_end: null,
      location: null,
      url: t.url,
      kind: t.date_kind,
      days_left: daysLeft,
    };
  }).sort((a, b) => (a.days_left ?? 9999) - (b.days_left ?? 9999));

  const upcoming = digest?.upcoming || [];
  const recent = digest?.recent || [];
  const today = new Date();

  const reminderRows = (label: string, day: CourseReminderDay) => (
    <div style={{ marginBottom: 10 }}>
      <Text strong>{label}{day.week ? ` · 第 ${day.week} 周` : ''}</Text>
      {day.special_dates.map(item => <Tag color="orange" key={`${day.date}-${item.label}`} style={{ marginLeft: 8 }}>{item.label}</Tag>)}
      {day.courses.length ? day.courses.map(course => (
        <div className="digest-event" key={`${label}-${course.id}`}>
          <div className="digest-date-badge badge-start">
            <div className="digest-badge-date">{course.start_time || `第${course.start_section || '?'}节`}</div>
            <div className="digest-badge-left">{course.end_time || ''}</div>
          </div>
          <div className="digest-event-body">
            <div className="digest-event-title"><span>{course.name}</span></div>
            <div className="digest-event-meta"><span>{course.location || '地点待定'} · {course.teachers.join('、') || '教师待定'}</span></div>
          </div>
        </div>
      )) : <div><Text type="secondary">暂无课程安排</Text></div>}
    </div>
  );

  return (
    <div className="digest-page">
      <div className="digest-header">
        <div>
          <div className="digest-today">
            {today.getMonth() + 1}月{today.getDate()}日 · 星期{WEEK_NAMES[today.getDay()]}
          </div>
          <Text type="secondary" className="digest-sub">
            今日校园 · 数据生成于 {digest?.generated_on ?? '—'}
          </Text>
        </div>
        <Space>
          <Button size="small" disabled={!tracked?.length || loading || trackingUnavailable} onClick={() => {
            setCalendarPreview((tracked || []).map(item => ({ ...item })));
            setCalendarSelection((tracked || []).filter(item => isCalendarDate(item.date_value)).map(item => item.source));
          }}>导出追踪日历</Button>
          <Button.Group>
            {[7, 14, 30].map((d) => (
              <Button key={d} size="small" type={days === d ? 'primary' : 'default'} onClick={() => setDays(d)}>
                {d} 天
              </Button>
            ))}
          </Button.Group>
          <Button size="small" aria-label="刷新今日面板" icon={<ReloadOutlined />} onClick={load} loading={loading} />
        </Space>
      </div>

      {(['digest', 'tracked', 'courses'] as const).filter(key => loadErrors[key]).map(key => <Alert key={key} type="error" showIcon style={{ marginBottom: 16 }}
        message={`${{ digest: '校园通知', tracked: '追踪事件', courses: '课程提醒' }[key]}加载失败`}
        description="此区域如有旧结果会保留，但可能已经过期；未取得数据不代表没有安排。其他区域仍可使用，请重试后核对。"
        action={<Button size="small" onClick={() => void load()} loading={loading}>重新加载</Button>}
      />)}

      <Modal title="预览追踪日历" open={calendarPreview !== null} onCancel={() => { if (!exporting) setCalendarPreview(null); }}
        onOk={() => void exportCalendar()} okText="确认下载日历" cancelText="取消" confirmLoading={exporting}
        okButtonProps={{ disabled: !calendarSelection.length || calendarSelection.length > 1000 }}>
        <Alert type="info" showIcon message="请核对日期后下载"
          description="仅导出所选项为全天事件，不代表具体截止时刻。文件是当前追踪记录的快照，不会自动随通知更新，也不会自动添加到你的日历。" style={{ marginBottom: 16 }} />
        <Checkbox.Group value={calendarSelection} onChange={values => setCalendarSelection(values as string[])}>
          <Space direction="vertical">
            {(calendarPreview || []).map(item => <Checkbox key={item.source} value={item.source} disabled={!isCalendarDate(item.date_value)}>
              {item.title || item.source} · {item.date_kind === 'deadline' ? '截止' : '开始'} {isCalendarDate(item.date_value) ? item.date_value : '日期待核对，不能导出'}
            </Checkbox>)}
          </Space>
        </Checkbox.Group>
      </Modal>

      {loading && !digest && !tracked && !courseReminders && (
        <div style={{ textAlign: 'center', padding: 48 }}><Spin /></div>
      )}
          {courseReminders?.calendar_configured && (
            <Card size="small" className="digest-card" title={<Space><BellOutlined style={{ color: '#1677ff' }} /><span>课程提醒 · {courseReminders.semester}</span></Space>}>
              {reminderRows('今天', courseReminders.today)}
              {reminderRows('明天', courseReminders.tomorrow)}
            </Card>
          )}
          {trackedAsEvents.length > 0 && (
            <EventSection
              title={`我追踪的事件（${trackedAsEvents.length}）`}
              icon={<BellOutlined style={{ color: '#faad14' }} />}
              events={trackedAsEvents}
              trackedSources={trackedSet}
              onTrack={handleTrack}
              onUntrack={handleUntrack}
              emptyHint=""
              trackingUnavailable={trackingUnavailable}
            />
          )}
          {digest && <EventSection
            title={`即将发生（${upcoming.length}）`}
            icon={<ClockCircleOutlined style={{ color: '#1677ff' }} />}
            events={upcoming}
            trackedSources={trackedSet}
            onTrack={handleTrack}
            onUntrack={handleUntrack}
            emptyHint={`未来 ${digest.days} 天暂无即将截止或开始的事件`}
            trackingUnavailable={trackingUnavailable}
          />}
          {digest && <EventSection
            title={`最近发布（${recent.length}）`}
            icon={<CalendarOutlined style={{ color: '#52c41a' }} />}
            events={recent}
            trackedSources={trackedSet}
            onTrack={handleTrack}
            onUntrack={handleUntrack}
            emptyHint={`最近 ${digest.days} 天暂无新通知`}
            trackingUnavailable={trackingUnavailable}
          />}
    </div>
  );
}
