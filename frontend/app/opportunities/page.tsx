'use client'

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ExternalLink, Loader2, TrendingDown } from 'lucide-react'
import { getOpportunities } from '@/lib/api'
import { formatCLP } from '@/lib/format'

export default function OpportunitiesPage() {
  const [draft, setDraft] = useState('')
  const [query, setQuery] = useState('')
  const [minDrop, setMinDrop] = useState(10)

  const { data, isLoading, isError } = useQuery({
    queryKey: ['opportunities', query, minDrop],
    queryFn: () => getOpportunities({ q: query || undefined, min_drop: minDrop }),
  })

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-black text-brand-900 flex items-center gap-2">
          <TrendingDown className="w-6 h-6 text-green-600" /> Oportunidades de compra
        </h1>
        <p className="text-sm text-gray-500 mt-2 max-w-3xl">
          Productos cuyo precio de hoy está bajo su propia mediana de los últimos 60 días. Cada producto se compara
          consigo mismo, con al menos 5 días de observaciones del catálogo.
        </p>
      </div>

      <form className="card flex flex-wrap gap-2 items-end"
        onSubmit={event => { event.preventDefault(); setQuery(draft.trim()) }}>
        <label className="text-xs font-semibold text-gray-500 flex-1 min-w-[220px]">
          Material (opcional)
          <input className="input mt-1" maxLength={120} placeholder="cemento 25 kg"
            value={draft} onChange={event => setDraft(event.target.value)} />
        </label>
        <label className="text-xs font-semibold text-gray-500">
          Caída mínima
          <select className="input mt-1" value={minDrop} onChange={event => setMinDrop(Number(event.target.value))}>
            {[5, 10, 15, 20, 30].map(value => <option key={value} value={value}>{value}%</option>)}
          </select>
        </label>
        <button className="btn-primary">Buscar</button>
      </form>

      {isLoading && (
        <div className="flex items-center justify-center py-16">
          <Loader2 className="w-8 h-8 text-brand-600 animate-spin" />
        </div>
      )}
      {isError && <div className="card border-red-200 bg-red-50 text-red-700 text-sm">No fue posible cargar las oportunidades.</div>}

      {data && data.opportunities.length === 0 && (
        <div className="card text-center py-12 text-gray-400">
          <TrendingDown className="w-10 h-10 mx-auto mb-3 opacity-30" />
          <p>Sin caídas de al menos {minDrop}% por ahora.</p>
          <p className="text-xs mt-1">
            Las oportunidades aparecen a medida que la ingesta acumula días de precios en el catálogo.
          </p>
        </div>
      )}

      {data && data.opportunities.length > 0 && (
        <div className="card overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left border-b text-xs text-gray-500">
                <th className="py-2">Producto</th><th>Tienda</th><th>Hoy</th><th>Mediana</th><th>Caída</th><th>Días</th><th></th>
              </tr>
            </thead>
            <tbody>
              {data.opportunities.map(item => (
                <tr key={`${item.store}-${item.title}`} className="border-b border-gray-100">
                  <td className="py-3 pr-3">
                    <p className="font-semibold">{item.title}</p>
                    {item.seller && item.seller !== item.store && <p className="text-xs text-gray-400">Vendido por {item.seller}</p>}
                  </td>
                  <td>{item.store}</td>
                  <td className="font-bold text-green-700">{formatCLP(item.current_price)}</td>
                  <td className="text-gray-500">{formatCLP(item.median_price)}</td>
                  <td>
                    <span className="badge badge-green text-xs">-{item.drop_pct.toFixed(1)}%</span>
                    {item.is_window_low && <p className="text-[11px] text-green-700 mt-0.5">Mínimo del período</p>}
                  </td>
                  <td className="text-gray-500">{item.days_observed}</td>
                  <td>
                    {item.link && (
                      <a href={item.link} target="_blank" rel="noopener noreferrer" className="text-brand-600 font-semibold inline-flex items-center gap-1">
                        <ExternalLink className="w-3 h-3" /> Ver
                      </a>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
