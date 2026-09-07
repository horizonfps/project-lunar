import { useState, useEffect, useRef, useCallback } from 'react'
import { Send } from 'lucide-react'
import { fetchCharacters } from '../api'
import { useGameStore } from '../store'

const ACTION_TYPES = [
  { id: 'DO', label: 'Do', description: 'Perform an action' },
  { id: 'SAY', label: 'Say', description: 'Speak or communicate' },
  { id: 'CONTINUE', label: 'Continue', description: 'Let the story flow' },
  { id: 'META', label: 'Meta', description: 'Talk to the AI narrator' },
]

export default function ActionInput({ onSubmit, disabled, draft }) {
  const [text, setText] = useState('')
  const [type, setType] = useState('DO')
  const [mentionState, setMentionState] = useState(null) // { startIndex, query }
  const [mentionResults, setMentionResults] = useState([])
  const [mentionIndex, setMentionIndex] = useState(0)
  const textareaRef = useRef(null)
  const dropdownRef = useRef(null)
  const campaignId = useGameStore((s) => s.activeCampaignId)

  // Load an externally supplied "[TYPE] text" draft into the field for editing
  useEffect(() => {
    if (!draft?.text) return
    const match = draft.text.match(/^\[(DO|SAY|CONTINUE|META)\]\s*/i)
    setType(match ? match[1].toUpperCase() : 'DO')
    setText(match ? draft.text.slice(match[0].length) : draft.text)
    textareaRef.current?.focus()
  }, [draft])

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

  // Fetch characters when mention query changes
  useEffect(() => {
    if (!mentionState || !campaignId) {
      setMentionResults([])
      return
    }
    let cancelled = false
    const timer = setTimeout(async () => {
      try {
        const chars = await fetchCharacters(campaignId, mentionState.query)
        if (!cancelled) {
          setMentionResults(chars)
          setMentionIndex(0)
        }
      } catch {
        if (!cancelled) setMentionResults([])
      }
    }, 100) // Small debounce
    return () => { cancelled = true; clearTimeout(timer) }
  }, [mentionState, campaignId])

  const closeMention = useCallback(() => {
    setMentionState(null)
    setMentionResults([])
    setMentionIndex(0)
  }, [])

  const insertMention = useCallback((charName) => {
    if (!mentionState) return
    const before = text.slice(0, mentionState.startIndex)
    const after = text.slice(mentionState.startIndex + mentionState.query.length + 1) // +1 for @
    const newText = `${before}@${charName}${after}`
    setText(newText)
    closeMention()
    // Refocus textarea
    setTimeout(() => textareaRef.current?.focus(), 0)
  }, [mentionState, text, closeMention])

  const handleTextChange = (e) => {
    const value = e.target.value
    setText(value)

    // Detect @ mention trigger
    const cursorPos = e.target.selectionStart
    const textBeforeCursor = value.slice(0, cursorPos)
    const atMatch = textBeforeCursor.match(/@([^\s@]*)$/)

    if (atMatch) {
      const startIndex = cursorPos - atMatch[0].length
      setMentionState({ startIndex, query: atMatch[1] })
    } else {
      closeMention()
    }
  }

  const handleSubmit = (e) => {
    e.preventDefault()
    if (mentionState && mentionResults.length > 0) return // Don't submit while picking mention
    const trimmed = text.trim()
    if (!trimmed && type !== 'CONTINUE' || disabled) return
    onSubmit(type === 'CONTINUE' ? '[CONTINUE]' : `[${type}] ${trimmed}`)
    setText('')
    closeMention()
  }

  const handleKeyDown = (e) => {
    // Handle mention dropdown navigation
    if (mentionState && mentionResults.length > 0) {
      if (e.key === 'ArrowDown') {
        e.preventDefault()
        setMentionIndex((prev) => Math.min(prev + 1, mentionResults.length - 1))
        return
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault()
        setMentionIndex((prev) => Math.max(prev - 1, 0))
        return
      }
      if (e.key === 'Enter' || e.key === 'Tab') {
        e.preventDefault()
        insertMention(mentionResults[mentionIndex].name)
        return
      }
      if (e.key === 'Escape') {
        e.preventDefault()
        closeMention()
        return
      }
    }

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
              ref={textareaRef}
              value={text}
              onChange={handleTextChange}
              onKeyDown={handleKeyDown}
              disabled={disabled}
              placeholder={
                disabled
                  ? 'Receiving transmission...'
                  : type === 'DO'
                  ? 'Input action directive... (use @ to mention characters)'
                  : type === 'SAY'
                  ? 'Input verbal communication... (use @ to mention characters)'
                  : 'Input system command...'
              }
              rows={2}
              className="w-full bg-white/[0.03] border border-white/10 rounded-xl px-5 py-3.5 text-white placeholder-white/20 focus:outline-none focus:border-white/40 focus:bg-white/[0.05] resize-none text-sm font-light transition-all custom-scrollbar leading-relaxed"
            />
            {/* @-mention autocomplete dropdown */}
            {mentionState && mentionResults.length > 0 && (
              <div
                ref={dropdownRef}
                className="absolute bottom-full left-0 mb-2 w-72 max-h-48 overflow-y-auto bg-lunar-900 border border-white/20 rounded-lg shadow-xl z-50"
              >
                {mentionResults.map((char, i) => (
                  <button
                    key={char.name}
                    type="button"
                    onClick={() => insertMention(char.name)}
                    className={`w-full text-left px-4 py-2.5 text-sm flex items-center gap-3 transition-colors
                      ${i === mentionIndex
                        ? 'bg-indigo-500/20 text-white'
                        : 'text-white/70 hover:bg-white/5 hover:text-white'
                      }`}
                  >
                    <span className="text-indigo-400 text-xs font-mono shrink-0">@</span>
                    <div className="min-w-0">
                      <div className="font-medium truncate">{char.name}</div>
                      {char.aliases?.length > 0 && (
                        <div className="text-xs text-white/30 truncate">
                          aka {char.aliases.join(', ')}
                        </div>
                      )}
                    </div>
                    <span className="ml-auto text-xs text-white/20 uppercase shrink-0">{char.type}</span>
                  </button>
                ))}
              </div>
            )}
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
