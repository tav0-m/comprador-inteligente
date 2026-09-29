export interface ProductOffer {
  title: string
  store: string | null
  source: string
  price_text: string | null
  extracted_price: number | null
  currency: string
  delivery: string | null
  availability: string | null
  link: string | null
  thumbnail: string | null
  free_shipping: boolean | null
  rating: number | null
  reviews: number | null
  ml_score: number | null
  score: number | null
  recommendation: string | null
  anomaly_flag: 'ok' | 'precio_muy_alto' | 'precio_muy_bajo' | 'sin_precio' | null
  price_vs_avg_pct: number | null
  price_percentile: number | null
  offer_log_id: number | null
  seller?: string | null
  relevance?: number | null
  spec_match?: 'ok' | 'unknown' | 'mismatch' | null
  pack_quantity?: number | null
  unit?: string | null
  unit_price?: number | null
}

export interface SearchResponse {
  query: string
  country: string
  city: string | null
  total_results: number
  offers: ProductOffer[]
  best_price: number | null
  avg_price: number | null
  price_spread_pct: number | null
  anomaly_count: number
  comparable_count?: number
  unit?: string | null
  best_unit_price?: number | null
  search_id: number | null
  elapsed_ms: number | null
}

export interface PriceHistoryPoint {
  date: string
  store: string
  price: number
  source: string
  link: string | null
}

export interface StatsResponse {
  total_searches: number
  total_offers_logged: number
  avg_score: number | null
  top_queries: { query: string; count: number }[]
  stores_seen: string[]
  cache: { available: boolean; keys: number }
}

export interface SearchParams {
  q: string
  country: string
  city?: string
  max_results: number
}

export interface BasketLine {
  query: string
  quantity: number
  unit: string
}

export interface BasketSelection {
  query: string
  quantity: number
  unit: string
  offer: ProductOffer
  packs?: number | null
  line_total: number
}

export interface BasketOptimizationResponse {
  selections: BasketSelection[]
  stores: string[]
  merchandise_total: number
  shipping_total: number
  total_cost: number
  single_store_baseline: number | null
  estimated_savings: number | null
  assumptions: string[]
  elapsed_ms: number
}
