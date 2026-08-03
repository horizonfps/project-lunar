import { useState, useEffect } from 'react'
import { Terminal, X, Trash2, ChevronRight } from 'lucide-react'

const fmtTok = (n) => {
  const v = Number(n) || 0
  if (v >= 1000) return `${(v / 1000).toFixed(1)}k`
  return String(v)
}

const TAG_COLORS = {
  narrator: 'text-emerald-400 border-emerald-400/30 bg-emerald-400/10',
  auditor: 'text-amber-400 border-amber-400/30 bg-amber-400/10',
  combat: 'text-rose-400 border-rose-400/30 bg-rose-400/10',
  npc_mind: 'text-indigo-400 border-indigo-400/30 bg-indigo-400/10',
  memory: 'text-sky-400 border-sky-400/30 bg-sky-400/10',
}
const tagColor = (tag) =>
  TAG_COLORS[tag] || 'text-white/60 border-white/15 bg-white/5'

const fmtDateTime = (iso) => {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

const truncate = (s, n) => {
  if (!s) return ''
  return s.length > n ? `${s.slice(0, n)}…` : s
}

function turnTotals(entries) {
  return (entries || []).reduce(
    (acc, e) => {
      const u = e.usage || {}
      acc.input += u.input || 0
      acc.output += u.output || 0
      acc.cacheRead += u.cache_read || 0
      acc.cacheWrite += u.cache_creation || 0
      return acc
    },
    { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }
  )
}

function CallCard({ entry }) {
  const [openInput, setOpenInput] = useState(false)
  const [openOutput, setOpenOutput] = useState(true)
  const u = entry.usage || {}
  return (
    <div className="rounded-xl bg-white/[0.03] border border-white/5 overflow-hidden">
      <div className="px-4 py-3 flex items-center gap-2 flex-wrap border-b border-white/5">
        <span className="text-white/30 text-xs font-mono">#{entry.seq}</span>
        <span className={`text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full border ${tagColor(entry.tag)}`}>
          {entry.tag}
        </span>
        <span className="text-white/60 text-xs font-mono truncate max-w-[280px]" title={entry.label}>
          {entry.label}
        </span>
        <span className="text-white/20 text-[10px] font-mono ml-auto">{entry.model}</span>
      </div>
      <div className="px-4 py-2 flex items-center gap-3 flex-wrap text-[11px] font-mono text-white/40">
        <span>in <span className="text-white/70">{fmtTok(u.input)}</span></span>
        <span>out <span className="text-white/70">{fmtTok(u.output)}</span></span>
        {u.cache_read > 0 && <span className="text-emerald-400/70">cache_r {fmtTok(u.cache_read)}</span>}
        {u.cache_creation > 0 && <span className="text-sky-400/70">cache_w {fmtTok(u.cache_creation)}</span>}
        <span>sys {fmtTok(entry.instructions_chars)}ch</span>
        <span className="text-white/25">{entry.elapsed_s}s</span>
      </div>

      <div className="px-4 pb-3 space-y-2">
        <button
          onClick={() => setOpenOutput((v) => !v)}
          className="flex items-center gap-1 text-[10px] uppercase tracking-widest font-bold text-white/50 hover:text-white transition-colors"
        >
          <ChevronRight size={12} className={`transition-transform ${openOutput ? 'rotate-90' : ''}`} />
          Output
        </button>
        {openOutput && (
          <pre className="text-[11px] leading-relaxed text-[#d1d1d1] font-mono whitespace-pre-wrap break-words bg-black/40 rounded-lg p-3 max-h-64 overflow-auto custom-scrollbar">
            {typeof entry.output === 'string' ? entry.output : JSON.stringify(entry.output, null, 2)}
          </pre>
        )}

        <button
          onClick={() => setOpenInput((v) => !v)}
          className="flex items-center gap-1 text-[10px] uppercase tracking-widest font-bold text-white/50 hover:text-white transition-colors"
        >
          <ChevronRight size={12} className={`transition-transform ${openInput ? 'rotate-90' : ''}`} />
          Input ({(entry.input || []).length} sections)
        </button>
        {openInput && (
          <div className="space-y-2">
            {(entry.input || []).map((s, i) => (
              <div key={i}>
                <div className="text-[10px] uppercase tracking-widest font-bold text-white/40 mb-1">
                  {s.title}{s.truncated ? ' · truncated' : ''}
                </div>
                <pre className="text-[11px] leading-relaxed text-white/70 font-mono whitespace-pre-wrap break-words bg-black/40 rounded-lg p-3 max-h-72 overflow-auto custom-scrollbar">
                  {s.body}
                </pre>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

export default function DevtoolsPanel({ open, onClose, traces, onClear }) {
  const [selectedKey, setSelectedKey] = useState(null)

  useEffect(() => {
    if (open && traces.length) setSelectedKey(traces[traces.length - 1].key)
  }, [open, traces])

  if (!open) return null

  const current = traces.find((t) => t.key === selectedKey) || traces[traces.length - 1] || null
  const tot = current ? turnTotals(current.entries) : null
  const currentEntries = current?.entries || []

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm">
      <div className="bg-white/[0.03] backdrop-blur-xl border border-white/5 rounded-[2rem] w-full max-w-5xl mx-4 overflow-hidden max-h-[85vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-white/5 flex-none">
          <div className="flex items-center gap-3">
            <Terminal size={16} className="text-white" />
            <h2 className="text-white font-bold text-sm uppercase tracking-widest">LLM Devtools</h2>
            <span className="text-white/30 text-xs font-mono">{traces.length} turns saved</span>
          </div>
          <div className="flex items-center gap-2">
            {traces.length > 0 && (
              <button
                onClick={onClear}
                className="text-white/40 hover:text-rose-400 transition-colors p-1"
                title="Clear captured traces"
              >
                <Trash2 size={14} />
              </button>
            )}
            <button onClick={onClose} className="text-white/40 hover:text-white transition-colors">
              <X size={18} />
            </button>
          </div>
        </div>

        {traces.length === 0 ? (
          <div className="flex-1 flex flex-col items-center justify-center py-16">
            <Terminal size={32} className="text-white/20 mb-3" />
            <p className="text-white/20 text-sm font-light">
              No calls captured yet. Take an action to trace the turn's LLM calls.
            </p>
          </div>
        ) : (
          <div className="flex flex-1 overflow-hidden">
            {/* Turn list */}
            <div className="w-40 flex-none border-r border-white/5 overflow-y-auto custom-scrollbar py-2">
              {[...traces].reverse().map((t) => (
                <button
                  key={t.key}
                  onClick={() => setSelectedKey(t.key)}
                  className={`w-full text-left px-4 py-2 text-xs font-mono transition-colors ${
                    (current && t.key === current.key)
                      ? 'text-white bg-white/10'
                      : 'text-white/40 hover:text-white hover:bg-white/5'
                  }`}
                >
                  {t.label}
                  {t.created_at && (
                    <span className="block text-[10px] text-white/25">{fmtDateTime(t.created_at)}</span>
                  )}
                  {t.action && (
                    <span className="block text-[10px] text-white/25 truncate" title={t.action}>
                      {truncate(t.action, 40)}
                    </span>
                  )}
                  <span className="block text-[10px] text-white/25">{(t.entries || []).length} calls</span>
                </button>
              ))}
            </div>

            {/* Calls of selected turn */}
            <div className="flex-1 overflow-y-auto custom-scrollbar p-6 space-y-3">
              {current && (
                <div className="flex items-center gap-3 flex-wrap text-[11px] font-mono text-white/40 pb-2">
                  <span className="text-white/60 uppercase tracking-widest font-bold text-[10px]">Turn total</span>
                  <span>in <span className="text-white/70">{fmtTok(tot.input)}</span></span>
                  <span>out <span className="text-white/70">{fmtTok(tot.output)}</span></span>
                  {tot.cacheRead > 0 ? (
                    <span className="text-emerald-400/70">cache_r {fmtTok(tot.cacheRead)} · cache_w {fmtTok(tot.cacheWrite)}</span>
                  ) : (
                    <span className="text-amber-400/60">cache off</span>
                  )}
                  <span className="text-white/25">{currentEntries.length} calls</span>
                </div>
              )}
              {currentEntries.map((e) => (
                <CallCard key={e.seq} entry={e} />
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
