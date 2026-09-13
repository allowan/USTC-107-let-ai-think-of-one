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

function harness(getStatus) {
  const slots = [];
  let index = 0, mounted = false, syncs = 0;
  const effects = [];
  const exports = {};
  const source = readFileSync(path.resolve(__dirname, '../frontend/src/pages/SyncPage.tsx'), 'utf8');
  const code = ts.transpileModule(source, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX,
  } }).outputText;
  vm.runInNewContext(code, { exports, require(name) {
    if (name === 'react') return { ...React,
      useState(initial) { const key = index++; if (!(key in slots)) slots[key] = initial; return [slots[key], value => { slots[key] = value; }]; },
      useRef(initial) { const key = index++; return slots[key] ||= { current: initial }; },
      useCallback: fn => fn, useEffect(fn) { if (!mounted) effects.push(fn); },
    };
    if (name === 'antd') return { ...Object.fromEntries(['Alert', 'Card', 'Button', 'Statistic', 'Row', 'Col', 'Spin', 'Tag'].map(key => [key, key])),
      Typography: { Text: 'Text' }, Descriptions: Object.assign(() => null, { Item: 'Item' }), App: { useApp: () => ({ message: { success() {}, error() {} } }) } };
    if (name === '@ant-design/icons') return new Proxy({}, { get: () => 'Icon' });
    if (name === '@/services/api') return { syncApi: { getStatus, syncNow: async () => { syncs++; return { data: { status: 'ok' } }; } } };
    return requireFrontend(name);
  } });
  return { render() { index = 0; const tree = exports.default(); effects.splice(0).forEach(fn => fn()); mounted = true; return tree; }, syncs: () => syncs };
}

function find(tree, predicate) {
  if (!tree || typeof tree !== 'object') return undefined;
  if (predicate(tree)) return tree;
  for (const child of [tree.props?.children].flat(Infinity)) { const found = find(child, predicate); if (found) return found; }
}
const button = (tree, text) => find(tree, node => node.type === 'Button' && node.props.children === text);

test('状态失败显示未知，保留旧状态并禁止同步，重试成功才恢复', async () => {
  let fail = true;
  const ui = harness(async () => { if (fail) throw new Error('offline'); return { data: { server_online: true, local_version: 7 } }; });
  ui.render(); await settle();
  let tree = ui.render();
  assert.equal(find(tree, node => node.type === 'Statistic').props.value, '未知');
  assert.equal(find(tree, node => node.type === 'Alert').props.message, '状态获取失败');
  await button(tree, '立即同步').props.onClick();
  assert.equal(ui.syncs(), 0);
  fail = false;
  await button(tree, '重新获取状态').props.onClick(); await settle();
  tree = ui.render();
  assert.equal(button(tree, '立即同步').props.disabled, false);
  fail = true;
  await button(tree, '重新获取状态').props.onClick(); await settle();
  tree = ui.render();
  assert.equal(find(tree, node => node.type === 'Statistic').props.title, '服务端状态（上次结果）');
  assert.equal(find(tree, node => node.type === 'Statistic' && node.props.title === '本地版本').props.value, 7);
  assert.equal(button(tree, '立即同步').props.disabled, true);
});
