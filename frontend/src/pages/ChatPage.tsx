import { useState, useRef, useEffect, useCallback } from 'react';
import { Input, Button, Spin, Empty } from 'antd';
import { SendOutlined, RobotOutlined, UserOutlined } from '@ant-design/icons';
import ReactMarkdown from 'react-markdown';
import { useUserStore } from '@/stores/userStore';
import type { ChatMessage } from '@/types';

const ChatBubble = ({ msg }: { msg: ChatMessage }) => {
  const isUser = msg.role === 'user';
  return (
    <div
      style={{
        display: 'flex',
        gap: 12,
        padding: '12px 0',
        flexDirection: isUser ? 'row-reverse' : 'row',
      }}
    >
      <div
        style={{
          width: 36,
          height: 36,
          borderRadius: '50%',
          background: isUser ? '#1677ff' : '#52c41a',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: '#fff',
          flexShrink: 0,
        }}
      >
        {isUser ? <UserOutlined /> : <RobotOutlined />}
      </div>
      <div
        style={{
          maxWidth: '70%',
          padding: '10px 16px',
          borderRadius: 12,
          background: isUser ? '#1677ff' : '#f5f5f5',
          color: isUser ? '#fff' : '#333',
          wordBreak: 'break-word',
        }}
      >
        {isUser ? (
          <span style={{ whiteSpace: 'pre-wrap' }}>{msg.content}</span>
        ) : (
          <div className="chat-markdown">
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
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const token = useUserStore((s) => s.token);

  const scrollBottom = useCallback(() => {
    setTimeout(() => {
      listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: 'smooth' });
    }, 50);
  }, []);

  useEffect(() => {
    scrollBottom();
  }, [messages, scrollBottom]);

  const connect = useCallback(() => {
    const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
    const ws = new WebSocket(`${protocol}://${window.location.host}/ws/chat?token=${token}`);

    ws.onopen = () => setConnected(true);
    ws.onclose = () => setConnected(false);

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.type === 'token') {
        // streaming tokens
        setMessages((prev) => {
          const last = prev[prev.length - 1];
          if (last && last.role === 'assistant') {
            return [...prev.slice(0, -1), { ...last, content: last.content + data.content }];
          }
          return [
            ...prev,
            { id: Date.now().toString(), role: 'assistant', content: data.content, timestamp: Date.now() },
          ];
        });
      } else if (data.type === 'done') {
        setLoading(false);
      } else if (data.type === 'error') {
        setMessages((prev) => [
          ...prev,
          { id: Date.now().toString(), role: 'assistant', content: `错误：${data.content}`, timestamp: Date.now() },
        ]);
        setLoading(false);
      }
    };

    ws.onerror = () => {
      setConnected(false);
      setLoading(false);
    };

    wsRef.current = ws;
  }, [token]);

  useEffect(() => {
    connect();
    return () => wsRef.current?.close();
  }, [connect]);

  const send = () => {
    if (!input.trim() || !wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;

    const userMsg: ChatMessage = {
      id: Date.now().toString(),
      role: 'user',
      content: input.trim(),
      timestamp: Date.now(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setInput('');
    setLoading(true);

    wsRef.current.send(JSON.stringify({ type: 'chat', content: userMsg.content }));
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', maxWidth: 800, margin: '0 auto' }}>
      <div
        style={{
          padding: '8px 0',
          fontSize: 12,
          color: connected ? '#52c41a' : '#ff4d4f',
          textAlign: 'center',
        }}
      >
        {connected ? '已连接' : '连接中...'}
      </div>

      <div
        ref={listRef}
        style={{
          flex: 1,
          overflow: 'auto',
          padding: '0 8px',
        }}
      >
        {messages.length === 0 && !loading && (
          <Empty
            description="开始和 AI 助手对话吧"
            style={{ marginTop: 120 }}
          />
        )}
        {messages.map((msg) => (
          <ChatBubble key={msg.id} msg={msg} />
        ))}
        {loading && (
          <div style={{ textAlign: 'center', padding: 16 }}>
            <Spin size="small" />
          </div>
        )}
      </div>

      <div style={{ padding: '16px 0', borderTop: '1px solid #f0f0f0' }}>
        <Input.TextArea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onPressEnter={(e) => {
            if (!e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
          placeholder="输入消息，Enter 发送，Shift+Enter 换行"
          autoSize={{ minRows: 1, maxRows: 4 }}
          disabled={!connected}
        />
        <Button
          type="primary"
          icon={<SendOutlined />}
          onClick={send}
          loading={loading}
          disabled={!connected || !input.trim()}
          style={{ marginTop: 8, float: 'right' }}
        >
          发送
        </Button>
        <div style={{ clear: 'both' }} />
      </div>
    </div>
  );
}
