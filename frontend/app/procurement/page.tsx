'use client'

import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { ClipboardList, Loader2, Plus, Trash2 } from 'lucide-react'
import { optimizeBasket } from '@/lib/api'
import type { BasketLine } from '@/lib/types'

function formatCLP(value: number | null) {
  if (value === null) return 'No disponible'
  return new Intl.NumberFormat('es-CL', {
    style: 'currency', currency: 'CLP', maximumFractionDigits: 0,
  }).format(value)
}

const EMPTY_LINE: BasketLine = { query: '', quantity: 1, unit: 'unidad' }

export default function ProcurementPage() {
  const [lines, setLines] = useState<BasketLine[]>([
    { query: 'cemento Portland 25 kg', quantity: 20, unit: 'saco' },
    { query: 'plancha OSB 9.5 mm 1.22 x 2.44 m', quantity: 10, unit: 'plancha' },
  ])
  const [city, setCity] = useState('Santiago')
  const [maxStores, setMaxStores] = useState(3)
  const mutation = useMutation({ mutationFn: optimizeBasket })

  function updateLine(index: number, patch: Partial<BasketLine>) {
    setLines(current => current.map((line, position) => position === index ? {...line, ...patch} : line))
  }

  function submit(event: React.FormEvent) {
    event.preventDefault()
    mutation.mutate({ lines, country: 'cl', city, max_stores: maxStores, shipping_costs: {} })
  }

  const result = mutation.data
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-black text-brand-900 flex items-center gap-2">
          <ClipboardList className="w-6 h-6 text-brand-600" /> Optimizar lista de materiales
        </h1>
        <p className="text-sm text-gray-500 mt-2 max-w-3xl">
          Busca todas las líneas de una obra y encuentra la combinación de proveedores de menor costo.
          Especifica marca, medida, formato y unidad para evitar productos incompatibles.
        </p>
      </div>

      <form onSubmit={submit} className="card space-y-4">
        <div className="space-y-3">
          {lines.map((line, index) => (
            <div key={index} className="grid grid-cols-12 gap-2 items-end">
              <label className="col-span-12 md:col-span-7 text-xs font-semibold text-gray-500">
                Material {index + 1}
                <input className="input mt-1" required minLength={2} maxLength={120}
                  value={line.query} onChange={event => updateLine(index, {query: event.target.value})} />
              </label>
              <label className="col-span-5 md:col-span-2 text-xs font-semibold text-gray-500">
                Cantidad
                <input className="input mt-1" type="number" min="0.01" step="0.01" required
                  value={line.quantity} onChange={event => updateLine(index, {quantity: Number(event.target.value)})} />
              </label>
              <label className="col-span-5 md:col-span-2 text-xs font-semibold text-gray-500">
                Unidad
                <input className="input mt-1" required maxLength={40}
                  value={line.unit} onChange={event => updateLine(index, {unit: event.target.value})} />
              </label>
              <button type="button" aria-label={`Eliminar material ${index + 1}`}
                disabled={lines.length === 1}
                onClick={() => setLines(current => current.filter((_, position) => position !== index))}
                className="col-span-2 md:col-span-1 h-10 rounded-xl border border-gray-200 flex items-center justify-center text-gray-400 hover:text-red-600 disabled:opacity-30">
                <Trash2 className="w-4 h-4" />
              </button>
            </div>
          ))}
        </div>
        <button type="button" className="btn-secondary text-sm" disabled={lines.length >= 12}
          onClick={() => setLines(current => [...current, {...EMPTY_LINE}])}>
          <Plus className="w-4 h-4" /> Agregar material
        </button>
        <div className="grid sm:grid-cols-2 gap-3 pt-2 border-t border-gray-100">
          <label className="text-xs font-semibold text-gray-500">Ciudad de la obra
            <input className="input mt-1" maxLength={100} value={city} onChange={event => setCity(event.target.value)} />
          </label>
          <label className="text-xs font-semibold text-gray-500">Máximo de proveedores
            <input className="input mt-1" type="number" min={1} max={6} value={maxStores}
              onChange={event => setMaxStores(Number(event.target.value))} />
          </label>
        </div>
        {mutation.isError && <p className="text-sm text-red-600">{String(mutation.error)}</p>}
        <button className="btn-primary w-full justify-center" disabled={mutation.isPending}>
          {mutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <ClipboardList className="w-4 h-4" />}
          {mutation.isPending ? 'Cotizando tiendas…' : 'Optimizar compra'}
        </button>
      </form>

      {result && (
        <section className="space-y-4">
          <div className="grid sm:grid-cols-3 gap-3">
            <div className="card"><p className="text-xs text-gray-500">Costo optimizado</p><p className="text-2xl font-black text-green-700">{formatCLP(result.total_cost)}</p></div>
            <div className="card"><p className="text-xs text-gray-500">Proveedores</p><p className="text-xl font-black text-brand-900">{result.stores.length}</p><p className="text-xs text-gray-400">{result.stores.join(', ')}</p></div>
            <div className="card"><p className="text-xs text-gray-500">Ahorro vs. un proveedor</p><p className="text-2xl font-black text-brand-600">{formatCLP(result.estimated_savings)}</p></div>
          </div>
          <div className="card overflow-x-auto">
            <table className="w-full text-sm">
              <thead><tr className="text-left border-b"><th className="py-2">Material</th><th>Tienda</th><th>Precio unitario</th><th>Cantidad</th><th>Total</th><th></th></tr></thead>
              <tbody>{result.selections.map((selection, index) => (
                <tr key={`${selection.query}-${index}`} className="border-b border-gray-100">
                  <td className="py-3 pr-3"><p className="font-semibold">{selection.offer.title}</p><p className="text-xs text-gray-400">{selection.query}</p></td>
                  <td>{selection.offer.store}</td><td>{formatCLP(selection.offer.extracted_price)}</td>
                  <td>{selection.quantity} {selection.unit}</td><td className="font-bold">{formatCLP(selection.line_total)}</td>
                  <td>{selection.offer.link && <a className="text-brand-600 font-semibold" target="_blank" rel="noreferrer" href={selection.offer.link}>Ver</a>}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
          <div className="text-xs text-gray-500 bg-amber-50 border border-amber-200 rounded-xl p-4">
            {result.assumptions.map(item => <p key={item}>• {item}</p>)}
          </div>
        </section>
      )}
    </div>
  )
}
