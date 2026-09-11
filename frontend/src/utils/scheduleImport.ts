import axios from 'axios';
import type { ScheduleImportPayload } from '@/types';

function csvRows(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = '';
  let quoted = false;
  let closedQuote = false;
  const content = text.replace(/^\uFEFF/, '');
  for (let index = 0; index <= content.length; index += 1) {
    const char = content[index];
    if (quoted) {
      if (char === undefined) throw new Error('CSV 存在未闭合的双引号');
      if (char === '"') {
        if (content[index + 1] === '"') { cell += '"'; index += 1; }
        else { quoted = false; closedQuote = true; }
      } else cell += char;
    } else if (char === ',' || char === '\n' || char === '\r' || char === undefined) {
      row.push(cell.trim());
      cell = '';
      closedQuote = false;
      if (char !== ',') {
        if (row.some(value => value !== '')) rows.push(row);
        row = [];
        if (char === '\r' && content[index + 1] === '\n') index += 1;
      }
    } else if (char === '"' && !cell.trim() && !closedQuote) {
      cell = '';
      quoted = true;
    } else if (char === '"' || (closedQuote && char.trim())) {
      throw new Error('CSV 双引号后只能出现分隔符，请检查文件格式');
    } else cell += char;
  }
  return rows;
}

export function parseScheduleCsv(text: string): ScheduleImportPayload {
  const [headers, ...rows] = csvRows(text);
  if (!headers || rows.length === 0) throw new Error('CSV 至少需要表头和一行课程');
  if (!headers.includes('name')) throw new Error('CSV 缺少 name 课程名称列');
  if (new Set(headers).size !== headers.length) throw new Error('CSV 表头不能重复');
  const semesters = new Set<string>();
  const courses = rows.map((cells, index) => {
    const position = `第 ${index + 1} 条课程`;
    if (cells.length !== headers.length) throw new Error(`${position}列数与表头不一致；包含逗号的单元格需用双引号包围`);
    const value = (name: string): string => cells[headers.indexOf(name)] || '';
    const number = (input: string, field: string): number => {
      if (!/^\d+$/.test(input)) throw new Error(`${position}的 ${field} 必须是整数`);
      const result = Number(input);
      if (!Number.isSafeInteger(result)) throw new Error(`${position}的 ${field} 数值过大`);
      return result;
    };
    const numbers = (field: string): number[] => {
      const input = value(field);
      if (!input) return [];
      return input.split(/[;，,]/).flatMap(part => {
        const range = part.trim().match(/^(\d+)\s*[-~]\s*(\d+)$/);
        if (!range) return [number(part.trim(), field)];
        const start = number(range[1], field);
        const end = number(range[2], field);
        if (start > end) throw new Error(`${position}的 ${field} 范围不能倒序`);
        if (end - start > 1000) throw new Error(`${position}的 ${field} 范围过大`);
        return Array.from({ length: end - start + 1 }, (_, offset) => start + offset);
      });
    };
    if (!value('name')) throw new Error(`${position}缺少课程名称`);
    if (value('semester')) semesters.add(value('semester'));
    const credits = value('credits') ? Number(value('credits')) : null;
    if (credits !== null && !Number.isFinite(credits)) throw new Error(`${position}的 credits 必须是数字`);
    return {
      course_code: value('course_code'), name: value('name'),
      teachers: value('teachers').split(/[;，]/).map(item => item.trim()).filter(Boolean),
      credits, raw_schedule: value('raw_schedule'),
      meetings: [{
        weekday: value('weekday') ? number(value('weekday'), 'weekday') : null,
        sections: numbers('sections'), weeks: numbers('weeks'), location: value('location'),
        start_time: value('start_time') || null, end_time: value('end_time') || null,
      }],
    };
  });
  if (semesters.size > 1) throw new Error('一次只能导入一个学期，请拆分 CSV 文件');
  return { semester: [...semesters][0] || '导入课表', courses };
}

export async function readScheduleFile(file: File): Promise<ScheduleImportPayload> {
  if (file.size > 5_000_000) throw new Error('课表文件不能超过 5 MB');
  const content = (await file.text()).replace(/^\uFEFF/, '');
  if (file.name.toLowerCase().endsWith('.csv')) return parseScheduleCsv(content);
  const payload = JSON.parse(content) as ScheduleImportPayload | null;
  if (!payload || !payload.semester || !Array.isArray(payload.courses)) throw new Error('JSON 需要包含 semester 和 courses');
  return payload;
}

export function scheduleImportError(error: unknown, fallback: string): string {
  if (axios.isAxiosError(error)) {
    if (error.response?.status === 404 || error.response?.status === 405) {
      return '课表接口不可用，请重启后端并刷新页面后重试';
    }
    const detail = error.response?.data?.detail;
    if (typeof detail === 'string' && detail) return detail;
    if (detail && Array.isArray(detail.errors)) return [detail.message, ...detail.errors].filter(Boolean).join('；');
    if (Array.isArray(detail)) return detail.map(item => `${item.loc?.join('.') || '课表'}：${item.msg}`).join('；');
  }
  return error instanceof Error ? error.message : fallback;
}
