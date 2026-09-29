'use client'
import { useState }          from 'react'
import { useQuery }           from '@tanstack/react-query'
import { getPriceHistory }    from '@/lib/api'
import { Loader2, TrendingUp } from 'lucide-react'
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, Legend, ResponsiveContainer,
} from 'recharts'

const STORE_COLORS = ['#1565c0','#2e7d32','#e65100','#6a1b9a','#c62828','#0277bd']

function formatCLP(n: number) {
  return new Intl.NumberFormat('es-CL', { style:'currency', currency:'CLP', maximumFractionDigits:0 }).format(n)
}

export default function HistoryPage() {
  const [q, setQ] = useState('martillo')
  const [search, setSearch] = useState('martillo')

  const { data, isLoading, isError } = useQuery({
    queryKey: ['history', search],
    queryFn:  () => getPriceHistory(search, 500),
    enabled:  !!search,
  })

  const history  = data?.history ?? []
  const stores   = [...new Set(history.map(h => h.store))]

  // Build chart data: group by date, one key per store
  const byDate: Record<string, Record<string, number>> = {}
  history.forEach(h => {
    const day = h.date.split('T')[0]
    if (!byDate[day]) byDate[day] = {}
    byDate[day][h.store] = h.price
  })
  const chartData = Object.entries(byDate)
    .sort(([a],[b]) => a.localeCompare(b))
    .map(([date, prices]) => ({ date, ...prices }))

  // Summary table per store
  const storeSummary = stores.map(s => {
    const prices = history.filter(h => h.store === s).map(h => h.price)
    return {
      store: s,
      min:   Math.min(...prices),
      max:   Math.max(...prices),
      avg:   prices.reduce((a,b) => a+b, 0) / prices.length,
      count: prices.length,
    }
  }).sort((a,b) => a.avg - b.avg)

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <TrendingUp className="w-6 h-6 text-brand-600" />
        <h1 className="text-2xl font-black text-brand-900">Historial de precios</h1>
      </div>

      {/* Search */}
      <div className="card flex gap-2">
        <input
          className="input flex-1"
          placeholder="Producto a consultar..."
          value={q}
          onChange={e => setQ(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && setSearch(q)}
        />
        <button className="btn-primary" onClick={() => setSearch(q)}>Ver historial</button>
      </div>

      {isLoading && (
        <div className="flex items-center justify-center py-20">
          <Loader2 className="w-8 h-8 text-brand-600 animate-spin" />
        </div>
      )}

      {isError && (
        <div className="card border-red-200 bg-red-50 text-red-700 text-sm p-4">
          Error al cargar historial. Verifica que la API esté disponible.
        </div>
      )}

      {!isLoading && history.length === 0 && (
        <div className="text-center py-16 text-gray-400">
          <TrendingUp className="w-12 h-12 mx-auto mb-3 opacity-30" />
          <p>Sin historial para <strong className="text-gray-600">{search}</strong>.</p>
          <p className="text-sm mt-1">Realiza búsquedas del mismo producto para generar historial.</p>
        </div>
      )}

      {chartData.length > 0 && (
        <>
          <div className="card">
            <p className="font-bold text-gray-700 mb-4">
              Evolución de precios — <span className="text-brand-600">{search}</span>
              <span className="text-gray-400 font-normal ml-2 text-sm">({history.length} registros)</span>
            </p>
            <ResponsiveContainer width="100%" height={340}>
              <LineChart data={chartData} margin={{ top:5, right:20, bottom:5, left:10 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                <XAxis dataKey="date" tick={{ fontSize:11 }} />
                <YAxis
                  tickFormatter={v => `$${(v/1000).toFixed(0)}k`}
                  tick={{ fontSize:11 }}
                />
                <Tooltip formatter={value => formatCLP(Number(value ?? 0))} />
                <Legend />
                {stores.map((s, i) => (
                  <Line
                    key={s} type="monotone" dataKey={s}
                    stroke={STORE_COLORS[i % STORE_COLORS.length]}
                    strokeWidth={2} dot={{ r:3 }}
                    connectNulls
                  />
                ))}
              </LineChart>
            </ResponsiveContainer>
          </div>

          {/* Summary table */}
          <div className="card overflow-x-auto">
            <p className="font-bold text-gray-700 mb-3">Resumen por tienda</p>
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-100">
                  {['Tienda','Registros','Mínimo','Promedio','Máximo'].map(h => (
                    <th key={h} className="text-left py-2 px-3 text-gray-500 font-semibold text-xs uppercase">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {storeSummary.map((s, i) => (
                  <tr key={s.store} className={i % 2 === 0 ? 'bg-gray-50' : ''}>
                    <td className="py-2 px-3 font-semibold text-gray-700">{s.store}</td>
                    <td className="py-2 px-3 text-gray-500">{s.count}</td>
                    <td className="py-2 px-3 text-green-700 font-bold">{formatCLP(s.min)}</td>
                    <td className="py-2 px-3 text-brand-600 font-bold">{formatCLP(s.avg)}</td>
                    <td className="py-2 px-3 text-red-600 font-bold">{formatCLP(s.max)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  )
}
