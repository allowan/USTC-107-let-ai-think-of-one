import { useEffect, useState, useCallback } from 'react';
import { Card, Tag, Button, App, Spin, Empty, Space, Typography, Tooltip } from 'antd';
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
import { digestApi, trackApi } from '@/services/api';
import type { DigestData, DigestEvent, TrackedEvent } from '@/types';

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
  if (d !== undefined && d <= 0) {
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
}

function EventRow({ e, tracked, onTrack, onUntrack }: EventRowProps) {
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
        </div>
      </div>
      <Tooltip title={tracked ? '取消追踪' : '追踪此事件'}>
        <Button
          type="text"
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
}

function EventSection({ title, icon, events, trackedSources, onTrack, onUntrack, emptyHint }: SectionProps) {
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
  const [tracked, setTracked] = useState<TrackedEvent[]>([]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [{ data: d }, { data: t }] = await Promise.all([
        digestApi.get(days),
        trackApi.list(),
      ]);
      setDigest(d);
      setTracked(t.items || []);
    } catch {
      message.error('加载今日面板失败');
    } finally {
      setLoading(false);
    }
  }, [days, message]);

  useEffect(() => { load(); }, [load]);

  const trackedSet = new Set(tracked.map((t) => t.source));

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
      setTracked((prev) => prev.filter((t) => t.source !== source));
    } catch {
      message.error('取消追踪失败');
    }
  };

  // 追踪事件渲染为顶部固定区；date_value 非法时跳过倒计时（NaN 防御）
  const trackedAsEvents: DigestEvent[] = tracked.map((t) => {
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    let daysLeft: number | undefined;
    if (t.date_value) {
      const d = new Date(t.date_value);
      if (!Number.isNaN(d.getTime())) {
        daysLeft = Math.round((d.getTime() - today.getTime()) / 86400000);
      }
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
          <Button.Group>
            {[7, 14, 30].map((d) => (
              <Button key={d} size="small" type={days === d ? 'primary' : 'default'} onClick={() => setDays(d)}>
                {d} 天
              </Button>
            ))}
          </Button.Group>
          <Button size="small" icon={<ReloadOutlined />} onClick={load} loading={loading} />
        </Space>
      </div>

      {loading && !digest ? (
        <div style={{ textAlign: 'center', padding: 48 }}><Spin /></div>
      ) : (
        <>
          {trackedAsEvents.length > 0 && (
            <EventSection
              title={`我追踪的事件（${trackedAsEvents.length}）`}
              icon={<BellOutlined style={{ color: '#faad14' }} />}
              events={trackedAsEvents}
              trackedSources={trackedSet}
              onTrack={handleTrack}
              onUntrack={handleUntrack}
              emptyHint=""
            />
          )}
          <EventSection
            title={`即将发生（${upcoming.length}）`}
            icon={<ClockCircleOutlined style={{ color: '#1677ff' }} />}
            events={upcoming}
            trackedSources={trackedSet}
            onTrack={handleTrack}
            onUntrack={handleUntrack}
            emptyHint={`未来 ${days} 天暂无即将截止或开始的事件`}
          />
          <EventSection
            title={`最近发布（${recent.length}）`}
            icon={<CalendarOutlined style={{ color: '#52c41a' }} />}
            events={recent}
            trackedSources={trackedSet}
            onTrack={handleTrack}
            onUntrack={handleUntrack}
            emptyHint={`最近 ${days} 天暂无新通知`}
          />
        </>
      )}
    </div>
  );
}
