import React from 'react';

/**
 * Simple loader component.  Displays a loading message while data is being
 * fetched.  Accepts an optional `message` prop to customize the text.
 */
const Loader = ({ message = 'Cargando…' }) => {
  return (
    <div style={{ padding: '10px' }}>
      <p>{message}</p>
    </div>
  );
};

export default Loader;
