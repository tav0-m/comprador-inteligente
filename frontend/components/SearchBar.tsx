'use client'
import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { Search, MapPin, Globe } from 'lucide-react'

const COUNTRIES = ['cl', 'ar', 'mx', 'co', 'pe']
const EXAMPLES  = ['martillo', 'cemento 25 kg', 'taladro percutor', 'tornillos 3 pulgadas', 'plancha OSB 9mm']

export default function SearchBar({ defaultQuery = '', defaultCountry = 'cl' }: {
  defaultQuery?:   string
  defaultCountry?: string
}) {
  const router = useRouter()
  const [q,       setQ]       = useState(defaultQuery)
  const [country, setCountry] = useState(defaultCountry)
  const [city,    setCity]    = useState('Santiago')
  const [maxRes,  setMaxRes]  = useState(20)

  function submit(e: React.FormEvent) {
    e.preventDefault()
    if (!q.trim()) return
    const params = new URLSearchParams({ q: q.trim(), country, city, max_results: String(maxRes) })
    router.push(`/results?${params}`)
  }

  return (
    <form onSubmit={submit} className="w-full space-y-3">
      {/* Main search row */}
      <div className="flex gap-2">
        <div className="relative flex-1">
          <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-400" />
          <input
            className="input pl-11 text-base h-12"
            placeholder="Busca un producto... ej: martillo, cemento 25 kg"
            value={q}
            onChange={e => setQ(e.target.value)}
            required
          />
        </div>
        <button type="submit" className="btn-primary px-6 h-12 text-base">
          <Search className="w-5 h-5" />
          Buscar
        </button>
      </div>

      {/* Filters row */}
      <div className="flex flex-wrap gap-2">
        <div className="flex items-center gap-1.5">
          <Globe className="w-4 h-4 text-gray-400" />
          <select
            className="input py-1.5 pr-8 text-sm w-auto"
            value={country}
            onChange={e => setCountry(e.target.value)}
          >
            {COUNTRIES.map(c => <option key={c} value={c}>{c.toUpperCase()}</option>)}
          </select>
        </div>
        <div className="flex items-center gap-1.5">
          <MapPin className="w-4 h-4 text-gray-400" />
          <input
            className="input py-1.5 text-sm w-32"
            placeholder="Ciudad"
            value={city}
            onChange={e => setCity(e.target.value)}
          />
        </div>
        <div className="flex items-center gap-1.5">
          <span className="text-sm text-gray-500">Máx.</span>
          <select
            className="input py-1.5 pr-8 text-sm w-auto"
            value={maxRes}
            onChange={e => setMaxRes(Number(e.target.value))}
          >
            {[10, 20, 30, 50].map(n => <option key={n} value={n}>{n} resultados</option>)}
          </select>
        </div>
      </div>

      {/* Quick examples */}
      <div className="flex flex-wrap gap-2">
        <span className="text-xs text-gray-400">Ejemplos:</span>
        {EXAMPLES.map(ex => (
          <button
            key={ex}
            type="button"
            onClick={() => setQ(ex)}
            className="text-xs bg-gray-100 hover:bg-brand-50 hover:text-brand-600
                       text-gray-600 px-2.5 py-1 rounded-full transition-colors"
          >
            {ex}
          </button>
        ))}
      </div>
    </form>
  )
}
