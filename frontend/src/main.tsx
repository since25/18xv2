import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import { VisualThemeProvider } from './theme'
import './index.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <VisualThemeProvider>
      <App />
    </VisualThemeProvider>
  </StrictMode>,
)
