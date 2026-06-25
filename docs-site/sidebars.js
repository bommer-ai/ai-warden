/** @type {import('@docusaurus/plugin-content-docs').SidebarsConfig} */
const sidebars = {
  docs: [
    'introduction',
    'getting-started',
    'concepts',
    'configuration',
    'hot-mode',
    'multi-agent',
    {
      type: 'category',
      label: 'Policies',
      collapsed: false,
      items: [
        'policies/overview',
        'policies/budget',
        'policies/pii',
        'policies/tools',
        'policies/agent-control',
        'policies/custom',
      ],
    },
    {
      type: 'category',
      label: 'Advanced',
      collapsed: true,
      items: [
        'advanced/architecture',
        'advanced/run-tracking',
        'advanced/streaming',
        'advanced/module-policy',
      ],
    },
    {
      type: 'category',
      label: 'Examples',
      collapsed: true,
      items: [
        'examples/single-agent',
        'examples/multi-agent-budget',
        'examples/custom-rules',
      ],
    },
  ],
};

module.exports = sidebars;
