import { useState } from 'react'
import { Sparkles, X, User, Zap, BookOpen } from 'lucide-react'

export default function PlotGeneratorPanel({ open, onClose, campaignId }) {
  const [tab, setTab] = useState('npc')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)

  const generate = async (type) => {
    setLoading(true)
    setResult(null)
    try {
      const r = await fetch(`/api/game/${campaignId}/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ type }),
      })
      if (!r.ok) throw new Error('Generation failed')
      const data = await r.json()
      setResult({ type, data })
    } catch {
      setResult({ type, data: null, error: 'Generation failed. Is the backend running?' })
    } finally {
      setLoading(false)
    }
  }

  if (!open) return null

  const tabs = [
    { id: 'npc', label: 'NPC', icon: User },
    { id: 'event', label: 'Event', icon: Zap },
    { id: 'plot', label: 'Plot Arc', icon: BookOpen },
  ]

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm">
      <div className="bg-white/[0.03] backdrop-blur-xl border border-white/5 rounded-[2rem] w-full max-w-lg mx-4 overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-white/5">
          <div className="flex items-center gap-3">
            <Sparkles size={16} className="text-amber-400" />
            <h2 className="text-white font-bold text-sm uppercase tracking-widest">Plot Generator</h2>
          </div>
          <button onClick={onClose} className="text-white/40 hover:text-white transition-colors">
            <X size={18} />
          </button>
        </div>

        {/* Tabs */}
        <div className="flex gap-1 px-6 pt-4">
          {tabs.map((t) => (
            <button
              key={t.id}
              onClick={() => { setTab(t.id); setResult(null) }}
              className={`flex items-center gap-2 px-4 py-2 rounded-lg text-xs font-bold uppercase tracking-widest transition-all border
                ${tab === t.id
                  ? 'bg-white/10 text-white border-white/20'
                  : 'text-white/20 hover:text-white/60 hover:bg-white/5 border-transparent'
                }`}
            >
              <t.icon size={12} />
              {t.label}
            </button>
          ))}
        </div>

        {/* Content */}
        <div className="p-6">
          {/* Description */}
          <p className="text-white/40 text-sm font-light mb-4">
            {tab === 'npc' && 'Generate a unique NPC with personality, goals, and secrets based on your world context.'}
            {tab === 'event' && 'Create a random encounter or event with branching choices for your current scenario.'}
            {tab === 'plot' && 'Generate a compelling plot hook for a new quest or story branch.'}
          </p>

          {/* Generate button */}
          <button
            onClick={() => generate(tab)}
            disabled={loading}
            className="w-full bg-white text-black hover:bg-gray-200 uppercase text-sm tracking-[0.2em] font-bold rounded-full px-6 py-3 rounded-lg font-semibold tracking-wide border border-white/20 mb-4"
          >
            {loading ? (
              <span className="flex items-center justify-center gap-2">
                <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                Generating...
              </span>
            ) : (
              <span className="flex items-center justify-center gap-2">
                <Sparkles size={14} />
                Generate {tab === 'npc' ? 'NPC' : tab === 'event' ? 'Event' : 'Plot Arc'}
              </span>
            )}
          </button>

          {/* Result */}
          {result?.error && (
            <div className="p-4 rounded-xl bg-rose-950/30 border border-rose-500/20 text-rose-300 text-sm">
              {result.error}
            </div>
          )}

          {result?.data && result.type === 'npc' && (
            <div className="p-4 rounded-xl bg-white/[0.03] border border-white/5 space-y-3">
              <div className="flex items-center justify-between">
                <h3 className="text-white font-bold text-lg">{result.data.name}</h3>
                <span className="text-[10px] font-bold uppercase tracking-widest font-mono text-white/40 px-2 py-0.5 rounded bg-amber-400/10 text-amber-400 border border-amber-400/30">
                  Power {result.data.power_level}/10
                </span>
              </div>
              <p className="text-white/60 text-sm font-light">{result.data.appearance}</p>
              <div className="grid grid-cols-2 gap-3 text-xs">
                <div>
                  <span className="text-white/20 uppercase tracking-widest text-[10px] font-bold">Personality</span>
                  <p className="text-[#d1d1d1] mt-1">{result.data.personality}</p>
                </div>
                <div>
                  <span className="text-white/20 uppercase tracking-widest text-[10px] font-bold">Goal</span>
                  <p className="text-[#d1d1d1] mt-1">{result.data.goal}</p>
                </div>
                <div className="col-span-2">
                  <span className="text-white/20 uppercase tracking-widest text-[10px] font-bold">Secret</span>
                  <p className="text-[#d1d1d1] mt-1 italic">{result.data.secret}</p>
                </div>
              </div>
            </div>
          )}

          {result?.data && result.type === 'event' && (
            <div className="p-4 rounded-xl bg-white/[0.03] border border-white/5 space-y-3">
              <h3 className="text-white font-bold text-lg">{result.data.title}</h3>
              <p className="text-white/60 text-sm font-light leading-relaxed">{result.data.description}</p>
              {result.data.choices?.length > 0 && (
                <div className="space-y-2">
                  <span className="text-white/20 uppercase tracking-widest text-[10px] font-bold">Choices</span>
                  {result.data.choices.map((c, i) => (
                    <div key={i} className="flex items-center gap-2 text-sm text-[#d1d1d1]">
                      <span className="text-white font-mono text-xs">{i + 1}.</span>
                      {c}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {result?.data && result.type === 'plot' && (
            <div className="p-4 rounded-xl bg-white/[0.03] border border-white/5">
              <p className="text-[#d1d1d1] text-sm font-light leading-relaxed italic">
                {typeof result.data === 'string' ? result.data : result.data.text}
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
