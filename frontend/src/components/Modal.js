import React from 'react';

/**
 * Simple modal component that renders its children inside a
 * centered panel with an overlay. It accepts `onClose` prop to be
 * called when the overlay is clicked or the Close button is
 * pressed. The caller must control whether the modal is shown.
 *
 * Usage:
 *   {show && (
 *     <Modal onClose={() => setShow(false)}>
 *       <div>Modal content</div>
 *     </Modal>
 *   )}
 */
export default function Modal({ children, onClose }) {
  return (
    <div
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        width: '100%',
        height: '100%',
        backgroundColor: 'rgba(0,0,0,0.4)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 1000,
      }}
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          backgroundColor: '#fff',
          padding: '20px',
          borderRadius: '4px',
          minWidth: '320px',
          maxWidth: '90%',
          maxHeight: '90%',
          overflowY: 'auto',
        }}
      >
        <button
          onClick={onClose}
          style={{ float: 'right', background: 'none', border: 'none', fontSize: '20px' }}
        >
          &times;
        </button>
        {children}
      </div>
    </div>
  );
}