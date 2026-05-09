<script setup lang="ts">
import { onMounted, ref } from "vue";

const loading = ref(true)
const error = ref("")

onMounted(async () => {
  try {
    const res = await fetch("/api/v1/config")
    if (!res.ok) {
      throw new Error(`/api/v1/config 请求失败(${res.status})`)
    }
    const data = await res.json()
    const { mountAnalysisWorkbench } = await import("./mount-analysis")
    await mountAnalysisWorkbench({
      config: {
        amap_js_api_key: String(data?.amap_js_api_key || ""),
        amap_js_security_code: String(data?.amap_js_security_code || ""),
        tianditu_key: String(data?.tianditu_key || ""),
      },
      typeMapConfig: (data?.map_type_config_json || { groups: [] }) as Record<string, unknown>,
    })
  } catch (e) {
    const message = e instanceof Error ? e.message : String(e)
    error.value = `初始化失败：${message}`
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <main class="analysis-shell">
    <div id="analysis-app-root" class="analysis-host"></div>
    <div v-if="loading" class="state state-overlay">正在初始化分析工作台...</div>
    <div v-else-if="error" class="state state-error">{{ error }}</div>
  </main>
</template>

<style scoped>
.analysis-shell {
  position: fixed;
  inset: 0;
  background: #f3f5f9;
}
.analysis-host {
  display: flex;
  align-items: stretch;
  width: 100%;
  height: 100%;
  min-height: 100vh;
  overflow: hidden;
}
.state {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #1f2937;
  font-size: 14px;
}
.state-overlay {
  background: rgba(243, 245, 249, 0.85);
}
.state-error {
  color: #b91c1c;
  background: rgba(255, 255, 255, 0.95);
}
</style>
