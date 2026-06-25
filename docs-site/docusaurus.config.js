// @ts-check

/** @type {import('@docusaurus/types').Config} */
const config = {
  title: 'ai-warden',
  tagline: 'Policy enforcement and observability for AI agents',
  favicon: 'img/favicon.ico',

  url: 'https://docs.aiwarden.dev',
  baseUrl: '/',

  organizationName: 'bommer-ai',
  projectName: 'ai-warden',

  onBrokenLinks: 'throw',
  onBrokenMarkdownLinks: 'warn',

  i18n: {
    defaultLocale: 'en',
    locales: ['en'],
  },

  presets: [
    [
      'classic',
      /** @type {import('@docusaurus/preset-classic').Options} */
      ({
        docs: {
          routeBasePath: '/',
          sidebarPath: './sidebars.js',
          editUrl: 'https://github.com/bommer-ai/ai-warden/tree/main/docs-site/',
        },
        blog: false,
        pages: false,
        theme: {
          customCss: './src/css/custom.css',
        },
      }),
    ],
  ],

  themeConfig:
    /** @type {import('@docusaurus/preset-classic').ThemeConfig} */
    ({
      colorMode: {
        defaultMode: 'light',
        disableSwitch: false,
        respectPrefersColorScheme: true,
      },
      navbar: {
        title: 'ai-warden',
        logo: {
          alt: 'ai-warden',
          src: 'img/logo.png',
          style: { height: '28px' },
        },
        items: [
          {
            type: 'docSidebar',
            sidebarId: 'docs',
            position: 'left',
            label: 'Docs',
          },
          {
            to: '/examples/single-agent',
            label: 'Examples',
            position: 'left',
          },
          {
            href: 'https://github.com/bommer-ai/ai-warden',
            position: 'right',
            className: 'header-github-link',
            'aria-label': 'GitHub repository',
          },
          {
            href: '/getting-started',
            label: 'Get Started',
            position: 'right',
            className: 'navbar-get-started',
          },
        ],
      },
      footer: {
        style: 'light',
        links: [
          {
            title: 'Docs',
            items: [
              { label: 'Getting Started', to: '/getting-started' },
              { label: 'Core Concepts', to: '/concepts' },
              { label: 'Configuration', to: '/configuration' },
            ],
          },
          {
            title: 'Policies',
            items: [
              { label: 'Overview', to: '/policies/overview' },
              { label: 'Budget Control', to: '/policies/budget' },
              { label: 'PII Protection', to: '/policies/pii' },
              { label: 'Tool Safety', to: '/policies/tools' },
            ],
          },
          {
            title: 'More',
            items: [
              { label: 'GitHub', href: 'https://github.com/bommer-ai/ai-warden' },
              { label: 'PyPI', href: 'https://pypi.org/project/ai-warden/' },
            ],
          },
        ],
        copyright: `Copyright ${new Date().getFullYear()} ai-warden contributors.`,
      },
      prism: {
        theme: require('prism-react-renderer').themes.github,
        darkTheme: require('prism-react-renderer').themes.dracula,
        additionalLanguages: ['bash', 'yaml', 'python', 'json'],
      },
      tableOfContents: {
        minHeadingLevel: 2,
        maxHeadingLevel: 4,
      },
    }),
};

module.exports = config;
