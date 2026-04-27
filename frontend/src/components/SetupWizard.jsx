import { useMemo, useState } from 'react'
import { saveSetupAnswers } from '../api'
import { interpolate } from '../lib/interpolate'

export default function SetupWizard({ scenario, campaignId, questions, onComplete }) {
  const ordered = useMemo(() => questions.filter(Boolean), [questions])
  const total = ordered.length
  const [step, setStep] = useState(0)
  const [answers, setAnswers] = useState({})
  const [textValue, setTextValue] = useState('')
  const [choiceLabel, setChoiceLabel] = useState(null)
  const [customValue, setCustomValue] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(null)

  const current = ordered[step]
  const resolvedPrompt = useMemo(
    () => interpolate(current?.prompt || '', answers),
    [current, answers],
  )

  const isLast = step === total - 1
  const optionByLabel = (label) =>
    (current?.options || []).find((o) => o.label === label) || null

  const canAdvance = () => {
    if (!current) return false
    if (current.type === 'text') {
      return !current.required || textValue.trim().length > 0
    }
    if (choiceLabel === '__custom__') {
      return !current.required || customValue.trim().length > 0
    }
    return !current.required || choiceLabel !== null
  }

  const buildAnswer = () => {
    if (!current) return null
    if (current.type === 'text') {
      return {
        var_name: current.var_name,
        resolved_prompt: resolvedPrompt,
        type: 'text',
        value: textValue.trim(),
        description: '',
      }
    }
    if (choiceLabel === '__custom__') {
      return {
        var_name: current.var_name,
        resolved_prompt: resolvedPrompt,
        type: 'choice',
        value: customValue.trim(),
        description: '',
      }
    }
    const opt = optionByLabel(choiceLabel)
    return {
      var_name: current.var_name,
      resolved_prompt: resolvedPrompt,
      type: 'choice',
      value: opt?.label || '',
      description: opt?.description || '',
    }
  }

  const loadStepIntoLocalState = (nextStep, allAnswers) => {
    const q = ordered[nextStep]
    const existing = q ? allAnswers[q.var_name] : null
    if (q?.type === 'text') {
      setTextValue(existing?.value || '')
      setChoiceLabel(null)
      setCustomValue('')
    } else {
      setTextValue('')
      if (existing) {
        const knownOpt = (q.options || []).find((o) => o.label === existing.value)
        if (knownOpt) {
          setChoiceLabel(knownOpt.label)
          setCustomValue('')
        } else {
          setChoiceLabel('__custom__')
          setCustomValue(existing.value || '')
        }
      } else {
        setChoiceLabel(null)
        setCustomValue('')
      }
    }
  }

  const handleNext = async () => {
    if (!canAdvance()) return
    const answer = buildAnswer()
    if (!answer) return
    const updated = { ...answers, [current.var_name]: answer }
    setAnswers(updated)

    if (!isLast) {
      const next = step + 1
      setStep(next)
      loadStepIntoLocalState(next, updated)
      return
    }

    setSubmitting(true)
    setError(null)
    try {
      await saveSetupAnswers(campaignId, updated)
      onComplete?.()
    } catch (err) {
      setError('Failed to save your character. Try again.')
      setSubmitting(false)
    }
  }

  const handleBack = () => {
    if (step === 0) return
    const prev = step - 1
    setStep(prev)
    loadStepIntoLocalState(prev, answers)
  }

  if (!current) {
    return (
      <div className="min-h-screen bg-black text-white flex items-center justify-center">
        <p className="text-white/40 text-sm">No setup questions defined.</p>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-black text-white selection:bg-white/10">
      <div className="min-h-screen bg-black/80 backdrop-blur-sm py-12 px-4">
        <div className="max-w-3xl mx-auto">
          {/* Header */}
          <div className="flex items-baseline justify-between mb-12 pb-4 border-b border-white/10">
            <div>
              <p className="text-[10px] uppercase tracking-[0.3em] text-white/40 font-mono mb-1">
                Initialization
              </p>
              <h1 className="text-2xl md:text-3xl font-bold tracking-tight">
                {scenario?.title || 'Character Setup'}
              </h1>
            </div>
            <p className="text-[10px] uppercase tracking-[0.3em] text-white/40 font-mono">
              Step {step + 1} of {total}
            </p>
          </div>

          {/* Prompt */}
          <div className="mb-10">
            <p className="text-xl md:text-2xl font-light leading-relaxed text-white/90 whitespace-pre-line">
              {resolvedPrompt}
            </p>
          </div>

          {/* Body */}
          <div className="mb-10">
            {current.type === 'text' && (
              <textarea
                autoFocus
                value={textValue}
                onChange={(e) => setTextValue(e.target.value)}
                placeholder="Type your answer…"
                rows={3}
                className="w-full bg-white/[0.03] backdrop-blur-sm border border-white/10 rounded-2xl px-5 py-4 text-white placeholder-white/20 focus:outline-none focus:border-white/30 transition-all text-base font-light resize-none"
              />
            )}

            {current.type === 'choice' && (
              <div className="space-y-3">
                {(current.options || []).map((opt) => {
                  const selected = choiceLabel === opt.label
                  return (
                    <button
                      type="button"
                      key={opt.label}
                      onClick={() => setChoiceLabel(opt.label)}
                      className={`w-full text-left p-5 rounded-2xl border transition-all flex items-start gap-4 ${
                        selected
                          ? 'bg-white/[0.08] border-white/40'
                          : 'bg-white/[0.02] border-white/10 hover:border-white/25'
                      }`}
                    >
                      <span
                        className={`mt-1 inline-block w-3 h-3 rounded-full border ${
                          selected ? 'bg-white border-white' : 'border-white/30'
                        }`}
                      />
                      <span className="flex-1">
                        <span className="block font-semibold text-white text-base mb-1">
                          {opt.label}
                        </span>
                        {opt.description && (
                          <span className="block text-sm text-white/50 leading-relaxed font-light">
                            {opt.description}
                          </span>
                        )}
                      </span>
                    </button>
                  )
                })}

                {current.allow_custom && (
                  <div
                    className={`p-5 rounded-2xl border transition-all ${
                      choiceLabel === '__custom__'
                        ? 'bg-white/[0.08] border-white/40'
                        : 'bg-white/[0.02] border-white/10 hover:border-white/25'
                    }`}
                  >
                    <button
                      type="button"
                      onClick={() => setChoiceLabel('__custom__')}
                      className="w-full flex items-center gap-4 text-left"
                    >
                      <span
                        className={`mt-0 inline-block w-3 h-3 rounded-full border ${
                          choiceLabel === '__custom__' ? 'bg-white border-white' : 'border-white/30'
                        }`}
                      />
                      <span className="font-semibold text-white text-base">Custom</span>
                    </button>
                    {choiceLabel === '__custom__' && (
                      <input
                        autoFocus
                        value={customValue}
                        onChange={(e) => setCustomValue(e.target.value)}
                        placeholder="Type your custom answer…"
                        className="mt-3 w-full bg-black/30 border border-white/10 rounded-xl px-4 py-3 text-white placeholder-white/20 focus:outline-none focus:border-white/30 text-sm font-light"
                      />
                    )}
                  </div>
                )}
              </div>
            )}
          </div>

          {error && (
            <div className="mb-6 p-4 rounded-xl bg-rose-500/10 border border-rose-500/20 text-rose-300 text-sm font-medium">
              {error}
            </div>
          )}

          {/* Footer */}
          <div className="flex items-center justify-between pt-6 border-t border-white/10">
            <button
              type="button"
              onClick={handleBack}
              disabled={step === 0 || submitting}
              className="px-6 py-3 text-xs uppercase tracking-[0.2em] text-white/50 hover:text-white disabled:opacity-30 disabled:cursor-not-allowed transition-colors font-bold"
            >
              ← Back
            </button>

            <button
              type="button"
              onClick={handleNext}
              disabled={!canAdvance() || submitting}
              className="px-10 py-4 bg-white text-black hover:bg-gray-200 disabled:bg-white/30 disabled:text-black/50 disabled:cursor-not-allowed uppercase text-xs tracking-[0.2em] font-bold rounded-full flex items-center gap-3 transition-all"
            >
              {submitting ? 'Saving…' : isLast ? (
                <>
                  Start
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M8 5v14l11-7z" />
                  </svg>
                </>
              ) : 'Next'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
