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

function harness(histories, frames = [], initialStore = {}) {
  const slots = [];
  const effects = [];
  let index = 0;
  let fetches = 0;
  const store = { activeTopicId: 'topic-a', topics: [{ id: 'topic-a', name: '已有话题' }], loaded: true, ...initialStore };
  const requests = [];
  store.consumeNoticeDraft = topicId => { if (store.noticeDraft?.topicId === topicId) store.noticeDraft = null; };
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
    if (name === 'antd') return { Input: { TextArea: 'TextArea' }, Button: 'Button', Empty: 'Empty', Select: 'Select', Space: 'Space', Tooltip: 'Tooltip', Popover: 'Popover', App: { useApp: () => ({ message: apiMessage }) } };
    if (name === '@ant-design/icons') return new Proxy({}, { get: () => 'Icon' });
    if (name === 'react-markdown' || name === 'remark-gfm') return { default: () => null };
    if (name === '@/stores/topicStore') return { useTopicStore };
    if (name === '@/components/NoticeAssistant') return { NoticeContextPanel: 'NoticeContextPanel' };
    if (name === '@/utils/markdownLinks') return { normalizeAutoLink: () => ({}) };
    if (name === '@/services/api') return { settingsApi: { getGlobal: async () => ({ data: { env: {}, groups: [] } }) }, topicApi: { getHistory: () => histories.shift().promise } };
    return requireFrontend(name);
  };
  const source = readFileSync(path.resolve(__dirname, '../frontend/src/pages/ChatPage.tsx'), 'utf8');
  const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX } }).outputText;
  const exports = {};
  const context = { require: requireMock, exports, AbortController, DOMException, TextDecoder, setTimeout: () => 0,
    window: { addEventListener() {}, removeEventListener() {} }, fetch: async (_url, options) => {
      fetches++;
      requests.push(JSON.parse(options.body));
      let cursor = 0;
      return { ok: true, body: { getReader: () => ({ read: async () => cursor < frames.length
        ? { done: false, value: new TextEncoder().encode(frames[cursor++]) } : { done: true } }) } };
    },
  };
  vm.runInNewContext(code, context);
  return { render() { index = 0; const tree = exports.default(); effects.splice(0).forEach(effect => effect()); return tree; },
    messages: () => slots[0], fetches: () => fetches, requests, store };
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

test('通知草稿不自动发送，历史就绪后发送使用只读模式', async () => {
  const history = deferred();
  const ui = harness([history], ['data: {"type":"done"}\n\n'], {
    noticeContexts: { 'topic-a': { source: 'notice', title: '通知', url: null } },
    noticeDraft: { topicId: 'topic-a', content: '整理通知草稿' },
  });
  ui.render();
  assert.equal(find(ui.render(), node => node.type === 'TextArea').props.value, '整理通知草稿');
  assert.equal(ui.fetches(), 0);
  assert.equal(ui.store.noticeDraft, null);
  history.resolve({ data: { messages: [] } }); await settle();
  await sendButton(ui.render()).props.onClick();
  assert.equal(ui.requests[0].read_only, true);
  assert.equal(ui.requests[0].content, '整理通知草稿');
});

async function citationRenderer(messages, content) {
  const history = deferred();
  const ui = harness([history]);
  ui.render();
  history.resolve({ data: { messages } });
  await settle();
  const bubble = find(ui.render(), node => node.props?.msg?.content === content);
  const rendered = bubble.type.type(bubble.props);
  return find(rendered, node => node.props?.components?.a).props.components.a;
}

test('行内来源精确匹配当前回合，并展示真实资料而非模型自报标题', async () => {
  const evidence = { id: 'a'.repeat(64), source: '通知.txt', title: '实际通知', url: 'https://example.org/a',
    published_at: '', excerpt: '实际片段', kind: 'official' };
  const renderLink = await citationRenderer([{ role: 'assistant', content: '回答', evidence: [evidence] }], '回答');
  const citation = renderLink({ href: `#evidence-${evidence.id}`, children: '已经核验的结论' });
  assert.equal(citation.type, 'Popover');
  assert.equal(citation.props.trigger, 'click');
  assert.match(citation.props.title, /请核对/);
  const button = find(citation, node => node.type === 'button');
  assert.equal(button.props.children, '查看来源');
  assert.equal(button.props['aria-label'], '查看引用来源：实际通知');
  const cards = find(citation.props.content, node => node.props?.evidence);
  assert.equal(cards.props.evidence[0].excerpt, '实际片段');
});

test('跨回合、虚构、截断标识与无证据旧历史均不伪造来源', async () => {
  const id = 'a'.repeat(64);
  const renderLink = await citationRenderer([
    { role: 'assistant', content: '旧回答', evidence: [{ id, source: '旧通知' }] },
    { role: 'assistant', content: '当前回答' },
  ], '当前回答');
  for (const value of [id, 'b'.repeat(64), 'a'.repeat(12), id.toUpperCase(), '']) {
    const citation = renderLink({ href: `#evidence-${value}`, children: '来源' });
    assert.equal(citation.type, 'span');
    assert.equal(citation.props.children, '来源未匹配');
    assert.equal(citation.props.href, undefined);
  }
});

test('普通网页与其他锚点继续使用原有 Markdown 链接渲染', async () => {
  const renderLink = await citationRenderer([{ role: 'assistant', content: '普通回答' }], '普通回答');
  for (const href of ['https://example.org/article', 'mailto:help@example.org', '#section']) {
    const link = renderLink({ href, children: '原有标题' });
    assert.equal(link.type.name, 'MarkdownLinkRenderer');
    assert.equal(link.props.href, href);
    assert.equal(link.props.children, '原有标题');
  }
});
