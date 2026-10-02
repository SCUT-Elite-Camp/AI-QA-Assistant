const messages: Record<string, string> = {
  invalid_query: '请输入有效的问题。',
  no_relevant_context: '没有找到足够相关的资料，请补充信息后重试。',
  retrieval_error: '资料检索暂时失败，请稍后重试。',
  llm_error: '回答服务暂时不可用，请稍后重试。',
  network_error: '连接失败，请检查网络后重试。',
}

export function getErrorMessage(status?: string, message?: string): string {
  return (status && messages[status]) || message || '请求失败，请稍后重试。'
}
