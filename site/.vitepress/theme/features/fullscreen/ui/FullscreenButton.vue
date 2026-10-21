<!-- beadloom:generated version=9.0.0 sha256=eb059e894aa6ccd3b7fbaf097bd371446af1dfa5b0725d32c2c736495b604326; written by `beadloom docs site`, a change belongs in .beadloom/site/.vitepress/theme/features/fullscreen/ui/FullscreenButton.vue -->
<script setup>
// The full-screen button of the viewer's toolbar.

defineProps({
  active: { type: Boolean, default: false },
});
const emit = defineEmits(["toggle"]);
</script>

<template>
  <button
    type="button"
    class="bl-fullscreen"
    :aria-pressed="active"
    :aria-label="active ? 'Exit full screen' : 'Full screen'"
    title="Full screen (f)"
    @click="emit('toggle')"
  >
    {{ active ? "Exit full screen" : "Full screen" }}
  </button>
</template>

<style scoped>
.bl-fullscreen {
  padding: 3px 10px;
  border: 1px solid var(--vp-c-divider);
  border-radius: 6px;
  background: var(--vp-c-bg-soft);
  color: var(--vp-c-text-1);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}
.bl-fullscreen:hover {
  border-color: var(--vp-c-brand-1);
}
</style>
