'use client'

import { useState } from 'react'
import { AlertTriangle, ExternalLink, Star, ThumbsDown, ThumbsUp, TrendingDown, TrendingUp, Truck } from 'lucide-react'
import { clsx } from 'clsx'
import type { ProductOffer } from '@/lib/types'
import { submitFeedback } from '@/lib/api'

function formatCLP(value: number | null): string {
  if (value === null) return 'Sin precio'
  return new Intl.NumberFormat('es-CL', {
    style: 'currency', currency: 'CLP', maximumFractionDigits: 0,
  }).format(value)
}

function formatUnitPrice(offer: ProductOffer): string | null {
  if (!offer.unit_price || !offer.unit) return null
  const value = new Intl.NumberFormat('es-CL', {
    style: 'currency', currency: 'CLP', maximumFractionDigits: offer.unit_price < 100 ? 1 : 0,
  }).format(offer.unit_price)
  return `${value} / ${offer.unit === 'u' ? 'unidad' : offer.unit}`
}

const STORE_COLORS: Record<string, string> = {
  Sodimac: 'bg-orange-100 text-orange-700',
  Easy: 'bg-green-100 text-green-700',
  Falabella: 'bg-pink-100 text-pink-700',
  Paris: 'bg-indigo-100 text-indigo-700',
  Construmart: 'bg-yellow-100 text-yellow-700',
  MercadoLibre: 'bg-blue-100 text-blue-700',
}

interface Props {
  offer: ProductOffer
  isBest?: boolean
  rank?: number
}

export default function ProductCard({ offer, isBest, rank }: Props) {
  const [feedback, setFeedback] = useState<'useful' | 'not_useful' | 'error' | null>(null)
  const anomalyHigh = offer.anomaly_flag === 'precio_muy_alto'
  const anomalyLow = offer.anomaly_flag === 'precio_muy_bajo'
  const store = offer.store ?? 'Tienda no identificada'
  const storeColor = STORE_COLORS[store] ?? 'bg-gray-100 text-gray-700'
  const unitPrice = formatUnitPrice(offer)
  const specMismatch = offer.spec_match === 'mismatch'
  const showSeller = offer.seller && offer.seller.toLowerCase() !== store.toLowerCase()

  async function rate(useful: boolean) {
    if (!offer.offer_log_id) return
    try {
      await submitFeedback(offer.offer_log_id, useful)
      setFeedback(useful ? 'useful' : 'not_useful')
    } catch {
      setFeedback('error')
    }
  }

  return (
    <article className={clsx(
      'card flex flex-col gap-3 relative transition-shadow hover:shadow-md',
      isBest && 'ring-2 ring-success-600 ring-offset-1',
      (anomalyHigh || anomalyLow) && !isBest && 'border-amber-200',
    )}>
      {rank !== undefined && (
        <span className="absolute -top-2 -left-2 w-7 h-7 rounded-full bg-brand-600 text-white text-xs font-black flex items-center justify-center shadow">{rank}</span>
      )}
      {isBest && <div className="absolute -top-2 right-3 badge badge-green text-xs">Mejor opción</div>}

      <div>
        <span className={clsx('badge text-xs mb-1.5', storeColor)}>{store}</span>
        <p className="font-semibold text-sm leading-tight text-gray-800 line-clamp-2">{offer.title}</p>
        {showSeller && <p className="text-xs text-gray-400 mt-0.5">Vendido por {offer.seller}</p>}
      </div>

      <div>
        <p className={clsx('text-2xl font-black', isBest ? 'text-success-600' : 'text-brand-600')}>
          {formatCLP(offer.extracted_price)}
        </p>
        {unitPrice && <p className="text-xs font-semibold text-gray-500">{unitPrice}</p>}
        {offer.price_vs_avg_pct !== null && (
          <p className={clsx('text-xs font-semibold flex items-center gap-0.5 mt-0.5', offer.price_vs_avg_pct < 0 ? 'text-green-600' : 'text-red-500')}>
            {offer.price_vs_avg_pct < 0 ? <TrendingDown className="w-3 h-3" /> : <TrendingUp className="w-3 h-3" />}
            {Math.abs(offer.price_vs_avg_pct).toFixed(1)}% vs. promedio comparable
          </p>
        )}
      </div>

      <div className="flex flex-wrap gap-1.5 text-xs">
        {offer.free_shipping && <span className="badge badge-purple"><Truck className="w-3 h-3" /> Envío gratis</span>}
        {offer.rating !== null && (
          <span className="badge badge-blue"><Star className="w-3 h-3" /> {offer.rating.toFixed(1)}{offer.reviews !== null && ` (${offer.reviews})`}</span>
        )}
        {specMismatch && (
          <span className="badge badge-orange"><AlertTriangle className="w-3 h-3" /> Medida distinta</span>
        )}
        {(anomalyHigh || anomalyLow) && (
          <span className="badge badge-orange"><AlertTriangle className="w-3 h-3" /> Confirmar precio atípico</span>
        )}
        {offer.ml_score !== null && <span className="badge badge-blue">Score {offer.ml_score}</span>}
      </div>

      {offer.delivery && <p className="text-xs text-gray-400 truncate">{offer.delivery}</p>}
      {offer.recommendation && <p className="text-xs text-gray-500">{offer.recommendation}</p>}

      {offer.offer_log_id && feedback === null && (
        <div className="flex items-center gap-2 text-xs text-gray-400">
          <span>¿Resultado útil?</span>
          <button type="button" aria-label="Resultado útil" className="hover:text-green-700" onClick={() => rate(true)}><ThumbsUp className="w-4 h-4" /></button>
          <button type="button" aria-label="Resultado no útil" className="hover:text-red-600" onClick={() => rate(false)}><ThumbsDown className="w-4 h-4" /></button>
        </div>
      )}
      {feedback && feedback !== 'error' && <p className="text-xs text-green-700">Gracias. Tu evaluación mejora el ranking.</p>}
      {feedback === 'error' && <p className="text-xs text-red-600">No fue posible registrar la evaluación.</p>}

      {offer.link ? (
        <a href={offer.link} target="_blank" rel="noopener noreferrer"
          className={clsx('mt-auto btn-primary justify-center text-sm py-2', isBest && 'bg-success-600 hover:bg-success-700')}>
          <ExternalLink className="w-4 h-4" /> Ver en la tienda
        </a>
      ) : <span className="mt-auto text-xs text-gray-300 text-center py-2">Sin enlace disponible</span>}
    </article>
  )
}
