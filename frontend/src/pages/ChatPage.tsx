import {
  useState,
  useRef,
  useEffect,
  useCallback,
  memo,
  type AnchorHTMLAttributes,
  type KeyboardEvent,
  type ReactNode,
} from 'react';
import { Input, Button, Empty, App } from 'antd';
import { GlobalOutlined, MailOutlined, SendOutlined, LoadingOutlined, StopOutlined, ToolOutlined } from '@ant-design/icons';
import ReactMarkdown, { type Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useTopicStore } from '@/stores/topicStore';
import { topicApi } from '@/services/api';
import type { ChatMessage } from '@/types';
import { normalizeAutoLink } from '@/utils/markdownLinks';

type ChatMarkdownLinkProps = AnchorHTMLAttributes<HTMLAnchorElement> & {
  children?: ReactNode;
};

function getFaviconUrl(href: string | undefined): string | undefined {
  if (!href) return undefined;
  try {
    const url = new URL(href);
    if (url.protocol !== 'http:' && url.protocol !== 'https:') return undefined;
    return `${url.origin}/favicon.ico`;
  } catch {
    return undefined;
  }
}

const ChatMarkdownLink = ({ href, children, ...props }: ChatMarkdownLinkProps) => {
  const isMailLink = href?.toLowerCase().startsWith('mailto:') ?? false;
  const faviconUrl = getFaviconUrl(href);
  const [faviconFailed, setFaviconFailed] = useState(false);

  return (
    <a
      {...props}
      href={href}
      className="chat-markdown-link"
      target="_blank"
      rel="noopener noreferrer"
      title={href}
    >
      <span className="chat-markdown-link-icon" aria-hidden="true">
        {isMailLink ? (
          <MailOutlined />
        ) : faviconUrl && !faviconFailed ? (
          <img src={faviconUrl} alt="" onError={() => setFaviconFailed(true)} />
        ) : (
          <GlobalOutlined />
        )}
      </span>
      <span className="chat-markdown-link-label">{children}</span>
    </a>
  );
};

const MarkdownLinkRenderer: Components['a'] = ({ node, href, children, ...props }) => {
  const link = normalizeAutoLink(href, children);
  return (
    <>
      <ChatMarkdownLink {...props} href={link.href}>
        {link.label}
      </ChatMarkdownLink>
      {link.trailing}
    </>
  );
};

const MarkdownTableRenderer: Components['table'] = ({ node, ...props }) => (
  <div className="chat-markdown-table">
    <table {...props} />
  </div>
);

const MARKDOWN_COMPONENTS: Components = {
  a: MarkdownLinkRenderer,
  table: MarkdownTableRenderer,
};
const MARKDOWN_PLUGINS = [remarkGfm];

const ChatBubble = memo(({ msg }: { msg: ChatMessage }) => {
  const isUser = msg.role === 'user';
  return (
    <div style={{ display: 'flex', gap: 12, padding: '12px 0', flexDirection: isUser ? 'row-reverse' : 'row' }}>
      <div style={{
        maxWidth: isUser ? '60%' : 'none', padding: '12px 18px', borderRadius: 12,
        background: isUser ? '#1677ff' : 'transparent', color: isUser ? '#fff' : '#333', wordBreak: 'break-word',
      }}>
        {isUser ? (
          <span style={{ whiteSpace: 'pre-wrap', fontSize: 16, lineHeight: 1.6 }}>{msg.content}</span>
        ) : (
          <div className="chat-markdown" style={{ fontSize: 16, lineHeight: 1.6 }}>
            <ReactMarkdown
              remarkPlugins={MARKDOWN_PLUGINS}
              components={MARKDOWN_COMPONENTS}
            >
              {msg.content}
            </ReactMarkdown>
          </div>
        )}
      </div>
    </div>
  );
});

