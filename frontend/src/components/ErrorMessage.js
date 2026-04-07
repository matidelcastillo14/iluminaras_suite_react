import React from 'react';

/**
 * Generic error message component.  It renders nothing when no error is
 * provided.  When an error string is passed it displays it in red.  Use
 * this component to surface API errors to the user without duplicating
 * markup across pages.
 */
const ErrorMessage = ({ error }) => {
  if (!error) return null;
  return (
    <div style={{ color: 'red', margin: '10px 0' }}>
      {error}
    </div>
  );
};

export default ErrorMessage;
