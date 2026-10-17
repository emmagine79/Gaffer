import '@fontsource-variable/archivo/wdth.css'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import { readSurface } from './app/surface'
import './styles/tokens.css'
import './styles/base.css'
import './styles/glass.css'

// Set before the first paint so each surface lays out right from the start.
document.documentElement.dataset.surface = readSurface()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
