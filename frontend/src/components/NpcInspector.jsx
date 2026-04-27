import { useState, useEffect } from 'react'
import { Brain, X, RefreshCw, Trash2, Pencil, Check, XCircle } from 'lucide-react'
import { fetchNpcMinds, deleteNpcMind, updateNpcMind } from '../api'

export default function NpcInspector({ open, onClose, campaignId }) {
  const [npcs, setNpcs] = useState([])
  const [loading, setLoading] = useState(false)
  const [expanded, setExpanded] = useState(null)
  const [editing, setEditing] = useState(null) // index of NPC being edited
  const [editDraft, setEditDraft] = useState({}) // {thought_key: value}
  const [confirmDelete, setConfirmDelete] = useState(null) // index of NPC pending delete

  const fetchNpcs = async () => {
    if (!campaignId) return
    setLoading(true)
    try {
      const data = await fetchNpcMinds(campaignId)
      setNpcs(data)
    } catch {
      setNpcs([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (open) {
      fetchNpcs()
      setEditing(null)
      setConfirmDelete(null)
    }
  }, [open, campaignId])

  if (!open) return null

  const thoughtLabels = {
    feeling: { label: 'Feeling', color: 'text-amber-400' },
    goal: { label: 'Current Goal', color: 'text-emerald-400' },
    opinion_of_player: { label: 'Opinion of Player', color: 'text-white' },
    secret_plan: { label: 'Secret Plan', color: 'text-rose-400' },
  }

  const handleDelete = async (npc, index) => {
    try {
      await deleteNpcMind(campaignId, npc.name)
      setNpcs(prev => prev.filter((_, i) => i !== index))
      setConfirmDelete(null)
      if (expanded === index) setExpanded(null)
      if (editing === index) setEditing(null)
    } catch {
      // silently fail
    }
  }

  const startEdit = (npc, index) => {
    const draft = {}
    for (const [key, thought] of Object.entries(npc.thoughts || {})) {
      draft[key] = thought.value
    }
    setEditDraft(draft)
    setEditing(index)
    setExpanded(index)
  }

  const cancelEdit = () => {
    setEditing(null)
    setEditDraft({})
  }

  const saveEdit = async (npc, index) => {
    try {
      const updated = await updateNpcMind(campaignId, npc.name, editDraft)
      setNpcs(prev => prev.map((n, i) => i === index ? updated : n))
      setEditing(null)
      setEditDraft({})
    } catch {
      // silently fail
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm">
      <div className="bg-white/[0.03] backdrop-blur-xl border border-white/5 rounded-[2rem] w-full max-w-lg mx-4 overflow-hidden max-h-[80vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-white/5 flex-none">
          <div className="flex items-center gap-3">
            <Brain size={16} className="text-white" />
            <h2 className="text-white font-bold text-sm uppercase tracking-widest">NPC Minds</h2>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={fetchNpcs}
              disabled={loading}
              className="text-white/40 hover:text-white transition-colors p-1"
              title="Refresh"
            >
              <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
            </button>
            <button onClick={onClose} className="text-white/40 hover:text-white transition-colors">
              <X size={18} />
            </button>
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto custom-scrollbar p-6 space-y-3">
          {npcs.length === 0 ? (
            <div className="text-center py-8">
              <Brain size={32} className="text-white/20 mx-auto mb-3" />
              <p className="text-white/20 text-sm font-light">
                {loading ? 'Scanning neural patterns...' : 'No NPC minds detected yet. Play more to populate NPC thoughts.'}
              </p>
            </div>
          ) : (
            npcs.map((npc, i) => (
              <div
                key={i}
                className="rounded-xl bg-white/[0.03] border border-white/5 overflow-hidden transition-all"
              >
                <div className="w-full px-4 py-3 flex items-center justify-between">
                  <button
                    onClick={() => {
                      if (editing !== i) setExpanded(expanded === i ? null : i)
                    }}
                    className="flex items-center gap-3 flex-1 hover:bg-white/5 transition-colors rounded-lg -ml-2 pl-2 py-1"
                  >
                    <div className="w-8 h-8 rounded-full bg-white/10 border border-white/20 flex items-center justify-center">
                      <span className="text-white text-xs font-bold">
                        {npc.name.charAt(0).toUpperCase()}
                      </span>
                    </div>
                    <span className="text-white font-semibold text-sm">{npc.name}</span>
                    <span className="text-white/20 text-xs">
                      {Object.keys(npc.thoughts || {}).length} thoughts
                    </span>
                  </button>

                  <div className="flex items-center gap-1 ml-2">
                    {editing === i ? (
                      <>
                        <button
                          onClick={() => saveEdit(npc, i)}
                          className="text-emerald-400/60 hover:text-emerald-400 transition-colors p-1.5 rounded-lg hover:bg-white/5"
                          title="Save"
                        >
                          <Check size={14} />
                        </button>
                        <button
                          onClick={cancelEdit}
                          className="text-white/30 hover:text-white/60 transition-colors p-1.5 rounded-lg hover:bg-white/5"
                          title="Cancel"
                        >
                          <XCircle size={14} />
                        </button>
                      </>
                    ) : (
                      <>
                        <button
                          onClick={() => startEdit(npc, i)}
                          className="text-white/20 hover:text-white/60 transition-colors p-1.5 rounded-lg hover:bg-white/5"
                          title="Edit thoughts"
                        >
                          <Pencil size={13} />
                        </button>
                        {confirmDelete === i ? (
                          <div className="flex items-center gap-1">
                            <button
                              onClick={() => handleDelete(npc, i)}
                              className="text-rose-400 hover:text-rose-300 transition-colors p-1.5 rounded-lg hover:bg-rose-400/10 text-[10px] font-bold uppercase tracking-wider"
                            >
                              Yes
                            </button>
                            <button
                              onClick={() => setConfirmDelete(null)}
                              className="text-white/30 hover:text-white/60 transition-colors p-1.5 rounded-lg hover:bg-white/5 text-[10px] font-bold uppercase tracking-wider"
                            >
                              No
                            </button>
                          </div>
                        ) : (
                          <button
                            onClick={() => setConfirmDelete(i)}
                            className="text-white/20 hover:text-rose-400/60 transition-colors p-1.5 rounded-lg hover:bg-white/5"
                            title="Delete NPC"
                          >
                            <Trash2 size={13} />
                          </button>
                        )}
                      </>
                    )}
                  </div>
                </div>

                {expanded === i && (
                  <div className="px-4 pb-4 space-y-2 border-t border-white/5 pt-3">
                    {Object.entries(npc.thoughts || {}).map(([key, thought]) => {
                      const meta = thoughtLabels[key] || { label: key, color: 'text-white/40' }
                      return (
                        <div key={key} className="flex flex-col gap-1">
                          <span className={`text-[10px] uppercase tracking-widest font-bold ${meta.color}`}>
                            {meta.label}
                          </span>
                          {editing === i ? (
                            <textarea
                              value={editDraft[key] ?? thought.value}
                              onChange={(e) => setEditDraft(prev => ({ ...prev, [key]: e.target.value }))}
                              className="bg-white/5 border border-white/10 rounded-lg text-[#d1d1d1] text-sm font-light leading-relaxed p-2 resize-none focus:outline-none focus:border-white/20 transition-colors"
                              rows={2}
                            />
                          ) : (
                            <p className="text-[#d1d1d1] text-sm font-light leading-relaxed pl-2 border-l-2 border-white/5">
                              {thought.value}
                            </p>
                          )}
                        </div>
                      )
                    })}
                  </div>
                )}
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  )
}
