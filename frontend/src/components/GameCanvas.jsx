import { useState, useEffect, useRef } from 'react'
import ReactMarkdown from 'react-markdown'
import { Settings, Sparkles, Clock, Brain, Gem, Map, Backpack, BookOpen } from 'lucide-react'
import { useGameStore } from '../store'
import { streamAction, fetchJournal } from '../api'
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

function NarratorSkeleton() {
  return (
    <div className="max-w-3xl pr-4 animate-pulse">
      <div className="flex items-center gap-2 mb-2 ml-1 opacity-60">
        <div className="w-1.5 h-1.5 rounded-full bg-white/[0.03]" />
        <span className="text-[10px] font-bold uppercase tracking-widest font-mono text-white/40 text-white/60">Narrator Core</span>
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

  // Restore session on mount if state is missing
  useEffect(() => {
    if (!activeCampaignId) restoreSession()
  }, [])

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

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
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
      scenarioTone: activeScenario?.tone_instructions ?? '',
      language: activeScenario?.language ?? 'en',
      action,
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
      onDone: () => {
        setStreaming(false)
        // Clear combat mode after response completes
        setTimeout(() => setCombatMode(false), 3000)
      },
      onError: () => setStreaming(false),
    })
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
        <header className="flex-none flex items-center justify-between px-6 py-4 bg-black/80 backdrop-blur-xl border-b border-white/5 z-10 shadow-lg">
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
          <div className="flex items-center gap-2">
            {/* Tool buttons */}
            <button
              onClick={() => setInventoryOpen(true)}
              title="Inventory"
              className="p-2 rounded-lg bg-white/5 hover:bg-white text-white/80 hover:text-black rounded-2xl border border-white/5 hover:text-orange-400 transition-colors"
            >
              <Backpack size={14} />
            </button>
            <button
              onClick={() => setMapOpen(true)}
              title="World Map"
              className="p-2 rounded-lg bg-white/5 hover:bg-white text-white/80 hover:text-black rounded-2xl border border-white/5 hover:text-emerald-400 transition-colors"
            >
              <Map size={14} />
            </button>
            <button
              onClick={() => setPlotGenOpen(true)}
              title="Plot Generator"
              className="p-2 rounded-lg bg-white/5 hover:bg-white text-white/80 hover:text-black rounded-2xl border border-white/5 hover:text-amber-400 transition-colors"
            >
              <Sparkles size={14} />
            </button>
            <button
              onClick={() => setTimeskipOpen(true)}
              title="Time Skip"
              className="p-2 rounded-lg bg-white/5 hover:bg-white text-white/80 hover:text-black rounded-2xl border border-white/5 hover:text-white transition-colors"
            >
              <Clock size={14} />
            </button>
            <button
              onClick={() => setNpcOpen(true)}
              title="NPC Minds"
              className="p-2 rounded-lg bg-white/5 hover:bg-white text-white/80 hover:text-black rounded-2xl border border-white/5 hover:text-white transition-colors"
            >
              <Brain size={14} />
            </button>
            <button
              onClick={() => setMemoryOpen(true)}
              title="Memory Crystals"
              className="p-2 rounded-lg bg-white/5 hover:bg-white text-white/80 hover:text-black rounded-2xl border border-white/5 hover:text-white transition-colors"
            >
              <Gem size={14} />
            </button>
            <button
              onClick={openJournal}
              title="Mission Log"
              className="p-2 rounded-lg bg-white/5 hover:bg-white text-white/80 hover:text-black rounded-2xl border border-white/5 hover:text-yellow-400 transition-colors"
            >
              <BookOpen size={14} />
            </button>
            <button
              onClick={() => setSettingsOpen(true)}
              title="Settings"
              className="p-2 rounded-lg bg-white/5 hover:bg-white text-white/80 hover:text-black rounded-2xl border border-white/5 hover:text-white transition-colors"
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
          <div className="flex-1 overflow-y-auto p-4 md:p-8 custom-scrollbar relative">
            <div className="max-w-4xl mx-auto space-y-8 pb-4">
              {messages.length === 0 && activeScenario?.opening_narrative && (
                <div className="bg-white/[0.03] backdrop-blur-xl border border-white/5 rounded-[2rem] p-6 md:p-8 shadow-[0_0_40px_rgba(255,255,255,0.15)]">
                  <div className="prose prose-invert max-w-none prose-p:leading-relaxed prose-p:font-light prose-p:text-white font-serif">
                    <ReactMarkdown>{activeScenario.opening_narrative}</ReactMarkdown>
                  </div>
                </div>
              )}

              {messages.map((msg, i) => {
                const isUser = msg.role === 'user';
                const displayContent = isUser ? msg.content : msg.content
                  .replace(/\[ITEM_ADD:[^\]]*\]/g, '')
                  .replace(/\[ITEM_USE:[^\]]*\]/g, '')
                  .replace(/\[ITEM_LOSE:[^\]]*\]/g, '');
                return (
                  <div key={i} className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
                    {isUser ? (
                      <div className={`max-w-2xl bg-white/10 backdrop-blur-md border border-white/20 text-white px-5 py-3.5 rounded-2xl rounded-tr-sm shadow-[0_4px_20px_rgba(0,0,0,0.2)] ${/^\[META\]/i.test(msg.content) ? 'font-mono' : ''}`}>
                        <p className="text-sm md:text-base font-light tracking-wide leading-relaxed">
                          {msg.content.replace(/^\[(DO|SAY|CONTINUE|META)\]\s*/i, (match, p1) => {
                             return `<span class="text-xs font-bold text-white uppercase mr-2 tracking-widest opacity-80">${p1}</span> `;
                          }).split('<span').map((part, idx) => {
                            if (idx === 0) return part;
                            const [spanContent, ...rest] = part.split('</span>');
                            const content = spanContent.split('>')[1];
                            return <span key={idx}><span className="text-xs font-bold text-white uppercase mr-2 tracking-widest opacity-80">{content}</span>{rest.join('</span>')}</span>;
                          })}
                        </p>
                      </div>
                    ) : (
                      <div className="max-w-3xl pr-4">
                        {/* System/Narrator indicator */}
                        <div className="flex items-center gap-2 mb-2 ml-1 opacity-60">
                           <div className={`w-1.5 h-1.5 rounded-full ${combatMode ? 'bg-rose-400' : 'bg-white/[0.03]'}`} />
                           <span className={`text-[10px] font-bold uppercase tracking-widest font-mono text-white/40 font-mono text-white/40 ${combatMode ? 'text-rose-300' : 'text-white/60'}`}>
                             {combatMode ? 'Combat Narrator' : 'Narrator Core'}
                           </span>
                        </div>
                        <div className="prose prose-invert max-w-none prose-p:leading-relaxed prose-p:font-light prose-p:text-white prose-headings:text-white prose-a:text-white font-serif">
                          <ReactMarkdown>{displayContent}</ReactMarkdown>
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
          <ActionInput onSubmit={handleAction} disabled={isStreaming} />
        </div>
      </div>

      {/* Modals */}
      <SettingsPanel open={settingsOpen} onClose={() => setSettingsOpen(false)} />
      <PlotGeneratorPanel open={plotGenOpen} onClose={() => setPlotGenOpen(false)} campaignId={activeCampaignId} />
      <TimeskipModal open={timeskipOpen} onClose={() => setTimeskipOpen(false)} campaignId={activeCampaignId} onTimeskip={handleTimeskip} />
      <NpcInspector open={npcOpen} onClose={() => setNpcOpen(false)} campaignId={activeCampaignId} />
      <MemoryInspector open={memoryOpen} onClose={() => setMemoryOpen(false)} campaignId={activeCampaignId} />
      <WorldMapModal open={mapOpen} onClose={() => setMapOpen(false)} campaignId={activeCampaignId} />
      <InventoryPanel open={inventoryOpen} onClose={() => setInventoryOpen(false)} campaignId={activeCampaignId} inventory={inventory} setInventory={setInventory} />
      <JournalPanel open={journalOpen} onClose={() => setJournalOpen(false)} entries={journal} onRefresh={refreshJournal} />
    </div>
  )
}
