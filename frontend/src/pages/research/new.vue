<script setup lang="ts">
import { onBeforeMount } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()

onBeforeMount(() => {
  router.replace('/?research=1')
})
</script>

<template>
  <div aria-hidden="true" />
</template>
