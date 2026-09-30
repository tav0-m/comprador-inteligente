const CLP = new Intl.NumberFormat('es-CL', { style: 'currency', currency: 'CLP', maximumFractionDigits: 0 })
const CLP_DECIMAL = new Intl.NumberFormat('es-CL', { style: 'currency', currency: 'CLP', maximumFractionDigits: 1 })

export function formatCLP(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  return CLP.format(value)
}

export function unitLabel(unit: string | null | undefined): string {
  if (!unit) return ''
  return unit === 'u' ? 'unidad' : unit === 'm2' ? 'm²' : unit
}

/** Precio por unidad: "$192 / kg"; con decimal bajo $100 ("$9,2 / unidad"). */
export function formatUnitPrice(value: number | null | undefined, unit: string | null | undefined): string | null {
  if (value === null || value === undefined || !unit) return null
  const formatted = value < 100 ? CLP_DECIMAL.format(value) : CLP.format(value)
  return `${formatted} / ${unitLabel(unit)}`
}

/** "hace 5 min", "hace 3 h", "hace 2 días" a partir de una fecha ISO. */
export function timeAgo(iso: string | null | undefined): string | null {
  if (!iso) return null
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return null
  const minutes = Math.max(0, Math.round((Date.now() - date.getTime()) / 60000))
  if (minutes < 1) return 'hace instantes'
  if (minutes < 60) return `hace ${minutes} min`
  const hours = Math.round(minutes / 60)
  if (hours < 48) return `hace ${hours} h`
  return `hace ${Math.round(hours / 24)} días`
}
