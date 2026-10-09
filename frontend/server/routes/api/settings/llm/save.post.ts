import { defineHandler, HTTPError } from 'nitro'
import { readBody } from 'nitro/h3'
import { useUserSession } from '../../../../utils/session'
import { agentFetch } from '../../../../utils/agent-client'

export default defineHandler(async (event) => {
  const session = await useUserSession(event)
  const userId = session.data.user?.id

  if (!userId) {
    throw new HTTPError({ statusCode: 401, statusMessage: 'Unauthorized: 请先登录' })
  }

  const body = await readBody(event)
  try {
    const res = await agentFetch('/api/config/llm/save', {
      method: 'POST',
      body: JSON.stringify(body || {}),
    })

    if (!res.ok) {
      const errData = await res.json().catch(() => null)
      const errDetail = errData?.detail || (await res.text().catch(() => ''))
      throw new HTTPError({
        statusCode: res.status,
        statusMessage: `Agent Error: ${errDetail}`,
      })
    }

    return await res.json()
  } catch (err: any) {
    if (err.statusCode) {
      throw err
    }
    throw new HTTPError({
      statusCode: 500,
      statusMessage: `保存失败: ${err.message}`,
    })
  }
})
