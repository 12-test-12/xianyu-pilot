import { asyncPage } from '../components/asyncPage.js'

// Navigation and the settings shell must preload the same component instances.
export const settingsPages = {
  'settings-system': asyncPage(() => import('../pages/admin/SystemSettingsPage.vue')),
  'settings-ai-cs': asyncPage(() => import('../pages/settings/AiCsSettings.vue')),
  'settings-model': asyncPage(() => import('../pages/admin/ModelSettingsPage.vue')),
  'settings-embedding': asyncPage(() => import('../pages/admin/EmbeddingSettingsPage.vue')),
  'settings-rag': asyncPage(() => import('../pages/admin/RagSettingsPage.vue')),
  'settings-product': asyncPage(() => import('../pages/settings/ProductOpSettings.vue')),
  'settings-about': asyncPage(() => import('../pages/settings/AboutSettings.vue')),
}
