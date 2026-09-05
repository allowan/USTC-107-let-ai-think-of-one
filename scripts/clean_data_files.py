# -*- coding: utf-8 -*-
"""清洗 campus_rag/data 下通知 txt 的站点装饰性噪声（幂等）。

背景：scripts/sync_ustc_columns.py 抓回的网页正文常夹杂站点导航菜单、
面包屑、发布元信息（发布者/发布时间/浏览次数）、版权页脚、相关文章列表，
以及 HTML 内联标签造成的多余空格。本脚本把这些噪声剥离，使每个文件符合
campus_rag/README.md 定义的统一格式：

    来源：<URL>
    标题：<标题>
    <空行>
    正文（段间无空行，无站点导航/页脚噪声）

规则（只删"装饰性噪声"，正文内容行一律保留）：
- 头部：导航 token / 面包屑 / 重复标题 / 发布元信息（仅头部区）/ 日期行（仅正文开头）
- 尾部：版权 / 备案 / 分享 / 相关文章等哨兵之后的整段截断 + 尾区元信息
- 逐行：仅做空白规整（去掉汉字与数字/ASCII 之间、中文标点前后、长句汉字间的 HTML 空格）
- teach WP "空壳页"（正文无任何长句）收敛为仅标题壳；无正文文件同理

用法：
    python scripts/clean_data_files.py                # 就地清洗 campus_rag/data
    python scripts/clean_data_files.py --dir <dir>    # 指定目录
    python scripts/clean_data_files.py --dry-run      # 只统计不改写

2026-09-05 由人工整理后沉淀：同一轮还完成了跨来源镜像去重（见当时的提交/README）。
"""
from __future__ import annotations

import argparse
import io
import os
import re

CJK = r'\u4e00-\u9fff\u3400-\u4dbf'

NAV = set('''
首 页 首页 | > 科大新闻 学校概况 院系介绍 科学研究 师资队伍 本科生教育 研究生教育 发展规划
报考科大 科大校友 在校师生 人才招聘 智慧门户 公共服务 公告通知 电子邮件 通知公告 服务类通知
科研类通知 管理类通知 教学类通知 本科教学 常用服务 快速通道 返回首页 English 学校要闻 媒体科大
新闻博览 学术活动 通知新闻 精品教育 服务指南 合作交流 规章制度 文档下载 专题 一流本科教育质量提升年
分享本文 打印本页 关闭窗口 相关文章 相关热门文章 热点新闻 最新通知 办公系统 信息查询 校园文化 学术科研
站内搜索 搜索 邮箱 电话 返回顶部 上页 下页 尾页
'''.split())
NAV.add('首 页')  # 含内部空格，无法用 split() 生成

LABEL_META = re.compile(
    r'^(发布者|发布人|责任编辑|编辑|作者|来源|供稿|撰稿|审核|录入)\s*[:：]|'
    r'^(发布时间|发布日期|更新时间|添加时间|录入时间|日期|时间)\s*[:：]?\s*$|'
    r'^(浏览次数|点击数|点击率|阅读次数|浏览量|访问量)\s*[:：]?\s*\d*\s*$|'
    r'^(分享|打印|关闭|字号|字体|大中小|收藏)\s*$')
DATE_LINE = re.compile(r'^\d{4}[-年/.]\d{1,2}[-月/.]\d{1,2}日?(\s+\d{1,2}[:：]\d{2})?\s*$')
DATEVIEW_LINE = re.compile(r'^\d{4}[-/]\d{1,2}[-/]\d{1,2}\s+\d{1,2}[:：]\d{2}\s*\|?\s*\d*\s*views?\s*$')
SOCIAL_TAIL = {'分享', '打印', '关闭', '分享本文', '微博', 'qzone', '微信', 'QQ空间', '新浪微博'}
FOOT_SENTINEL = re.compile(
    r'Copyright|版权所有|皖ICP备|皖公网安备|站点地图|设为首页|加入收藏|ICP备案号|'
    r'Powered By|分享本文|相关文章|相关热门文章|上一篇|下一篇|上一条|下一条|'
    r'本页二维码|移动应用|回到顶部|返回顶部')


def ws_norm(s: str) -> str:
    return re.sub(r'\s+', '', s or '')


def is_meta_line(l: str) -> bool:
    return bool(LABEL_META.search(l)) and len(l) <= 60


def norm_line(l: str) -> str:
    l = l.replace('\u3000', ' ').replace('\xa0', ' ')
    l = re.sub(r'(?<=[%s])\s+(?=[0-9A-Za-z])' % CJK, '', l)
    l = re.sub(r'(?<=[0-9A-Za-z])\s+(?=[%s])' % CJK, '', l)
    l = re.sub(r'\s+(?=[，。；：！？、）】》」』”’．・%])', '', l)
    l = re.sub(r'(?<=[（【《「『“‘])\s+', '', l)
    l = re.sub(r'(?<=[，。；：、．])\s+', '', l)
    l = re.sub(r'\s+(?=[（【《“‘「『])', '', l)
    l = re.sub(r'(?<=[）】》”’」』])\s+(?=[%s0-9A-Za-z])' % CJK, '', l)
    l = re.sub(r'\s*．\s*', '．', l)
    # 邮箱/域名被 HTML 拆开：'@ustc .edu .cn' -> '@ustc.edu.cn'
    l = re.sub(r'(?<=[A-Za-z0-9@])\s+(?=\.(?=[A-Za-z0-9]))', '', l)
    if len(l) >= 35:  # 长句按正文段落处理：清掉汉字间随机空格；短行(词列表/表格单元)保留
        l = re.sub(r'(?<=[%s])\s+(?=[%s])' % (CJK, CJK), '', l)
    return re.sub(r'\s{2,}', ' ', l).strip()


