import { onMounted, onUnmounted } from 'vue'

/**
 * 前端性能监控 composable。
 * 采集 Web Vitals (LCP, FCP, INP) 并通过 Beacon API 上报到服务端。
 */
export function usePerformanceObserver() {
  let observers: PerformanceObserver[] = []

  function report(metric: { name: string; value: number; rating: string }) {
    // 使用 sendBeacon 确保页面卸载时也能发送
    const payload = JSON.stringify({
      name: metric.name,
      value: Math.round(metric.value),
      rating: metric.rating,
      timestamp: Date.now(),
      page: window.location.pathname,
    })

    if (navigator.sendBeacon) {
      navigator.sendBeacon('/api/telemetry', payload)
    } else {
      fetch('/api/telemetry', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: payload,
        keepalive: true,
      }).catch(() => { /* 静默失败 */ })
    }
  }

  function observeLCP() {
    try {
      const observer = new PerformanceObserver((list) => {
        const entries = list.getEntries()
        const lastEntry = entries[entries.length - 1]
        if (lastEntry) {
          report({
            name: 'LCP',
            value: (lastEntry as PerformanceEntry & { startTime: number }).startTime,
            rating: (lastEntry as PerformanceEntry & { startTime: number }).startTime < 2500 ? 'good' :
                    (lastEntry as PerformanceEntry & { startTime: number }).startTime < 4000 ? 'needs-improvement' : 'poor',
          })
        }
      })
      observer.observe({ type: 'largest-contentful-paint', buffered: true })
      observers.push(observer)
    } catch { /* 浏览器不支持 */ }
  }

  function observeFCP() {
    try {
      const observer = new PerformanceObserver((list) => {
        const entries = list.getEntriesByName('first-contentful-paint')
        if (entries.length > 0) {
          const fcp = entries[0]!
          report({
            name: 'FCP',
            value: fcp.startTime,
            rating: fcp.startTime < 1800 ? 'good' :
                    fcp.startTime < 3000 ? 'needs-improvement' : 'poor',
          })
        }
      })
      observer.observe({ type: 'paint', buffered: true })
      observers.push(observer)
    } catch { /* 浏览器不支持 */ }
  }

  function observeINP() {
    try {
      let maxDuration = 0
      const observer = new PerformanceObserver((list) => {
        for (const entry of list.getEntries()) {
          const dur = (entry as PerformanceEventTiming).duration
          if (dur > maxDuration) {
            maxDuration = dur
          }
        }
      })
      observer.observe({
        type: 'event',
        buffered: true,
        durationThreshold: 16,
      } as PerformanceObserverInit)

      // 在页面隐藏时上报 INP
      const visibilityHandler = () => {
        if (document.visibilityState === 'hidden' && maxDuration > 0) {
          report({
            name: 'INP',
            value: maxDuration,
            rating: maxDuration < 200 ? 'good' :
                    maxDuration < 500 ? 'needs-improvement' : 'poor',
          })
        }
      }
      document.addEventListener('visibilitychange', visibilityHandler)
      observers.push(observer)
    } catch { /* 浏览器不支持 */ }
  }

  onMounted(() => {
    observeLCP()
    observeFCP()
    observeINP()
  })

  onUnmounted(() => {
    for (const observer of observers) {
      observer.disconnect()
    }
    observers = []
  })
}
