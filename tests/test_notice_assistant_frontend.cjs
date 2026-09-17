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

function load(file, dependencies = {}) {
  const exports = {};
  const code = ts.transpileModule(readFileSync(path.resolve(__dirname, '../frontend/src', file), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  vm.runInNewContext(code, { exports, URL, require: name => dependencies[name] || requireFrontend(name) });
  return exports;
}
const utils = load('utils/noticeAssistant.ts');
const { isCalendarDate } = load('utils/calendarExport.ts');
const notice = { source: 'notice.txt', title: '通知标题', url: 'https://example.edu/a', publishedAt: '2026-09-17' };

function panel(api, current = notice) {
  const slots = [];
  let index = 0;
  const components = load('components/NoticeAssistant.tsx', {
    react: { ...React,
      useState(initial) { const key = index++; if (!(key in slots)) slots[key] = initial; return [slots[key], value => { slots[key] = value; }]; },
      useRef(initial) { const key = index++; return slots[key] ||= { current: initial }; },
    },
    antd: { ...Object.fromEntries(['Alert', 'Button', 'Input', 'Modal', 'Select', 'Space'].map(key => [key, key])),
      Typography: { Text: 'Text', Paragraph: 'Paragraph' }, App: { useApp: () => ({ message: { success() {}, error() {} } }) } },
    'react-router-dom': { useNavigate: () => () => {} },
    '@/stores/topicStore': { useTopicStore: () => ({}) },
    '@/services/api': { trackApi: api },
    '@/utils/calendarExport': { isCalendarDate },
    '@/utils/noticeAssistant': utils,
  });
  return { render() { index = 0; return components.NoticeContextPanel({ notice: current }); } };
}
function find(tree, predicate) {
  if (!tree || typeof tree !== 'object') return undefined;
  if (predicate(tree)) return tree;
  for (const child of [tree.props?.children].flat(Infinity)) { const found = find(child, predicate); if (found) return found; }
}
const modal = ui => find(ui.render(), node => node.type === 'Modal');
const preview = ui => find(ui.render(), node => node.props.children === '追踪这则通知').props.onClick();
const setDate = (ui, value) => find(ui.render(), node => node.props['aria-label'] === '核对后的追踪日期').props.onChange({ target: { value } });

test('草稿不把发布日期当截止日，拒绝非法来源和带凭据链接', () => {
  const prompt = utils.buildNoticePrompt(notice);
  assert.match(prompt, /"known_date": null/);
  assert.match(prompt, /无法获得正文/);
  assert.match(prompt, /不写入个人资料/);
  assert.equal(utils.noticeUrl('javascript:alert(1)'), null);
  assert.equal(utils.noticeUrl('https://user:pass@example.edu'), null);
  assert.throws(() => utils.buildNoticePrompt({ ...notice, source: '' }), /来源/);
});

test('创建独立话题只预填草稿，创建失败不改变现有话题', async () => {
  let fail = true, creates = 0;
  const { useTopicStore } = load('stores/topicStore.ts', {
    '@/utils/noticeAssistant': utils,
    '@/services/api': { topicApi: { create: async () => { creates++; if (fail) throw Error('offline'); return { data: { id: 'notice-topic', name: '办理' } }; } } },
  });
  useTopicStore.setState({ activeTopicId: 'old', topics: [{ id: 'old', name: '旧话题' }] });
  await assert.rejects(useTopicStore.getState().createNoticeTopic(notice), /offline/);
  assert.equal(useTopicStore.getState().activeTopicId, 'old');
  assert.equal(useTopicStore.getState().noticeCreating, false);
  fail = false;
  await useTopicStore.getState().createNoticeTopic(notice);
  assert.equal(creates, 2);
  assert.equal(useTopicStore.getState().topics.length, 2);
  assert.equal(useTopicStore.getState().noticeDraft.topicId, 'notice-topic');
  assert.equal(useTopicStore.getState().noticeContexts['notice-topic'].source, notice.source);
  useTopicStore.getState().consumeNoticeDraft('old');
  assert.ok(useTopicStore.getState().noticeDraft);
  useTopicStore.getState().consumeNoticeDraft('notice-topic');
  assert.equal(useTopicStore.getState().noticeDraft, null);
});

test('预览和取消不写入，没有日期不能确认，确认仅保存一次', async () => {
  const writes = [];
  let finish;
  const ui = panel({ list: async () => ({ data: { items: [] } }), add: value => { writes.push(value); return new Promise(resolve => { finish = resolve; }); } });
  preview(ui); await settle();
  assert.equal(modal(ui).props.open, true);
  assert.equal(modal(ui).props.okButtonProps.disabled, true);
  modal(ui).props.onOk(); await settle();
  assert.equal(writes.length, 0);
  modal(ui).props.onCancel();
  assert.equal(modal(ui).props.open, false);
  preview(ui); await settle();
  setDate(ui, '2026-09-25');
  modal(ui).props.onOk(); modal(ui).props.onOk();
  assert.equal(writes.length, 1);
  assert.equal(writes[0].date_value, '2026-09-25');
  finish({}); await settle();
  assert.equal(modal(ui).props.open, false);
});

test('未知追踪状态阻止保存，已存在记录展示更新说明，失败保留表单', async () => {
  let readable = false;
  const ui = panel({ list: async () => { if (!readable) throw Error('offline'); return { data: { items: [{ source: notice.source, date_kind: 'start', date_value: '2026-09-20' }] } }; },
    add: async () => { throw Error('offline'); } });
  preview(ui); await settle();
  assert.equal(modal(ui).props.open, false);
  assert.ok(find(ui.render(), node => node.props.message?.includes?.('无法读取现有追踪')));
  readable = true;
  preview(ui); await settle();
  assert.equal(modal(ui).props.okText, '确认更新追踪');
  assert.ok(find(ui.render(), node => node.props.description === '原记录：开始 2026-09-20'));
  setDate(ui, '2026-09-26');
  modal(ui).props.onOk(); await settle();
  assert.equal(modal(ui).props.open, true);
  assert.ok(find(ui.render(), node => node.props.message?.includes?.('保存失败')));
  assert.equal(find(ui.render(), node => node.type === 'Input').props.value, '2026-09-26');
});
