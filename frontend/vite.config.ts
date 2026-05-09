import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      vue: 'vue/dist/vue.esm-bundler.js',
    },
  },
  base: '/static/frontend/',
  build: {
    outDir: '../static/frontend',
    emptyOutDir: true,
    rollupOptions: {
      output: {
        manualChunks(id) {
          const normalizedId = id.replace(/\\/g, '/')
          if (normalizedId.includes('node_modules')) {
            if (normalizedId.includes('/vue/') || normalizedId.includes('/pinia/')) return 'vendor-vue'
            return 'vendor'
          }
          if (normalizedId.includes('/src/pages/analysis/analysis-template')) return 'analysis-template'
          if (normalizedId.includes('/src/pages/analysis/components/')) return 'analysis-template'
          if (normalizedId.includes('/src/pages/analysis/orchestrators/')) return 'analysis-runtime'
          if (normalizedId.includes('/src/features/agent/')) return 'feature-agent'
          if (normalizedId.includes('/src/features/road/') || normalizedId.includes('/src/map/')) return 'feature-road-map'
          if (normalizedId.includes('/src/features/h3/')) return 'feature-h3'
          if (normalizedId.includes('/src/features/history/')) return 'feature-history'
          if (normalizedId.includes('/src/features/export/')) return 'feature-export'
          if (normalizedId.includes('/src/features/poi/')) return 'feature-poi'
          if (normalizedId.includes('/src/features/isochrone/')) return 'feature-isochrone'
          if (normalizedId.includes('/src/stores/')) return 'feature-stores'
          return undefined
        },
      },
    },
  },
})
