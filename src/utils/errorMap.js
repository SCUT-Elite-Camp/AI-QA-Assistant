export const ERROR_MESSAGES = {
  success: '',
  invalid_query: '请输入有效问题',
  no_relevant_context: '当前知识库没有足够信息回答该问题',
  retrieval_error: '检索服务暂时不可用，请稍后重试',
  llm_error: '模型服务暂时不可用，请稍后重试',
  network_error: '网络连接异常，请检查服务是否启动',
  timeout_error: '请求超时，请稍后重试',
  stream_error: '生成中断，请稍后重试',
  unknown_error: '服务暂时不可用，请稍后重试',
};

export function getErrorMessage(status, fallbackMessage) {
  const normalizedFallback = typeof fallbackMessage === 'string' ? fallbackMessage.trim() : '';

  if (normalizedFallback) {
    return normalizedFallback;
  }

  if (status && Object.prototype.hasOwnProperty.call(ERROR_MESSAGES, status)) {
    return ERROR_MESSAGES[status];
  }

  return ERROR_MESSAGES.unknown_error;
}
