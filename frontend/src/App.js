import React from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';

// Context provider and route protection
import { AuthProvider } from './context/AuthContext';
import ProtectedRoute from './components/ProtectedRoute';

// Layout and pages
import Layout from './components/Layout';
import Login from './pages/Login';
import Home from './pages/Home';
import EtiquetasPage from './modules/Etiquetas/EtiquetasPage';
import CfeAutoPage from './modules/CfeAuto/CfeAutoPage';
import CfeManualPage from './modules/CfeManual/CfeManualPage';
import BatchPedidosPage from './modules/BatchPedidos/BatchPedidosPage';
import RastreoPage from './modules/Tracking/TrackingPage';
import RastreoFlexPage from './modules/RastreoFlex/RastreoFlexPage';
import TrackingAdminPage from './modules/RastreoVentas/RastreoVentasPage';
import PostulacionesPage from './modules/Postulaciones/PostulacionesPage';
import PuertaPage from './modules/Puerta/PuertaPage';
import RelojHomeOfficePage from './modules/RelojHomeOffice/RelojHomeOfficePage';
import AdminDashboard from './modules/Admin/AdminDashboard';

/**
 * Top level application component.
 * Defines all routes and wraps them in AuthProvider for session context.
 */
function App() {
  return (
    <AuthProvider>
      <Routes>
        {/* Public route for login */}
        <Route path="/login" element={<Login />} />
        {/* Protected routes wrapped in Layout */}
        <Route
          path="/"
          element={
            <ProtectedRoute>
              <Layout />
            </ProtectedRoute>
          }
        >
          {/* Index/home page */}
          <Route index element={<Home />} />
          {/* Modules */}
          <Route path="cfe-auto" element={<CfeAutoPage />} />
          <Route path="etiquetas" element={<EtiquetasPage />} />
          <Route path="cfe-manual" element={<CfeManualPage />} />
          <Route path="batch-pedidos" element={<BatchPedidosPage />} />
          <Route path="rastreo" element={<RastreoPage />} />
          <Route path="rastreo-flex/*" element={<RastreoFlexPage />} />
          <Route path="tracking-admin" element={<TrackingAdminPage />} />
          <Route path="postulaciones" element={<PostulacionesPage />} />
          <Route path="puerta" element={<PuertaPage />} />
          <Route path="reloj-home-office" element={<RelojHomeOfficePage />} />
          <Route path="admin/*" element={<AdminDashboard />} />
        </Route>
        {/* Fallback: redirect anything unknown back to home */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AuthProvider>
  );
}

export default App;