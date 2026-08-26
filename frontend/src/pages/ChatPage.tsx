import { useState, useRef, useEffect, useCallback } from 'react';
import { Input, Button, Empty, App } from 'antd';
import { SendOutlined, LoadingOutlined, ToolOutlined } from '@ant-design/icons';
import ReactMarkdown from 'react-markdown';
import { useTopicStore } from '@/stores/topicStore';
import { topicApi } from '@/services/api';
import type { ChatMessage } from '@/types';

const ChatBubble = ({ msg }: { msg: ChatMessage }) => {
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
            <ReactMarkdown>{msg.content}</ReactMarkdown>
          </div>
        )}
      </div>
    </div>
  );
};

export default function ChatPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [statusText, setStatusText] = useState<string>('');
  const listRef = useRef<HTMLDivElement>(null);
  const summarizedRef = useRef<Set<string>>(new Set());
  // 流式请求的中止控制器提升到 ref：组件卸载（切去其他页面）时必须中止，
  // 否则流在后台继续跑完并对已卸载组件 setState。
  const abortRef = useRef<AbortController | null>(null);
  const autoCreatedRef = useRef(false);
  const { activeTopicId, topics, loaded, createTopic, renameTopic } = useTopicStore();
  const { message } = App.useApp();

  useEffect(() => () => { abortRef.current?.abort(); }, []);

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
    abortRef.current = abortController;

    // 逐行解析 SSE：单行坏数据（代理改写/截断）只跳过该行，不得杀掉整个流，
    // 否则已缓冲的 token 全部丢失且用户看到原始解析错误。
    const handleLine = (line: string) => {
      if (!line.startsWith('data: ')) return;
      let data: { type: string; content?: string };
      try {
        data = JSON.parse(line.slice(6));
      } catch {
        return;
      }
      const text = data.content ?? '';
      if (data.type === 'thinking') {
        setStatusText('Thinking...');
      } else if (data.type === 'tool_use') {
        setStatusText(`Using tool: ${text}`);
      } else if (data.type === 'token') {
        setStatusText('');
        setMessages((prev) => {
          // Only append if we're still on the same topic
          if (useTopicStore.getState().activeTopicId !== topicId) return prev;
          const last = prev[prev.length - 1];
          if (last && last.role === 'assistant') {
            return [...prev.slice(0, -1), { ...last, content: last.content + text }];
          }
          return [...prev, { id: Date.now().toString(), role: 'assistant', content: text, timestamp: Date.now() }];
        });
      } else if (data.type === 'error') {
        setStatusText('');
        if (useTopicStore.getState().activeTopicId !== topicId) return;
        setMessages((prev) => [...prev, { id: Date.now().toString(), role: 'assistant', content: `错误：${text}`, timestamp: Date.now() }]);
      }
    };

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
        // Stop streaming if user switched to a different topic
        if (useTopicStore.getState().activeTopicId !== topicId) {
          abortController.abort();
          break;
        }
        const { done, value } = await reader.read();
        if (done) {
          // flush 解码器中跨块缓存的半个字符，残余行留待循环后处理，
          // 否则末尾事件无尾换行时最后一个 token 会被静默丢弃。
          buffer += decoder.decode();
          break;
        }

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';
        for (const line of lines) handleLine(line);
      }
      if (buffer.trim()) handleLine(buffer);
    } catch (err: unknown) {
      if (err instanceof DOMException && err.name === 'AbortError') return;
      if (useTopicStore.getState().activeTopicId !== topicId) return;
      const msg = err instanceof Error ? err.message : '请求失败';
      setMessages((prev) => [...prev, { id: Date.now().toString(), role: 'assistant', content: `错误：${msg}`, timestamp: Date.now() }]);
    } finally {
      abortRef.current = null;
      // 无条件复位：切换话题中断时若跳过复位，loading 会永久卡死（发送按钮
      // 一直转圈且可再次触发并行流）；新话题的历史加载会重置消息列表。
      setLoading(false);
      setStatusText('');
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', maxWidth: 1200, margin: '0 auto', width: '100%' }}>
      <div ref={listRef} style={{ flex: 1, overflow: 'auto', padding: '0 8px' }}>
        {messages.length === 0 && !loading && <Empty description="开始和 AI 助手对话吧" style={{ marginTop: 120 }} />}
        {messages.map((msg) => <ChatBubble key={msg.id} msg={msg} />)}
        {loading && (
          <div className="stream-status">
            {statusText.startsWith('Using tool:') ? (
              <span><ToolOutlined spin style={{ marginRight: 8 }} />{statusText}</span>
            ) : (
              <span><LoadingOutlined style={{ marginRight: 8 }} />{statusText || 'Thinking...'}</span>
            )}
          </div>
        )}
      </div>
      <div style={{ padding: '16px 0', borderTop: '1px solid #f0f0f0' }}>
        <Input.TextArea
          value={input} onChange={(e) => setInput(e.target.value)}
          onPressEnter={(e) => { if (!e.shiftKey) { e.preventDefault(); send(); } }}
          placeholder="输入消息，Enter 发送，Shift+Enter 换行"
          autoSize={{ minRows: 1, maxRows: 4 }}
        />
        <Button type="primary" icon={<SendOutlined />} onClick={send} loading={loading}
          disabled={!input.trim()} style={{ marginTop: 8, float: 'right' }}>
          发送
        </Button>
        <div style={{ clear: 'both' }} />
      </div>
    </div>
  );
}
