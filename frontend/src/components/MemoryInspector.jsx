import { useState, useEffect } from 'react'
import { Gem, X, RefreshCw } from 'lucide-react'
import { fetchMemoryCrystals, crystallizeMemory } from '../api'

const TIER_STYLES = {
  SHORT: { label: 'Short Crystal', color: 'text-white', bg: 'bg-white/10 border-white/20' },
  LONG: { label: 'Permanent Crystal', color: 'text-amber-400', bg: 'bg-amber-600/10 border-amber-500/20' },
}

export default function MemoryInspector({ open, onClose, campaignId }) {
  const [crystals, setCrystals] = useState([])
  const [loading, setLoading] = useState(false)

  const fetchCrystals = async () => {
    if (!campaignId) return
    setLoading(true)
    try {
      const data = await fetchMemoryCrystals(campaignId)
      setCrystals(data)
    } catch {
      setCrystals([])
    } finally {
      setLoading(false)
    }
  }

  const handleCrystallize = async () => {
    setLoading(true)
    try {
      await crystallizeMemory(campaignId)
      await fetchCrystals()
    } catch {} finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (open) fetchCrystals()
  }, [open, campaignId])

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm">
      <div className="bg-white/[0.03] backdrop-blur-xl border border-white/5 rounded-[2rem] w-full max-w-lg mx-4 overflow-hidden max-h-[80vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-white/5 flex-none">
          <div className="flex items-center gap-3">
            <Gem size={16} className="text-white" />
            <h2 className="text-white font-bold text-sm uppercase tracking-widest">Memory Crystals</h2>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={fetchCrystals}
              disabled={loading}
              className="text-white/40 hover:text-white transition-colors p-1"
              title="Refresh"
            >
              <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
            </button>
            <button onClick={onClose} className="text-white/40 hover:text-white transition-colors">
              <X size={18} />
            </button>
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto custom-scrollbar p-6 space-y-3">
          {crystals.length === 0 ? (
            <div className="text-center py-8">
              <Gem size={32} className="text-white/20 mx-auto mb-3" />
              <p className="text-white/20 text-sm font-light">
                {loading ? 'Scanning crystal lattice...' : 'No memory crystals formed yet. Crystallize to compress your adventure history.'}
              </p>
            </div>
          ) : (
            crystals.map((crystal, i) => {
              const style = TIER_STYLES[crystal.tier] || TIER_STYLES.SHORT
              return (
                <div key={i} className={`p-4 rounded-xl border ${style.bg}`}>
                  <div className="flex items-center justify-between mb-2">
                    <span className={`text-[10px] uppercase tracking-widest font-bold ${style.color}`}>
                      {style.label}
                    </span>
                    <span className="text-[10px] text-white/20 font-mono">
                      {crystal.event_count} events compressed
                    </span>
                  </div>
                  <p className="text-[#d1d1d1] text-sm font-light leading-relaxed">
                    {crystal.content}
                  </p>
                </div>
              )
            })
          )}
        </div>

        {/* Actions */}
        <div className="flex-none p-4 border-t border-white/5">
          <button
            onClick={handleCrystallize}
            disabled={loading}
            className="w-full bg-white text-black hover:bg-gray-200 uppercase text-sm tracking-[0.2em] font-bold rounded-full px-6 py-3 rounded-lg font-semibold tracking-wide border border-white/20"
          >
            {loading ? (
              <span className="flex items-center justify-center gap-2">
                <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                Crystallizing...
              </span>
            ) : (
              <span className="flex items-center justify-center gap-2">
                <Gem size={14} />
                Crystallize Recent Events
              </span>
            )}
          </button>
        </div>
      </div>
    </div>
  )
}
