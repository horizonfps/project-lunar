import { Pencil, ArrowUp } from 'lucide-react'

/** Next-action options offered after a narrator turn. Send as-is or load into the input to edit. */
export default function SuggestionList({ suggestions, disabled, onSend, onEdit }) {
  if (!suggestions?.length) return null

  const toInput = (s) => (s.speech ? `[SAY] ${s.speech}` : `[DO] ${s.action}`)

  return (
    <div className="flex flex-col gap-2 mb-3">
      {suggestions.map((s, i) => (
        <div
          key={i}
          className="group flex items-center gap-2 rounded-xl border border-white/[0.06] bg-white/[0.02] hover:bg-white/[0.05] transition-colors"
        >
          <button
            type="button"
            disabled={disabled}
            onClick={() => onEdit?.(toInput(s))}
            title="Edit before sending"
            className="p-2.5 text-white/25 hover:text-white/70 disabled:opacity-30 transition-colors"
          >
            <Pencil size={14} />
          </button>
          <button
            type="button"
            disabled={disabled}
            onClick={() => onSend?.(toInput(s))}
            className="flex-1 text-left py-2.5 pr-1 text-sm font-light leading-relaxed disabled:opacity-40"
          >
            {s.action && <span className="text-white/40 italic mr-1.5">{s.action}</span>}
            {s.speech && <span className="text-white">&ldquo;{s.speech}&rdquo;</span>}
          </button>
          <button
            type="button"
            disabled={disabled}
            onClick={() => onSend?.(toInput(s))}
            title="Send"
            className="p-2.5 text-white/25 group-hover:text-white/70 disabled:opacity-30 transition-colors"
          >
            <ArrowUp size={14} />
          </button>
        </div>
      ))}
    </div>
  )
}
