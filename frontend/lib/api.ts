import type {
  BasketLine,
  BasketOptimizationResponse,
  PriceHistoryPoint,
  SearchParams,
  SearchResponse,
  StatsResponse,
} from './types'

const BASE = process.env.NEXT_PUBLIC_API_BASE ?? '/api'

function urlFor(path: string, params?: Record<string, string | number | boolean | undefined>) {
  const search = new URLSearchParams()
  Object.entries(params ?? {}).forEach(([key, value]) => {
    if (value !== undefined) search.set(key, String(value))
  })
  const suffix = search.size ? `?${search.toString()}` : ''
  return `${BASE}${path}${suffix}`
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { cache: 'no-store', ...init })
  if (!response.ok) {
    let detail = `Error ${response.status}`
    try {
      const body = await response.json()
      detail = body.detail ?? detail
    } catch { /* respuesta no JSON */ }
    throw new Error(detail)
  }
  return response.json()
}

export const searchProducts = (params: SearchParams) =>
  request<SearchResponse>(urlFor('/search', {
    q: params.q,
    country: params.country,
    city: params.city,
    max_results: params.max_results,
  }))

export const getPriceHistory = (query: string, limit = 500) =>
  request<{ query: string; count: number; history: PriceHistoryPoint[] }>(
    urlFor('/price-history', { q: query, limit }),
  )

export const getStats = () => request<StatsResponse>(urlFor('/stats'))

export const createAlert = (data: {
  query: string
  target_price: number
  email: string
  store_filter?: string
  note?: string
}) => request<{ status: 'pending_confirmation'; alert_id: number; message: string }>(urlFor('/alerts'), {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(data),
})

export const submitFeedback = (offerLogId: number, useful: boolean) =>
  request<{ status: string }>(urlFor('/feedback'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ offer_log_id: offerLogId, useful }),
  })

export const optimizeBasket = (data: {
  lines: BasketLine[]
  country: string
  city?: string
  max_stores: number
  shipping_costs: Record<string, number>
}) => request<BasketOptimizationResponse>(urlFor('/basket/optimize'), {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(data),
})

export const getHealth = () => request<{
  status: string
  version: string
  database: boolean
  playwright: boolean
  redis: boolean
  ranking_mode: string
}>(urlFor('/health'))

export const searchAsync = (params: SearchParams) =>
  request<{ task_id: string; status: string; result?: SearchResponse }>(
    urlFor('/search/async', {
      q: params.q,
      country: params.country,
      city: params.city,
      max_results: params.max_results,
    }),
    { method: 'POST' },
  )

export const getTaskResult = (taskId: string) =>
  request<{ state: string; meta: Record<string, unknown>; result?: SearchResponse }>(
    urlFor(`/search/result/${taskId}`),
  )

export const getFeatureImportance = () =>
  request<{ feature_importance: Record<string, number> }>(urlFor('/feature-importance'))

export const getRankingStatus = () =>
  request<{
    status: { mode: 'heuristic' | 'feedback_model'; ndcg_at_5?: number }
    feature_importance: Record<string, number>
  }>(urlFor('/ranking/status'))
