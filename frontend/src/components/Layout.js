import React from 'react';
import { Link, Outlet } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

/**
 * Defines available modules and their metadata.
 *
 * Each module entry includes:
 * - `key`: the permission key used in the backend to authorize access.
 * - `label`: the human readable label shown in the navigation menu.
 * - `path`: the internal React route for the module.  All modules here
 *   implement a full React page; there are no legacy fallbacks.
 * - `adminOnly` (optional): set to true for modules that should only
 *   appear for admin users regardless of view permissions.
 */
const modules = [
  { key: 'cfe_auto', label: 'CFE Auto', path: '/cfe-auto' },
  { key: 'etiquetas', label: 'Etiquetas', path: '/etiquetas' },
  { key: 'cfe_manual', label: 'CFE Manual', path: '/cfe-manual' },
  { key: 'batch_pedidos', label: 'Batch Pedidos', path: '/batch-pedidos' },
  { key: 'rastreo_deposito', label: 'Rastreo', path: '/rastreo' },
  { key: 'cadete_flex', label: 'Rastreo Flex', path: '/rastreo-flex' },
  { key: 'rastreo_ventas', label: 'Tracking Admin', path: '/tracking-admin' },
  { key: 'admin_postulaciones', label: 'Postulaciones', path: '/postulaciones' },
  { key: 'puerta', label: 'Puerta', path: '/puerta' },
  { key: 'reloj_home_office', label: 'Reloj Home', path: '/reloj-home-office' },
  // The administration dashboard is reserved for admin users.  It does not
  // correspond to a specific view permission but instead depends on the
  // user role.
  { key: 'admin_dashboard', label: 'Administración', path: '/admin', adminOnly: true },
];

/**
 * Layout component that renders a simple header, side navigation and outlet for pages.
 * It uses permissions from the AuthContext to build the navigation dynamically.
 */
const Layout = () => {
  const { user, permissions, logout } = useAuth();

  const handleLogout = async () => {
    await logout();
    // Recargar completamente para limpiar estado e ir a login
    window.location.href = '/login';
  };

  return (
    <div>
      <header
        style={{ padding: '10px', backgroundColor: '#f5f5f5', borderBottom: '1px solid #ddd' }}
      >
        <span style={{ marginRight: '20px' }}>
          {user ? `Usuario: ${user.username}` : 'No autenticado'}
        </span>
        <button onClick={handleLogout}>Salir</button>
      </header>
      <div style={{ display: 'flex' }}>
        <nav style={{ width: '220px', borderRight: '1px solid #ddd', padding: '10px' }}>
          <ul style={{ listStyle: 'none', padding: 0 }}>
            {modules.map((m) => {
              // Admin only modules are displayed only if the user has the admin role.
              if (m.adminOnly && user?.role !== 'admin') return null;
              // Non admin modules rely on view permissions.
              if (!m.adminOnly && !permissions.includes(m.key)) return null;
              return (
                <li key={m.key} style={{ marginBottom: '8px' }}>
                  <Link to={m.path}>{m.label}</Link>
                </li>
              );
            })}
          </ul>
        </nav>
        <main style={{ flex: 1, padding: '10px' }}>
          <Outlet />
        </main>
      </div>
    </div>
  );
};

export default Layout;