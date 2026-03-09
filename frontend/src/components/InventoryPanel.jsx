import { useState, useEffect } from 'react'
import { X, Sword, Shield, FlaskConical, Key, Wrench, Package } from 'lucide-react'
import { fetchInventory, updateInventoryItem } from '../api'

const CATEGORY_ICONS = {
  weapon: Sword,
  armor: Shield,
  consumable: FlaskConical,
  quest: Key,
  tool: Wrench,
  misc: Package,
}

const STATUS_COLORS = {
  carried: 'text-emerald-400',
  used: 'text-white/20',
  lost: 'text-rose-400',
}

export default function InventoryPanel({ open, onClose, campaignId, inventory, setInventory }) {
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (open && campaignId) {
      setLoading(true)
      fetchInventory(campaignId)
        .then(setInventory)
        .catch(() => {})
        .finally(() => setLoading(false))
    }
  }, [open, campaignId])

  if (!open) return null

  const handleAction = async (name, action) => {
    await updateInventoryItem(campaignId, name, action)
    const updated = await fetchInventory(campaignId)
    setInventory(updated)
  }

  const carriedItems = inventory.filter((i) => i.status === 'carried')
  const expiredItems = inventory.filter((i) => i.status !== 'carried')

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm">
      <div className="bg-white/[0.03] border border-white/10 rounded-2xl shadow-[0_0_40px_rgba(255,255,255,0.15)] w-full max-w-lg max-h-[80vh] flex flex-col">
        <div className="flex items-center justify-between px-6 py-4 border-b border-white/5">
          <h2 className="text-white font-bold text-base tracking-wide">Inventory</h2>
          <button onClick={onClose} className="text-white/40 hover:text-white transition-colors">
            <X size={18} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-2">
          {loading && <p className="text-white/40 text-sm text-center py-8">Loading...</p>}
          {!loading && inventory.length === 0 && (
            <p className="text-white/20 text-sm text-center py-8">No items yet.</p>
          )}

          {carriedItems.length > 0 && (
            <>
              <p className="text-white/40 text-[10px] font-bold uppercase tracking-widest font-mono px-2">Carried</p>
              {carriedItems.map((item) => {
                const Icon = CATEGORY_ICONS[item.category] || Package
                return (
                  <div key={item.name} className="flex items-center gap-3 px-3 py-2.5 rounded-lg bg-white/5 hover:bg-white/10 transition-colors">
                    <Icon size={16} className="text-white/60 flex-none" />
                    <div className="flex-1 min-w-0">
                      <p className="text-white text-sm font-medium truncate">{item.name}</p>
                      <p className="text-white/40 text-xs truncate">{item.source}</p>
                    </div>
                    <div className="flex gap-1">
                      <button
                        onClick={() => handleAction(item.name, 'use')}
                        className="px-2 py-1 text-[10px] uppercase tracking-wider bg-amber-500/10 text-amber-400 rounded hover:bg-amber-500/20 transition-colors"
                      >
                        Use
                      </button>
                      <button
                        onClick={() => handleAction(item.name, 'discard')}
                        className="px-2 py-1 text-[10px] uppercase tracking-wider bg-rose-500/10 text-rose-400 rounded hover:bg-rose-500/20 transition-colors"
                      >
                        Drop
                      </button>
                    </div>
                  </div>
                )
              })}
            </>
          )}

          {expiredItems.length > 0 && (
            <>
              <p className="text-white/40 text-[10px] font-bold uppercase tracking-widest font-mono px-2 mt-4">Used / Lost</p>
              {expiredItems.map((item) => {
                const Icon = CATEGORY_ICONS[item.category] || Package
                return (
                  <div key={item.name} className="flex items-center gap-3 px-3 py-2 rounded-lg bg-white/[0.03] opacity-50">
                    <Icon size={16} className="text-white/20 flex-none" />
                    <div className="flex-1 min-w-0">
                      <p className="text-white/60 text-sm truncate">{item.name}</p>
                      <p className="text-white/20 text-xs">{item.status}</p>
                    </div>
                  </div>
                )
              })}
            </>
          )}
        </div>
      </div>
    </div>
  )
}
