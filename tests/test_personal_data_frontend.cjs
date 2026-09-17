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

function harness(list) {
  const slots = [], effects = [];
  let index = 0, mounted = false;
  const exports = {};
  const code = ts.transpileModule(readFileSync(path.resolve(__dirname, '../frontend/src/pages/PersonalDataPage.tsx'), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  vm.runInNewContext(code, { exports, require(name) {
    if (name === 'react') return { ...React,
      useState(initial) { const key = index++; if (!(key in slots)) slots[key] = initial; return [slots[key], value => { slots[key] = value; }]; },
      useRef(initial) { const key = index++; return slots[key] ||= { current: initial }; },
      useCallback: fn => fn, useEffect(fn) { if (!mounted) effects.push(fn); },
    };
    if (name === 'antd') return { ...Object.fromEntries(['Alert', 'Button', 'Modal', 'Card', 'Space', 'Empty', 'Popconfirm', 'Segmented', 'Spin'].map(key => [key, key])),
      Input: Object.assign(() => null, { TextArea: 'TextArea' }), Upload: { Dragger: 'Dragger' }, Typography: { Text: 'Text', Paragraph: 'Paragraph' },
      App: { useApp: () => ({ message: { error() {}, success() {}, warning() {} } }) } };
    if (name === '@ant-design/icons') return new Proxy({}, { get: () => 'Icon' });
    if (name === '@/services/api') return { personalDataApi: { list } };
    if (name.startsWith('@/components/')) return { default: () => null };
    return requireFrontend(name);
  } });
  return { render() { index = 0; const tree = exports.default(); effects.splice(0).forEach(fn => fn()); mounted = true; return tree; } };
}
function find(tree, predicate) {
  if (!tree || typeof tree !== 'object') return undefined;
  if (predicate(tree)) return tree;
  for (const child of [tree.props?.children, tree.props?.extra].flat(Infinity)) { const found = find(child, predicate); if (found) return found; }
}
const button = (tree, label) => find(tree, node => node.type === 'Button' && node.props.children === label);

test('首次失败显示错误而非空资料，重试成功空列表才显示空状态', async () => {
  let fail = true;
  const ui = harness(async () => { if (fail) throw { response: { data: { detail: '资料存储暂时不可读' } } }; return { data: { items: [] } }; });
  assert.ok(find(ui.render(), node => node.type === 'Spin'));
  await settle();
  assert.equal(find(ui.render(), node => node.type === 'Empty'), undefined);
  const alert = find(ui.render(), node => node.type === 'Alert');
  assert.equal(alert.props.message, '资料存储暂时不可读');
  fail = false;
  alert.props.action.props.onClick(); await settle();
  assert.equal(find(ui.render(), node => node.type === 'Alert'), undefined);
  assert.ok(find(ui.render(), node => node.type === 'Empty'));
});

test('刷新失败保留旧资料并暂停编辑，恢复后重新允许编辑', async () => {
  let fail = false;
  const ui = harness(async () => { if (fail) throw Error('offline'); return { data: { items: [{ source: '原资料', full_content: '正文', chunks: 1 }] } }; });
  ui.render(); await settle();
  assert.equal(button(ui.render(), '编辑').props.disabled, false);
  fail = true;
  button(ui.render(), '刷新资料').props.onClick(); await settle();
  assert.ok(find(ui.render(), node => node.type === 'Card'));
  assert.equal(button(ui.render(), '编辑').props.disabled, true);
  assert.match(find(ui.render(), node => node.type === 'Alert').props.description, /保留上次/);
  fail = false;
  button(ui.render(), '刷新资料').props.onClick(); await settle();
  assert.equal(button(ui.render(), '编辑').props.disabled, false);
});

test('旧列表迟到不能覆盖更新请求的结果', async () => {
  let resolveOld, calls = 0;
  const ui = harness(() => ++calls === 1 ? new Promise(resolve => { resolveOld = resolve; }) : Promise.resolve({ data: { items: [] } }));
  ui.render();
  button(ui.render(), '刷新资料').props.onClick(); await settle();
  resolveOld({ data: { items: [{ source: '过期结果', chunks: 1 }] } }); await settle();
  assert.equal(find(ui.render(), node => node.type === 'Card'), undefined);
  assert.ok(find(ui.render(), node => node.type === 'Empty'));
});
