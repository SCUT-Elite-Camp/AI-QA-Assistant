import { getMemoryFeatureFlags } from './memoryFeatureFlags'

/**
 * Fact lifecycle is fail-closed until an operator explicitly enables it.
 * This is server-only configuration; browser input is never consulted.
 */
export function isSessionFactEnabled (
  environment: Record<string, string | undefined> = process.env
): boolean {
  return getMemoryFeatureFlags(environment).sessionFactEnabled
}
