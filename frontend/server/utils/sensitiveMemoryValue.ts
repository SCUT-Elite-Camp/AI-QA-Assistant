const SENSITIVE_KEYWORDS = [
  'password',
  'passwd',
  'secret',
  'token',
  'api key',
  'private key',
  'access key',
  '银行卡',
  '银行账户',
  '账号',
  '住址',
  '详细地址',
  '诊断',
  '病历',
  '疾病',
  '药物',
  '金融账户'
] as const

const CHINESE_ID_PATTERN = /\b\d{17}[\dXx]\b/u

/**
 * Frozen Unit 07-compatible sensitivity check. It is pure and deliberately
 * neither logs nor persists the text it examines.
 */
export function isSensitiveMemoryValue (text: string): boolean {
  const normalized = text.toLowerCase().replace(/\s+/gu, ' ')
  if (SENSITIVE_KEYWORDS.some(keyword => normalized.includes(keyword))) return true
  if (CHINESE_ID_PATTERN.test(text)) return true

  const digitCount = text.replace(/\D+/gu, '').length
  return digitCount >= 13 && digitCount <= 19
}
