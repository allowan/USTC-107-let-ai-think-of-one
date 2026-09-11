const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { createRequire } = require('node:module');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

// 复用前端 TypeScript 编译器，不额外安装测试运行时。
const requireFrontend = createRequire(path.resolve(__dirname, '../frontend/package.json'));
const ts = requireFrontend('typescript');
const source = readFileSync(path.resolve(__dirname, '../frontend/src/utils/scheduleImport.ts'), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
const moduleObject = { exports: {} };
vm.runInThisContext(`(function(require, exports) { ${compiled}\n})`)(requireFrontend, moduleObject.exports);
const { parseScheduleCsv, readScheduleFile, scheduleImportError } = moduleObject.exports;

test('CSV 空白安排保持待定，不生成第零节或第零周', () => {
  const payload = parseScheduleCsv('name,weekday,sections,weeks\n课程A,,,');
  assert.equal(payload.courses[0].meetings[0].weekday, null);
  assert.deepEqual(payload.courses[0].meetings[0].sections, []);
  assert.deepEqual(payload.courses[0].meetings[0].weeks, []);
});

test('CSV 支持 BOM、引号逗号、转义引号、多行字段和间断周范围', () => {
  const payload = parseScheduleCsv('\uFEFFsemester,name,weekday,sections,weeks,raw_schedule\r\n秋季,"课程,A",1,11-13,"1-3;5,7","第一行\n第二行 ""说明"""');
  assert.equal(payload.semester, '秋季');
  assert.equal(payload.courses[0].name, '课程,A');
  assert.deepEqual(payload.courses[0].meetings[0].sections, [11, 12, 13]);
  assert.deepEqual(payload.courses[0].meetings[0].weeks, [1, 2, 3, 5, 7]);
  assert.equal(payload.courses[0].raw_schedule, '第一行\n第二行 "说明"');
});

test('CSV 无效单元格不能被静默丢弃或改成待定', () => {
  for (const [field, value] of [['sections', 'abc'], ['weekday', '1.5'], ['weeks', '1;abc'], ['sections', '5-3']]) {
    assert.throws(() => parseScheduleCsv(`name,${field}\n课程A,${value}`), /第 1 条课程/);
  }
  assert.throws(() => parseScheduleCsv('name,sections\n,1'), /缺少课程名称/);
  assert.throws(() => parseScheduleCsv('name,sections\n课程A,1,2'), /列数/);
  assert.throws(() => parseScheduleCsv('name,name\n课程A,课程B'), /表头不能重复/);
  assert.throws(() => parseScheduleCsv('name\n"课程A'), /未闭合/);
  assert.throws(() => parseScheduleCsv('name\n"课程A"其他'), /双引号后/);
  assert.throws(() => parseScheduleCsv('semester,name\n春季,A\n秋季,B'), /一个学期/);
});

test('课表读取检查 JSON 外层结构和文件大小', async () => {
  const file = content => ({ name: 'schedule.json', size: content.length, text: async () => content });
  await assert.rejects(readScheduleFile(file('null')), /semester/);
  await assert.rejects(readScheduleFile(file('{}')), /semester/);
  await assert.rejects(readScheduleFile({ size: 5_000_001 }), /5 MB/);
  assert.equal((await readScheduleFile(file('\uFEFF{"semester":"秋季","courses":[]}'))).semester, '秋季');
});

test('后端错误展示课程定位和完整校验原因', () => {
  const error = detail => ({ isAxiosError: true, response: { data: { detail } } });
  assert.equal(scheduleImportError(error({ message: '校验失败', errors: ['课程A第1个安排节次越界'] }), '失败'), '校验失败；课程A第1个安排节次越界');
  assert.equal(scheduleImportError(error([{ loc: ['body', 'courses', 0, 'name'], msg: '必填' }]), '失败'), 'body.courses.0.name：必填');
  assert.match(scheduleImportError({ isAxiosError: true, response: { status: 405 } }, '失败'), /重启后端/);
});

function componentHarness(relativePath, api = {}) {
  const React = requireFrontend('react');
  const state = [];
  let stateIndex = 0;
  const Preview = () => null;
  const fakeReact = {
    ...React,
    useState: initial => {
      const index = stateIndex++;
      if (!(index in state)) state[index] = initial;
      return [state[index], value => { state[index] = value; }];
    },
    useRef: () => ({ current: null }), useEffect: () => {},
    useMemo: callback => callback(), useCallback: callback => callback,
  };
  const fakeRequire = name => {
    if (name === 'react') return fakeReact;
    if (name === 'antd') return {
      App: { useApp: () => ({ message: { success() {}, error() {}, warning() {} } }) },
      Input: { TextArea: 'TextArea' }, Typography: { Text: 'Text', Title: 'Title', Paragraph: 'Paragraph' },
      Modal: 'Modal', Alert: 'Alert', Button: 'Button', Space: 'Space', Table: 'Table',
      Empty: 'Empty', List: 'List', Select: 'Select', Spin: 'Spin', Tag: 'Tag',
    };
    if (name === '@ant-design/icons') return new Proxy({}, { get: () => 'Icon' });
    if (name === '@/services/api') return { scheduleApi: api };
    if (name === '@/utils/scheduleImport') return moduleObject.exports;
    if (name.includes('ScheduleImportPreviewModal')) return { default: Preview };
    if (name.startsWith('@/components/')) return { default: () => null };
    return requireFrontend(name);
  };
  const text = readFileSync(path.resolve(__dirname, '../frontend/src', relativePath), 'utf8');
  const result = ts.transpileModule(text, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX,
  } }).outputText;
  const componentModule = { exports: {} };
  vm.runInThisContext(`(function(require, exports) { ${result}\n})`)(fakeRequire, componentModule.exports);
  return {
    Preview,
    render: props => { stateIndex = 0; return componentModule.exports.default(props); },
  };
}

