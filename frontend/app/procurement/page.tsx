'use client'

import { useRef, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { ClipboardList, Download, FileUp, Loader2, Plus, Trash2, Truck } from 'lucide-react'
import { downloadPurchaseOrder, importBom, optimizeBasket, type BasketRequest } from '@/lib/api'
import { formatUnitPrice, unitLabel } from '@/lib/format'
import type { BasketLine, StoreTerms } from '@/lib/types'

function formatCLP(value: number | null | undefined) {
  if (value === null || value === undefined) return 'No disponible'
  return new Intl.NumberFormat('es-CL', {
    style: 'currency', currency: 'CLP', maximumFractionDigits: 0,
  }).format(value)
}

const MAX_LINES = 30
const EMPTY_LINE: BasketLine = { query: '', quantity: 1, unit: 'unidad' }
const STORES = ['Sodimac', 'Easy', 'Falabella', 'Paris']
const EMPTY_TERMS: StoreTerms = { shipping_cost: 0, free_shipping_threshold: null, fixed_cost: 0 }

// Con kg, l, m2 o unidades el optimizador calcula envases enteros por el contenido de cada producto.
const UNIT_SUGGESTIONS = ['kg', 'l', 'm2', 'unidades', 'unidad', 'saco', 'plancha', 'rollo']
const MEASURED_UNITS = new Set(['kg', 'kilo', 'kilos', 'g', 'gr', 'ton', 'l', 'lt', 'litro', 'litros',
  'm2', 'mt2', 'm²', 'u', 'un', 'unidades', 'piezas'])

function formatPacks(packs: number | null | undefined, offer: { pack_quantity?: number | null; unit?: string | null }) {
  if (!packs) return null
  const content = offer.pack_quantity && offer.unit ? ` de ${offer.pack_quantity} ${unitLabel(offer.unit)}` : ''
  return `${packs} envase${packs === 1 ? '' : 's'}${content}`
}

function numberOrNull(value: string): number | null {
  if (value.trim() === '') return null
  const parsed = Number(value)
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : null
}

export default function ProcurementPage() {
  const [lines, setLines] = useState<BasketLine[]>([
    { query: 'cemento 25 kg', quantity: 500, unit: 'kg' },
    { query: 'plancha OSB 15 mm', quantity: 10, unit: 'plancha' },
  ])
  const [city, setCity] = useState('Santiago')
  const [maxStores, setMaxStores] = useState(3)
  const [terms, setTerms] = useState<Record<string, StoreTerms>>(
    Object.fromEntries(STORES.map(store => [store, { ...EMPTY_TERMS }])),
  )
  const fileInput = useRef<HTMLInputElement>(null)
  const optimize = useMutation({ mutationFn: optimizeBasket })
  const exporter = useMutation({ mutationFn: downloadPurchaseOrder })
  const importer = useMutation({
    mutationFn: importBom,
    onSuccess: data => {
      setLines(data.lines.map(({ query, quantity, unit }) => ({ query, quantity, unit })))
      optimize.reset()
    },
  })

  function updateLine(index: number, patch: Partial<BasketLine>) {
    setLines(current => current.map((line, position) => position === index ? {...line, ...patch} : line))
  }

  function updateTerms(store: string, patch: Partial<StoreTerms>) {
    setTerms(current => ({ ...current, [store]: { ...current[store], ...patch } }))
  }

  function buildRequest(): BasketRequest {
    return { lines, country: 'cl', city, max_stores: maxStores, store_terms: terms }
  }

  function submit(event: React.FormEvent) {
    event.preventDefault()
    optimize.mutate(buildRequest())
  }

  function onFileSelected(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    if (file) importer.mutate(file)
    event.target.value = ''
  }

  const result = optimize.data
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-black text-brand-900 flex items-center gap-2">
          <ClipboardList className="w-6 h-6 text-brand-600" /> Optimizar lista de materiales
        </h1>
        <p className="text-sm text-gray-500 mt-2 max-w-3xl">
          Importa el presupuesto de la obra o escribe los materiales, indica las condiciones de despacho de cada
          proveedor y obtén la combinación de menor costo total, resuelta de forma exacta.
        </p>
      </div>

      <div className="card flex flex-wrap items-center gap-3">
        <input ref={fileInput} type="file" accept=".xlsx,.csv,.txt" className="hidden" onChange={onFileSelected} />
        <button type="button" className="btn-secondary text-sm" disabled={importer.isPending}
          onClick={() => fileInput.current?.click()}>
          {importer.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <FileUp className="w-4 h-4" />}
          Importar lista (.xlsx o .csv)
        </button>
        <p className="text-xs text-gray-400 flex-1 min-w-[220px]">
          Columnas reconocidas: material o descripción, cantidad y unidad. Se fusionan filas repetidas.
        </p>
        {importer.isError && <p className="text-sm text-red-600 w-full">{String(importer.error)}</p>}
        {importer.data && (
          <div className="w-full text-xs text-gray-600 space-y-1">
            <p className="font-semibold text-green-700">
              {importer.data.lines.length} materiales importados de {importer.data.rows_read} filas
              {importer.data.rows_skipped > 0 && ` (${importer.data.rows_skipped} omitidas)`}.
            </p>
            {importer.data.warnings.map(warning => (
              <p key={warning} className="text-amber-700">• {warning}</p>
            ))}
          </div>
        )}
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
                <input className="input mt-1" required maxLength={40} list="unit-suggestions"
                  value={line.unit} onChange={event => updateLine(index, {unit: event.target.value})} />
                {MEASURED_UNITS.has(line.unit.trim().toLowerCase()) && (
                  <span className="block mt-1 font-normal text-[11px] text-green-700">Calcula envases enteros</span>
                )}
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
        <datalist id="unit-suggestions">
          {UNIT_SUGGESTIONS.map(unit => <option key={unit} value={unit} />)}
        </datalist>
        <p className="text-xs text-gray-400">
          Usa <strong>kg</strong>, <strong>l</strong>, <strong>m2</strong> o <strong>unidades</strong> para
          comparar formatos distintos (p. ej. sacos de 25 y 42,5 kg); con otra unidad la cantidad se toma como envases.
        </p>
        <button type="button" className="btn-secondary text-sm" disabled={lines.length >= MAX_LINES}
          onClick={() => setLines(current => [...current, {...EMPTY_LINE}])}>
          <Plus className="w-4 h-4" /> Agregar material
        </button>

        <div className="grid sm:grid-cols-2 gap-3 pt-2 border-t border-gray-100">
          <label className="text-xs font-semibold text-gray-500">Ciudad de la obra
            <input className="input mt-1" maxLength={100} value={city} onChange={event => setCity(event.target.value)} />
          </label>
          <label className="text-xs font-semibold text-gray-500">Máximo de proveedores
            <input className="input mt-1" type="number" min={1} max={8} value={maxStores}
              onChange={event => setMaxStores(Number(event.target.value))} />
          </label>
        </div>

        <details className="pt-2 border-t border-gray-100">
          <summary className="text-sm font-semibold text-gray-600 cursor-pointer flex items-center gap-2">
            <Truck className="w-4 h-4 text-brand-600" /> Condiciones de despacho por proveedor (opcional)
          </summary>
          <div className="overflow-x-auto mt-3">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-gray-500">
                  <th className="py-1">Proveedor</th><th>Despacho CLP</th><th>Gratis desde CLP</th><th>Costo fijo CLP</th>
                </tr>
              </thead>
              <tbody>
                {STORES.map(store => (
                  <tr key={store}>
                    <td className="py-1 pr-2 font-semibold text-gray-700">{store}</td>
                    <td className="pr-2">
                      <input className="input" type="number" min={0} step={10} aria-label={`Despacho ${store}`}
                        value={terms[store].shipping_cost}
                        onChange={event => updateTerms(store, { shipping_cost: numberOrNull(event.target.value) ?? 0 })} />
                    </td>
                    <td className="pr-2">
                      <input className="input" type="number" min={0} step={1000} placeholder="Sin umbral"
                        aria-label={`Despacho gratis desde ${store}`}
                        value={terms[store].free_shipping_threshold ?? ''}
                        onChange={event => updateTerms(store, { free_shipping_threshold: numberOrNull(event.target.value) })} />
                    </td>
                    <td>
                      <input className="input" type="number" min={0} step={100} aria-label={`Costo fijo ${store}`}
                        value={terms[store].fixed_cost}
                        onChange={event => updateTerms(store, { fixed_cost: numberOrNull(event.target.value) ?? 0 })} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="text-xs text-gray-400 mt-2">
              El costo fijo representa el esfuerzo de sumar un proveedor (orden, recepción, facturas): úsalo para
              consolidar compras cuando el ahorro no lo justifica.
            </p>
          </div>
        </details>

        {optimize.isError && <p className="text-sm text-red-600">{String(optimize.error)}</p>}
        <button className="btn-primary w-full justify-center" disabled={optimize.isPending}>
          {optimize.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <ClipboardList className="w-4 h-4" />}
          {optimize.isPending ? 'Cotizando tiendas…' : 'Optimizar compra'}
        </button>
      </form>

      {result && (
        <section className="space-y-4">
          <div className="grid sm:grid-cols-4 gap-3">
            <div className="card"><p className="text-xs text-gray-500">Costo total óptimo</p><p className="text-2xl font-black text-green-700">{formatCLP(result.total_cost)}</p><p className="text-xs text-gray-400">incluye despacho y costos fijos</p></div>
            <div className="card"><p className="text-xs text-gray-500">Despacho</p><p className="text-xl font-black text-brand-900">{formatCLP(result.shipping_total)}</p></div>
            <div className="card"><p className="text-xs text-gray-500">Proveedores</p><p className="text-xl font-black text-brand-900">{result.stores.length}</p><p className="text-xs text-gray-400">{result.stores.join(', ')}</p></div>
            <div className="card"><p className="text-xs text-gray-500">Ahorro vs. un proveedor</p><p className="text-2xl font-black text-brand-600">{formatCLP(result.estimated_savings)}</p></div>
          </div>

          <div className="card overflow-x-auto">
            <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
              <p className="font-bold text-gray-700">Detalle por material</p>
              <button type="button" className="btn-secondary text-sm" disabled={exporter.isPending}
                onClick={() => exporter.mutate(buildRequest())}>
                {exporter.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Download className="w-4 h-4" />}
                Descargar orden de compra
              </button>
            </div>
            {exporter.isError && <p className="text-sm text-red-600 mb-2">{String(exporter.error)}</p>}
            <table className="w-full text-sm">
              <thead><tr className="text-left border-b"><th className="py-2">Material</th><th>Tienda</th><th>Precio envase</th><th>Pedido</th><th>Compra</th><th>Total</th><th></th></tr></thead>
              <tbody>{result.selections.map((selection, index) => (
                <tr key={`${selection.query}-${index}`} className="border-b border-gray-100">
                  <td className="py-3 pr-3"><p className="font-semibold">{selection.offer.title}</p><p className="text-xs text-gray-400">{selection.query}</p></td>
                  <td>{selection.offer.store}</td>
                  <td>
                    {formatCLP(selection.offer.extracted_price)}
                    {selection.offer.unit_price && (
                      <p className="text-xs text-gray-400">{formatUnitPrice(selection.offer.unit_price, selection.offer.unit)}</p>
                    )}
                  </td>
                  <td>{selection.quantity} {selection.unit}</td>
                  <td>{formatPacks(selection.packs, selection.offer) ?? `${selection.quantity} ${selection.unit}`}</td>
                  <td className="font-bold">{formatCLP(selection.line_total)}</td>
                  <td>{selection.offer.link && <a className="text-brand-600 font-semibold" target="_blank" rel="noreferrer" href={selection.offer.link}>Ver</a>}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>

          <div className="card overflow-x-auto">
            <p className="font-bold text-gray-700 mb-3">Resumen por proveedor</p>
            <table className="w-full text-sm">
              <thead><tr className="text-left border-b text-xs text-gray-500"><th className="py-2">Proveedor</th><th>Líneas</th><th>Mercadería</th><th>Despacho</th><th>Costo fijo</th><th>Total</th></tr></thead>
              <tbody>{result.store_breakdown.map(item => (
                <tr key={item.store} className="border-b border-gray-100">
                  <td className="py-2 font-semibold">{item.store}</td>
                  <td>{item.lines}</td>
                  <td>{formatCLP(item.merchandise)}</td>
                  <td>{item.free_shipping ? <span className="badge badge-green text-xs">Gratis</span> : formatCLP(item.shipping)}</td>
                  <td>{formatCLP(item.fixed_cost)}</td>
                  <td className="font-bold">{formatCLP(item.total)}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>

          <div className="text-xs text-gray-500 bg-amber-50 border border-amber-200 rounded-xl p-4">
            {result.assumptions.map(item => <p key={item}>• {item}</p>)}
            <p className="mt-1 text-gray-400">Método: {result.solver} · {result.elapsed_ms} ms</p>
          </div>
        </section>
      )}
    </div>
  )
}
