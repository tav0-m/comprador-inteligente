import Link from 'next/link'
import { ClipboardList, Database, HardHat, ShieldCheck, TrendingDown } from 'lucide-react'
import SearchBar from '@/components/SearchBar'

const FEATURES = [
  { icon: ClipboardList, title: 'Canasta completa', desc: 'Optimiza materiales, cantidades y límite de proveedores.' },
  { icon: Database, title: 'Datos trazables', desc: 'Precio, tienda, disponibilidad e historial en una sola vista.' },
  { icon: ShieldCheck, title: 'Ranking explicable', desc: 'Reglas auditables hasta reunir feedback real suficiente.' },
  { icon: TrendingDown, title: 'Ahorro verificable', desc: 'Compara contra comprar todo a un solo proveedor.' },
]

export default function HomePage() {
  return (
    <div className="space-y-10">
      <div className="text-center pt-8">
        <div className="flex items-center justify-center gap-3 mb-4">
          <HardHat className="w-10 h-10 text-yellow-500" />
          <h1 className="text-4xl font-black text-brand-900">Comprador <span className="text-brand-600">Inteligente</span></h1>
        </div>
        <p className="text-gray-600 text-lg max-w-2xl mx-auto">Cotiza materiales y optimiza el costo total de abastecimiento de tu obra.</p>
      </div>
      <div className="card max-w-3xl mx-auto"><SearchBar /></div>
      <div className="text-center"><Link href="/procurement" className="btn-secondary">¿Tienes una lista completa? Optimizar compra de obra</Link></div>
      <div className="flex flex-wrap justify-center gap-3">
        {['Sodimac', 'Easy', 'Falabella', 'Paris', 'Construmart', 'Mercado Libre'].map(store => (
          <span key={store} className="px-4 py-1.5 bg-white border border-gray-200 rounded-full text-sm font-semibold text-gray-600 shadow-sm">{store}</span>
        ))}
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {FEATURES.map(({icon: Icon, title, desc}) => (
          <div key={title} className="card text-center"><Icon className="w-8 h-8 text-brand-600 mx-auto mb-3" /><h3 className="font-bold text-gray-800 mb-1">{title}</h3><p className="text-sm text-gray-500">{desc}</p></div>
        ))}
      </div>
    </div>
  )
}
