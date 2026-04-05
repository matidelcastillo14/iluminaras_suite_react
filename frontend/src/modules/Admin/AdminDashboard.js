import React from 'react';
import { Routes, Route, useParams } from 'react-router-dom';
import AdminNav from '../../components/AdminNav';
import UsersPage from './UsersPage';
import UserEditPage from './UserEditPage';
import SettingsPage from './SettingsPage';
import ModulesPage from './ModulesPage';

// Simple overview component displayed on the admin root. You can
// extend this with stats or shortcuts.
function OverviewPage() {
  return <p>Panel de administración. Selecciona una opción del menú.</p>;
}

/**
 * Parent component for the admin module. Renders a side nav and
 * nested routes for each sub‑section.
 */
export default function AdminDashboard() {
  return (
    <div style={{ display: 'flex' }}>
      <AdminNav />
      <div style={{ flex: 1, padding: '10px' }}>
        <Routes>
          <Route index element={<OverviewPage />} />
          <Route path="users" element={<UsersPage />} />
          <Route path="users/:id" element={<UserEditPage />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="modules" element={<ModulesPage />} />
        </Routes>
      </div>
    </div>
  );
}