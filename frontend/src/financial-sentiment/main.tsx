import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import FinancialSentiment from './FinancialSentiment'
import './financial-sentiment.css'

const root = document.getElementById('financial-sentiment-root')
if (!root) throw new Error('Financial Sentiment Using Prices root element is missing')

createRoot(root).render(
  <StrictMode>
    <FinancialSentiment />
  </StrictMode>,
)
