'use client'

import { useQuery } from '@tanstack/react-query'
import { LineChart as LineIcon, Loader2 } from 'lucide-react'
import {
  CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { getPriceIndex } from '@/lib/api'
import { formatCLP, formatUnitPrice, unitLabel } from '@/lib/format'

interface Props {
  query: string
  days?: number
  height?: number
}

/** Índice diario del catálogo: mínimo y mediana de las ofertas comparables. */
export default function PriceIndexChart({ query, days = 30, height = 260 }: Props) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['price-index', query, days],
    queryFn: () => getPriceIndex(query, days),
    enabled: query.trim().length >= 2,
    staleTime: 5 * 60 * 1000,
  })

  if (isLoading) {
    return (
      <div className="card flex items-center justify-center py-10">
        <Loader2 className="w-6 h-6 text-brand-600 animate-spin" />
      </div>
    )
  }
  if (isError || !data) return null

  const byUnit = data.unit !== null && data.series.some(point => point.min_unit_price !== null)
  const chartData = data.series.map(point => ({
    date: point.date,
    Mínimo: byUnit ? point.min_unit_price : point.min_price,
    Mediana: byUnit ? point.median_unit_price : point.median_price,
    ofertas: point.offers,
  }))
  const last = data.series[data.series.length - 1]
  const first = data.series[0]
  const lastValue = last ? (byUnit ? last.min_unit_price : last.min_price) : null
  const firstValue = first ? (byUnit ? first.min_unit_price : first.min_price) : null
  const change = lastValue !== null && firstValue ? ((lastValue - firstValue) / firstValue) * 100 : null
  const format = (value: number | null) => (byUnit ? formatUnitPrice(value, data.unit) ?? '—' : formatCLP(value))

  return (
    <section className="card space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="font-bold text-gray-700 flex items-center gap-2">
          <LineIcon className="w-4 h-4 text-brand-600" />
          Índice de precios {byUnit ? `por ${unitLabel(data.unit)}` : 'por envase'}
          <span className="text-gray-400 font-normal text-sm">· últimos {days} días</span>
        </h2>
        {lastValue !== null && (
          <p className="text-sm text-gray-500">
            Mínimo actual <strong className="text-brand-900">{format(lastValue)}</strong>
            {change !== null && data.series.length > 1 && (
              <span className={change <= 0 ? 'text-green-700 ml-2' : 'text-red-600 ml-2'}>
                {change > 0 ? '+' : ''}{change.toFixed(1)}% en el período
              </span>
            )}
          </p>
        )}
      </div>

      {data.series.length === 0 ? (
        <p className="text-sm text-gray-400 py-6 text-center">
          Aún no hay observaciones del catálogo para esta búsqueda.
        </p>
      ) : (
        <>
          <ResponsiveContainer width="100%" height={height}>
            <LineChart data={chartData} margin={{ top: 5, right: 16, bottom: 5, left: 8 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis dataKey="date" tick={{ fontSize: 11 }} />
              <YAxis
                tick={{ fontSize: 11 }}
                tickFormatter={value => (byUnit ? `$${Math.round(Number(value))}` : `$${(Number(value) / 1000).toFixed(0)}k`)}
                domain={['auto', 'auto']}
              />
              <Tooltip formatter={value => format(value === null || value === undefined ? null : Number(value))} />
              <Legend />
              <Line type="monotone" dataKey="Mínimo" stroke="#2e7d32" strokeWidth={2} dot={{ r: 3 }} connectNulls />
              <Line type="monotone" dataKey="Mediana" stroke="#1565c0" strokeWidth={2} dot={{ r: 3 }} connectNulls />
            </LineChart>
          </ResponsiveContainer>
          {data.series.length < 7 && (
            <p className="text-xs text-gray-400">
              La serie se construye con cada actualización del catálogo; con más días se podrán detectar
              tendencias y mejores momentos de compra.
            </p>
          )}
        </>
      )}
    </section>
  )
}
