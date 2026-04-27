import { useState, useRef } from 'react'
import { createScenario, importScenario, previewOpening } from '../api'

const LANGUAGES = [
  { value: 'en', label: 'English' },
  { value: 'pt-br', label: 'Português (BR)' },
]

const CARD_TYPES = ['NPC', 'LOCATION', 'FACTION', 'ITEM', 'LORE']

const newCard = () => ({
  card_type: 'NPC',
  name: '',
  contentText: '',
})

const QUESTION_TYPES = [
  { value: 'text', label: 'Text' },
  { value: 'choice', label: 'Choice' },
]

const uid = () =>
  (typeof crypto !== 'undefined' && crypto.randomUUID)
    ? crypto.randomUUID()
    : `q_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`

const newOption = () => ({ label: '', description: '' })

const newQuestion = () => ({
  id: uid(),
  var_name: '',
  prompt: '',
  type: 'text',
  options: [],
  allow_custom: false,
  required: true,
})

const questionsFromPayload = (payloadQuestions) => {
  if (!Array.isArray(payloadQuestions)) return []
  return payloadQuestions.map((q) => ({
    id: q?.id || uid(),
    var_name: q?.var_name || '',
    prompt: q?.prompt || '',
    type: q?.type === 'choice' ? 'choice' : 'text',
    options: Array.isArray(q?.options)
      ? q.options.map((o) => ({ label: o?.label || '', description: o?.description || '' }))
      : [],
    allow_custom: !!q?.allow_custom,
    required: q?.required !== false,
  }))
}

// Render a content dict as inner JSON lines (no outer braces, dedented 2 spaces).
const contentToInner = (content) => {
  const formatted = JSON.stringify(content || {}, null, 2)
  const lines = formatted.split('\n')
  if (lines.length < 2) return ''
  return lines
    .slice(1, -1)
    .map((l) => (l.startsWith('  ') ? l.slice(2) : l))
    .join('\n')
}

const cardsFromPayload = (payloadCards) => {
  if (!Array.isArray(payloadCards)) return []
  return payloadCards.map((c) => ({
    card_type: CARD_TYPES.includes(c?.card_type) ? c.card_type : 'NPC',
    name: c?.name || '',
    contentText: contentToInner(c?.content),
  }))
}

const escapeHtml = (s) =>
  s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')

// Tokenize "key": value pairs and wrap them in colored spans for the overlay.
const highlightContent = (text) => {
  if (!text) return ''
  const KEY = 'text-sky-300/90'
  const STRING = 'text-emerald-300/90'
  const NUMBER = 'text-violet-300/90'
  const LITERAL = 'text-rose-300/90'
  const PUNCT = 'text-white/40'

  let out = ''
  let i = 0
  let expectingValue = false

  while (i < text.length) {
    const ch = text[i]

    if (ch === '"') {
      let j = i + 1
      while (j < text.length) {
        if (text[j] === '\\' && j + 1 < text.length) { j += 2; continue }
        if (text[j] === '"') break
        j++
      }
      const end = j < text.length ? j : text.length - 1
      const str = text.slice(i, end + 1)
      const cls = expectingValue ? STRING : KEY
      out += `<span class="${cls}">${escapeHtml(str)}</span>`
      if (expectingValue) expectingValue = false
      i = end + 1
      continue
    }

    if (ch === ':') {
      out += `<span class="${PUNCT}">:</span>`
      expectingValue = true
      i++
      continue
    }

    if (ch === ',') {
      out += `<span class="${PUNCT}">,</span>`
      expectingValue = false
      i++
      continue
    }

    if (expectingValue) {
      const numMatch = text.slice(i).match(/^-?\d+(\.\d+)?([eE][+-]?\d+)?/)
      if (numMatch) {
        out += `<span class="${NUMBER}">${escapeHtml(numMatch[0])}</span>`
        i += numMatch[0].length
        expectingValue = false
        continue
      }
      let lit = null
      for (const candidate of ['true', 'false', 'null']) {
        if (text.startsWith(candidate, i)) { lit = candidate; break }
      }
      if (lit) {
        out += `<span class="${LITERAL}">${lit}</span>`
        i += lit.length
        expectingValue = false
        continue
      }
    }

    out += escapeHtml(ch)
    i++
  }
  return out
}

