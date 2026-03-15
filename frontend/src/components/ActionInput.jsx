import { useState, useEffect } from 'react'
import { Send } from 'lucide-react'

const ACTION_TYPES = [
  { id: 'DO', label: 'Do', description: 'Perform an action' },
  { id: 'SAY', label: 'Say', description: 'Speak or communicate' },
  { id: 'CONTINUE', label: 'Continue', description: 'Let the story flow' },
  { id: 'META', label: 'Meta', description: 'Talk to the AI narrator' },
]

export default function ActionInput({ onSubmit, disabled }) {
  const [text, setText] = useState('')
  const [type, setType] = useState('DO')

  // Listen to keyboard shortcut for continue
  useEffect(() => {
    const handleGlobalKey = (e) => {
      // Ctrl+Enter or Cmd+Enter defaults to continue if empty text
      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
        if (!text.trim() && !disabled) {
          e.preventDefault()
          onSubmit('[CONTINUE]')
        }
      }
    }
    window.addEventListener('keydown', handleGlobalKey)
    return () => window.removeEventListener('keydown', handleGlobalKey)
  }, [text, disabled, onSubmit])

  const handleSubmit = (e) => {
    e.preventDefault()
    const trimmed = text.trim()
    if (!trimmed && type !== 'CONTINUE' || disabled) return
    onSubmit(type === 'CONTINUE' ? '[CONTINUE]' : `[${type}] ${trimmed}`)
    setText('')
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit(e)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="p-4 md:p-6 max-w-4xl mx-auto w-full">
      <div className="flex gap-2 mb-3">
        {ACTION_TYPES.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => {
              setType(t.id)
              if (t.id === 'CONTINUE') setText('')
            }}
            title={t.description}
            className={`px-4 py-2.5 sm:py-1.5 rounded-lg text-xs font-bold uppercase tracking-widest transition-all duration-200 min-h-[44px] sm:min-h-0
              ${type === t.id
                ? 'bg-white/10 text-white border border-white/20 shadow-[0_0_10px_rgba(99,102,241,0.2)]'
                : 'bg-transparent text-white/20 hover:text-white/60 hover:bg-white/5 border border-transparent'
              }`}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div className="flex gap-3 items-end">
        {type === 'CONTINUE' ? (
          <button
            type="button"
            onClick={handleSubmit}
            disabled={disabled}
            className="flex-1 text-left bg-white/[0.03] border border-white/20 rounded-xl px-5 py-3.5 text-white hover:bg-white/[0.03] hover:border-white/20 transition-all font-light text-sm group disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
          >
            <span className="opacity-70 group-hover:opacity-100 transition-opacity">Press Enter to proceed with the simulation...</span>
          </button>
        ) : (
          <div className="flex-1 relative">
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={disabled}
              placeholder={
                disabled
                  ? 'Receiving transmission...'
                  : type === 'DO'
                  ? 'Input action directive...'
                  : type === 'SAY'
                  ? 'Input verbal communication...'
                  : 'Input system command...'
              }
              rows={2}
              className="w-full bg-white/[0.03] border border-white/10 rounded-xl px-5 py-3.5 text-white placeholder-white/20 focus:outline-none focus:border-white/40 focus:bg-white/[0.05] resize-none text-sm font-light transition-all custom-scrollbar leading-relaxed"
            />
          </div>
        )}
        <button
          type="submit"
          disabled={disabled || (type !== 'CONTINUE' && !text.trim())}
          className="bg-white text-black hover:bg-gray-200 uppercase text-sm tracking-[0.2em] font-bold rounded-full px-5 py-3.5 h-[52px] flex items-center justify-center shrink-0 border border-white/20"
          title="Send command (Enter)"
        >
          <Send size={18} className="transform translate-x-[-1px] translate-y-[1px]" />
        </button>
      </div>
    </form>
  )
}