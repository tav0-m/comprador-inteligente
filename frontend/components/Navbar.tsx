'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { BarChart2, Bell, ClipboardList, HardHat, Search, TrendingUp, Zap } from 'lucide-react'
import { clsx } from 'clsx'

const links = [
  { href: '/', label: 'Buscar', icon: Search },
  { href: '/procurement', label: 'Cotizar obra', icon: ClipboardList },
  { href: '/history', label: 'Historial', icon: TrendingUp },
  { href: '/alerts', label: 'Alertas', icon: Bell },
  { href: '/stats', label: 'Métricas', icon: BarChart2 },
  { href: '/live', label: 'En vivo', icon: Zap },
]

export default function Navbar() {
  const path = usePathname()
  return (
    <nav className="bg-brand-900 text-white shadow-lg">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between min-h-14 gap-3">
          <Link href="/" className="flex items-center gap-2 font-black text-lg tracking-tight whitespace-nowrap">
            <HardHat className="w-6 h-6 text-yellow-300" />
            <span className="hidden sm:inline">Comprador <span className="text-yellow-300">Inteligente</span></span>
          </Link>
          <div className="flex items-center gap-1 overflow-x-auto py-2">
            {links.map(({href, label, icon: Icon}) => (
              <Link key={href} href={href} className={clsx(
                'flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium whitespace-nowrap transition-colors',
                path === href ? 'bg-white/15 text-white' : 'text-blue-200 hover:bg-white/10 hover:text-white',
              )}>
                <Icon className="w-4 h-4" /> <span className="hidden lg:inline">{label}</span>
              </Link>
            ))}
          </div>
        </div>
      </div>
    </nav>
  )
}
