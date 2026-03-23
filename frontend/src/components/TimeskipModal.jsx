import { useState } from 'react'
import { Clock, X } from 'lucide-react'
import { timeskip } from '../api'

const PRESETS = [
  { label: '1 Hour', seconds: 3600 },
  { label: '8 Hours', seconds: 28800 },
  { label: '1 Day', seconds: 86400 },
  { label: '3 Days', seconds: 259200 },
  { label: '1 Week', seconds: 604800 },
  { label: '1 Month', seconds: 2592000 },
]

export default function TimeskipModal({ open, onClose, campaignId, onTimeskip }) {
  const [selected, setSelected] = useState(null)
  const [loading, setLoading] = useState(false)
  const [summary, setSummary] = useState(null)

  const handleTimeskip = async () => {
    if (!selected) return
    setLoading(true)
    setSummary(null)
    try {
      const data = await timeskip(campaignId, selected.seconds)
      setSummary(data.summary)
      onTimeskip?.(data)
    } catch {
      setSummary('Time passes, but the world remains still...')
    } finally {
      setLoading(false)
    }
  }

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm">
      <div className="bg-white/[0.03] backdrop-blur-xl border border-white/5 rounded-[2rem] w-full max-w-md mx-4 overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-white/5">
          <div className="flex items-center gap-3">
            <Clock size={16} className="text-white" />
            <h2 className="text-white font-bold text-sm uppercase tracking-widest">Time Skip</h2>
          </div>
          <button onClick={() => { onClose(); setSummary(null); setSelected(null) }} className="text-white/40 hover:text-white transition-colors">
            <X size={18} />
          </button>
        </div>

        <div className="p-6 space-y-4">
          {!summary ? (
            <>
              <p className="text-white/40 text-sm font-light">
                Advance narrative time. The world will react to the passage of time — NPCs move, factions shift, rumors spread.
              </p>

              {/* Preset grid */}
              <div className="grid grid-cols-3 gap-2">
                {PRESETS.map((p) => (
                  <button
                    key={p.seconds}
                    onClick={() => setSelected(p)}
                    className={`px-3 py-3 rounded-xl text-sm font-medium transition-all border
                      ${selected?.seconds === p.seconds
                        ? 'bg-white/10 text-white border-white/20 shadow-[0_0_10px_rgba(6,182,212,0.15)]'
                        : 'bg-white/[0.03] text-white/40 border-white/5 hover:border-white/20 hover:text-[#d1d1d1]'
                      }`}
                  >
                    {p.label}
                  </button>
                ))}
              </div>

              {/* Execute */}
              <button
                onClick={handleTimeskip}
                disabled={!selected || loading}
                className="w-full bg-white text-black hover:bg-gray-200 uppercase text-sm tracking-[0.2em] font-bold rounded-full px-6 py-3 rounded-lg font-semibold tracking-wide border border-white/20"
              >
                {loading ? (
                  <span className="flex items-center justify-center gap-2">
                    <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                    World is evolving...
                  </span>
                ) : (
                  `Skip ${selected?.label || '...'}`
                )}
              </button>
            </>
          ) : (
            <>
              {/* Summary */}
              <div className="text-center mb-2">
                <span className="text-[10px] uppercase tracking-widest text-white font-bold">
                  {selected?.label} has passed
                </span>
              </div>
              <div className="p-4 rounded-xl bg-white/[0.03] border border-white/5">
                <p className="text-[#d1d1d1] text-sm font-light leading-relaxed italic">
                  {summary}
                </p>
              </div>
              <button
                onClick={() => { onClose(); setSummary(null); setSelected(null) }}
                className="w-full px-6 py-3 rounded-lg font-semibold text-sm tracking-wide bg-white/5 hover:bg-white text-white/80 hover:text-black rounded-2xl border border-white/5 transition-all"
              >
                Continue
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