function findElement(tree, predicate) {
  if (!tree || typeof tree !== 'object') return undefined;
  if (predicate(tree)) return tree;
  for (const child of [tree.props?.children].flat(Infinity)) {
    const found = findElement(child, predicate);
    if (found) return found;
  }
}

const nextRender = () => new Promise(resolve => setImmediate(resolve));
const previewFixture = () => ({
  payload: { semester: '秋季', courses: [{ name: '课程A', meetings: [{ weekday: 1, sections: [1, 2], weeks: [1] }] }] },
  course_count: 1, meeting_count: 1, existing_meeting_count: 2, errors: [], warnings: [],
});

test('教务导入先预览，返回保留输入，确认后只保存预览的课程', async () => {
  const calls = [];
  const preview = previewFixture();
  const harness = componentHarness('components/Schedule/UstcScheduleImportModal.tsx', {
    previewUstc: async content => { calls.push(['preview', content]); return { data: preview }; },
    import: async payload => { calls.push(['save', payload]); return { data: { semester: '秋季', meeting_count: 1 } }; },
  });
  const props = { open: true, onCancel() {}, onImported() {} };
  let tree = harness.render(props);
  findElement(tree, item => item.type === 'TextArea').props.onChange({ target: { value: '原始 HTML' } });
  tree = harness.render(props);
  findElement(tree, item => item.type === 'Modal').props.onOk();
  await nextRender();
  tree = harness.render(props);
  assert.deepEqual(calls.map(call => call[0]), ['preview']);
  findElement(tree, item => item.type === harness.Preview).props.onCancel();
  tree = harness.render(props);
  assert.equal(findElement(tree, item => item.type === 'TextArea').props.value, '原始 HTML');
  findElement(tree, item => item.type === 'Modal').props.onOk();
  await nextRender();
  tree = harness.render(props);
  findElement(tree, item => item.type === harness.Preview).props.onConfirm();
  await nextRender();
  assert.deepEqual(calls.map(call => call[0]), ['preview', 'preview', 'save']);
  assert.deepEqual(calls[2][1], preview.payload);
});

test('JSON 文件选择和取消预览不会保存课表，保存失败保留预览', async () => {
  const calls = [];
  const preview = previewFixture();
  const harness = componentHarness('pages/SchedulePage.tsx', {
    preview: async () => { calls.push('preview'); return { data: preview }; },
    import: async () => { calls.push('save'); throw new Error('连接中断'); },
  });
  const selectFile = async () => {
    const tree = harness.render();
    findElement(tree, item => item.type === 'input' && item.props.type === 'file').props.onChange({
      target: { value: '', files: [{ name: 'schedule.json', size: 100, text: async () => JSON.stringify(preview.payload) }] },
    });
    await nextRender();
  };
  await selectFile();
  let tree = harness.render();
  assert.deepEqual(calls, ['preview']);
  findElement(tree, item => item.type === harness.Preview).props.onCancel();
  assert.equal(findElement(harness.render(), item => item.type === harness.Preview).props.preview, null);
  await selectFile();
  tree = harness.render();
  findElement(tree, item => item.type === harness.Preview).props.onConfirm();
  await nextRender();
  const modal = findElement(harness.render(), item => item.type === harness.Preview);
  assert.deepEqual(calls, ['preview', 'preview', 'save']);
  assert.equal(modal.props.preview, preview);
  assert.equal(modal.props.error, '连接中断');
});

test('预览包含校验错误时禁用确认，保存中不能关闭', () => {
  const harness = componentHarness('components/Schedule/ScheduleImportPreviewModal.tsx');
  let cancelled = 0;
  const props = { preview: { ...previewFixture(), errors: ['节次越界'] }, saving: false, error: null, onConfirm() {}, onCancel() { cancelled++; } };
  let modal = harness.render(props);
  assert.equal(modal.props.okButtonProps.disabled, true);
  assert.equal(findElement(modal, item => item.type === 'Table'), undefined);
  modal = harness.render({ ...props, saving: true });
  modal.props.onCancel();
  assert.equal(cancelled, 0);
});

test('预览使用独立只读接口，旧后端不能将预览误当成保存', async () => {
  const calls = [];
  const apiModule = { exports: {} };
  const text = readFileSync(path.resolve(__dirname, '../frontend/src/services/api.ts'), 'utf8');
  const result = ts.transpileModule(text, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } }).outputText;
  const fakeRequire = () => ({ default: { create: () => ({ post: async (...args) => calls.push(args) }) } });
  vm.runInThisContext(`(function(require, exports) { ${result}\n})`)(fakeRequire, apiModule.exports);
  await apiModule.exports.scheduleApi.preview(previewFixture().payload);
  await apiModule.exports.scheduleApi.previewUstc('HTML', 'schedule.html');
  assert.deepEqual(calls.map(call => call[0]), ['/schedule/preview', '/schedule/preview-ustc']);
});
