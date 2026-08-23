const ENABLED_VALUES = new Set(['1', 'true', 'yes', 'on'])

/**
 * Fact lifecycle is fail-closed until an operator explicitly enables it.
 * This is server-only configuration; browser input is never consulted.
 */
export function isSessionFactEnabled (
  environment: Record<string, string | undefined> = process.env
): boolean {
  return ENABLED_VALUES.has(environment.SESSION_FACT_ENABLED?.trim().toLowerCase() ?? '')
}
