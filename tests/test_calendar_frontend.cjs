const assert = require('node:assert/strict');
const { webcrypto } = require('node:crypto');
const { readFileSync } = require('node:fs');
const { createRequire } = require('node:module');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');
const requireFrontend = createRequire(path.resolve(__dirname, '../frontend/package.json'));
const ts = requireFrontend('typescript');
const exportsModule = {};
const source = readFileSync(path.resolve(__dirname, '../frontend/src/utils/calendarExport.ts'), 'utf8');
vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } }).outputText,
  { exports: exportsModule, TextEncoder, crypto: webcrypto, URL });
const { buildTrackedCalendar, isCalendarDate } = exportsModule;
const event = { source: '学习/通知', title: '活动', date_kind: 'deadline', date_value: '2026-12-31', url: 'https://example.org/notice' };

test('全天日期跨年正确且不虚构截止时刻，UID稳定并按来源去重', async () => {
  const first = (await buildTrackedCalendar([event, event], new Date('2026-09-13T00:00:00Z'))).replace(/\r\n /g, '');
  const second = (await buildTrackedCalendar([{ ...event, date_value: '2027-01-02' }])).replace(/\r\n /g, '');
  assert.match(first, /DTSTART;VALUE=DATE:20261231\r\nDTEND;VALUE=DATE:20270101/);
  assert.equal(first.match(/BEGIN:VEVENT/g).length, 1);
  assert.equal(first.match(/UID:([^\r]+)/)[1], second.match(/UID:([^\r]+)/)[1]);
  assert.doesNotMatch(first, /VALARM|ATTENDEE|METHOD:/);
});

test('中文按UTF-8折行，标题换行不能注入日历字段，非法URL不导出', async () => {
  const title = '中文😀'.repeat(50) + ',;\\\r\nBEGIN:VEVENT';
  const text = await buildTrackedCalendar([{ ...event, title, url: 'javascript:alert(1)' }]);
  for (const line of text.split('\r\n')) assert.ok(Buffer.byteLength(line, 'utf8') <= 75);
  const unfolded = text.replace(/\r\n /g, '');
  assert.equal(unfolded.match(/\r\nBEGIN:VEVENT\r\n/g).length, 1);
  assert.ok(unfolded.includes('中文😀'.repeat(50)));
  assert.ok(unfolded.includes('\\,\\;\\\\\\nBEGIN:VEVENT'));
  assert.doesNotMatch(unfolded, /\r\nURL:/);
});

test('拒绝缺失/不存在的日期和超量，不静默导出部分数据', async () => {
  assert.equal(isCalendarDate('2026-02-29'), false);
  assert.equal(isCalendarDate('2028-02-29'), true);
  assert.equal(isCalendarDate('9999-12-31'), false);
  await assert.rejects(buildTrackedCalendar([{ ...event, date_value: null }]), /日期/);
  await assert.rejects(buildTrackedCalendar([]), /请选择/);
  await assert.rejects(buildTrackedCalendar(Array(1001).fill(event)), /1000/);
});

test('今日面板先预览，取消不下载，确认才导出选中的快照', async () => {
  const React = requireFrontend('react');
  const state = [];
  let index = 0, generated = 0, downloaded = 0;
  const componentExports = {};
  const code = ts.transpileModule(readFileSync(path.resolve(__dirname, '../frontend/src/pages/DigestPage.tsx'), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  const Button = Object.assign(() => null, { Group: 'ButtonGroup' });
  const Checkbox = Object.assign(() => null, { Group: 'CheckboxGroup' });
  vm.runInNewContext(code, { exports: componentExports, Blob, setTimeout: fn => fn(),
    URL: { createObjectURL: () => 'blob:calendar', revokeObjectURL() {} },
    document: { createElement: () => ({ click: () => downloaded++ }) },
    require(name) {
      if (name === 'react') return { ...React,
        useState(initial) { const key = index++; if (!(key in state)) state[key] = initial; return [state[key], value => { state[key] = value; }]; },
        useCallback: fn => fn, useEffect() {},
      };
      if (name === 'antd') return { Button, Checkbox, Modal: 'Modal', Alert: 'Alert', Card: 'Card', Tag: 'Tag', Spin: 'Spin', Empty: 'Empty', Space: 'Space', Tooltip: 'Tooltip',
        Typography: { Text: 'Text', Link: 'Link' }, App: { useApp: () => ({ message: { error() {} } }) } };
      if (name === '@ant-design/icons') return new Proxy({}, { get: () => 'Icon' });
      if (name === '@/utils/calendarExport') return { isCalendarDate, buildTrackedCalendar: async items => { generated++; assert.equal(items.length, 1); return 'calendar'; } };
      if (name === '@/services/api') return {
        digestApi: { get: async () => ({ data: { upcoming: [], recent: [] } }) },
        trackApi: { list: async () => ({ data: { items: [event, { ...event, source: '无日期', date_value: null }] } }) },
        scheduleApi: { getReminders: async () => ({ data: { calendar_configured: false } }) },
      };
      return requireFrontend(name);
    },
  });
  const render = () => { index = 0; return componentExports.default(); };
  function find(tree, predicate) {
    if (!tree || typeof tree !== 'object') return undefined;
    if (predicate(tree)) return tree;
    for (const child of [tree.props?.children].flat(Infinity)) { const result = find(child, predicate); if (result) return result; }
  }
  await find(render(), node => node.type === Button && node.props.icon).props.onClick();
  const open = () => find(render(), node => node.type === Button && node.props.children === '导出追踪日历').props.onClick();
  open();
  assert.equal(generated, 0);
  find(render(), node => node.type === 'Modal').props.onCancel();
  assert.equal(find(render(), node => node.type === 'Modal').props.open, false);
  assert.equal(downloaded, 0);
  open();
  find(render(), node => node.type === 'Modal').props.onOk();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(generated, 1);
  assert.equal(downloaded, 1);
});
