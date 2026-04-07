import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

const Login = () => {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const { login } = useAuth();
  const navigate = useNavigate();

  const translateError = (message) => {
    switch (message) {
      case 'invalid_credentials':
        return 'Credenciales inválidas';
      case 'must_change_password':
        return 'Debes cambiar la contraseña antes de continuar';
      case 'username_and_password_required':
        return 'Usuario y contraseña son obligatorios';
      default:
        return message || 'No se pudo iniciar sesión';
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');

    try {
      const res = await login(username, password);
      if (res?.ok) {
        navigate('/');
        return;
      }
      setError(translateError(res?.error));
    } catch (err) {
      setError(translateError(err?.message));
    }
  };

  return (
    <div style={{ maxWidth: '400px', margin: '60px auto' }}>
      <h2>Iniciar sesión</h2>
      <form onSubmit={handleSubmit}>
        <div style={{ marginBottom: '10px' }}>
          <label>Usuario o email</label>
          <input
            type="text"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
            style={{ width: '100%' }}
          />
        </div>
        <div style={{ marginBottom: '10px' }}>
          <label>Contraseña</label>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            style={{ width: '100%' }}
          />
        </div>
        {error && <p style={{ color: 'red' }}>{error}</p>}
        <button type="submit">Entrar</button>
      </form>
    </div>
  );
};

export default Login;
