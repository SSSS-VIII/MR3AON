import { defineConfig } from 'vitepress'

// https://vitepress.dev/reference/site-config
export default defineConfig({
  title: 'MR3A',
  description: '《忍者必须死3》自动化助手 - 用户文档',
  base: '/MR3A/',
  lastUpdated: true,
  cleanUrls: true,
  ignoreDeadLinks: [
    /cli$/,
    /introduction$/,
    /MirrorChyan$/,
  ],

  head: [
    ['link', { rel: 'icon', href: '/MR3A/logo.webp' }],
    ['style', {}, '.VPHero .text { white-space: pre-line; }'],
  ],

  // develop/ 仅保留在仓库，不在站点展示
  srcExclude: ['develop/**'],

  themeConfig: {
    logo: '/logo.webp',

    nav: [
      { text: '首页', link: '/' },
      { text: '用户手册', link: '/manual/newbie' },
      { text: 'MaaFramework 文档', link: 'https://maafw.com/docs/1.1-QuickStarted' },
    ],

    sidebar: {
      '/manual/': [
        {
          text: '用户手册',
          items: [
            { text: '新手上路', link: '/manual/newbie' },
            { text: '连接设置', link: '/manual/connection' },
            { text: '配置说明', link: '/manual/config' },
            { text: '使用场景', link: '/manual/scenarios' },
            { text: '常见问题', link: '/manual/faq' },
          ],
        },
      ],
    },

    socialLinks: [
      { icon: 'github', link: 'https://github.com/originalsage/MR3A' },
    ],

    footer: {
      message: 'Powered by <a href="https://github.com/MaaXYZ/MaaFramework">MaaFramework</a> &amp; <a href="https://github.com/MaaXYZ/MFAAvalonia">MFAAvalonia</a>',
    },

    outline: {
      level: [2, 3],
      label: '本页目录',
    },

    search: {
      provider: 'local',
    },
  },
})
