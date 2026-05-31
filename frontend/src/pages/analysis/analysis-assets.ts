const scriptCache = new Map<string, Promise<void>>()
function ensureScript(src: string): Promise<void> {
  const cached = scriptCache.get(src)
  if (cached) return cached

  const p = new Promise<void>((resolve, reject) => {
    const existing = document.querySelector(`script[data-analysis-src="${src}"]`) as HTMLScriptElement | null
    if (existing) {
      if ((existing as any).__loaded) {
        resolve()
        return
      }
      existing.addEventListener('load', () => resolve(), { once: true })
      existing.addEventListener('error', () => reject(new Error(`script load failed: ${src}`)), { once: true })
      return
    }

    const s = document.createElement('script')
    s.src = src
    s.async = false
    s.dataset.analysisSrc = src
    s.onload = () => {
      ;(s as any).__loaded = true
      resolve()
    }
    s.onerror = () => reject(new Error(`script load failed: ${src}`))
    document.head.appendChild(s)
  })

  scriptCache.set(src, p)
  return p
}

export async function ensureAnalysisVendorsAndStyles(): Promise<void> {
  await ensureScript('/static/vendor/html2canvas.min.js')
  await ensureScript('/static/vendor/echarts.min.js')
}
