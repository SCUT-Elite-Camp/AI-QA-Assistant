import { defineHandler } from 'nitro'
import { attachmentServiceFetch } from '../../../utils/attachmentService'

export default defineHandler(async () => {
  if (process.env.ATTACHMENTS_ENABLED !== 'true') return { enabled: false }
  const response = await attachmentServiceFetch('/health/ready').catch(() => null)
  return { enabled: response?.ok === true }
})
