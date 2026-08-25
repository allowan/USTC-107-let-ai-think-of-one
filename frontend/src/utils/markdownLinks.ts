import type { ReactNode } from 'react';

export interface NormalizedLink {
  href: string | undefined;
  label: ReactNode;
  trailing: string;
}

const AUTO_LINK_PATTERN = /^(?:https?:\/\/|www\.)/i;
const ALWAYS_TRAILING_PUNCTUATION = new Set([
  '.', ',', '!', '?', ';', ':',
  '。', '，', '！', '？', '；', '：', '、', '…',
  '）', '】', '》', '」', '』', '”', '’',
]);
const URL_BOUNDARY_PUNCTUATION = new Set([
  '（', '）', '【', '】', '《', '》', '「', '」', '『', '』',
  '，', '。', '、', '；', '：', '！', '？', '…', '“', '”', '‘', '’',
]);

function isUnbalancedClosing(text: string, index: number, closing: string, opening: string): boolean {
  const prefix = text.slice(0, index + 1);
  return (prefix.match(new RegExp(`\\${closing}`, 'g'))?.length ?? 0)
    > (prefix.match(new RegExp(`\\${opening}`, 'g'))?.length ?? 0);
}

function isTrailingPunctuation(text: string, index: number): boolean {
  const character = text[index];
  if (ALWAYS_TRAILING_PUNCTUATION.has(character)) return true;
  if (character === ')') return isUnbalancedClosing(text, index, ')', '(');
  if (character === ']') return isUnbalancedClosing(text, index, ']', '[');
  if (character === '}') return isUnbalancedClosing(text, index, '}', '{');
  return false;
}

function isUrlBoundary(character: string): boolean {
  const codePoint = character.codePointAt(0) ?? 0;
  return URL_BOUNDARY_PUNCTUATION.has(character)
    || (codePoint >= 0x3400 && codePoint <= 0x9fff);
}

function findBareUrlEnd(label: string): number {
  for (let index = 0; index < label.length; index += 1) {
    if (isUrlBoundary(label[index])) return index;
  }
  return label.length;
}

function removeTrailingHrefText(href: string, trailing: string): string {
  const encodedTrailing = encodeURIComponent(trailing);
  const lowerHref = href.toLowerCase();
  const suffixes = [trailing, encodedTrailing.toLowerCase()];
  for (const suffix of suffixes) {
    if (lowerHref.endsWith(suffix)) return href.slice(0, -suffix.length);
  }
  return href;
}

/**
 * Keep punctuation outside an autolink, like Codex-style rendered links.
 *
 * GFM correctly keeps balanced ASCII parentheses inside a URL, but a closing
 * Chinese bracket after a bare URL is otherwise treated as part of the URL.
 */
export function normalizeAutoLink(href: string | undefined, children: ReactNode): NormalizedLink {
  if (!href || typeof children !== 'string') {
    return { href, label: children, trailing: '' };
  }

  const label = children;
  if (!AUTO_LINK_PATTERN.test(label.trim()) && !AUTO_LINK_PATTERN.test(href.trim())) {
    return { href, label, trailing: '' };
  }

  let end = findBareUrlEnd(label);
  while (end > 0 && isTrailingPunctuation(label, end - 1)) end -= 1;
  if (end === label.length) return { href, label, trailing: '' };

  const cleanLabel = label.slice(0, end);
  const trailing = label.slice(end);
  const cleanHref = removeTrailingHrefText(href, trailing);
  return { href: cleanHref, label: cleanLabel, trailing };
}
