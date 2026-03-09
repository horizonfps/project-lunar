import { useState, useRef } from 'react'
import { createScenario, importScenario } from '../api'

const LANGUAGES = [
  { value: 'en', label: 'English' },
  { value: 'pt-br', label: 'Português (BR)' },
]

export default function ScenarioBuilder({ onCreated }) {
  const [form, setForm] = useState({
    title: '',
    description: '',
    tone_instructions: '',
    opening_narrative: '',
    language: 'en',
    lore_text: '',
  })
  const [importPayload, setImportPayload] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const fileRef = useRef(null)

  const update = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }))

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
        })
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
    setLoading(true)
    setError(null)
    try {
      let scenario
      if (importPayload) {
        scenario = await importScenario({
          ...importPayload,
          scenario: form,
        })
      } else {
        scenario = await createScenario(form)
      }
      onCreated?.(scenario)
    } catch {
      setError('Signal lost. Failed to connect to core systems (Backend offline?)')
    } finally {
      setLoading(false)
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
                      <option key={l.value} value={l.value} className="bg-white/[0.03] text-white">{l.label}</option>
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
                  <label className={labelClass}>Initialization Sequence</label>
                  <textarea
                    value={form.opening_narrative}
                    onChange={update('opening_narrative')}
                    placeholder="The opening scene presented to the user upon link..."
                    rows={4}
                    className={`${inputClass} resize-none`}
                  />
                </div>
              </div>

              {/* Row 4 */}
              <div>
                <label className="flex items-center justify-between mb-2 ml-1">
                  <span className="text-xs font-semibold text-white/60 uppercase tracking-wider">Lore Matrix</span>
                  <span className="text-[10px] uppercase font-bold text-white tracking-wider bg-white/10 px-2 py-0.5 rounded">Auto-Extract AI Enabled</span>
                </label>
                <textarea
                  value={form.lore_text}
                  onChange={update('lore_text')}
                  placeholder="Paste extensive world details, character backgrounds, and history here. The system will parse and extract entities."
                  rows={8}
                  className={inputClass}
                />
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