def clean(raw: str):
    """返回清洗后的文本；无法识别头部时返回 None。"""
    lines = raw.split('\n')
    i = 0
    if i < len(lines) and lines[i].startswith('来源'):
        src_line = re.sub(r'^来源[:：]\s*//', '来源：https://', lines[i].rstrip())
        i += 1
    else:
        return None
    if i < len(lines) and lines[i].startswith('标题'):
        title_line = lines[i].rstrip()
        i += 1
    else:
        return None
    title = title_line.split('：', 1)[-1].split(':', 1)[-1].strip()
    t_norm = ws_norm(title)
    host = ''
    m = re.search(r'https?://([^/]+)', src_line)
    if m:
        host = m.group(1)
    rest = lines[i:]

    # teach WP 壳页（'章节名 : 中国科学技术大学教务处' 开头）：定位到最后标记之后
    shell_mode = False
    first_nonblank = next((l for l in rest if l.strip()), '')
    if 'teach.ustc.edu.cn' in host and re.search(
            r'^[^：:\n]{1,30}[:：]\s*中国科学技术大学教务处\s*$', first_nonblank.strip()):
        shell_mode = True
        cut = None
        for k in range(len(rest) - 1, -1, -1):
            if '»' in rest[k] or (t_norm and ws_norm(rest[k]) == t_norm) \
                    or re.search(r'[:：]\s*中国科学技术大学教务处\s*$', rest[k]):
                cut = k
                break
        body = rest[cut + 1:] if cut is not None else []
    else:
        body = rest

    # 定位正文起点：跳过导航 / 面包屑 / 空行
    start = 0
    while start < len(body):
        l = body[start].strip()
        if not l or l in NAV or l in ('|', '>'):
            start += 1
            continue
        if (l.startswith('首页') or l.startswith('当前位置')) and '»' in l:
            start += 1
            continue
        break
    # 头部装饰区（前 40 行）：重复标题 / 日期行 / 标签元信息 / 社交块
    head_limit = min(len(body), start + 40)
    j, saw_real = start, False
    while j < head_limit:
        l = body[j].strip()
        if not l:
            j += 1
            continue
        if l in NAV or l in ('|', '>'):
            j += 1
            continue
        if is_meta_line(l) or DATEVIEW_LINE.search(l):
            j += 1
            continue
        if t_norm and ws_norm(l) == t_norm:
            j += 1
            continue
        if not saw_real and DATE_LINE.search(l):
            j += 1
            continue
        if l in SOCIAL_TAIL and not saw_real:
            j += 1
            continue
        saw_real = True
        break
    body = body[j:]

    # 尾部哨兵：命中即截断其后全部
    cut = next((k for k, l in enumerate(body) if FOOT_SENTINEL.search(l)), None)
    if cut is not None:
        body = body[:cut]
    tail_from = max(0, len(body) - 15)
    k = len(body) - 1
    while k >= tail_from and k >= 0:
        l = body[k].strip()
        if not l or l in NAV or l in ('|', '>') or is_meta_line(l) or DATEVIEW_LINE.search(l) \
                or l in SOCIAL_TAIL:
            k -= 1
            continue
        break
    body = body[:k + 1]

    out = []
    for l in body:
        l = norm_line(l.strip())
        if not l or l in NAV or l in ('|', '>'):
            continue
        out.append(l)
    if shell_mode:  # 壳页无长句正文 => 收敛为标题壳
        cjk = re.compile(r'[%s]' % CJK)
        if not any(len(l) >= 25 and len(cjk.findall(l)) >= 3 for l in out):
            out = []

    head = '\n'.join([src_line, title_line]) + '\n\n'
    return (head + '\n'.join(out) + '\n') if out else head


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--dir', default='campus_rag/data', help='通知 txt 目录')
    ap.add_argument('--dry-run', action='store_true', help='只统计不改写')
    args = ap.parse_args()

    changed = skipped = stub = 0
    for fn in sorted(os.listdir(args.dir)):
        if not fn.endswith('.txt'):
            continue
        path = os.path.join(args.dir, fn)
        raw = io.open(path, encoding='utf-8', errors='replace').read()
        new = clean(raw)
        if new is None or new == raw:
            if new is None:
                skipped += 1
            continue
        if not new.split('\n\n', 1)[-1].strip():
            stub += 1
        changed += 1
        if not args.dry_run:
            io.open(path, 'w', encoding='utf-8', newline='\n').write(new)
    print(f'{args.dir}: changed={changed} (stub={stub}) skipped={skipped} dry_run={args.dry_run}')


if __name__ == '__main__':
    main()
