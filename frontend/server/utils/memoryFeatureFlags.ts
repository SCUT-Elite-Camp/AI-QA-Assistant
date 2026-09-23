const ENABLED_VALUES = new Set(['1', 'true', 'yes', 'on'])

export interface MemoryFeatureFlags {
  persistentMemoryEnabled: boolean
  sessionFactEnabled: boolean
}

export class MemoryFeatureConfigurationError extends Error {
  readonly code = 'memory_cache_not_supported'

  constructor () {
    super('memory_cache_not_supported')
    this.name = 'MemoryFeatureConfigurationError'
  }
}

function isEnabled (
  value: string | undefined
): boolean {
  return ENABLED_VALUES.has(value?.trim().toLowerCase() ?? '')
}

/**
 * Parse Memory flags only on the server and fail closed for unknown values.
 * Cache support is deliberately absent in this rollout, so an explicit cache
 * enablement must prevent the BFF from becoming ready.
 */
export function getMemoryFeatureFlags (
  environment: Record<string, string | undefined> = process.env
): MemoryFeatureFlags {
  if (isEnabled(environment.MEMORY_CACHE_ENABLED)) {
    throw new MemoryFeatureConfigurationError()
  }

  return {
    persistentMemoryEnabled: isEnabled(environment.PERSISTENT_MEMORY_ENABLED),
    sessionFactEnabled: isEnabled(environment.SESSION_FACT_ENABLED)
  }
}

export function shouldUsePersistentMemory (
  isAuthenticated: boolean,
  environment?: Record<string, string | undefined>
): boolean {
  const flags = getMemoryFeatureFlags(environment)
  return isAuthenticated && flags.persistentMemoryEnabled
}
