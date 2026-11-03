import React from 'react';

export const DropdownTrigger = ({ children, onClick }) => {
  return (
    <div className="dropdown__trigger">
      <span role="button" onClick={onClick}>
        {children}
      </span>
    </div>
  );
};
