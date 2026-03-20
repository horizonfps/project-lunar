import { useState } from 'react'
import { useGameStore } from '../store'
import { Settings, X } from 'lucide-react'

const PROVIDERS = [
  { id: 'deepseek', label: 'DeepSeek', models: ['deepseek-chat', 'deepseek-reasoner'] },
  { id: 'anthropic', label: 'Anthropic', models: ['claude-sonnet-4-6', 'claude-opus-4-6'] },
  { id: 'openai', label: 'OpenAI', models: ['gpt-4o', 'gpt-4o-mini'] },
]

export default function SettingsPanel({ open, onClose }) {
  const { llmProvider, llmModel, temperature, maxTokens, updateSettings } = useGameStore()
  const [provider, setProvider] = useState(llmProvider)
  const [model, setModel] = useState(llmModel)
  const [temp, setTemp] = useState(temperature)
  const [tokens, setTokens] = useState(maxTokens)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  const currentProviderModels = PROVIDERS.find((p) => p.id === provider)?.models || []

  const handleProviderChange = (newProvider) => {
    setProvider(newProvider)
    const providerModels = PROVIDERS.find((p) => p.id === newProvider)?.models || []
    setModel(providerModels[0] || '')
  }

  const handleSave = async () => {
    setSaving(true)
    try {
      await fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          provider,
          model,
          temperature: temp,
          max_tokens: tokens,
        }),
      })
      updateSettings({
        llmProvider: provider,
        llmModel: model,
        temperature: temp,
        maxTokens: tokens,
      })
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    } catch {
      // silent fail — settings still update locally
      updateSettings({
        llmProvider: provider,
        llmModel: model,
        temperature: temp,
        maxTokens: tokens,
      })
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm">
      <div className="bg-white/[0.03] backdrop-blur-xl border border-white/5 rounded-[2rem] w-full max-w-md mx-4 overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-white/5">
          <div className="flex items-center gap-3">
            <Settings size={16} className="text-white" />
            <h2 className="text-white font-bold text-sm uppercase tracking-widest">Settings</h2>
          </div>
          <button onClick={onClose} className="text-white/40 hover:text-white transition-colors">
            <X size={18} />
          </button>
        </div>

        <div className="p-6 space-y-6">
          {/* Provider */}
          <div>
            <label className="block text-[10px] font-bold uppercase tracking-widest font-mono text-white/40 mb-2">
              LLM Provider
            </label>
            <select
              value={provider}
              onChange={(e) => handleProviderChange(e.target.value)}
              className="w-full bg-white/[0.03] border border-white/10 rounded-lg px-4 py-2.5 text-sm text-white focus:outline-none focus:border-white/40 focus:bg-white/[0.05] transition-all"
            >
              {PROVIDERS.map((p) => (
                <option key={p.id} value={p.id} className="bg-[#1a1a1a] text-white">{p.label}</option>
              ))}
            </select>
          </div>

          {/* Model */}
          <div>
            <label className="block text-[10px] font-bold uppercase tracking-widest font-mono text-white/40 mb-2">
              Model
            </label>
            <select
              value={model}
              onChange={(e) => setModel(e.target.value)}
              className="w-full bg-white/[0.03] border border-white/10 rounded-lg px-4 py-2.5 text-sm text-white focus:outline-none focus:border-white/40 focus:bg-white/[0.05] transition-all"
            >
              {currentProviderModels.map((m) => (
                <option key={m} value={m} className="bg-[#1a1a1a] text-white">{m}</option>
              ))}
            </select>
          </div>

          {/* Temperature */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <label className="text-[10px] font-bold uppercase tracking-widest font-mono text-white/40">
                Temperature
              </label>
              <span className="text-xs text-white font-mono">{temp.toFixed(2)}</span>
            </div>
            <input
              type="range"
              min={0}
              max={2}
              step={0.05}
              value={temp}
              onChange={(e) => setTemp(parseFloat(e.target.value))}
              className="w-full accent-white h-1.5 bg-white/[0.03] rounded-full appearance-none cursor-pointer [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-4 [&::-webkit-slider-thumb]:h-4 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-white/10 [&::-webkit-slider-thumb]:shadow-[0_0_8px_rgba(99,102,241,0.6)]"
            />
            <div className="flex justify-between text-[9px] text-white/20 mt-1">
              <span>Precise</span>
              <span>Balanced</span>
              <span>Creative</span>
            </div>
          </div>

          {/* Max Tokens */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <label className="text-[10px] font-bold uppercase tracking-widest font-mono text-white/40">
                Max Tokens
              </label>
              <span className="text-xs text-white font-mono">{tokens}</span>
            </div>
            <input
              type="range"
              min={256}
              max={8192}
              step={256}
              value={tokens}
              onChange={(e) => setTokens(parseInt(e.target.value))}
              className="w-full accent-white h-1.5 bg-white/[0.03] rounded-full appearance-none cursor-pointer [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-4 [&::-webkit-slider-thumb]:h-4 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-white/10 [&::-webkit-slider-thumb]:shadow-[0_0_8px_rgba(99,102,241,0.6)]"
            />
            <div className="flex justify-between text-[9px] text-white/20 mt-1">
              <span>Short</span>
              <span>Standard</span>
              <span>Extended</span>
            </div>
          </div>

          {/* Save */}
          <button
            onClick={handleSave}
            disabled={saving}
            className="w-full bg-white text-black hover:bg-gray-200 uppercase text-sm tracking-[0.2em] font-bold rounded-full px-6 py-3 rounded-lg font-semibold tracking-wide border border-white/20"
          >
            {saved ? 'Saved!' : saving ? 'Applying...' : 'Apply Settings'}
          </button>
        </div>
      </div>
    </div>
  )
}
