import { describe, expect, it } from 'vitest'
import {
  MemoryFeatureConfigurationError,
  getMemoryFeatureFlags,
  shouldUsePersistentMemory
} from '../../server/utils/memoryFeatureFlags'
import { createSafeMemoryLogPayload } from '../../server/utils/logger'
import {
  getMetrics,
  recordMemoryCompaction,
  recordMemoryDuration,
  recordMemoryFact,
  recordMemoryFallback,
  recordMemoryResolve,
  resetMetrics
} from '../../server/utils/metrics'

describe('Memory feature flags', () => {
  it('defaults closed and treats unknown booleans as disabled', () => {
    expect(getMemoryFeatureFlags({})).toEqual({
      persistentMemoryEnabled: false,
      sessionFactEnabled: false
    })
    expect(getMemoryFeatureFlags({
      PERSISTENT_MEMORY_ENABLED: 'sometimes',
      SESSION_FACT_ENABLED: '0'
    })).toEqual({
      persistentMemoryEnabled: false,
      sessionFactEnabled: false
    })
  })

  it('enables only authenticated persistent Memory and rejects cache configuration', () => {
    const environment = {
      PERSISTENT_MEMORY_ENABLED: 'true',
      SESSION_FACT_ENABLED: 'yes'
    }
    expect(getMemoryFeatureFlags(environment)).toEqual({
      persistentMemoryEnabled: true,
      sessionFactEnabled: true
    })
    expect(shouldUsePersistentMemory(false, environment)).toBe(false)
    expect(shouldUsePersistentMemory(true, environment)).toBe(true)
    expect(() => shouldUsePersistentMemory(false, { MEMORY_CACHE_ENABLED: 'on' }))
      .toThrow(MemoryFeatureConfigurationError)
    expect(() => getMemoryFeatureFlags({ MEMORY_CACHE_ENABLED: 'on' }))
      .toThrow(MemoryFeatureConfigurationError)
    expect(() => getMemoryFeatureFlags({ MEMORY_CACHE_ENABLED: 'on' }))
      .toThrow('memory_cache_not_supported')
  })

  it('keeps Memory metric and log payloads finite and content-free', () => {
    resetMetrics()
    recordMemoryResolve('trusted_context', 'success')
    recordMemoryCompaction('planned')
    recordMemoryFact('proposed', 'success')
    recordMemoryFallback('agent_disabled')
    recordMemoryDuration('context', 12)

    expect(getMetrics().memory).toEqual(expect.objectContaining({
      compaction: { planned: 1 },
      fact: { 'proposed:success': 1 },
      fallback: { agent_disabled: 1 },
      resolve: { 'trusted_context:success': 1 }
    }))
    expect(createSafeMemoryLogPayload({
      event: 'memory_fact',
      action: 'proposed',
      outcome: 'success',
      query: 'do not log this',
      value: 'do not log this either'
    })).toEqual({ event: 'memory_fact', action: 'proposed', outcome: 'success' })
  })
})
