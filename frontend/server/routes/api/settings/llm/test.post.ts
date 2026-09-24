import { defineHandler, HTTPError } from 'nitro'
import { readBody } from 'nitro/h3'
import { agentFetch } from '../../../../utils/agent-client'

export default defineHandler(async (event) => {
  const body = await readBody(event)
  try {
    const res = await agentFetch('/api/config/llm/test', {
      method: 'POST',
      body: JSON.stringify(body || {}),
    })

    if (!res.ok) {
      const errData = await res.json().catch(() => null)
      const errDetail = errData?.detail || (await res.text().catch(() => ''))
      return {
        success: false,
        latency_ms: 0,
        model: body?.llm_model || '',
        error: `Agent HTTP ${res.status}: ${errDetail}`,
      }
    }

    return await res.json()
  } catch (err: any) {
    return {
      success: false,
      latency_ms: 0,
      model: body?.llm_model || '',
      error: `无法连接 Agent 后端: ${err.message}`,
    }
  }
})
