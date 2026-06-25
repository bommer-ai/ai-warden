import React from 'react';

export function Steps({ children }) {
  return <div className="steps">{children}</div>;
}

export function Step({ title, number, children }) {
  return (
    <div className="step" data-step={number}>
      <div className="step__title">{title}</div>
      <div className="step__content">{children}</div>
    </div>
  );
}
