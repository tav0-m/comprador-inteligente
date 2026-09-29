'use client'
import { useQuery }  from '@tanstack/react-query'
import { getStats, getRankingStatus } from '@/lib/api'
import { Loader2, BarChart2, Database, Wifi, WifiOff } from 'lucide-react'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts'

export default function StatsPage() {
  const { data: stats, isLoading: loadingStats } = useQuery({
    queryKey: ['stats'],
    queryFn:  getStats,
    refetchInterval: 30_000,
  })
  const { data: ranking, isLoading: loadingFI } = useQuery({
    queryKey: ['ranking-status'],
    queryFn:  getRankingStatus,
  })

  const topQueries = stats?.top_queries ?? []
  const feats = Object.entries(ranking?.feature_importance ?? {})
    .map(([k,v]) => ({ name: k, value: Math.round(v as number) }))
    .sort((a,b) => b.value - a.value)

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <BarChart2 className="w-6 h-6 text-brand-600" />
        <h1 className="text-2xl font-black text-brand-900">Estadísticas del sistema</h1>
      </div>

      {loadingStats
        ? <div className="flex items-center justify-center py-16"><Loader2 className="w-8 h-8 text-brand-600 animate-spin" /></div>
        : stats && (
          <>
            {/* KPIs */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              {[
                { label:'🔍 Búsquedas',  value: stats.total_searches.toLocaleString() },
                { label:'📦 Ofertas',     value: stats.total_offers_logged.toLocaleString() },
                { label:'🤖 Score prom.', value: stats.avg_score ? stats.avg_score.toFixed(1) : '—' },
                { label:'💾 Cache',       value: `${stats.cache?.keys ?? 0} keys` },
              ].map(m => (
                <div key={m.label} className="card text-center">
                  <p className="text-xs text-gray-500 mb-1">{m.label}</p>
                  <p className="text-2xl font-black text-brand-900">{m.value}</p>
                </div>
              ))}
            </div>

            {/* Redis status */}
            <div className="card flex items-center gap-3">
              {stats.cache?.available
                ? <><Wifi   className="w-5 h-5 text-green-600" /><span className="font-semibold text-green-700">Redis conectado</span><span className="text-gray-400 text-sm">— {stats.cache.keys} claves en caché</span></>
                : <><WifiOff className="w-5 h-5 text-red-500" /> <span className="font-semibold text-red-600">Redis no disponible</span><span className="text-gray-400 text-sm">— Búsquedas sin caché</span></>
              }
            </div>

            {/* Stores seen */}
            {stats.stores_seen?.length > 0 && (
              <div className="card">
                <p className="font-semibold text-gray-700 mb-2 flex items-center gap-2">
                  <Database className="w-4 h-4" /> Tiendas en base de datos
                </p>
                <div className="flex flex-wrap gap-2">
                  {stats.stores_seen.map(s => (
                    <span key={s} className="badge badge-blue">{s}</span>
                  ))}
                </div>
              </div>
            )}

            {/* Top queries chart */}
            {topQueries.length > 0 && (
              <div className="card">
                <p className="font-semibold text-gray-700 mb-4">🔥 Búsquedas más frecuentes</p>
                <ResponsiveContainer width="100%" height={220}>
                  <BarChart data={[...topQueries].sort((a,b) => b.count - a.count).slice(0,10)}
                            layout="vertical" margin={{ left:10, right:20 }}>
                    <XAxis type="number" tick={{ fontSize:11 }} />
                    <YAxis dataKey="query" type="category" width={120} tick={{ fontSize:11 }} />
                    <Tooltip />
                    <Bar dataKey="count" radius={[0,6,6,0]}>
                      {topQueries.map((_,i) => (
                        <Cell key={i} fill={`hsl(${210 + i*15}, 70%, ${50 + i*3}%)`} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </>
        )
      }

      {/* Feature importance */}
      <div className="card">
        <p className="font-semibold text-gray-700 mb-1">Factores del ranking</p>
        <p className="text-xs text-gray-500 mb-4">
          Modo actual: <strong>{ranking?.status.mode === 'feedback_model' ? 'modelo entrenado con feedback' : 'heurística auditable'}</strong>
          {ranking?.status.ndcg_at_5 !== undefined && ` · NDCG@5: ${ranking.status.ndcg_at_5}`}
        </p>
        {loadingFI
          ? <Loader2 className="w-5 h-5 animate-spin text-brand-600" />
          : feats.length === 0
            ? <p className="text-gray-400 text-sm">No disponible</p>
            : (
              <ResponsiveContainer width="100%" height={300}>
                <BarChart data={feats} layout="vertical" margin={{ left:20, right:20 }}>
                  <XAxis type="number" tick={{ fontSize:11 }} />
                  <YAxis dataKey="name" type="category" width={130} tick={{ fontSize:11 }} />
                  <Tooltip />
                  <Bar dataKey="value" fill="#1565c0" radius={[0,6,6,0]} />
                </BarChart>
              </ResponsiveContainer>
            )
        }
      </div>
    </div>
  )
}
