import React, { createContext, useContext, useState, useEffect } from 'react';
import api from '../services/api';

// Contexto de autenticación para administrar sesión y permisos.
const AuthContext = createContext({});

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [permissions, setPermissions] = useState([]);
  const [loading, setLoading] = useState(true);

  // Cargar datos del usuario al iniciar la app
  const fetchUser = async () => {
    try {
      const res = await api.get('/auth/api/me');
      if (res && res.ok && res.authenticated) {
        setUser(res.user);
        setPermissions(res.permissions || []);
      } else {
        setUser(null);
        setPermissions([]);
      }
    } catch (e) {
      setUser(null);
      setPermissions([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchUser();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Iniciar sesión llamando al API JSON
  const login = async (username, password) => {
    const res = await api.post('/auth/api/login', { username, password });
    // Si el login fue exitoso, recargar usuario
    await fetchUser();
    return res;
  };

  // Cerrar sesión
  const logout = async () => {
    try {
      await api.post('/auth/api/logout');
    } catch (e) {
      // Ignorar errores de logout
    }
    setUser(null);
    setPermissions([]);
  };

  return (
    <AuthContext.Provider value={{ user, permissions, loading, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
};

// Hook para consumir contexto
export const useAuth = () => useContext(AuthContext);