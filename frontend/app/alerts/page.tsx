'use client'

import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Bell, Loader2 } from 'lucide-react'
import { createAlert } from '@/lib/api'

export default function AlertsPage() {
  const [form, setForm] = useState({
    query: '', target_price: 15000, email: '', store_filter: '', note: '',
  })
  const mutation = useMutation({
    mutationFn: createAlert,
    onSuccess: () => setForm({ query: '', target_price: 15000, email: '', store_filter: '', note: '' }),
  })

  function submit(event: React.FormEvent) {
    event.preventDefault()
    mutation.mutate({
      query: form.query,
      target_price: form.target_price,
      email: form.email,
      store_filter: form.store_filter || undefined,
      note: form.note || undefined,
    })
  }

  return (
    <div className="space-y-6 max-w-3xl mx-auto">
      <div>
        <h1 className="text-2xl font-black text-brand-900 flex items-center gap-2">
          <Bell className="w-6 h-6 text-brand-600" /> Alerta de precio
        </h1>
        <p className="text-sm text-gray-500 mt-2">
          Te avisaremos cuando exista una observación reciente bajo tu precio objetivo.
          Siempre confirma stock, especificación y despacho con la tienda.
        </p>
      </div>

      <form onSubmit={submit} className="card space-y-4">
        <div className="grid sm:grid-cols-2 gap-4">
          <label className="text-sm font-semibold text-gray-600">
            Producto exacto
            <input className="input mt-1" minLength={2} maxLength={120} required
              placeholder="cemento Portland 25 kg"
              value={form.query} onChange={event => setForm({...form, query: event.target.value})} />
          </label>
          <label className="text-sm font-semibold text-gray-600">
            Precio objetivo CLP
            <input className="input mt-1" type="number" min={10} max={30000000} required
              value={form.target_price}
              onChange={event => setForm({...form, target_price: Number(event.target.value)})} />
          </label>
          <label className="text-sm font-semibold text-gray-600">
            Email
            <input className="input mt-1" type="email" required placeholder="compras@empresa.cl"
              value={form.email} onChange={event => setForm({...form, email: event.target.value})} />
          </label>
          <label className="text-sm font-semibold text-gray-600">
            Tienda opcional
            <input className="input mt-1" maxLength={100} placeholder="Sodimac"
              value={form.store_filter} onChange={event => setForm({...form, store_filter: event.target.value})} />
          </label>
        </div>
        <label className="text-sm font-semibold text-gray-600 block">
          Nota opcional
          <input className="input mt-1" maxLength={500} placeholder="Obra Los Alerces"
            value={form.note} onChange={event => setForm({...form, note: event.target.value})} />
        </label>

        {mutation.isError && <p className="text-sm text-red-600">{String(mutation.error)}</p>}
        {mutation.isSuccess && <p className="text-sm text-green-700 font-semibold">{mutation.data.message}</p>}
        <button className="btn-primary w-full justify-center" disabled={mutation.isPending}>
          {mutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Bell className="w-4 h-4" />}
          Crear alerta
        </button>
      </form>

      <p className="text-xs text-gray-400">
        La alerta se activa solo después de confirmar el enlace enviado a tu email (vence en 48 horas).
        Cada aviso incluye un enlace para cancelarla.
      </p>
    </div>
  )
}
