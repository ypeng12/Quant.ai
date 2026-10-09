export type SourceId = 'news' | 'futu' | 'prices' | 'sec' | 'x'

export interface SourceCoverage {
  id: SourceId
  name: string
  records: number | null
  status: string
  detail: string
}

export interface LabStatus {
  project: string
  mode: string
  audit_date: string
  model_status: string
  evaluation_status: string
  sources: SourceCoverage[]
  current_stage: string
  next_stage: string
  plan_url?: string
}

export interface AuditEvent {
  id: string
  symbols: string[]
  title: string
  published_at: string | null
  source: string
  has_body: boolean
  received_at: string | null
}

export interface EventResponse {
  items: AuditEvent[]
  total: number
}

const API_ROOT = '/api/research/signal-lab'

async function request<T>(path: string, signal: AbortSignal): Promise<T> {
  const response = await fetch(`${API_ROOT}${path}`, {
    signal: AbortSignal.any([signal, AbortSignal.timeout(12_000)]),
    headers: { Accept: 'application/json' },
  })
  if (!response.ok) throw new Error(`The research API returned HTTP ${response.status}.`)
  const contentType = response.headers.get('content-type') ?? ''
  if (!contentType.includes('application/json')) {
    throw new Error('The research API did not return JSON. Check that the local research service is running.')
  }
  return response.json() as Promise<T>
}

export async function getStatus(signal: AbortSignal): Promise<LabStatus> {
  const status = await request<LabStatus>('/status', signal)
  if (!status || typeof status.project !== 'string' || !Array.isArray(status.sources)) {
    throw new Error('The research API returned an unexpected status format.')
  }
  return status
}

export async function getEvents(source: 'news' | 'futu', symbol: string, signal: AbortSignal): Promise<EventResponse> {
  const query = new URLSearchParams({ source, limit: '8' })
  if (symbol) query.set('symbol', symbol)
  const data = await request<EventResponse>(`/events?${query}`, signal)
  if (!data || !Array.isArray(data.items) || typeof data.total !== 'number') {
    throw new Error('The research API returned an unexpected event format.')
  }
  return data
}

export function errorMessage(error: unknown): string {
  if (error instanceof Error && error.name === 'TimeoutError') return 'The research API took too long to respond. Try again.'
  if (error instanceof TypeError) return 'The research API is unavailable. Check the local research service and try again.'
  return error instanceof Error ? error.message : 'The research data could not be loaded.'
}
