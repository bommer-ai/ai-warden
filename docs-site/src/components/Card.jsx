import React from 'react';
import Link from '@docusaurus/Link';

const ICONS = {
  shield: '🛡️',
  'chart-line': '📊',
  users: '👥',
  gear: '⚙️',
  lightbulb: '💡',
  rocket: '🚀',
  code: '💻',
  lock: '🔒',
  zap: '⚡',
  eye: '👁️',
  dollar: '💰',
  tool: '🔧',
  file: '📄',
  terminal: '💻',
};

export function Card({ title, icon, href, children }) {
  const iconEmoji = ICONS[icon] || '📋';

  const content = (
    <div className="feature-card">
      <span className="feature-card__icon">{iconEmoji}</span>
      <div className="feature-card__title">{title}</div>
      {children && <p className="feature-card__description">{children}</p>}
    </div>
  );

  if (href) {
    return <Link to={href}>{content}</Link>;
  }

  return content;
}

export function CardGroup({ cols = 2, children }) {
  return (
    <div className={`card-group card-group--cols-${cols}`}>
      {children}
    </div>
  );
}
