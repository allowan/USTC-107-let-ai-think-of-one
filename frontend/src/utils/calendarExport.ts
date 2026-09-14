import type { TrackedEvent } from '@/types';

export function isCalendarDate(value: string | null): value is string {
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const date = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(date.getTime()) && date.toISOString().slice(0, 10) === value && value < '9999-12-31';
}

function escapeText(value: string): string {
  return value.replace(/\\/g, '\\\\').replace(/\r\n|\r|\n/g, '\\n').replace(/;/g, '\\;').replace(/,/g, '\\,').replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/g, '');
}

function foldLine(value: string): string {
  const encoder = new TextEncoder();
  let line = '', length = 0, result = '';
  // 按 Unicode 字符计 UTF-8 字节，避免中文被折断；续行空格占一字节。
  for (const character of value) {
    const bytes = encoder.encode(character).length;
    if (length + bytes > 75) { result += `${line}\r\n`; line = ' '; length = 1; }
    line += character;
    length += bytes;
  }
  return result + line;
}

export async function buildTrackedCalendar(items: TrackedEvent[], now = new Date()): Promise<string> {
  if (!items.length || items.length > 1000) throw new Error('请选择 1–1000 个追踪事件');
  if (items.some(item => !item.source || !isCalendarDate(item.date_value))) throw new Error('事件日期缺失或无效，请核对后再导出');
  const lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//USTC Campus Assistant//Tracked Events//ZH', 'CALSCALE:GREGORIAN'];
  const stamp = now.toISOString().replace(/[-:]/g, '').replace(/\.\d{3}Z$/, 'Z');
  for (const item of new Map(items.map(item => [item.source, item])).values()) {
    const day = item.date_value!;
    const nextDay = new Date(`${day}T00:00:00Z`);
    nextDay.setUTCDate(nextDay.getUTCDate() + 1);
    const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(`${item.source}\0${item.date_kind}`));
    const uid = Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('');
    lines.push('BEGIN:VEVENT', `UID:${uid}@campus-assistant.local`, `DTSTAMP:${stamp}`,
      `DTSTART;VALUE=DATE:${day.replace(/-/g, '')}`, `DTEND;VALUE=DATE:${nextDay.toISOString().slice(0, 10).replace(/-/g, '')}`,
      `SUMMARY:${escapeText(`${item.date_kind === 'deadline' ? '截止' : '开始'}：${item.title || item.source}`)}`,
      `DESCRIPTION:${escapeText(`来源：${item.source}\n导出时的追踪日期：${day}。全天标记不代表具体截止时刻，请核对原文。`)}`,
      'TRANSP:TRANSPARENT');
    if (item.url) {
      try {
        const url = new URL(item.url);
        if (['http:', 'https:'].includes(url.protocol) && !url.username && !url.password) lines.push(`URL:${url.href}`);
      } catch { /* 非法链接不进入日历，标题和日期仍可导出。 */ }
    }
    lines.push('END:VEVENT');
  }
  lines.push('END:VCALENDAR');
  return `${lines.map(foldLine).join('\r\n')}\r\n`;
}
