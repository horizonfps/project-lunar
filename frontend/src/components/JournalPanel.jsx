import { useState } from 'react'
import { BookOpen, RefreshCw, X } from 'lucide-react'

const CATEGORIES = [
  { id: null, label: 'All' },
  { id: 'DISCOVERY', label: 'Discovery' },
  { id: 'COMBAT', label: 'Combat' },
  { id: 'DECISION', label: 'Decision' },
  { id: 'RELATIONSHIP_CHANGE', label: 'Relationship' },
  { id: 'WORLD_EVENT', label: 'World' },
]

const CATEGORY_COLORS = {
  DISCOVERY: 'text-amber-400 bg-amber-400/10 border-amber-400/30',
  COMBAT: 'text-rose-400 bg-rose-400/10 border-rose-400/30',
  DECISION: 'text-white bg-white/10 border-white/20',
  RELATIONSHIP_CHANGE: 'text-emerald-400 bg-emerald-400/10 border-emerald-400/30',
  WORLD_EVENT: 'text-white bg-white/10 border-white/20',
}

export default function JournalPanel({ open, onClose, entries, onRefresh }) {
  const [filter, setFilter] = useState(null)

  if (!open) return null

  const filtered = filter
    ? entries.filter((e) => e.category === filter)
    : entries

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm">
      <div className="bg-white/[0.03] border border-white/10 rounded-2xl shadow-[0_0_40px_rgba(255,255,255,0.15)] w-full max-w-[33rem] max-h-[70vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-white/5">
          <div className="flex items-center gap-3">
            <BookOpen size={16} className="text-yellow-400" />
            <h2 className="text-white font-bold text-sm uppercase tracking-widest">
              Mission Log
              {entries.length > 0 && (
                <span className="ml-2 text-white/40 font-normal text-xs">{entries.length}</span>
              )}
            </h2>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={onRefresh}
              title="Refresh"
              className="text-white/40 hover:text-white transition-colors"
            >
              <RefreshCw size={14} />
            </button>
            <button onClick={onClose} className="text-white/40 hover:text-white transition-colors">
              <X size={18} />
            </button>
          </div>
        </div>

        {/* Category filters */}
        <div className="flex flex-wrap gap-1.5 px-6 py-3 border-b border-white/5">
          {CATEGORIES.map((c) => (
            <button
              key={c.id ?? 'all'}
              onClick={() => setFilter(c.id)}
              className={`px-3 py-1 rounded-lg text-[10px] font-bold uppercase tracking-widest font-mono text-white/40 whitespace-nowrap transition-all
                ${filter === c.id
                  ? 'bg-white/10 text-white border border-white/20'
                  : 'text-white/20 hover:text-white/60 hover:bg-white/5 border border-transparent'
                }`}
            >
              {c.label}
            </button>
          ))}
        </div>

        {/* Entries */}
        <div className="flex-1 overflow-y-auto custom-scrollbar p-4 space-y-2">
          {filtered.length === 0 ? (
            <p className="text-white/20 text-sm font-light text-center py-8">No entries recorded.</p>
          ) : (
            [...filtered].reverse().map((entry, i) => (
              <div key={i} className="p-3.5 rounded-xl bg-white/[0.03] border border-white/5">
                <div className="flex items-center gap-2 mb-2">
                  <span className={`text-[10px] font-bold uppercase tracking-widest font-mono text-white/40 px-2 py-0.5 rounded border ${CATEGORY_COLORS[entry.category] || 'text-white/40 bg-white/[0.03] border-white/5'}`}>
                    {entry.category?.replace('_', ' ') || 'LOG'}
                  </span>
                  <span className="text-[10px] text-white/20 font-mono">
                    {entry.created_at?.slice(11, 19) || ''}
                  </span>
                </div>
                <p className="text-white text-sm font-light leading-relaxed">
                  {entry.summary}
                </p>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  )
}
