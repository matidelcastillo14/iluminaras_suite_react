import React, { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import Loader from '../../components/Loader';
import ErrorMessage from '../../components/ErrorMessage';
import Table from '../../components/Table';
import { listUsers, toggleUser, resetUserPassword } from '../../services/admin';

export default function UsersPage() {
  const navigate = useNavigate();
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [msg, setMsg] = useState('');

  const loadUsers = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await listUsers();
      setUsers(res.users || res);
    } catch (err) {
      setError(err?.message || String(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadUsers();
  }, []);

  const handleToggle = async (id) => {
    try {
      await toggleUser(id);
      await loadUsers();
    } catch (err) {
      setMsg(err?.message || String(err));
    }
  };

  const handleReset = async (id) => {
    if (!window.confirm('¿Restablecer contraseña temporal?')) return;
    try {
      const res = await resetUserPassword(id);
      const temp = res.temp_password || res.password || res.tmp || null;
      const sent = res.sent;
      setMsg(`Nueva contraseña: ${temp || '(desconocida)'}${sent ? ' (enviada por email)' : ''}`);
      await loadUsers();
    } catch (err) {
      setMsg(err?.message || String(err));
    }
  };

  return (
    <div>
      <h3>Usuarios</h3>
      {loading && <Loader />}
      {error && <ErrorMessage error={error} />}
      {msg && <p>{msg}</p>}
      {!loading && !error && (
        <div>
          <div style={{ marginBottom: '10px' }}>
            <Link to="/admin/users/new">Nuevo usuario</Link>
          </div>
          {users && users.length > 0 ? (
            <Table
              headers={['ID', 'Usuario', 'Nombre', 'Rol', 'Activo', 'Acciones']}
              rows={users.map((u) => [
                u.id,
                u.username,
                `${u.first_name || ''} ${u.last_name || ''}`.trim(),
                u.role,
                u.is_active ? 'Sí' : 'No',
                '',
              ])}
              onRowClick={(idx) => navigate(`/admin/users/${users[idx].id}`)}
              renderCell={(rowIdx, colIdx, value) => {
                const user = users[rowIdx];
                if (colIdx !== 5) return value;
                return (
                  <span>
                    <button onClick={(e) => { e.stopPropagation(); handleToggle(user.id); }} style={{ marginRight: '5px' }}>
                      {user.is_active ? 'Desactivar' : 'Activar'}
                    </button>
                    <button onClick={(e) => { e.stopPropagation(); handleReset(user.id); }}>
                      Reset clave
                    </button>
                  </span>
                );
              }}
            />
          ) : (
            <p>No hay usuarios.</p>
          )}
        </div>
      )}
    </div>
  );
}
