import { Routes, Route, Navigate } from 'react-router-dom';
import AppLayout from '@/components/Layout/AppLayout';
import ChatPage from '@/pages/ChatPage';
import DigestPage from '@/pages/DigestPage';
import NewsPage from '@/pages/NewsPage';
import SyncPage from '@/pages/SyncPage';
import PersonalDataPage from '@/pages/PersonalDataPage';
import SchedulePage from '@/pages/SchedulePage';

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<AppLayout />}>
        <Route index element={<Navigate to="/today" replace />} />
        <Route path="today" element={<DigestPage />} />
        <Route path="chat" element={<ChatPage />} />
        <Route path="personal-data" element={<PersonalDataPage />} />
        <Route path="schedule" element={<SchedulePage />} />
        <Route path="news" element={<NewsPage />} />
        <Route path="sync" element={<SyncPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
