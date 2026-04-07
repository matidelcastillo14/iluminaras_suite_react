import React, { createContext, useContext, useState, useEffect } from 'react';
import api from '../services/api';

const AuthContext = createContext({});

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [permissions, setPermissions] = useState([]);
  const [loading, setLoading] = useState(true);

  const fetchUser = async () => {
    try {
      const res = await api.get('/auth/api/me');
      if (res?.ok && res?.authenticated) {
        setUser(res.user || null);
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

  const login = async (username, password) => {
    const res = await api.post('/auth/api/login', { username, password });
    await fetchUser();
    return res;
  };

  const logout = async () => {
    try {
      await api.post('/auth/api/logout');
    } catch (e) {
      // ignorar error de logout
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

export const useAuth = () => useContext(AuthContext);
