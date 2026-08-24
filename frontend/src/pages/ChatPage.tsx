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
    if (loaded && topics.length === 0) {
      // 后端瞬时不可用时避免未处理的 rejection
      createTopic().catch(() => {});
    }
  }, [loaded, topics.length]);

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

    try {
      const response = await fetch('/api/chat/stream', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ content, topic_id: topicId }),
        signal: abortController.signal,
      });

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
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
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
      if (useTopicStore.getState().activeTopicId === topicId) {
        setLoading(false);
        setStatusText('');
      }
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
