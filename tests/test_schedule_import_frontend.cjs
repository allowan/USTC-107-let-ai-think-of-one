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
});