export default function ChatPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [statusText, setStatusText] = useState<string>('');
  const listRef = useRef<HTMLDivElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const isComposingRef = useRef(false);
  const summarizedRef = useRef<Set<string>>(new Set());
  const autoCreatedRef = useRef(false);
  const { activeTopicId, topics, loaded, createTopic, renameTopic } = useTopicStore();
  const { message } = App.useApp();

  const scrollBottom = useCallback(() => {
    setTimeout(() => {
      listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: 'smooth' });
    }, 50);
  }, []);

  useEffect(() => { scrollBottom(); }, [messages, scrollBottom]);

  // Auto-create first topic after loaded
  useEffect(() => {
    // ref 守卫：StrictMode 下 effect 双执行会创建两个重复的"默认话题"
    if (loaded && topics.length === 0 && !autoCreatedRef.current) {
      autoCreatedRef.current = true;
      // 后端瞬时不可用时避免未处理的 rejection
      createTopic().catch(() => {});
    }
  }, [loaded, topics.length, createTopic]);

  // Load history when switching topics
  useEffect(() => {
    // A topic switch must also stop the previous network request. Otherwise an
    // old stream can keep consuming model output in the background.
    abortControllerRef.current?.abort();
    abortControllerRef.current = null;
    setLoading(false);
    setStatusText('');

    let cancelled = false;
    setMessages([]);
    if (activeTopicId) {
      topicApi.getHistory(activeTopicId).then(({ data }) => {
        if (cancelled) return;
        if (data.messages.length > 0) {
          const msgs: ChatMessage[] = data.messages.map((m, i) => ({
            id: `${activeTopicId}-${i}`,
            role: m.role,
            content: m.content,
            timestamp: Date.now(),
          }));
          setMessages(msgs);
        }
      }).catch(() => {});
    }
    return () => { cancelled = true; };
  }, [activeTopicId]);

  // Navigating away from the chat page should not leave a stream running
  // (abort on unmount is the same mechanism as the stop button).
  useEffect(() => () => {
    abortControllerRef.current?.abort();
    abortControllerRef.current = null;
  }, []);

  // Auto-summarize on first exchange
  const wasLoadingRef = useRef(false);
  useEffect(() => {
    if (wasLoadingRef.current && !loading && messages.length >= 2 && activeTopicId) {
      const topicId = activeTopicId;
      const topic = topics.find((t) => t.id === topicId);
      if (!summarizedRef.current.has(topicId) && topic?.name === '默认话题') {
        summarizedRef.current.add(topicId);
        const userMsg = messages.filter((m) => m.role === 'user')[0];
        const aiMsg = messages.filter((m) => m.role === 'assistant')[0];
        if (userMsg && aiMsg) {
          topicApi.summarize(topicId, userMsg.content, aiMsg.content).then(({ data }) => {
            renameTopic(topicId, data.name);
          }).catch(() => {});
        }
      }
    }
    wasLoadingRef.current = loading;
  }, [loading]);

  const stopGeneration = () => {
    const controller = abortControllerRef.current;
    if (!controller) return;
    controller.abort();
    setLoading(false);
    setStatusText('');
    message.info('已停止生成');
  };

  const send = async () => {
    // loading 时拦截：Enter 键不经过按钮的 loading 态，不拦截会并行发两条流，
    // token 交错追加进同一条消息导致输出错乱。
    if (loading) return;
    const content = input.trim();
    if (!content) return;
    if (!activeTopicId) { message.warning('请先在左侧创建一个话题'); return; }

    const topicId = activeTopicId;
    const userMsg: ChatMessage = { id: Date.now().toString(), role: 'user', content, timestamp: Date.now() };
    setMessages((prev) => [...prev, userMsg]);
    setInput('');
    setLoading(true);
    setStatusText('');

    const abortController = new AbortController();
    abortControllerRef.current = abortController;

    try {
      const response = await fetch('/api/chat/stream', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ content, topic_id: topicId }),
        signal: abortController.signal,
      });

      // 非 2xx（参数校验/后端异常）时响应体不是 SSE 流，
      // 若不拦截会静默走完解析循环，用户看不到任何错误反馈。
      if (!response.ok) {
        let detail = `请求失败（HTTP ${response.status}）`;
        try {
          const err = await response.json();
          if (err?.detail) detail = String(err.detail);
        } catch { /* 非 JSON 错误体时保留默认提示 */ }
        throw new Error(detail);
      }

      const reader = response.body?.getReader();
      if (!reader) throw new Error('No reader');

      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        if (abortController.signal.aborted) break;
        // Stop streaming if user switched to a different topic
        if (useTopicStore.getState().activeTopicId !== topicId) {
          abortController.abort();
          break;
        }
        const { done, value } = await reader.read();
        if (done) break;
        if (abortController.signal.aborted) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (abortController.signal.aborted) break;
          if (line.startsWith('data: ')) {
            const data = JSON.parse(line.slice(6));
            if (data.type === 'thinking') {
              setStatusText('Thinking...');
            } else if (data.type === 'tool_use') {
              setStatusText(`Using tool: ${data.content}`);
            } else if (data.type === 'token') {
              setStatusText('');
              setMessages((prev) => {
                // Only append if we're still on the same topic
                if (useTopicStore.getState().activeTopicId !== topicId) return prev;
                const last = prev[prev.length - 1];
                if (last && last.role === 'assistant') {
                  return [...prev.slice(0, -1), { ...last, content: last.content + data.content }];
                }
                return [...prev, { id: Date.now().toString(), role: 'assistant', content: data.content, timestamp: Date.now() }];
              });
            } else if (data.type === 'error') {
              setStatusText('');
              if (useTopicStore.getState().activeTopicId !== topicId) return;
              setMessages((prev) => [...prev, { id: Date.now().toString(), role: 'assistant', content: `错误：${data.content}`, timestamp: Date.now() }]);
            }
          }
        }
      }
    } catch (err: unknown) {
      if (err instanceof DOMException && err.name === 'AbortError') return;
      if (useTopicStore.getState().activeTopicId !== topicId) return;
      const msg = err instanceof Error ? err.message : '请求失败';
      setMessages((prev) => [...prev, { id: Date.now().toString(), role: 'assistant', content: `错误：${msg}`, timestamp: Date.now() }]);
    } finally {
      // Do not let an old request clear the loading state of a newer request
      // started immediately after the user pressed stop.
      if (abortControllerRef.current === abortController) {
        abortControllerRef.current = null;
      }
      if (
        abortControllerRef.current === null &&
        useTopicStore.getState().activeTopicId === topicId
      ) {
        setLoading(false);
        setStatusText('');
      }
    }
  };

  const handleInputKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== 'Enter' || event.shiftKey) return;

    // Enter is also the commit key for Chinese/English IME composition. Do
    // not submit the message until the input method has finished committing
    // its candidate text. keyCode 229 covers browsers that omit isComposing.
    if (isComposingRef.current || event.nativeEvent.isComposing || event.keyCode === 229) {
      return;
    }

    event.preventDefault();
    void send();
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', maxWidth: 1200, margin: '0 auto', width: '100%' }}>
      <div ref={listRef} style={{ flex: 1, overflow: 'auto', padding: '0 8px' }}>
        {messages.length === 0 && !loading && <Empty description="开始和 AI 助手对话吧" style={{ marginTop: 120 }} />}
        {messages.map((msg) => <ChatBubble key={msg.id} msg={msg} />)}
        {loading && (
          <div className="stream-status">
            {statusText.startsWith('Using tool:') ? (
              <span><ToolOutlined style={{ marginRight: 8 }} />{statusText}</span>
            ) : (
              <span><LoadingOutlined style={{ marginRight: 8 }} />{statusText || 'Thinking...'}</span>
            )}
          </div>
        )}
      </div>
      <div style={{ padding: '16px 0', borderTop: '1px solid #f0f0f0' }}>
        <Input.TextArea
          value={input} onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleInputKeyDown}
          onCompositionStart={() => { isComposingRef.current = true; }}
          onCompositionEnd={() => { isComposingRef.current = false; }}
          placeholder="输入消息，Enter 发送，Shift+Enter 换行"
          autoSize={{ minRows: 1, maxRows: 4 }}
        />
        {loading ? (
          <Button danger icon={<StopOutlined />} onClick={stopGeneration}
            style={{ marginTop: 8, float: 'right' }}>
            停止生成
          </Button>
        ) : (
          <Button type="primary" icon={<SendOutlined />} onClick={send}
            disabled={!input.trim()} style={{ marginTop: 8, float: 'right' }}>
            发送
          </Button>
        )}
        <div style={{ clear: 'both' }} />
      </div>
    </div>
  );
}
