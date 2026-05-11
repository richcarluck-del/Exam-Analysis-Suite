import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

/** 开发与 start_fastapi.ps1 对齐；预处理测试 UI 在 8001，勿与该端口混淆。可通过 .env.development 中 VITE_DEV_API_ORIGIN 覆盖。 */
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const devPort = Number.parseInt(String(env.VITE_DEV_PORT || '5174'), 10)
  const apiOrigin = (env.VITE_DEV_API_ORIGIN || 'http://127.0.0.1:8000').replace(/\/$/, '')
  const wsOrigin = apiOrigin.startsWith('https')
    ? apiOrigin.replace(/^https/, 'wss')
    : apiOrigin.replace(/^http/, 'ws')

  return {
    plugins: [react()],
    server: {
      host: '0.0.0.0',
      port: Number.isFinite(devPort) && devPort > 0 ? devPort : 5174,
      strictPort: true,
      proxy: {
        '/api': {
          target: apiOrigin,
          changeOrigin: true,
        },
        '/ws': {
          target: wsOrigin,
          ws: true,
        },
      },
    },
  }
})
