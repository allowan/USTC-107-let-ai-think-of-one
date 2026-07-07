import { Routes, Route, Navigate } from 'react-router-dom';
import AppLayout from '@/components/Layout/AppLayout';
import LoginPage from '@/pages/LoginPage';
import ChatPage from '@/pages/ChatPage';
import FilesPage from '@/pages/FilesPage';
import AdminPage from '@/pages/AdminPage';
import { useUserStore } from '@/stores/userStore';

function PrivateRoute({ children }: { children: React.ReactNode }) {
  const token = useUserStore((s) => s.token);
  return token ? <>{children}</> : <Navigate to="/login" replace />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/"
        element={
          <PrivateRoute>
            <AppLayout />
          </PrivateRoute>
        }
      >
        <Route index element={<Navigate to="/chat" replace />} />
        <Route path="chat" element={<ChatPage />} />
        <Route path="files" element={<FilesPage />} />
        <Route path="admin" element={<AdminPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
