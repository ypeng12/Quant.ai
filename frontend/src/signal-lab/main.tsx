import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import SignalLab from './SignalLab'
import './signal-lab.css'

const root = document.getElementById('signal-lab-root')
if (!root) throw new Error('Signal Lab root element is missing')

createRoot(root).render(
  <StrictMode>
    <SignalLab />
  </StrictMode>,
)
