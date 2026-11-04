import { createApp } from 'vue'
import App from './App.vue'
import './styles.css'
import './auth-pages.css'
import { initializeDesktopSession } from './utils/desktopSession.js'

initializeDesktopSession().catch(error => console.error(error.message)).finally(() => createApp(App).mount('#app'))
