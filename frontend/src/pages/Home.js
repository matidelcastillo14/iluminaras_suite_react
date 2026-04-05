import React from 'react';
import { useAuth } from '../context/AuthContext';

/**
 * Home page shown after successful login.
 * Greets the user and instructs them to use the menu.
 */
const Home = () => {
  const { user } = useAuth();
  return (
    <div>
      <h1>Bienvenido{user?.username ? `, ${user.username}` : ''}</h1>
      <p>Usá el menú para navegar por los módulos disponibles.</p>
    </div>
  );
};

export default Home;