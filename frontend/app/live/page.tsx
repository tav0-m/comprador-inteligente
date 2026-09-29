'use client'
import { useState, useRef }  from 'react'
import { Zap, Loader2 }      from 'lucide-react'
import BestBanner            from '@/components/BestBanner'
import ProductCard           from '@/components/ProductCard'
import type { ProductOffer } from '@/lib/types'

const API = process.env.NEXT_PUBLIC_API_BASE ?? '/api'

interface StoreResult { store: string; count: number }
interface DoneEvent {
  total:       number
  best_price:  number | null
  avg_price:   number | null
  offers:      ProductOffer[]
}

export default function LivePage() {
  const [q,        setQ]       = useState('martillo')
  const country = 'cl'
  const [maxRes,   setMaxRes]  = useState(20)
  const [running,  setRunning] = useState(false)
  const [stores,   setStores]  = useState<StoreResult[]>([])
  const [expectedStores, setExpectedStores] = useState<string[]>([])
  const [total,    setTotal]   = useState(0)
  const [finalRes, setFinalRes]= useState<DoneEvent | null>(null)
  const [error,    setError]   = useState('')
  const abortRef = useRef<AbortController | null>(null)

  async function startSearch() {
    if (!q.trim()) return
    abortRef.current?.abort()
    abortRef.current = new AbortController()
    setRunning(true); setStores([]); setExpectedStores([]); setTotal(0); setFinalRes(null); setError('')

    const url = `${API}/search/stream?q=${encodeURIComponent(q)}&country=${country}&max_results=${maxRes}`
    try {
      const res = await fetch(url, { signal: abortRef.current.signal })
      const reader = res.body!.getReader()
      const dec    = new TextDecoder()
      let   buf    = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buf += dec.decode(value, { stream: true })
        const lines = buf.split('\n')
        buf = lines.pop() ?? ''
        for (const line of lines) {
          if (!line.startsWith('data:')) continue
          try {
            const ev = JSON.parse(line.slice(5).trim())
            if (ev.type === 'start') {
              setExpectedStores(ev.stores ?? [])
            } else if (ev.type === 'store_result') {
              setStores(prev => {
                const idx = prev.findIndex(s => s.store === ev.store)
                if (idx >= 0) { const n = [...prev]; n[idx].count = ev.count; return n }
                return [...prev, { store: ev.store, count: ev.count }]
              })
            } else if (ev.type === 'done') {
              setFinalRes(ev); setTotal(ev.total)
            } else if (ev.type === 'error') {
              setError(ev.message)
            }
          } catch { /* skip */ }
        }
      }
    } catch (e: unknown) {
      if ((e as Error).name !== 'AbortError') setError(String(e))
    } finally {
      setRunning(false)
    }
  }

  const doneCount = stores.filter(s => s.count >= 0).length
  const storeNames = expectedStores
  const pct = storeNames.length > 0 ? Math.round(doneCount / storeNames.length * 100) : 0

  return (
    <div className="space-y-6 max-w-4xl">
      <div className="flex items-center gap-3">
        <Zap className="w-6 h-6 text-yellow-500" />
        <h1 className="text-2xl font-black text-brand-900">Búsqueda en vivo</h1>
        <span className="badge badge-blue text-xs">SSE Streaming</span>
      </div>
      <p className="text-gray-500 text-sm">
        Los resultados aparecen tienda a tienda en tiempo real sin esperar que todas terminen.
      </p>

      {/* Controls */}
      <div className="card flex flex-wrap gap-2">
        <input className="input flex-1 min-w-48" placeholder="Producto..."
          value={q} onChange={e => setQ(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && !running && startSearch()} />
        <span className="input w-20 text-center" aria-label="Mercado">CL</span>
        <select className="input w-36" value={maxRes} onChange={e => setMaxRes(Number(e.target.value))}>
          {[10,20,30,50].map(n => <option key={n} value={n}>{n} resultados</option>)}
        </select>
        <button
          className={running ? 'btn-secondary' : 'btn-primary'}
          onClick={running ? () => abortRef.current?.abort() : startSearch}
        >
          {running ? <><Loader2 className="w-4 h-4 animate-spin" /> Detener</> : <><Zap className="w-4 h-4" /> Buscar en vivo</>}
        </button>
      </div>

      {/* Progress */}
      {running && (
        <div className="card space-y-3">
          <div className="flex justify-between text-sm text-gray-600">
            <span>Consultando tiendas...</span>
            <span className="font-bold">{pct}%</span>
          </div>
          <div className="w-full bg-gray-100 rounded-full h-2">
            <div className="bg-brand-600 h-2 rounded-full transition-all duration-500"
                 style={{ width: `${pct}%` }} />
          </div>
          <div className="flex flex-wrap gap-2">
            {storeNames.map(s => {
              const r = stores.find(st => st.store === s)
              return (
                <span key={s} className={`badge ${r ? (r.count > 0 ? 'badge-green' : 'badge-orange') : 'bg-gray-100 text-gray-400'}`}>
                  {r ? (r.count > 0 ? '✅' : '⬜') : '⏳'} {s} {r ? `(${r.count})` : ''}
                </span>
              )
            })}
          </div>
        </div>
      )}

      {error && (
        <div className="card border-red-200 bg-red-50 text-red-700 text-sm p-4">{error}</div>
      )}

      {/* Final results */}
      {finalRes && (
        <div className="space-y-4">
          <p className="text-sm font-semibold text-green-700">
            ✅ Búsqueda completada — {total} resultados
          </p>
          {finalRes.offers?.[0] && <BestBanner offer={finalRes.offers[0]} />}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {(finalRes.offers ?? []).map((o, i) => (
              <ProductCard key={i} offer={o} isBest={i === 0} rank={i + 1} />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
