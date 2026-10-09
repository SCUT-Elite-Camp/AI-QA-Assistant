export function evidenceUrl(messageId: string, evidenceRef: string): string {
  if (!messageId || !evidenceRef) throw new Error('这条旧引用没有可核验的来源绑定，请重新提问。')
  return `/api/messages/${encodeURIComponent(messageId)}/evidence/${encodeURIComponent(evidenceRef)}`
}

export function evidenceError(error: unknown): string {
  const failure = error as { statusCode?: number, status?: number, response?: { status?: number } }
  const status = failure.statusCode ?? failure.status ?? failure.response?.status
  if (status === 401) return '登录已失效，请重新登录后查看原文。'
  if (status === 403 || status === 404) return '当前无法访问这条消息或其证据，请检查权限或重新提问。'
  if (status === 409) return '原文版本已变化，不能用当前内容替代旧引用。请重新提问获取新依据。'
  if (status === 503) return '访问校验暂不可用，请稍后重试。'
  return error instanceof Error ? error.message : '原文读取失败，请稍后重试。'
}

export function formatRetrievalScore(value: unknown): string {
  return typeof value === 'number' && Number.isFinite(value) ? value.toPrecision(4) : '未知'
}
