import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['favicon.svg', 'apple-touch-icon.png'],
      workbox: {
        // 端末内完結アプリ: 全アセットをprecacheしてオフライン完全動作
        globPatterns: ['**/*.{js,css,html,svg,png,woff2}'],
        navigateFallback: 'index.html',
      },
      manifest: {
        name: 'しゃべるえほん',
        short_name: 'しゃべるえほん',
        description: 'かぞくのしゃべる絵本メーカー',
        lang: 'ja',
        dir: 'ltr',
        display: 'standalone',
        orientation: 'any',
        start_url: '/',
        scope: '/',
        background_color: '#fff8e1',
        theme_color: '#ffb300',
        icons: [
          { src: 'icon-192.png', sizes: '192x192', type: 'image/png' },
          { src: 'icon-512.png', sizes: '512x512', type: 'image/png' },
          {
            src: 'icon-maskable-512.png',
            sizes: '512x512',
            type: 'image/png',
            purpose: 'maskable',
          },
        ],
      },
    }),
  ],
})
