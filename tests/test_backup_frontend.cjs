const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { createRequire } = require('node:module');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const requireFrontend = createRequire(path.resolve(__dirname, '../frontend/package.json'));
const ts = requireFrontend('typescript');
const React = requireFrontend('react');
const options = { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX };

function loadModule(file, requireMock) {
  const source = readFileSync(path.resolve(__dirname, '../frontend/src', file), 'utf8');
  const code = ts.transpileModule(source, { compilerOptions: options }).outputText;
  const module = { exports: {} };
  vm.runInThisContext(`(function(require, exports) { ${code}\n})`)(requireMock, module.exports);
  return module.exports;
}

function harness(api) {
  const state = [];
  let index = 0;
  let refreshed = 0;
  const requireMock = name => {
    if (name === 'react') return { ...React,
      useState: initial => { const key = index++; if (!(key in state)) state[key] = initial; return [state[key], value => { state[key] = value; }]; },
      useRef: () => ({ current: null }), useEffect() {}, useCallback: callback => callback,
    };
    if (name === 'antd') return { Alert: 'Alert', Button: 'Button', Card: 'Card', Checkbox: { Group: 'CheckboxGroup' },
      Empty: 'Empty', Modal: 'Modal', Space: 'Space', Spin: 'Spin', Typography: { Title: 'Title', Text: 'Text' } };
    if (name === '@ant-design/icons') return new Proxy({}, { get: () => 'Icon' });
    if (name === '@/services/api') return { backupApi: { catalog: async () => ({ data: { topics: [], documents: [], errors: [] } }), ...api } };
    if (name === '@/stores/topicStore') return { useTopicStore: { getState: () => ({ fetchTopics: async () => { refreshed++; } }) } };
    return requireFrontend(name);
  };
  const component = loadModule('pages/BackupPage.tsx', requireMock).default;
  return { render: () => { index = 0; return component(); }, refreshed: () => refreshed };
}

function find(tree, type) {
  if (!tree || typeof tree !== 'object') return undefined;
  if (tree.type === type) return tree;
  for (const child of [tree.props?.children].flat(Infinity)) {
    const result = find(child, type);
    if (result) return result;
  }
}

const settle = () => new Promise(resolve => setImmediate(resolve));
const preview = { checksum: 'a'.repeat(64), created_at: '2026-09-12T00:00:00+00:00', topics: [{ name: '测试话题', message_count: 2 }], documents: [] };
const file = { name: 'backup.json', size: 100 };

async function select(ui, chosen = file) {
  find(ui.render(), 'input').props.onChange({ target: { value: '', files: [chosen] } });
  await settle();
}

test('选择文件只预览，取消不恢复，确认绑定预览文件与校验和', async () => {
  const calls = [];
  const ui = harness({
    preview: async selected => { calls.push(['preview', selected]); return { data: preview }; },
    restore: async (...args) => { calls.push(['restore', ...args]); return { data: { restored: 1, skipped: 0, failed: 0, results: [] } }; },
  });
  await select(ui);
  assert.deepEqual(calls.map(item => item[0]), ['preview']);
  find(ui.render(), 'Modal').props.onCancel();
  assert.equal(find(ui.render(), 'Modal').props.open, false);
  await select(ui);
  find(ui.render(), 'Modal').props.onOk();
  await settle();
  assert.deepEqual(calls[2], ['restore', file, preview.checksum]);
  assert.equal(find(ui.render(), 'Modal').props.open, false);
  assert.equal(ui.refreshed(), 1);
});

test('选择超限或校验失败的新文件后，旧预览不能再被确认', async () => {
  let saves = 0;
  const ui = harness({ preview: async () => ({ data: preview }), restore: async () => { saves++; } });
  await select(ui);
  await select(ui, { ...file, size: 21 * 1024 * 1024 });
  const modal = find(ui.render(), 'Modal');
  assert.equal(modal.props.open, false);
  modal.props.onOk();
  await settle();
  assert.equal(saves, 0);
});

test('恢复失败保留预览，重试仍使用同一文件与校验和', async () => {
  let attempts = 0;
  const ui = harness({ preview: async () => ({ data: preview }), restore: async (selected, checksum) => {
    assert.equal(selected, file);
    assert.equal(checksum, preview.checksum);
    attempts++;
    return { data: { restored: 0, skipped: 0, failed: 1, results: [{ kind: 'topic', name: '测试话题', status: 'failed', message: '请重试' }] } };
  } });
  await select(ui);
  find(ui.render(), 'Modal').props.onOk();
  await settle();
  const modal = find(ui.render(), 'Modal');
  assert.equal(modal.props.open, true);
  assert.equal(modal.props.okText, '重试失败项');
  modal.props.onOk();
  await settle();
  assert.equal(attempts, 2);
});

test('API 使用独立预览接口，只有恢复请求携带确认校验和', async () => {
  const calls = [];
  const api = loadModule('services/api.ts', () => ({ default: { create: () => ({ post: async (...args) => { calls.push(args); } }) } })).backupApi;
  const selected = new Blob(['{}'], { type: 'application/json' });
  await api.preview(selected);
  await api.restore(selected, preview.checksum);
  assert.equal(calls[0][0], '/backup/preview');
  assert.equal(calls[0][1].get('confirmed_checksum'), null);
  assert.equal(calls[1][0], '/backup/restore');
  assert.equal(calls[1][1].get('confirmed_checksum'), preview.checksum);
});
