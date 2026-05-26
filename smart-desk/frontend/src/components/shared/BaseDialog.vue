<template>
  <div v-if="modelValue" class="overlay" @click.self="close" @keydown.escape="close">
    <div class="dialog card" role="dialog">
      <h2>{{ title }}</h2>
      <slot></slot>
      <div class="dialog-actions" v-if="$slots.actions">
        <slot name="actions"></slot>
      </div>
    </div>
  </div>
</template>

<script setup>
defineProps({
  modelValue: { type: Boolean, default: false },
  title: { type: String, default: '' },
})

const emit = defineEmits(['update:modelValue'])

function close() {
  emit('update:modelValue', false)
}
</script>
