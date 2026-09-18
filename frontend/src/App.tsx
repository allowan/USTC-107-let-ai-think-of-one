import { lazy } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import AppLayout from '@/components/Layout/AppLayout';

const ChatPage = lazy(() => import('@/pages/ChatPage'));
const DigestPage = lazy(() => import('@/pages/DigestPage'));
const NewsPage = lazy(() => import('@/pages/NewsPage'));
const SyncPage = lazy(() => import('@/pages/SyncPage'));
const PersonalDataPage = lazy(() => import('@/pages/PersonalDataPage'));
const SchedulePage = lazy(() => import('@/pages/SchedulePage'));
const BackupPage = lazy(() => import('@/pages/BackupPage'));

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
        <Route path="backup" element={<BackupPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