export default function ScenarioBuilder({ onCreated }) {
  const [form, setForm] = useState({
    title: '',
    description: '',
    tone_instructions: '',
    opening_narrative: '',
    language: 'en',
    lore_text: '',
    opening_mode: 'fixed',
    ai_opening_directive: '',
  })
  const [cards, setCards] = useState([])
  const [questions, setQuestions] = useState([])
  const [importPayload, setImportPayload] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [openingPreview, setOpeningPreview] = useState('')
  const [previewing, setPreviewing] = useState(false)
  const fileRef = useRef(null)

  const update = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }))

  const updateCard = (index, key, value) => {
    setCards((prev) => prev.map((c, i) => (i === index ? { ...c, [key]: value } : c)))
  }
  const addCard = () => setCards((prev) => [...prev, newCard()])
  const removeCard = (index) => setCards((prev) => prev.filter((_, i) => i !== index))

  const updateQuestion = (index, key, value) => {
    setQuestions((prev) => prev.map((q, i) => (i === index ? { ...q, [key]: value } : q)))
  }
  const addQuestion = () => setQuestions((prev) => [...prev, newQuestion()])
  const removeQuestion = (index) => setQuestions((prev) => prev.filter((_, i) => i !== index))
  const updateOption = (qIndex, oIndex, key, value) => {
    setQuestions((prev) => prev.map((q, i) => {
      if (i !== qIndex) return q
      return { ...q, options: q.options.map((o, j) => (j === oIndex ? { ...o, [key]: value } : o)) }
    }))
  }
  const addOption = (qIndex) => {
    setQuestions((prev) => prev.map((q, i) => (
      i === qIndex ? { ...q, options: [...q.options, newOption()] } : q
    )))
  }
  const removeOption = (qIndex, oIndex) => {
    setQuestions((prev) => prev.map((q, i) => (
      i === qIndex ? { ...q, options: q.options.filter((_, j) => j !== oIndex) } : q
    )))
  }

  const handleFileLoad = (e) => {
    const file = e.target.files[0]
    if (!file) return
    const reader = new FileReader()
    reader.onload = (ev) => {
      try {
        const parsed = JSON.parse(ev.target.result)
        if (!parsed.scenario || typeof parsed.scenario !== 'object' || Array.isArray(parsed.scenario)) {
          throw new Error('Invalid format')
        }
        setForm({
          title: parsed.scenario.title || '',
          description: parsed.scenario.description || '',
          tone_instructions: parsed.scenario.tone_instructions || '',
          opening_narrative: parsed.scenario.opening_narrative || '',
          language: parsed.scenario.language || 'en',
          lore_text: parsed.scenario.lore_text || '',
          opening_mode: parsed.scenario.opening_mode === 'ai' ? 'ai' : 'fixed',
          ai_opening_directive: parsed.scenario.ai_opening_directive || '',
        })
        setCards(cardsFromPayload(parsed.story_cards))
        setQuestions(questionsFromPayload(parsed.scenario.setup_questions))
        setImportPayload(parsed)
        setError(null)
      } catch (err) {
        if (err.message === 'Invalid format') {
          setError('Invalid structure. Missing "scenario" object.')
        } else {
          setError('Failed to parse JSON file.')
        }
      }
    }
    reader.readAsText(file)
    e.target.value = ''
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!form.title.trim()) return

    let parsedCards
    try {
      parsedCards = cards.map((c, i) => {
        if (!c.name.trim()) throw new Error(`Card #${i + 1} missing designation`)
        const raw = c.contentText.trim()
        const content = raw ? JSON.parse(`{${raw}}`) : {}
        return { card_type: c.card_type, name: c.name.trim(), content }
      })
    } catch (err) {
      setError(`Invalid story card: ${err.message}`)
      return
    }

    let parsedQuestions
    try {
      const seenVars = new Set()
      const VAR_RE = /^[a-z][a-z0-9_]*$/
      parsedQuestions = questions.map((q, i) => {
        const varName = (q.var_name || '').trim()
        const prompt = (q.prompt || '').trim()
        if (!varName) throw new Error(`Question #${i + 1} missing variable name`)
        if (!VAR_RE.test(varName)) throw new Error(`Question #${i + 1} var_name "${varName}" must be lowercase letters, digits, underscores (start with a letter)`)
        if (seenVars.has(varName)) throw new Error(`Duplicate var_name: ${varName}`)
        seenVars.add(varName)
        if (!prompt) throw new Error(`Question #${i + 1} missing prompt`)
        const type = q.type === 'choice' ? 'choice' : 'text'
        let options = []
        if (type === 'choice') {
          options = q.options
            .map((o) => ({ label: (o.label || '').trim(), description: (o.description || '').trim() }))
            .filter((o) => o.label)
          if (!q.allow_custom && options.length === 0) {
            throw new Error(`Question #${i + 1} ("${varName}") needs at least one option or allow_custom`)
          }
        }
        return {
          id: q.id || uid(),
          var_name: varName,
          prompt,
          type,
          options,
          allow_custom: !!q.allow_custom,
          required: q.required !== false,
        }
      })
    } catch (err) {
      setError(`Invalid setup question: ${err.message}`)
      return
    }

    setLoading(true)
    setError(null)
    try {
      const scenarioPayload = { ...form, setup_questions: parsedQuestions }
      let scenario
      if (importPayload || parsedCards.length > 0 || parsedQuestions.length > 0) {
        scenario = await importScenario({
          version: importPayload?.version || '1.0',
          scenario: scenarioPayload,
          story_cards: parsedCards,
          campaigns: importPayload?.campaigns || [],
        })
      } else {
        scenario = await createScenario(scenarioPayload)
      }
      onCreated?.(scenario)
    } catch {
      setError('Signal lost. Failed to connect to core systems (Backend offline?)')
    } finally {
      setLoading(false)
    }
  }

  const handlePreviewOpening = async () => {
    setPreviewing(true)
    setError(null)
    try {
      const sampleQuestions = questions
        .filter((q) => (q.var_name || '').trim())
        .map((q) => ({
          id: q.id || uid(),
          var_name: q.var_name.trim(),
          prompt: (q.prompt || '').trim() || q.var_name,
          type: q.type === 'choice' ? 'choice' : 'text',
          options: (q.options || [])
            .map((o) => ({ label: (o.label || '').trim(), description: (o.description || '').trim() }))
            .filter((o) => o.label),
          allow_custom: !!q.allow_custom,
          required: q.required !== false,
        }))
      const result = await previewOpening({
        language: form.language,
        tone: form.tone_instructions,
        lore: form.lore_text,
        directive: form.ai_opening_directive,
        setup_questions: sampleQuestions,
      })
      setOpeningPreview(result.opening || '')
    } catch {
      setError('Failed to generate preview. Check backend connection and API keys.')
    } finally {
      setPreviewing(false)
    }
  }

  const inputClass = "w-full bg-white/[0.03] backdrop-blur-sm border border-white/5 rounded-xl px-4 py-3 text-white placeholder-white/20 focus:outline-none focus:border-white/20  transition-all text-sm font-light";
  const labelClass = "block text-xs font-semibold text-white/60 uppercase tracking-wider mb-2 ml-1";

  return (
    <div className="min-h-screen bg-black bg-cover bg-center bg-fixed text-white selection:bg-white/10">
      <div className="min-h-screen bg-black/80 backdrop-blur-sm py-12 px-4 relative">
        <div className="max-w-3xl mx-auto relative z-10">
          
          <div className="mb-8">
            <a href="/" className="inline-flex items-center text-white/40 hover:text-white text-sm font-medium transition-colors tracking-wide">
              <span className="mr-2">←</span> Return to Orbit
            </a>
          </div>

          <div className="bg-white/[0.03] backdrop-blur-xl border border-white/5 rounded-[2rem] p-8 md:p-12 relative overflow-hidden">
            {/* Subtle inner glow */}
            <div className="absolute top-0 inset-x-0 h-px bg-gradient-to-r from-transparent via-white/20 to-transparent" />
            
            <div className="mb-10">
              <h1 className="text-3xl md:text-4xl font-bold text-white mb-2 tracking-tight">World Builder</h1>
              <p className="text-white/40 text-sm font-light">
                Define the parameters of your simulation. Input manual data or upload a pre-compiled JSON matrix.
              </p>
            </div>

            {/* Import Area */}
            <div className="mb-8 p-5 rounded-2xl bg-white/[0.03] border border-white/20 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
              <div>
                <p className="text-sm font-medium text-white mb-1">Data Injection</p>
                <p className="text-xs text-white/40">Load a complete world state from a JSON file.</p>
              </div>
              <input ref={fileRef} type="file" accept=".json" className="hidden" onChange={handleFileLoad} />
              <div className="flex items-center gap-3">
                <button
                  type="button"
                  onClick={() => fileRef.current?.click()}
                  className="whitespace-nowrap px-4 py-2 bg-white/10 hover:bg-white/10 text-white text-xs font-semibold uppercase tracking-wider rounded-lg border border-white/20 transition-colors"
                >
                  Upload Payload
                </button>
                {importPayload && <span className="text-xs text-emerald-400 font-medium px-2 py-1 bg-emerald-400/10 rounded">Loaded</span>}
              </div>
            </div>

            <form onSubmit={handleSubmit} className="space-y-8">
              {/* Row 1 */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div>
                  <label className={labelClass}>
                    Designation <span className="text-rose-400">*</span>
                  </label>
                  <input
                    value={form.title}
                    onChange={update('title')}
                    placeholder="e.g. Sector 7 Outpost"
                    required
                    className={inputClass}
                  />
                </div>
                <div>
                  <label className={labelClass}>Communication Protocol</label>
                  <select
                    value={form.language}
                    onChange={update('language')}
                    className={`${inputClass} appearance-none`}
                  >
                    {LANGUAGES.map((l) => (
                      <option key={l.value} value={l.value} className="bg-[#1a1a1a] text-white">{l.label}</option>
                    ))}
                  </select>
                </div>
              </div>

              {/* Row 2 */}
              <div>
                <label className={labelClass}>Abstract</label>
                <textarea
                  value={form.description}
                  onChange={update('description')}
                  placeholder="Brief overview of the scenario..."
                  rows={2}
                  className={`${inputClass} resize-none`}
                />
              </div>

              {/* Row 3 */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div>
                  <label className={labelClass}>Tone & Directives</label>
                  <textarea
                    value={form.tone_instructions}
                    onChange={update('tone_instructions')}
                    placeholder="Atmosphere, rules, style (e.g. Gritty cyberpunk, high stakes)"
                    rows={4}
                    className={`${inputClass} resize-none`}
                  />
                </div>
                <div>
                  <div className="flex items-center justify-between mb-2 ml-1">
                    <span className="text-xs font-semibold text-white/60 uppercase tracking-wider">
                      Initialization Sequence
                    </span>
                    <div className="flex bg-white/[0.03] border border-white/10 rounded-lg p-0.5">
                      {[
                        { value: 'fixed', label: 'Fixed Text' },
                        { value: 'ai', label: 'Generated by AI' },
                      ].map((opt) => {
                        const active = form.opening_mode === opt.value
                        return (
                          <button
                            key={opt.value}
                            type="button"
                            onClick={() => setForm((f) => ({ ...f, opening_mode: opt.value }))}
                            className={`px-3 py-1 text-[10px] uppercase tracking-wider font-bold rounded-md transition-colors ${
                              active ? 'bg-white text-black' : 'text-white/60 hover:text-white'
                            }`}
                          >
                            {opt.label}
                          </button>
                        )
                      })}
                    </div>
                  </div>
                  {form.opening_mode === 'fixed' ? (
                    <textarea
                      value={form.opening_narrative}
                      onChange={update('opening_narrative')}
                      placeholder="The opening scene presented to the user upon link… use {var_name} to interpolate setup answers."
                      rows={4}
                      className={`${inputClass} resize-none`}
                    />
                  ) : (
                    <>
                      <textarea
                        value={form.ai_opening_directive}
                        onChange={update('ai_opening_directive')}
                        placeholder="Optional director's note — guidance the AI must respect. Leave blank for a default atmospheric opening."
                        rows={4}
                        className={`${inputClass} resize-none`}
                      />
                      <div className="mt-3 flex items-center gap-3">
                        <button
                          type="button"
                          onClick={handlePreviewOpening}
                          disabled={previewing}
                          className="px-4 py-2 bg-white/10 hover:bg-white/20 disabled:opacity-40 text-white text-xs font-semibold uppercase tracking-wider rounded-lg border border-white/20 transition-colors"
                        >
                          {previewing ? 'Generating…' : 'Preview AI Opening'}
                        </button>
                        {!form.tone_instructions && !form.lore_text && (
                          <span className="text-[10px] text-white/40 italic">
                            Tip: richer tone/lore yields stronger openings.
                          </span>
                        )}
                      </div>
                      {openingPreview && (
                        <div className="mt-3 p-4 rounded-xl bg-black/40 border border-white/10 text-sm text-white/80 font-light leading-relaxed whitespace-pre-wrap max-h-72 overflow-y-auto">
                          {openingPreview}
                        </div>
                      )}
                    </>
                  )}
                </div>
              </div>

              {/* Row 4 — Story Cards */}
              <div>
                <label className="flex items-center justify-between mb-3 ml-1">
                  <span className="text-xs font-semibold text-white/60 uppercase tracking-wider">
                    Story Cards <span className="text-white/30 normal-case font-normal tracking-normal ml-1">— {cards.length} entries</span>
                  </span>
                  <span className="text-[10px] uppercase font-bold text-white tracking-wider bg-white/10 px-2 py-0.5 rounded">
                    NPCs · Locations · Factions · Items · Lore
                  </span>
                </label>

                <div className="space-y-3">
                  {cards.length === 0 && (
                    <div className="text-center text-white/30 text-xs py-6 border border-dashed border-white/10 rounded-xl">
                      No story cards. Upload a payload or add entries below.
                    </div>
                  )}

                  {cards.map((card, i) => (
                    <div
                      key={i}
                      className="p-4 rounded-xl bg-white/[0.02] border border-white/10 space-y-3"
                    >
                      <div className="flex items-center gap-3">
                        <div className="relative w-36">
                          <select
                            value={card.card_type}
                            onChange={(e) => updateCard(i, 'card_type', e.target.value)}
                            className={`${inputClass} appearance-none w-full py-2 pr-9 text-xs uppercase tracking-wider`}
                          >
                            {CARD_TYPES.map((t) => (
                              <option key={t} value={t} className="bg-[#1a1a1a] text-white">{t}</option>
                            ))}
                          </select>
                          <svg
                            className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-white/50"
                            viewBox="0 0 20 20"
                            fill="none"
                            stroke="currentColor"
                            strokeWidth="2"
                            strokeLinecap="round"
                            strokeLinejoin="round"
                          >
                            <polyline points="6 8 10 12 14 8" />
                          </svg>
                        </div>
                        <input
                          value={card.name}
                          onChange={(e) => updateCard(i, 'name', e.target.value)}
                          placeholder="Designation (e.g. Soren Arkhelion)"
                          className={`${inputClass} flex-1 py-2`}
                        />
                        <button
                          type="button"
                          onClick={() => removeCard(i)}
                          className="px-3 py-2 text-xs uppercase tracking-wider text-rose-300/70 hover:text-rose-300 hover:bg-rose-500/10 rounded-lg border border-rose-500/20 transition-colors"
                          aria-label={`Remove card ${i + 1}`}
                        >
                          Purge
                        </button>
                      </div>
                      <div className="flex items-center gap-2 ml-1">
                        <span className="text-[10px] uppercase tracking-wider text-white/40">Attributes</span>
                        <div className="relative group">
                          <span className="cursor-help text-[10px] text-white/40 group-hover:text-white border border-white/20 group-hover:border-white/60 rounded-full w-4 h-4 inline-flex items-center justify-center font-semibold transition-colors leading-none">?</span>
                          <div className="pointer-events-none absolute left-0 top-6 z-30 hidden group-hover:block w-80 p-3 bg-black/95 backdrop-blur-md border border-white/20 rounded-lg text-[11px] text-white/70 shadow-2xl space-y-2 normal-case tracking-normal font-light">
                            <p>
                              Each line is a <code className="text-sky-300/90">"key"</code><span className="text-white/40">:</span> <code className="text-emerald-300/90">"value"</code> pair, separated by <code className="text-white/40">,</code>
                            </p>
                            <p>Use any keys you want — common ones for NPCs: <code className="text-sky-300/90">"personality"</code>, <code className="text-sky-300/90">"power_level"</code>, <code className="text-sky-300/90">"secret"</code>.</p>
                            <pre className="bg-white/5 p-2 rounded text-[10px] font-mono leading-relaxed">
                              <span className="text-sky-300/90">"personality"</span><span className="text-white/40">:</span> <span className="text-emerald-300/90">"Calm and observant"</span><span className="text-white/40">,</span>{'\n'}
                              <span className="text-sky-300/90">"power_level"</span><span className="text-white/40">:</span> <span className="text-violet-300/90">7</span><span className="text-white/40">,</span>{'\n'}
                              <span className="text-sky-300/90">"secret"</span><span className="text-white/40">:</span> <span className="text-emerald-300/90">"Hidden agenda"</span>
                            </pre>
                            <p className="text-white/40">Values: strings (quoted), numbers, true/false/null.</p>
                          </div>
                        </div>
                      </div>
                      <div className="relative">
                        <pre
                          aria-hidden="true"
                          className="absolute inset-0 m-0 px-4 py-3 border border-transparent rounded-xl font-mono text-xs leading-relaxed whitespace-pre-wrap break-words pointer-events-none overflow-auto bg-transparent"
                          dangerouslySetInnerHTML={{ __html: highlightContent(card.contentText) + '\n' }}
                        />
                        <textarea
                          value={card.contentText}
                          onChange={(e) => updateCard(i, 'contentText', e.target.value)}
                          onScroll={(e) => {
                            const pre = e.currentTarget.previousElementSibling
                            if (pre) {
                              pre.scrollTop = e.currentTarget.scrollTop
                              pre.scrollLeft = e.currentTarget.scrollLeft
                            }
                          }}
                          placeholder={'"personality": "...",\n"power_level": 5,\n"secret": "..."'}
                          rows={6}
                          spellCheck={false}
                          className={`${inputClass} font-mono text-xs leading-relaxed resize-y caret-white relative bg-white/[0.03]`}
                          style={{ color: 'transparent', WebkitTextFillColor: 'transparent' }}
                        />
                      </div>
                    </div>
                  ))}

                  <button
                    type="button"
                    onClick={addCard}
                    className="w-full py-3 text-xs font-semibold uppercase tracking-[0.2em] text-white/60 hover:text-white border border-dashed border-white/15 hover:border-white/30 rounded-xl transition-colors"
                  >
                    + Inscribe Story Card
                  </button>
                </div>
              </div>

              {/* Row 5 — First-Play Setup */}
              <div>
                <label className="flex items-center justify-between mb-3 ml-1">
                  <span className="text-xs font-semibold text-white/60 uppercase tracking-wider">
                    First-Play Setup <span className="text-white/30 normal-case font-normal tracking-normal ml-1">— {questions.length} questions</span>
                  </span>
                  <span className="text-[10px] uppercase font-bold text-white tracking-wider bg-white/10 px-2 py-0.5 rounded">
                    Wizard before campaign starts
                  </span>
                </label>
                <p className="text-[11px] text-white/40 ml-1 mb-3">
                  Players answer these once when starting a campaign. Answers are locked into the LLM context as a permanent character setup.
                  Use <code className="text-sky-300/90">{'{var_name}'}</code> in a prompt to interpolate a previous answer (e.g. <code className="text-sky-300/90">{"\"{name}, what's your race?\""}</code>).
                </p>

                <div className="space-y-3">
                  {questions.length === 0 && (
                    <div className="text-center text-white/30 text-xs py-6 border border-dashed border-white/10 rounded-xl">
                      No setup questions. Players will jump straight into the opening narrative.
                    </div>
                  )}

                  {questions.map((q, i) => (
                    <div
                      key={q.id}
                      className="p-4 rounded-xl bg-white/[0.02] border border-white/10 space-y-3"
                    >
                      <div className="flex items-center gap-3">
                        <div className="relative w-32">
                          <select
                            value={q.type}
                            onChange={(e) => updateQuestion(i, 'type', e.target.value)}
                            className={`${inputClass} appearance-none w-full py-2 pr-9 text-xs uppercase tracking-wider`}
                          >
                            {QUESTION_TYPES.map((t) => (
                              <option key={t.value} value={t.value} className="bg-[#1a1a1a] text-white">{t.label}</option>
                            ))}
                          </select>
                          <svg
                            className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-white/50"
                            viewBox="0 0 20 20" fill="none" stroke="currentColor"
                            strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
                          >
                            <polyline points="6 8 10 12 14 8" />
                          </svg>
                        </div>
                        <input
                          value={q.var_name}
                          onChange={(e) => updateQuestion(i, 'var_name', e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, ''))}
                          placeholder="var_name (e.g. race)"
                          className={`${inputClass} flex-1 py-2 font-mono text-xs`}
                          spellCheck={false}
                        />
                        <label className="flex items-center gap-2 text-[10px] uppercase tracking-wider text-white/50 cursor-pointer">
                          <input
                            type="checkbox"
                            checked={q.required}
                            onChange={(e) => updateQuestion(i, 'required', e.target.checked)}
                            className="accent-white"
                          />
                          Required
                        </label>
                        <button
                          type="button"
                          onClick={() => removeQuestion(i)}
                          className="px-3 py-2 text-xs uppercase tracking-wider text-rose-300/70 hover:text-rose-300 hover:bg-rose-500/10 rounded-lg border border-rose-500/20 transition-colors"
                          aria-label={`Remove question ${i + 1}`}
                        >
                          Purge
                        </button>
                      </div>

                      <textarea
                        value={q.prompt}
                        onChange={(e) => updateQuestion(i, 'prompt', e.target.value)}
                        placeholder={"Question prompt — supports {var_name} interpolation, e.g. \"{name}, what's your race?\""}
                        rows={2}
                        className={`${inputClass} resize-none text-sm`}
                      />

                      {q.type === 'choice' && (
                        <div className="space-y-2 pl-3 border-l border-white/10">
                          <div className="flex items-center justify-between">
                            <span className="text-[10px] uppercase tracking-wider text-white/40">
                              Options ({q.options.length})
                            </span>
                            <label className="flex items-center gap-2 text-[10px] uppercase tracking-wider text-white/50 cursor-pointer">
                              <input
                                type="checkbox"
                                checked={q.allow_custom}
                                onChange={(e) => updateQuestion(i, 'allow_custom', e.target.checked)}
                                className="accent-white"
                              />
                              Allow custom answer
                            </label>
                          </div>
                          {q.options.map((o, j) => (
                            <div key={j} className="space-y-2 p-3 rounded-lg bg-white/[0.02] border border-white/5">
                              <div className="flex items-center gap-2">
                                <input
                                  value={o.label}
                                  onChange={(e) => updateOption(i, j, 'label', e.target.value)}
                                  placeholder="Option label (e.g. Three-eyed Pirate)"
                                  className={`${inputClass} flex-1 py-2 text-xs`}
                                />
                                <button
                                  type="button"
                                  onClick={() => removeOption(i, j)}
                                  className="px-2 py-1 text-[10px] uppercase tracking-wider text-rose-300/70 hover:text-rose-300 hover:bg-rose-500/10 rounded border border-rose-500/20 transition-colors"
                                >
                                  ×
                                </button>
                              </div>
                              <textarea
                                value={o.description}
                                onChange={(e) => updateOption(i, j, 'description', e.target.value)}
                                placeholder="Optional description (locked into LLM context if chosen)"
                                rows={2}
                                className={`${inputClass} resize-none text-xs`}
                              />
                            </div>
                          ))}
                          <button
                            type="button"
                            onClick={() => addOption(i)}
                            className="w-full py-2 text-[10px] font-semibold uppercase tracking-[0.2em] text-white/60 hover:text-white border border-dashed border-white/15 hover:border-white/30 rounded-lg transition-colors"
                          >
                            + Add Option
                          </button>
                        </div>
                      )}
                    </div>
                  ))}

                  <button
                    type="button"
                    onClick={addQuestion}
                    className="w-full py-3 text-xs font-semibold uppercase tracking-[0.2em] text-white/60 hover:text-white border border-dashed border-white/15 hover:border-white/30 rounded-xl transition-colors"
                  >
                    + Add Question
                  </button>
                </div>
              </div>

              {error && (
                <div className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/20 flex items-center gap-3 text-rose-300 text-sm font-medium">
                  <span className="text-xl">!</span> {error}
                </div>
              )}

              <div className="pt-4 border-t border-white/5">
                <button
                  type="submit"
                  disabled={loading || !form.title.trim()}
                  className="w-full bg-white text-black hover:bg-gray-200 uppercase text-sm tracking-[0.2em] font-bold rounded-full py-4 tracking-widest flex items-center justify-center gap-2"
                >
                  {loading && (
                    <svg className="animate-spin -ml-1 mr-2 h-4 w-4 text-white" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                    </svg>
                  )}
                  {loading
                    ? (importPayload ? 'Processing Import...' : 'Compiling World...')
                    : (importPayload ? 'Execute Import' : 'Initialize Scenario')}
                </button>
              </div>
            </form>
          </div>
        </div>
      </div>
    </div>
  )
}