const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { createRequire } = require('node:module');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const requireFrontend = createRequire(path.resolve(__dirname, '../frontend/package.json'));
const ts = requireFrontend('typescript');
const React = requireFrontend('react');
const settle = () => new Promise(resolve => setImmediate(resolve));
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
};

function harness(histories, frames = []) {
  const slots = [];
  const effects = [];
  let index = 0;
  let fetches = 0;
  const store = { activeTopicId: 'topic-a', topics: [{ id: 'topic-a', name: '已有话题' }], loaded: true };
  const useTopicStore = () => store;
  useTopicStore.getState = () => store;
  const apiMessage = { error() {}, info() {}, warning() {} };
  const react = { ...React,
    useState(initial) {
      const key = index++;
      if (!(key in slots)) slots[key] = initial;
      return [slots[key], value => { slots[key] = typeof value === 'function' ? value(slots[key]) : value; }];
    },
    useRef(initial) { const key = index++; return slots[key] ||= { current: initial }; },
    useCallback(callback) { return callback; },
    useEffect(callback, deps) {
      const key = index++;
      const previous = slots[key];
      if (!previous || deps.some((value, i) => value !== previous.deps[i])) {
        effects.push(() => { previous?.cleanup?.(); slots[key] = { deps, cleanup: callback() }; });
      }
    },
  };
  const requireMock = name => {
    if (name === 'react') return react;
    if (name === 'antd') return { Input: { TextArea: 'TextArea' }, Button: 'Button', Empty: 'Empty', Select: 'Select', Space: 'Space', Tooltip: 'Tooltip', App: { useApp: () => ({ message: apiMessage }) } };
    if (name === '@ant-design/icons') return new Proxy({}, { get: () => 'Icon' });
    if (name === 'react-markdown' || name === 'remark-gfm') return { default: () => null };
    if (name === '@/stores/topicStore') return { useTopicStore };
    if (name === '@/utils/markdownLinks') return { normalizeAutoLink: () => ({}) };
    if (name === '@/services/api') return { settingsApi: { getGlobal: async () => ({ data: { env: {}, groups: [] } }) }, topicApi: { getHistory: () => histories.shift().promise } };
    return requireFrontend(name);
  };
  const source = readFileSync(path.resolve(__dirname, '../frontend/src/pages/ChatPage.tsx'), 'utf8');
  const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX } }).outputText;
  const exports = {};
  const context = { require: requireMock, exports, AbortController, DOMException, TextDecoder, setTimeout: () => 0,
    window: { addEventListener() {}, removeEventListener() {} }, fetch: async () => {
      fetches++;
      let cursor = 0;
      return { ok: true, body: { getReader: () => ({ read: async () => cursor < frames.length
        ? { done: false, value: new TextEncoder().encode(frames[cursor++]) } : { done: true } }) } };
    },
  };
  vm.runInNewContext(code, context);
  return { render() { index = 0; const tree = exports.default(); effects.splice(0).forEach(effect => effect()); return tree; },
    messages: () => slots[0], fetches: () => fetches, store };
}

function find(tree, predicate) {
  if (!tree || typeof tree !== 'object') return undefined;
  if (predicate(tree)) return tree;
  for (const child of [tree.props?.children].flat(Infinity)) { const result = find(child, predicate); if (result) return result; }
}
const sendButton = tree => find(tree, node => node.type === 'Button' && node.props.children === '发送');
function type(ui) { find(ui.render(), node => node.type === 'TextArea').props.onChange({ target: { value: '新问题' } }); }

test('历史未就绪时按钮和 Enter 均不能发送，加载后保留完整上下文', async () => {
  const history = deferred();
  const ui = harness([history], ['data: {"type":"token","content":"新回答"}\n\ndata: {"type":"done"}\n\n']);
  type(ui);
  assert.equal(sendButton(ui.render()).props.disabled, true);
  await sendButton(ui.render()).props.onClick();
  find(ui.render(), node => node.type === 'TextArea').props.onKeyDown({ key: 'Enter', nativeEvent: {}, preventDefault() {} });
  assert.equal(ui.fetches(), 0);
  history.resolve({ data: { messages: [{ role: 'user', content: '旧问题' }, { role: 'assistant', content: '旧回答' }] } });
  await settle();
  await sendButton(ui.render()).props.onClick();
  assert.deepEqual(Array.from(ui.messages(), message => message.content), ['旧问题', '旧回答', '新问题', '新回答']);
});

test('历史加载失败必须显式重试，切换话题后旧请求不能解锁发送', async () => {
  const first = deferred(), second = deferred(), retry = deferred();
  const ui = harness([first, second, retry]);
  type(ui);
  ui.store.activeTopicId = 'topic-b';
  ui.render();
  first.resolve({ data: { messages: [{ role: 'assistant', content: '旧话题' }] } });
  second.reject(new Error('offline'));
  await settle();
  assert.equal(sendButton(ui.render()).props.disabled, true);
  assert.equal(ui.messages().length, 0);
  find(ui.render(), node => node.type === 'Button' && node.props.children === '重新加载').props.onClick();
  ui.render();
  retry.resolve({ data: { messages: [] } });
  await settle();
  assert.equal(sendButton(ui.render()).props.disabled, false);
});

test('SSE 提前 EOF 保留已收到文字并提示不完整，不自动重发', async () => {
  const history = deferred();
  const ui = harness([history], ['data: {"type":"token","content":"部分回答"}\n\n']);
  type(ui);
  history.resolve({ data: { messages: [] } });
  await settle();
  await sendButton(ui.render()).props.onClick();
  assert.equal(ui.fetches(), 1);
  assert.match(ui.messages()[1].content, /部分回答/);
  assert.match(ui.messages()[2].content, /连接提前结束/);
});

test('SSE 明确 error 结束不会额外误报连接中断', async () => {
  const history = deferred();
  const ui = harness([history], ['data: {"type":"error","content":"模型不可用"}\n\n']);
  type(ui);
  history.resolve({ data: { messages: [] } });
  await settle();
  await sendButton(ui.render()).props.onClick();
  assert.equal(ui.messages().length, 2);
  assert.match(ui.messages()[1].content, /模型不可用/);
});

test('工具证据在回答前到达并跨帧去重，切换历史后仍可显示', async () => {
  const evidence = { id: 'source-1', source: '通知.txt', title: '实际通知', url: 'https://example.org/a',
    published_at: '', excerpt: '实际片段', kind: 'official' };
  const frame = `data: ${JSON.stringify({ type: 'evidence', content: { evidence: [evidence], warnings: ['关键词降级'] } })}\n\n`;
  const history = deferred();
  const ui = harness([history], [frame.slice(0, 14), frame.slice(14), frame, 'data: {"type":"token","content":"回答"}\n\ndata: {"type":"done"}\n\n']);
  type(ui);
  history.resolve({ data: { messages: [] } }); await settle();
  await sendButton(ui.render()).props.onClick();
  assert.equal(ui.messages().length, 2);
  assert.equal(ui.messages()[1].content, '回答');
  assert.equal(ui.messages()[1].evidence.length, 1);
  assert.equal(ui.messages()[1].warnings.length, 1);

  const restored = deferred();
  const next = harness([restored]); next.render();
  restored.resolve({ data: { messages: [{ role: 'assistant', content: '历史回答', evidence: [evidence], warnings: ['关键词降级'] }] } });
  await settle(); next.render();
  assert.equal(next.messages()[0].evidence[0].excerpt, '实际片段');
  assert.equal(next.messages()[0].warnings[0], '关键词降级');
});

