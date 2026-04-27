import { useState, useEffect, useRef, useMemo } from 'react'
import ReactMarkdown from 'react-markdown'
import { Settings, Sparkles, Clock, Brain, Gem, Map, Backpack, BookOpen, Undo2, RefreshCw } from 'lucide-react'
import { useGameStore } from '../store'
import {
  streamAction,
  fetchJournal,
  fetchHistory,
  fetchInventory as fetchInventoryApi,
  rewindLastAction,
  fetchScenarioView,
  regenerateOpening,
} from '../api'
import ActionInput from './ActionInput'
import JournalPanel from './JournalPanel'
import CombatOverlay from './CombatOverlay'
import SettingsPanel from './SettingsPanel'
import PlotGeneratorPanel from './PlotGeneratorPanel'
import TimeskipModal from './TimeskipModal'
import NpcInspector from './NpcInspector'
import MemoryInspector from './MemoryInspector'
import WorldMapModal from './WorldMapModal'
import InventoryPanel from './InventoryPanel'

/** Render text with @mentions highlighted in indigo */
function MentionText({ children }) {
  if (typeof children !== 'string') return children
  // Match @Name (captures multi-word names like @Satoru Gojo until punctuation or end)
  const parts = children.split(/(@[A-Z\u00C0-\u024F][A-Za-z\u00C0-\u024F]*(?:\s+[A-Z\u00C0-\u024F][A-Za-z\u00C0-\u024F]*)*)/g)
  if (parts.length === 1) return children
  return parts.map((part, i) => {
    if (part.startsWith('@')) {
      return (
        <span key={i} className="text-indigo-400 font-medium" title={part.slice(1)}>
          {part}
        </span>
      )
    }
    return part
  })
}

/** ReactMarkdown components override to render @mentions in all text */
const mentionComponents = {
  p: ({ children }) => <p>{processChildren(children)}</p>,
  li: ({ children }) => <li>{processChildren(children)}</li>,
  em: ({ children }) => <em>{processChildren(children)}</em>,
  strong: ({ children }) => <strong>{processChildren(children)}</strong>,
}

function processChildren(children) {
  if (!children) return children
  if (typeof children === 'string') return <MentionText>{children}</MentionText>
  if (Array.isArray(children)) {
    return children.map((child, i) => {
      if (typeof child === 'string') return <MentionText key={i}>{child}</MentionText>
      return child
    })
  }
  return children
}

function NarratorSkeleton() {
  return (
    <div className="max-w-3xl pr-4 animate-pulse">
      <div className="flex items-center gap-2 mb-2 ml-1 opacity-60">
        <div className="w-1.5 h-1.5 rounded-full bg-white/[0.03]" />
        <span className="text-[10px] font-bold uppercase tracking-widest font-mono text-white/60">Narrator Core</span>
      </div>
      <div className="space-y-3">
        <div className="h-3 bg-white/[0.03] rounded w-[85%]" />
        <div className="h-3 bg-white/[0.03] rounded w-[70%]" />
        <div className="h-3 bg-white/[0.03] rounded w-[55%]" />
      </div>
    </div>
  )
}

