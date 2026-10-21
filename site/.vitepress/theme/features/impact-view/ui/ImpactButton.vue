<!-- beadloom:generated version=9.0.0 sha256=1d44f25d8eb2dbb000370fe973a98d94fe5f9166d2f9f87b0f2e60a30eecfa96; written by `beadloom docs site`, a change belongs in .beadloom/site/.vitepress/theme/features/impact-view/ui/ImpactButton.vue -->
<script setup>
// The toolbar's switch between the neighbourhood and the impact mode.

defineProps({
  active: { type: Boolean, default: false },
});
const emit = defineEmits(["toggle"]);
</script>

<template>
  <button
    type="button"
    class="bl-impact-button"
    :aria-pressed="active"
    aria-label="Impact"
    title="Impact: everything that depends on the selected node"
    @click="emit('toggle')"
  >
    Impact
  </button>
</template>

<style scoped>
.bl-impact-button {
  padding: 3px 10px;
  border: 1px solid var(--vp-c-divider);
  border-radius: 6px;
  background: var(--vp-c-bg-soft);
  color: var(--vp-c-text-1);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}
.bl-impact-button:hover,
.bl-impact-button[aria-pressed="true"] {
  border-color: var(--vp-c-brand-1);
  color: var(--vp-c-brand-1);
}
</style>
