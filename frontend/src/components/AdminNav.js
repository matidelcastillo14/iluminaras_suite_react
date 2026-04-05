import React from 'react';
import { NavLink } from 'react-router-dom';

/**
 * Navigation component used within the admin dashboard. It renders
 * links to the various admin sub‑modules. Active links are styled
 * differently via NavLink's activeClassName.
 */
export default function AdminNav() {
  const baseStyle = {
    padding: '8px 12px',
    display: 'block',
    textDecoration: 'none',
    color: '#333',
  };
  const getStyle = (isActive) =>
    isActive
      ? {
          ...baseStyle,
          fontWeight: 'bold',
          color: '#007bff',
        }
      : baseStyle;

  return (
    <nav
      style={{
        width: '200px',
        borderRight: '1px solid #ddd',
        padding: '10px 0',
      }}
    >
      <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
        <li>
          <NavLink
            to="."
            end
            style={({ isActive }) => getStyle(isActive)}
          >
            Inicio
          </NavLink>
        </li>
        <li>
          <NavLink
            to="users"
            style={({ isActive }) => getStyle(isActive)}
          >
            Usuarios
          </NavLink>
        </li>
        <li>
          <NavLink
            to="settings"
            style={({ isActive }) => getStyle(isActive)}
          >
            Configuración
          </NavLink>
        </li>
        <li>
          <NavLink
            to="modules"
            style={({ isActive }) => getStyle(isActive)}
          >
            Módulos
          </NavLink>
        </li>
      </ul>
    </nav>
  );
}