import type { ProductOffer } from '@/lib/types'
import { ExternalLink, Truck, ShieldCheck } from 'lucide-react'
import { formatCLP, formatUnitPrice } from '@/lib/format'

export default function BestBanner({ offer }: { offer: ProductOffer }) {
  const unitPrice = formatUnitPrice(offer.unit_price, offer.unit)
  const showSeller = offer.seller && offer.seller.toLowerCase() !== (offer.store ?? '').toLowerCase()
  return (
    <div className="rounded-2xl p-6 text-white mb-6 flex items-center justify-between flex-wrap gap-4"
         style={{ background: 'linear-gradient(135deg, #1b5e20 0%, #2e7d32 50%, #388e3c 100%)' }}>
      <div className="flex-1 min-w-0">
        <p className="text-xs font-bold uppercase tracking-widest text-green-300 mb-1">
          ⭐ Mejor opción comparable
        </p>
        <p className="font-bold text-lg leading-snug truncate">{offer.title}</p>
        <p className="text-green-200 text-sm mt-1 flex items-center gap-2 flex-wrap">
          <ShieldCheck className="w-4 h-4" />
          {offer.store}
          {showSeller && <span className="text-green-300">· vendido por {offer.seller}</span>}
          {offer.free_shipping && (
            <span className="flex items-center gap-1 bg-white/20 px-2 py-0.5 rounded-full text-xs">
              <Truck className="w-3 h-3" /> Envío gratis
            </span>
          )}
        </p>
      </div>
      <div className="text-right shrink-0">
        <p className="text-4xl font-black">{formatCLP(offer.extracted_price)}</p>
        {unitPrice && <p className="text-green-200 text-sm font-semibold">{unitPrice}</p>}
        {offer.link ? (
          <a
            href={offer.link}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-2 mt-3 bg-white text-green-800
                       font-black px-5 py-2.5 rounded-full shadow hover:scale-105 transition-transform"
          >
            <ExternalLink className="w-4 h-4" />
            Ir a comprar →
          </a>
        ) : (
          <p className="text-green-300 text-sm mt-3">Sin link disponible</p>
        )}
      </div>
    </div>
  )
}
