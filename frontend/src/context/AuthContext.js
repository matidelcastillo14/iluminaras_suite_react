import React, { createContext, useContext, useEffect, useMemo, useState } from 'react';
import api from '../services/api';

const AuthContext = createContext({});

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [permissions, setPermissions] = useState([]);
  const [loading, setLoading] = useState(true);

  const fetchUser = async () => {
    try {
      const res = await api.get('/auth/api/me');
      if (res?.authenticated && res?.user) {
        setUser(res.user);
        setPermissions(Array.isArray(res.permissions) ? res.permissions : []);
        return res;
      }
    } catch (_) {
      // sesión inexistente o expirada
    }

    setUser(null);
    setPermissions([]);
    return { authenticated: false };
  };

  useEffect(() => {
    let mounted = true;

    (async () => {
      try {
        const res = await api.get('/auth/api/me');
        if (!mounted) return;

        if (res?.authenticated && res?.user) {
          setUser(res.user);
          setPermissions(Array.isArray(res.permissions) ? res.permissions : []);
        } else {
          setUser(null);
          setPermissions([]);
        }
      } catch (_) {
        if (mounted) {
          setUser(null);
          setPermissions([]);
        }
      } finally {
        if (mounted) setLoading(false);
      }
    })();

    return () => {
      mounted = false;
    };
  }, []);

  const login = async (username, password) => {
    const res = await api.post('/auth/api/login', { username, password });
    const me = await fetchUser();
    return { ...res, authenticated: !!me?.authenticated };
  };

  const logout = async () => {
    try {
      await api.post('/auth/api/logout');
    } catch (_) {
      // ignorar
    }
    setUser(null);
    setPermissions([]);
  };

  const value = useMemo(() => ({
    user,
    permissions,
    loading,
    login,
    logout,
    refreshUser: fetchUser,
  }), [user, permissions, loading]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

export const useAuth = () => useContext(AuthContext);