export default function GameCanvas() {
  const {
    messages,
    isStreaming,
    combatMode,
    appendMessage,
    appendToLastMessage,
    setStreaming,
    setCombatMode,
    activeCampaignId,
    activeScenario,
    journal,
    addJournalEntry,
    setJournal,
    inventory,
    setInventory,
    addInventoryItem,
    updateInventoryItem: updateInventoryStore,
    restoreSession,
    clearSession,
    maxTokens,
    llmProvider,
    llmModel,
    temperature,
    replaceLastAssistantMessage,
    popLastPair,
  } = useGameStore()
  const bottomRef = useRef(null)
  const [journalOpen, setJournalOpen] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [plotGenOpen, setPlotGenOpen] = useState(false)
  const [timeskipOpen, setTimeskipOpen] = useState(false)
  const [npcOpen, setNpcOpen] = useState(false)
  const [memoryOpen, setMemoryOpen] = useState(false)
  const [mapOpen, setMapOpen] = useState(false)
  const [inventoryOpen, setInventoryOpen] = useState(false)
  const [rewinding, setRewinding] = useState(false)
  const [scenarioView, setScenarioView] = useState(null)
  const [regenerating, setRegenerating] = useState(false)

  // Restore session on mount if state is missing
  useEffect(() => {
    if (!activeCampaignId) restoreSession()
  }, [])

  // Pull the per-campaign resolved scenario surface (interpolated opening,
  // tone, lore) so we never render raw {var} tokens in-game. Falls back to
  // the raw activeScenario when the request fails.
  useEffect(() => {
    if (!activeCampaignId) {
      setScenarioView(null)
      return
    }
    let cancelled = false
    fetchScenarioView(activeCampaignId)
      .then((view) => {
        if (!cancelled) setScenarioView(view)
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [activeCampaignId])

  // Restore chat history from backend when campaign has no local messages
  useEffect(() => {
    if (!activeCampaignId || messages.length > 0) return
    fetchHistory(activeCampaignId)
      .then(({ messages: history }) => {
        if (history && history.length > 0) {
          history.forEach((msg) => appendMessage(msg))
        }
      })
      .catch(() => {})
    fetchInventoryApi(activeCampaignId)
      .then((items) => setInventory(items))
      .catch(() => {})
    fetchJournal(activeCampaignId)
      .then((entries) => setJournal(entries))
      .catch(() => {})
  }, [activeCampaignId])

  const resolvedOpening = scenarioView?.opening_narrative ?? activeScenario?.opening_narrative ?? ''
  const resolvedTone = scenarioView?.tone_instructions ?? activeScenario?.tone_instructions ?? ''
  const canRerollOpening =
    !!scenarioView &&
    scenarioView.opening_mode === 'ai' &&
    messages.length === 0 &&
    !isStreaming &&
    !regenerating

  const handleRerollOpening = async () => {
    if (!activeCampaignId || !canRerollOpening) return
    setRegenerating(true)
    try {
      const result = await regenerateOpening(activeCampaignId)
      setScenarioView((prev) => ({
        ...(prev || {}),
        opening_narrative: result.opening_narrative,
        has_generated_opening: true,
        opening_mode: prev?.opening_mode ?? 'ai',
      }))
    } catch (err) {
      const detail = err?.detail || 'Could not regenerate the opening.'
      window.alert(detail)
    } finally {
      setRegenerating(false)
    }
  }

  const formatAutoPlotMessage = (plot) => {
    const kind = String(plot?.kind || '').toLowerCase()
    const data = plot?.data || {}

    if (kind === 'npc') {
      return [
        '### Auto Plot: New NPC Seed',
        `**${data.name || 'Unknown'}** (Power ${data.power_level || 5}/10)`,
        data.appearance || '',
        data.goal ? `Goal: ${data.goal}` : '',
        data.secret ? `Secret: ${data.secret}` : '',
      ].filter(Boolean).join('\n\n')
    }

    if (kind === 'event') {
      const choices = Array.isArray(data.choices)
        ? data.choices.map((choice, index) => `${index + 1}. ${choice}`).join('\n')
        : ''

      return [
        '### Auto Plot: Random Event',
        `**${data.title || 'Unexpected Event'}**`,
        data.description || '',
        choices ? `Choices:\n${choices}` : '',
      ].filter(Boolean).join('\n\n')
    }

    return [
      '### Auto Plot: Plot Arc',
      typeof data === 'string' ? data : (data.text || 'A new plot branch emerges.'),
    ].join('\n\n')
  }

  const scrollContainerRef = useRef(null)
  const userScrolledUp = useRef(false)

  useEffect(() => {
    const container = scrollContainerRef.current
    if (!container) return
    const handleScroll = () => {
      const { scrollTop, scrollHeight, clientHeight } = container
      userScrolledUp.current = scrollHeight - scrollTop - clientHeight > 120
    }
    container.addEventListener('scroll', handleScroll)
    return () => container.removeEventListener('scroll', handleScroll)
  }, [])

  useEffect(() => {
    if (!userScrolledUp.current) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [messages])

  const openJournal = async () => {
    if (activeCampaignId) {
      try {
        const entries = await fetchJournal(activeCampaignId)
        setJournal(entries)
      } catch {}
    }
    setJournalOpen(true)
  }

  const refreshJournal = async () => {
    if (activeCampaignId) {
      try {
        const entries = await fetchJournal(activeCampaignId)
        setJournal(entries)
      } catch {}
    }
  }

  const handleAction = (action) => {
    appendMessage({ role: 'user', content: action })
    setStreaming(true)
    streamAction({
      campaignId: activeCampaignId,
      scenarioTone: resolvedTone,
      language: scenarioView?.language ?? activeScenario?.language ?? 'en',
      action,
      openingNarrative: resolvedOpening,
      maxTokens: maxTokens || 2000,
      provider: llmProvider,
      model: llmModel,
      temperature,
      onChunk: appendToLastMessage,
      onJournal: addJournalEntry,
      onMode: (mode) => {
        const normalized = String(mode || '').trim().split('.').pop()?.trim().toUpperCase()
        setCombatMode(normalized === 'COMBAT')
      },
      onInventory: (item) => {
        if (item.action === 'add') addInventoryItem(item)
        else if (item.action === 'use') updateInventoryStore(item.name, 'used')
        else if (item.action === 'lose') updateInventoryStore(item.name, 'lost')
      },
      onPlotAuto: (plot) => {
        appendMessage({ role: 'assistant', content: formatAutoPlotMessage(plot) })
      },
      onTruncateClean: (cleanText) => {
        replaceLastAssistantMessage(cleanText)
      },
      onDone: () => {
        setStreaming(false)
        // Clear combat mode after response completes
        const COMBAT_CLEAR_DELAY_MS = 3000
        setTimeout(() => setCombatMode(false), COMBAT_CLEAR_DELAY_MS)
      },
      onError: () => setStreaming(false),
    })
  }

  const handleRewind = async () => {
    if (!activeCampaignId || isStreaming || rewinding || messages.length === 0) return
    if (!window.confirm('Undo the last action? This cannot be reversed.')) return
    setRewinding(true)
    try {
      await rewindLastAction(activeCampaignId)
      popLastPair()
    } catch (err) {
      console.error('Rewind failed:', err)
    } finally {
      setRewinding(false)
    }
  }

  const handleTimeskip = (data) => {
    if (data.summary) {
      appendMessage({ role: 'assistant', content: `*Time passes...*\n\n${data.summary}` })
    }
  }

  return (
    <div className="flex flex-col h-screen bg-black bg-cover bg-center bg-fixed">
      <div className="flex flex-col h-full bg-black/80 backdrop-blur-md">

        {/* Combat Overlay */}
        <CombatOverlay active={combatMode} />

        {/* Header */}
        <header className="flex-none flex items-center justify-between px-3 sm:px-6 py-3 sm:py-4 bg-black/80 backdrop-blur-xl border-b border-white/5 z-10 shadow-lg gap-2">
          <div className="flex items-center gap-4">
            <div className={`w-2 h-2 rounded-full animate-pulse ${combatMode ? 'bg-rose-400 shadow-[0_0_8px_rgba(244,63,94,0.8)]' : 'bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.8)]'}`} />
            <div>
              <h1 className="text-white font-bold text-base tracking-wide drop-shadow-[0_0_15px_rgba(255,255,255,0.4)]">
                {activeScenario?.title ?? 'Unknown Coordinates'}
              </h1>
              <div className="flex items-center gap-2 text-white/40 text-xs font-mono uppercase">
                <span>Link ID: {activeCampaignId?.slice(0, 8) || 'OFFLINE'}</span>
              </div>
            </div>
          </div>
          <div className="flex items-center gap-1 sm:gap-2 flex-wrap justify-end">
            {/* Tool buttons */}
            <button
              onClick={() => setInventoryOpen(true)}
              title="Inventory"
              aria-label="Open inventory"
              className="p-2 rounded-lg bg-white/5 hover:bg-white text-white/80 hover:text-black rounded-2xl border border-white/5 hover:text-orange-400 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-white/50"
            >
              <Backpack size={14} />
            </button>
            <button
              onClick={() => setMapOpen(true)}
              title="World Map"
              aria-label="Open world map"
              className="p-2 rounded-lg bg-white/5 hover:bg-white text-white/80 hover:text-black rounded-2xl border border-white/5 hover:text-emerald-400 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-white/50"
            >
              <Map size={14} />
            </button>
            <button
              onClick={() => setPlotGenOpen(true)}
              title="Plot Generator"
              aria-label="Open plot generator"
              className="p-2 rounded-lg bg-white/5 hover:bg-white text-white/80 hover:text-black rounded-2xl border border-white/5 hover:text-amber-400 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-white/50"
            >
              <Sparkles size={14} />
            </button>
            <button
              onClick={() => setTimeskipOpen(true)}
              title="Time Skip"
              aria-label="Open time skip"
              className="p-2 rounded-lg bg-white/5 hover:bg-white text-white/80 hover:text-black rounded-2xl border border-white/5 hover:text-white transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-white/50"
            >
              <Clock size={14} />
            </button>
            <button
              onClick={() => setNpcOpen(true)}
              title="NPC Minds"
              aria-label="Open NPC minds"
              className="p-2 rounded-lg bg-white/5 hover:bg-white text-white/80 hover:text-black rounded-2xl border border-white/5 hover:text-white transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-white/50"
            >
              <Brain size={14} />
            </button>
            <button
              onClick={() => setMemoryOpen(true)}
              title="Memory Crystals"
              aria-label="Open memory crystals"
              className="p-2 rounded-lg bg-white/5 hover:bg-white text-white/80 hover:text-black rounded-2xl border border-white/5 hover:text-white transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-white/50"
            >
              <Gem size={14} />
            </button>
            <button
              onClick={openJournal}
              title="Mission Log"
              aria-label="Open mission log"
              className="p-2 rounded-lg bg-white/5 hover:bg-white text-white/80 hover:text-black rounded-2xl border border-white/5 hover:text-yellow-400 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-white/50"
            >
              <BookOpen size={14} />
            </button>
            <button
              onClick={() => setSettingsOpen(true)}
              title="Settings"
              aria-label="Open settings"
              className="p-2 rounded-lg bg-white/5 hover:bg-white text-white/80 hover:text-black rounded-2xl border border-white/5 hover:text-white transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-white/50"
            >
              <Settings size={14} />
            </button>

            <div className="w-px h-6 bg-white/10 mx-1" />

            <button
              onClick={() => { clearSession(); window.location.href = '/' }}
              className="px-4 py-2 rounded-lg bg-white/5 hover:bg-white text-white/80 hover:text-black rounded-2xl border border-white/5 text-xs font-semibold uppercase tracking-wider transition-colors"
            >
              Disconnect
            </button>
          </div>
        </header>

        {/* Main content area */}
        <div className="flex flex-1 overflow-hidden">
          {/* Message feed */}
          <div ref={scrollContainerRef} className="flex-1 overflow-y-auto p-4 md:p-8 custom-scrollbar relative">
            <div className="max-w-4xl mx-auto space-y-8 pb-4">
              {messages.length === 0 && resolvedOpening && (
                <div className="relative bg-white/[0.03] backdrop-blur-xl border border-white/5 rounded-[2rem] p-6 md:p-8 shadow-[0_0_40px_rgba(255,255,255,0.15)]">
                  <div className="prose prose-invert max-w-none prose-p:leading-relaxed prose-p:font-light prose-p:text-white font-serif">
                    <ReactMarkdown components={mentionComponents}>{resolvedOpening}</ReactMarkdown>
                  </div>
                  {canRerollOpening && (
                    <button
                      onClick={handleRerollOpening}
                      title="Re-roll AI-generated opening"
                      aria-label="Re-roll opening"
                      className="absolute top-4 right-4 p-2 rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 text-white/60 hover:text-white transition-colors disabled:opacity-30"
                    >
                      <RefreshCw size={14} className={regenerating ? 'animate-spin' : ''} />
                    </button>
                  )}
                </div>
              )}

              {messages.map((msg, i) => {
                const isUser = msg.role === 'user';
                const displayContent = isUser ? msg.content : msg.content
                  .replace(/\[ITEM_ADD:[^\]]+\]/g, '')
                  .replace(/\[ITEM_USE:[^\]]+\]/g, '')
                  .replace(/\[ITEM_LOSE:[^\]]+\]/g, '');
                return (
                  <div key={i} className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
                    {isUser ? (
                      <div className={`max-w-2xl bg-white/10 backdrop-blur-md border border-white/20 text-white px-5 py-3.5 rounded-2xl rounded-tr-sm shadow-[0_4px_20px_rgba(0,0,0,0.2)] ${/^\[META\]/i.test(msg.content) ? 'font-mono' : ''}`}>
                        <p className="text-sm md:text-base font-light tracking-wide leading-relaxed">
                          {(() => {
                            const typeMatch = msg.content.match(/^\[(DO|SAY|CONTINUE|META)\]\s*/i);
                            const actionType = typeMatch ? typeMatch[1] : null;
                            const body = typeMatch ? msg.content.slice(typeMatch[0].length) : msg.content;
                            return (
                              <>
                                {actionType && <span className="text-xs font-bold text-white uppercase mr-2 tracking-widest opacity-80">{actionType}</span>}
                                <MentionText>{body}</MentionText>
                              </>
                            );
                          })()}
                        </p>
                      </div>
                    ) : (
                      <div className="max-w-3xl pr-4">
                        {/* System/Narrator indicator */}
                        <div className="flex items-center gap-2 mb-2 ml-1 opacity-60">
                           <div className={`w-1.5 h-1.5 rounded-full ${combatMode ? 'bg-rose-400' : 'bg-white/[0.03]'}`} />
                           <span className={`text-[10px] font-bold uppercase tracking-widest font-mono ${combatMode ? 'text-rose-300' : 'text-white/60'}`}>
                             {combatMode ? 'Combat Narrator' : 'Narrator Core'}
                           </span>
                        </div>
                        <div className="prose prose-invert max-w-none prose-p:leading-relaxed prose-p:font-light prose-p:text-white prose-headings:text-white prose-a:text-white font-serif">
                          <ReactMarkdown components={mentionComponents}>{displayContent}</ReactMarkdown>
                          {isStreaming && i === messages.length - 1 && (
                            <span className={`inline-block w-2 h-4 animate-pulse ml-2 align-middle ${combatMode ? 'bg-rose-400 shadow-[0_0_8px_rgba(244,63,94,0.8)]' : 'bg-white/10 shadow-[0_0_8px_rgba(99,102,241,0.8)]'}`} />
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
              {/* Shimmer skeleton while waiting for first assistant token */}
              {isStreaming && messages.length > 0 && messages[messages.length - 1].role === 'user' && (
                <NarratorSkeleton />
              )}
              <div ref={bottomRef} className="h-4" />
            </div>
          </div>

        </div>

        {/* Input Area */}
        <div className="flex-none bg-black/80 backdrop-blur-2xl border-t border-white/5 relative z-20 shadow-[0_-10px_40px_rgba(0,0,0,0.5)]">
          <div className="flex items-end max-w-4xl mx-auto w-full">
            <div className="flex-1">
              <ActionInput onSubmit={handleAction} disabled={isStreaming} />
            </div>
            <div className="pb-4 pr-4 md:pr-6">
              <button
                onClick={handleRewind}
                disabled={isStreaming || rewinding || messages.length === 0}
                title="Undo last action"
                aria-label="Undo last action"
                className="p-3 rounded-xl bg-white/5 border border-white/10 text-white/40 hover:text-rose-400 hover:border-rose-400/30 hover:bg-rose-400/10 transition-all disabled:opacity-20 disabled:cursor-not-allowed disabled:hover:text-white/40 disabled:hover:border-white/10 disabled:hover:bg-white/5"
              >
                <Undo2 size={18} />
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Modals */}
      {settingsOpen && <SettingsPanel open={settingsOpen} onClose={() => setSettingsOpen(false)} />}
      <PlotGeneratorPanel open={plotGenOpen} onClose={() => setPlotGenOpen(false)} campaignId={activeCampaignId} language={activeScenario?.language ?? 'en'} />
      <TimeskipModal open={timeskipOpen} onClose={() => setTimeskipOpen(false)} campaignId={activeCampaignId} onTimeskip={handleTimeskip} />
      <NpcInspector open={npcOpen} onClose={() => setNpcOpen(false)} campaignId={activeCampaignId} />
      <MemoryInspector open={memoryOpen} onClose={() => setMemoryOpen(false)} campaignId={activeCampaignId} />
      <WorldMapModal open={mapOpen} onClose={() => setMapOpen(false)} campaignId={activeCampaignId} />
      <InventoryPanel open={inventoryOpen} onClose={() => setInventoryOpen(false)} campaignId={activeCampaignId} inventory={inventory} setInventory={setInventory} />
      <JournalPanel open={journalOpen} onClose={() => setJournalOpen(false)} entries={journal} onRefresh={refreshJournal} />
    </div>
  )
}
