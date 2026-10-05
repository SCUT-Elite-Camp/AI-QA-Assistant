import { defineHandler } from 'nitro'
import { agentFetch } from '../../../utils/agent-client'

export default defineHandler(async () => {
  try {
    const res = await agentFetch('/api/config/llm')
    if (!res.ok) {
      const errText = await res.text().catch(() => '')
      return {
        error: `Agent returned ${res.status}: ${errText}`,
        llm_api_base: '',
        llm_model: '',
        llm_api_key_masked: '',
        has_api_key: false,
        llm_http_proxy: '',
        llm_temperature: 0.1,
        llm_max_tokens: 2000,
        llm_timeout: 60,
      }
    }
    return await res.json()
  } catch (err: any) {
    return {
      error: `Failed to connect to Agent: ${err.message}`,
      llm_api_base: '',
      llm_model: '',
      llm_api_key_masked: '',
      has_api_key: false,
      llm_http_proxy: '',
      llm_temperature: 0.1,
      llm_max_tokens: 2000,
      llm_timeout: 60,
    }
  }
})
