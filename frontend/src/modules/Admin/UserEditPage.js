import React, { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import Loader from '../../components/Loader';
import ErrorMessage from '../../components/ErrorMessage';
import {
  getUser,
  createUser,
  updateUser,
  listRoles,
  resetUserPassword,
  toggleUser,
} from '../../services/admin';

/**
 * Form for creating or editing a user. When id === 'new' it will
 * create a fresh user; otherwise it loads the existing user and
 * allows updating fields. Buttons are provided to toggle active and
 * reset the temporary password on existing users.
 */
export default function UserEditPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const isNew = id === 'new';
  const [user, setUser] = useState({
    username: '',
    email: '',
    first_name: '',
    last_name: '',
    phone: '',
    attendance_ref_code: '',
    home_office_clock_enabled: false,
    role: 'operator',
    is_active: true,
  });
  const [roles, setRoles] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [msg, setMsg] = useState('');

  useEffect(() => {
    async function fetchData() {
      setLoading(true);
      setError(null);
      try {
        const rolesRes = await listRoles();
        setRoles(rolesRes.roles || rolesRes);
        if (!isNew) {
          const u = await getUser(id);
          setUser(u);
        }
      } catch (err) {
        setError(err?.message || String(err));
      } finally {
        setLoading(false);
      }
    }
    fetchData();
  }, [id, isNew]);

  const handleChange = (field, value) => {
    setUser((prev) => ({ ...prev, [field]: value }));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setMsg('');
    try {
      if (isNew) {
        await createUser(user);
        setMsg('Usuario creado.');
        navigate('/admin/users');
      } else {
        await updateUser(id, user);
        setMsg('Usuario actualizado.');
      }
    } catch (err) {
      setMsg(err?.message || String(err));
    }
  };

  const handleResetTemp = async () => {
    if (!window.confirm('¿Generar contraseña temporal?')) return;
    try {
      const res = await resetUserPassword(id);
      const temp = res.temp_password || res.password || res.tmp || null;
      const sent = res.sent;
      setMsg(`Nueva contraseña: ${temp || '(desconocida)'}${sent ? ' (enviada por email)' : ''}`);
    } catch (err) {
      setMsg(err?.message || String(err));
    }
  };

  const handleToggleActive = async () => {
    try {
      await toggleUser(id);
      const updated = await getUser(id);
      setUser(updated);
    } catch (err) {
      setMsg(err?.message || String(err));
    }
  };

  return (
    <div>
      {loading && <Loader />}
      {error && <ErrorMessage message={error} />}
      {!loading && !error && (
        <div>
          <h3>{isNew ? 'Nuevo usuario' : `Editar usuario #${id}`}</h3>
          {msg && <p>{msg}</p>}
          <form onSubmit={handleSubmit}>
            <div>
              <label>
                Usuario
                <br />
                <input
                  type="text"
                  value={user.username}
                  onChange={(e) => handleChange('username', e.target.value)}
                  required
                />
              </label>
            </div>
            <div>
              <label>
                Email
                <br />
                <input
                  type="email"
                  value={user.email}
                  onChange={(e) => handleChange('email', e.target.value)}
                  required
                />
              </label>
            </div>
            <div>
              <label>
                Nombre
                <br />
                <input
                  type="text"
                  value={user.first_name}
                  onChange={(e) => handleChange('first_name', e.target.value)}
                  required
                />
              </label>
            </div>
            <div>
              <label>
                Apellido
                <br />
                <input
                  type="text"
                  value={user.last_name}
                  onChange={(e) => handleChange('last_name', e.target.value)}
                  required
                />
              </label>
            </div>
            <div>
              <label>
                Teléfono
                <br />
                <input
                  type="text"
                  value={user.phone || ''}
                  onChange={(e) => handleChange('phone', e.target.value)}
                />
              </label>
            </div>
            <div>
              <label>
                CI (attendance_ref_code)
                <br />
                <input
                  type="text"
                  value={user.attendance_ref_code || ''}
                  onChange={(e) => handleChange('attendance_ref_code', e.target.value)}
                />
              </label>
            </div>
            <div>
              <label>
                Reloj Home habilitado
                <input
                  type="checkbox"
                  checked={!!user.home_office_clock_enabled}
                  onChange={(e) => handleChange('home_office_clock_enabled', e.target.checked)}
                  style={{ marginLeft: '8px' }}
                />
              </label>
            </div>
            <div>
              <label>
                Rol
                <br />
                <select value={user.role} onChange={(e) => handleChange('role', e.target.value)}>
                  {roles.map((r) => (
                    <option key={r} value={r}>
                      {r}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            {!isNew && (
              <div>
                <label>
                  Activo
                  <input
                    type="checkbox"
                    checked={!!user.is_active}
                    onChange={(e) => handleChange('is_active', e.target.checked)}
                    style={{ marginLeft: '8px' }}
                  />
                </label>
              </div>
            )}
            <div style={{ marginTop: '10px' }}>
              <button type="submit">{isNew ? 'Crear' : 'Guardar'}</button>
              <button
                type="button"
                onClick={() => navigate('/admin/users')}
                style={{ marginLeft: '10px' }}
              >
                Volver
              </button>
            </div>
          </form>
          {!isNew && (
            <div style={{ marginTop: '20px' }}>
              <button onClick={handleToggleActive} style={{ marginRight: '10px' }}>
                {user.is_active ? 'Desactivar usuario' : 'Activar usuario'}
              </button>
              <button onClick={handleResetTemp}>Resetear contraseña</button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}