'use client'
import { useSearchParams } from 'next/navigation'
import { useQuery }        from '@tanstack/react-query'
import { Suspense }        from 'react'
import { searchProducts }  from '@/lib/api'
import BestBanner          from '@/components/BestBanner'
import ProductCard         from '@/components/ProductCard'
import SearchBar           from '@/components/SearchBar'
import { Loader2, AlertCircle, ShoppingBag } from 'lucide-react'

function formatCLP(n: number | null) {
  if (!n) return '—'
  return new Intl.NumberFormat('es-CL', { style: 'currency', currency: 'CLP', maximumFractionDigits: 0 }).format(n)
}

function ResultsInner() {
  const sp      = useSearchParams()
  const q       = sp.get('q') ?? ''
  const country = sp.get('country') ?? 'cl'
  const city    = sp.get('city')    ?? undefined
  const maxRes  = Number(sp.get('max_results') ?? 20)

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['search', q, country, city, maxRes],
    queryFn:  () => searchProducts({ q, country, city, max_results: maxRes }),
    enabled:  !!q,
  })

  if (!q) return (
    <div className="text-center py-20 text-gray-400">
      <ShoppingBag className="w-16 h-16 mx-auto mb-4 opacity-30" />
      <p className="text-lg">Realiza una búsqueda desde la página principal</p>
    </div>
  )

  if (isLoading) return (
    <div className="flex flex-col items-center justify-center py-24 gap-4">
      <Loader2 className="w-10 h-10 text-brand-600 animate-spin" />
      <p className="text-gray-600 font-medium">
        Buscando <strong>{q}</strong> en 6 tiendas...
      </p>
      <p className="text-sm text-gray-400">Sodimac · Easy · Falabella · Paris · Construmart · Mercado Libre</p>
    </div>
  )

  if (isError) return (
    <div className="card border-red-200 bg-red-50 flex items-center gap-3 text-red-700">
      <AlertCircle className="w-5 h-5 shrink-0" />
      <div>
        <p className="font-semibold">Error al conectar con la API</p>
        <p className="text-sm opacity-75">{String(error)}</p>
        <p className="text-sm mt-1">Asegúrate de que la API esté corriendo en <code>localhost:8000</code></p>
      </div>
    </div>
  )

  if (!data) return null

  const offers = data.offers ?? []
  if (offers.length === 0) return (
    <div className="text-center py-20 text-gray-400">
      <ShoppingBag className="w-12 h-12 mx-auto mb-3 opacity-30" />
      <p>Sin resultados para <strong className="text-gray-600">{q}</strong>. Intenta otro término.</p>
    </div>
  )

  const best = offers[0]

  return (
    <div className="space-y-6">
      {/* Search refinement bar */}
      <div className="card">
        <SearchBar defaultQuery={q} defaultCountry={country} />
      </div>

      {/* Summary metrics */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[
          { label: '🏆 Mejor precio',   value: formatCLP(data.best_price) },
          { label: '📊 Precio promedio', value: formatCLP(data.avg_price) },
          { label: '📉 Dispersión',       value: data.price_spread_pct ? `${data.price_spread_pct.toFixed(1)}%` : '—' },
          { label: `${data.anomaly_count ? '🔴' : '🟢'} Anomalías`, value: data.anomaly_count },
        ].map(m => (
          <div key={m.label} className="card text-center">
            <p className="text-xs text-gray-500 mb-1">{m.label}</p>
            <p className="text-lg font-black text-brand-900">{m.value}</p>
          </div>
        ))}
      </div>

      {/* Best offer banner */}
      <BestBanner offer={best} />

      {/* Results count */}
      <p className="text-sm text-gray-500">
        <strong className="text-gray-800">{offers.length}</strong> resultados para{' '}
        <strong className="text-brand-600">«{q}»</strong>
      </p>

      {/* Cards grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
        {offers.map((offer, i) => (
          <ProductCard
            key={`${offer.store}-${i}`}
            offer={offer}
            isBest={i === 0}
            rank={i + 1}
          />
        ))}
      </div>
    </div>
  )
}

export default function ResultsPage() {
  return (
    <Suspense fallback={
      <div className="flex items-center justify-center py-20">
        <Loader2 className="w-8 h-8 text-brand-600 animate-spin" />
      </div>
    }>
      <ResultsInner />
    </Suspense>
  )
}
