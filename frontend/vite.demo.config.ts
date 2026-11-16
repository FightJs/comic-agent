import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { resolve } from 'node:path'
export default defineConfig({ root: resolve(__dirname, 'demo'), base: '/comic-agent/', plugins: [react()], publicDir: false, build: { outDir: resolve(__dirname, 'dist-demo'), emptyOutDir: true } })
