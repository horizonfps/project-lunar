import { useState, useEffect } from 'react'
import { Brain, X, RefreshCw } from 'lucide-react'

export default function NpcInspector({ open, onClose, campaignId }) {
  const [npcs, setNpcs] = useState([])
  const [loading, setLoading] = useState(false)
  const [expanded, setExpanded] = useState(null)

  const fetchNpcs = async () => {
    if (!campaignId) return
    setLoading(true)
    try {
      const r = await fetch(`/api/game/${campaignId}/npc-minds`)
      if (!r.ok) throw new Error('Failed')
      const data = await r.json()
      setNpcs(data)
    } catch {
      setNpcs([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (open) fetchNpcs()
  }, [open, campaignId])

  if (!open) return null

  const thoughtLabels = {
    feeling: { label: 'Feeling', color: 'text-amber-400' },
    goal: { label: 'Current Goal', color: 'text-emerald-400' },
    opinion_of_player: { label: 'Opinion of Player', color: 'text-white' },
    secret_plan: { label: 'Secret Plan', color: 'text-rose-400' },
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm">
      <div className="bg-white/[0.03] backdrop-blur-xl border border-white/5 rounded-[2rem] w-full max-w-lg mx-4 overflow-hidden max-h-[80vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-white/5 flex-none">
          <div className="flex items-center gap-3">
            <Brain size={16} className="text-white" />
            <h2 className="text-white font-bold text-sm uppercase tracking-widest">NPC Minds</h2>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={fetchNpcs}
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
          {npcs.length === 0 ? (
            <div className="text-center py-8">
              <Brain size={32} className="text-white/20 mx-auto mb-3" />
              <p className="text-white/20 text-sm font-light">
                {loading ? 'Scanning neural patterns...' : 'No NPC minds detected yet. Play more to populate NPC thoughts.'}
              </p>
            </div>
          ) : (
            npcs.map((npc, i) => (
              <div
                key={i}
                className="rounded-xl bg-white/[0.03] border border-white/5 overflow-hidden transition-all"
              >
                <button
                  onClick={() => setExpanded(expanded === i ? null : i)}
                  className="w-full px-4 py-3 flex items-center justify-between hover:bg-white/5 transition-colors"
                >
                  <div className="flex items-center gap-3">
                    <div className="w-8 h-8 rounded-full bg-white/10 border border-white/20 flex items-center justify-center">
                      <span className="text-white text-xs font-bold">
                        {npc.name.charAt(0).toUpperCase()}
                      </span>
                    </div>
                    <span className="text-white font-semibold text-sm">{npc.name}</span>
                  </div>
                  <span className="text-white/20 text-xs">
                    {Object.keys(npc.thoughts || {}).length} thoughts
                  </span>
                </button>

                {expanded === i && (
                  <div className="px-4 pb-4 space-y-2 border-t border-white/5 pt-3">
                    {Object.entries(npc.thoughts || {}).map(([key, thought]) => {
                      const meta = thoughtLabels[key] || { label: key, color: 'text-white/40' }
                      return (
                        <div key={key} className="flex flex-col gap-1">
                          <span className={`text-[10px] uppercase tracking-widest font-bold ${meta.color}`}>
                            {meta.label}
                          </span>
                          <p className="text-[#d1d1d1] text-sm font-light leading-relaxed pl-2 border-l-2 border-white/5">
                            {thought.value}
                          </p>
                        </div>
                      )
                    })}
                  </div>
                )}
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  )
}
