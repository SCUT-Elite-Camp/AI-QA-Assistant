<template>
  <div class="research-mode-notice">
    <div class="flex min-w-0 items-start gap-3">
      <span class="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
        <UIcon name="i-lucide-telescope" class="size-4" />
      </span>
      <div class="min-w-0 flex-1">
        <p class="text-sm font-semibold text-highlighted">Deep Research enabled</p>
        <p class="mt-0.5 text-xs leading-5 text-muted">
          Research searches all knowledge base documents you can access. Review and approve the plan before research starts.
        </p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.research-mode-notice {
  margin-top: 0.625rem;
  border: 1px solid color-mix(in srgb, var(--ui-primary) 24%, var(--ui-border));
  border-radius: 0.875rem;
  background: color-mix(in srgb, var(--ui-primary) 5%, var(--ui-bg));
  padding: 0.875rem;
}
</style>
