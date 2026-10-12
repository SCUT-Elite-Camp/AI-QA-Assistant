<script setup lang="ts">
import DataPipeline from '../components/pipeline/DataPipeline.vue'
</script>

<template>
  <div class="pipeline-page-container">
    <DataPipeline />
  </div>
</template>

<style scoped>
.pipeline-page-container {
  width: 100%;
  max-width: 1420px;
  margin: 0 auto;
  padding: 32px 48px 56px 48px;
  min-height: 100vh;
  background-color: #fafaf8;
}

@media (max-width: 1024px) {
  .pipeline-page-container {
    padding: 24px;
  }
}
</style>
