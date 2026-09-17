const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { createRequire } = require('node:module');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');
const requireFrontend = createRequire(path.resolve(__dirname, '../frontend/package.json'));
const React = requireFrontend('react');
const ts = requireFrontend('typescript');
const settle = () => new Promise(resolve => setImmediate(resolve));
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
};
const notice = { source: 'notice', title: '测试通知', deadline: '2026-09-17', days_left: 0, kind: 'deadline' };
const digest = { days: 7, generated_on: '2026-09-17', upcoming: [notice], recent: [] };

function harness(api) {
  const slots = [], effects = [];
  let index = 0;
  const exports = {};
  const code = ts.transpileModule(readFileSync(path.resolve(__dirname, '../frontend/src/pages/DigestPage.tsx'), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  vm.runInNewContext(code, { exports, Date, require(name) {
    if (name === 'react') return { ...React,
      useState(initial) { const key = index++; if (!(key in slots)) slots[key] = initial; return [slots[key], value => { slots[key] = typeof value === 'function' ? value(slots[key]) : value; }]; },
      useRef(initial) { const key = index++; return slots[key] ||= { current: initial }; },
      useCallback(fn, deps) {
        const key = index++;
        if (!slots[key] || deps.some((value, i) => value !== slots[key].deps[i])) slots[key] = { fn, deps };
        return slots[key].fn;
      },
      useEffect(fn, deps) {
        const key = index++, previous = slots[key];
        if (!previous || deps.some((value, i) => value !== previous.deps[i])) effects.push(() => {
          previous?.cleanup?.(); slots[key] = { deps, cleanup: fn() };
        });
      },
    };
    if (name === 'antd') return { ...Object.fromEntries(['Alert', 'Modal', 'Card', 'Tag', 'Spin', 'Empty', 'Space', 'Tooltip'].map(key => [key, key])),
      Button: Object.assign(() => null, { Group: 'ButtonGroup' }), Checkbox: { Group: 'CheckboxGroup' },
      Typography: { Text: 'Text', Link: 'Link' }, App: { useApp: () => ({ message: { success() {}, error() {} } }) } };
    if (name === '@ant-design/icons') return new Proxy({}, { get: () => 'Icon' });
    if (name === '@/services/api') return api;
    if (name === '@/utils/calendarExport') return { isCalendarDate: value => /^\d{4}-\d{2}-\d{2}$/.test(value || '') };
    return requireFrontend(name);
  } });
  return { render() { index = 0; const tree = exports.default(); effects.splice(0).forEach(fn => fn()); return tree; } };
}

function find(tree, predicate) {
  if (!tree || typeof tree !== 'object') return undefined;
  if (predicate(tree)) return tree;
  for (const child of [tree.props?.children].flat(Infinity)) { const found = find(child, predicate); if (found) return found; }
}
function text(tree) {
  if (tree == null || typeof tree === 'boolean') return '';
  if (typeof tree !== 'object') return String(tree);
  return [tree.props?.children].flat(Infinity).map(text).join('');
}
const section = tree => find(tree, node => node.props.title?.startsWith?.('即将发生'));
const refresh = tree => find(tree, node => node.props['aria-label'] === '刷新今日面板');
function apiWith(get, tracked = async () => ({ data: { items: [] } }), reminders = async () => ({ data: { calendar_configured: false } })) {
  return { digestApi: { get }, trackApi: { list: tracked }, scheduleApi: { getReminders: reminders } };
}

test('截止与开始的过去日期不冒充今天，进行中保持独立语义', async () => {
  for (const [event, expected] of [
    [{ ...notice, days_left: -2 }, '已截止 2 天'],
    [{ ...notice, kind: 'start', days_left: -2, event_start: '2026-09-15' }, '已开始 2 天'],
    [notice, '今天截止'],
    [{ ...notice, days_left: 2 }, 'D-2'],
    [{ ...notice, days_left: -2, ongoing: true }, '进行中'],
  ]) {
    const ui = harness(apiWith(async () => ({ data: { ...digest, upcoming: [event] } })));
    ui.render(); await settle();
    const eventSection = section(ui.render());
    const row = find(eventSection.type(eventSection.props), node => node.props.e);
    assert.ok(text(row.type(row.props)).includes(expected));
  }
});

test('课程请求未结束或失败时通知仍可读，追踪失败不伪造空状态', async () => {
  const slow = deferred();
  const ui = harness(apiWith(async () => ({ data: digest }), async () => { throw Error('offline'); }, () => slow.promise));
  ui.render(); await settle();
  let tree = ui.render();
  assert.equal(section(tree).props.events.length, 1);
  assert.equal(section(tree).props.trackingUnavailable, true);
  assert.equal(find(tree, node => node.type === 'Alert').props.message, '追踪事件加载失败');
  slow.reject(Error('offline')); await settle();
  tree = ui.render();
  assert.ok(find(tree, node => node.props.message === '课程提醒加载失败'));
  assert.equal(section(tree).props.events.length, 1);
});

test('失败保留旧通知并标注，重试成功清除错误', async () => {
  let fail = false;
  const ui = harness(apiWith(async () => { if (fail) throw Error('offline'); return { data: digest }; }));
  ui.render(); await settle();
  fail = true;
  await refresh(ui.render()).props.onClick();
  assert.equal(section(ui.render()).props.events.length, 1);
  assert.ok(find(ui.render(), node => node.props.message === '校园通知加载失败'));
  fail = false;
  await refresh(ui.render()).props.onClick();
  assert.equal(find(ui.render(), node => node.props.message === '校园通知加载失败'), undefined);
});

test('首次通知失败不显示暂无事件，迟到旧响应不能覆盖新时间范围', async () => {
  const old = deferred();
  const ui = harness(apiWith(days => days === 7 ? old.promise : Promise.resolve({ data: { ...digest, days: 14 } })));
  ui.render();
  find(ui.render(), node => Array.isArray(node.props.children) && node.props.children[0] === 14).props.onClick();
  ui.render(); await settle();
  old.reject(Error('old request failed')); await settle();
  assert.equal(section(ui.render()).props.emptyHint, '未来 14 天暂无即将截止或开始的事件');
  assert.equal(find(ui.render(), node => node.props.message === '校园通知加载失败'), undefined);

  const failed = harness(apiWith(async () => { throw Error('offline'); }));
  failed.render(); await settle();
  assert.equal(section(failed.render()), undefined);
  assert.ok(find(failed.render(), node => node.props.message === '校园通知加载失败'));
});
