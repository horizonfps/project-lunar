import { BrowserRouter, Routes, Route, Link, useNavigate } from 'react-router-dom'
import { useEffect, useState } from 'react'
import { useGameStore } from './store'
import { fetchScenarios, exportScenario, fetchCampaigns, createCampaign, checkNeo4j, deleteCampaign, deleteScenario } from './api'
import ErrorBoundary from './components/ErrorBoundary'
import GameCanvas from './components/GameCanvas'
import ScenarioBuilder from './components/ScenarioBuilder'

const ArchiveIcon = () => (
  <svg viewBox="0 0 24 24" width="20" height="20" stroke="currentColor" strokeWidth="1.5" fill="none" strokeLinecap="round" strokeLinejoin="round">
    <polyline points="21 8 21 21 3 21 3 8"></polyline>
    <rect x="1" y="3" width="22" height="5"></rect>
    <line x1="10" y1="12" x2="14" y2="12"></line>
  </svg>
)

const PowerIcon = () => (
  <svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round">
    <path d="M18.36 6.64a9 9 0 1 1-12.73 0"></path>
    <line x1="12" y1="2" x2="12" y2="12"></line>
  </svg>
)

function Home() {
  const { scenarios, setScenarios, setActiveScenario, setActiveCampaignId, clearMessages } =
    useGameStore()
  const navigate = useNavigate()
  const [campaignsMap, setCampaignsMap] = useState({})

  useEffect(() => {
    fetchScenarios()
      .then((data) => {
        setScenarios(data)
        data.forEach((s) =>
          fetchCampaigns(s.id)
            .then((camps) => setCampaignsMap((prev) => ({ ...prev, [s.id]: camps })))
            .catch(() => {})
        )
      })
      .catch(() => {})
  }, [])

  const warnIfNeo4jDown = async () => {
    const ok = await checkNeo4j()
    if (!ok) {
      alert(
        'Neo4j is not running.\n\n' +
        'The World Map will not be available during this session. ' +
        'Entity relationships and graph data will not be stored.\n\n' +
        'To enable it, start Neo4j via Docker:\n' +
        'docker-compose up -d neo4j'
      )
    }
  }

  const playCampaign = async (scenario) => {
    try {
      await warnIfNeo4jDown()
      const campaigns = campaignsMap[scenario.id] || []
      if (campaigns.length > 0) {
        // Resume the most recent campaign
        setActiveScenario(scenario)
        setActiveCampaignId(campaigns[0].id)
        navigate('/play')
      } else {
        // No campaigns yet — create one
        const campaign = await createCampaign(scenario.id)
        setActiveScenario(scenario)
        setActiveCampaignId(campaign.id)
        clearMessages()
        navigate('/play')
      }
    } catch {
      alert('Failed to start adventure')
    }
  }

  const startNewCampaign = async (scenario) => {
    if (!confirm('Start a new adventure? Your current progress will be kept separately.')) return
    try {
      await warnIfNeo4jDown()
      const campaign = await createCampaign(scenario.id)
      setActiveScenario(scenario)
      setActiveCampaignId(campaign.id)
      clearMessages()
      navigate('/play')
    } catch {
      alert('Failed to create adventure')
    }
  }

  const handleDeleteAdventures = async (scenarioId) => {
    const campaigns = campaignsMap[scenarioId] || []
    if (campaigns.length === 0) return
    if (!confirm(`Delete all ${campaigns.length} adventure(s) for this scenario? All progress will be lost.`)) return
    try {
      for (const c of campaigns) {
        await deleteCampaign(scenarioId, c.id)
      }
      setCampaignsMap((prev) => ({ ...prev, [scenarioId]: [] }))
    } catch {
      alert('Failed to delete adventures.')
    }
  }

  const handleDeleteScenario = async (scenarioId) => {
    if (!confirm('Delete this scenario and ALL its adventures? This cannot be undone.')) return
    try {
      await deleteScenario(scenarioId)
      setScenarios(scenarios.filter((s) => s.id !== scenarioId))
    } catch {
      alert('Failed to delete scenario.')
    }
  }

  return (
    <div className="min-h-screen bg-black text-[#d1d1d1] font-sans selection:bg-white/20 selection:text-white relative overflow-hidden flex flex-col items-center justify-center">
      
      {/* High-Quality Background Image from Nano Banana 2 (Imagen 3) */}
      <div 
        className="absolute inset-0 bg-cover bg-center bg-no-repeat opacity-60 mix-blend-screen animate-pulse-slow" 
        style={{ backgroundImage: "url('/lunar-bg.jpg')" }}
      ></div>
      
      {/* Dark Gradient Overlay */}
      <div className="absolute inset-0 bg-gradient-to-t from-black via-black/60 to-black/90 pointer-events-none"></div>

      <div className="w-full max-w-4xl px-4 sm:px-8 relative z-10 flex flex-col items-center">
        
        {/* Main Interface Header */}
        <header className="mb-16 flex flex-col items-center text-center">
          <div className="mb-8">
            <img 
              src="/lunar-logo.png"
              alt="Lunar Logo"
              className="w-64 h-64 md:w-80 md:h-80 object-contain drop-shadow-[0_0_15px_rgba(255,255,255,0.4)]"            />
          </div>
          
          <h1 className="text-4xl sm:text-6xl md:text-8xl font-bold text-white mb-6 tracking-tighter drop-shadow-2xl">
            Lunar Project
          </h1>
          
          <p className="text-gray-400 max-w-2xl text-base sm:text-lg md:text-xl font-light leading-relaxed mb-8 sm:mb-12 drop-shadow-md px-2">
            Localized storytelling core. Multi-agent narrative orchestration with persistent world state and creativity-based resolution.
          </p>
          
          <Link
            to="/create"
            className="group px-12 py-4 bg-white text-black hover:bg-gray-200 transition-all rounded-full font-bold flex items-center gap-4 uppercase text-sm tracking-[0.2em] shadow-[0_0_40px_rgba(255,255,255,0.15)]"
          >
            <span className="text-2xl group-hover:rotate-90 transition-transform duration-300">+</span> 
            Construct Scenario
          </Link>
        </header>

        {/* Centered Scenario Archive */}
        <div className="w-full max-w-2xl flex flex-col items-center">
          <div className="flex items-center gap-4 mb-10 pb-4 border-b border-white/10 w-full justify-center">
            <ArchiveIcon />
            <h2 className="text-xs font-bold uppercase tracking-[0.3em] text-white/60">Narrative Archives</h2>
            <div className="w-1.5 h-1.5 rounded-full bg-white/20"></div>
            <span className="text-[10px] text-white/40 font-mono tracking-widest">
              UNITS: {scenarios.length.toString().padStart(2, '0')}
            </span>
          </div>

          {scenarios.length === 0 ? (
            <div className="py-20 w-full flex flex-col items-center justify-center text-white/30 bg-white/[0.02] backdrop-blur-md rounded-[2rem] border border-white/5">
              <p className="mb-4 tracking-[0.2em] text-xs uppercase font-semibold">No narrative units detected.</p>
              <Link to="/create" className="text-white hover:underline underline-offset-8 transition-all text-[10px] tracking-widest font-bold">
                INITIATE CONSTRUCTION
              </Link>
            </div>
          ) : (
            <div className="flex flex-col gap-6 w-full">
              {scenarios.map((s) => (
                <div key={s.id} className="bg-white/[0.03] backdrop-blur-xl p-5 sm:p-8 rounded-[2rem] border border-white/5 transition-all hover:bg-white/[0.06] hover:border-white/20 group">
                  <div className="flex flex-col md:flex-row items-center gap-8">
                    <div className="flex-1 text-center md:text-left">
                      <div className="text-[10px] text-white/20 tracking-widest uppercase mb-2 font-mono">NODE_HASH: {s.id.split('-')[0]}</div>
                      <h3 className="text-xl sm:text-3xl font-bold text-white mb-3 group-hover:text-white transition-colors">
                        {s.title}
                      </h3>
                      <p className="text-sm text-gray-500 line-clamp-2 leading-relaxed italic">
                        {s.description || s.tone_instructions || 'Unit requires narrative seeding.'}
                      </p>
                    </div>

                    <div className="flex flex-col gap-3 items-end">
                      <div className="flex gap-3">
                        <button
                          onClick={(e) => { e.stopPropagation(); handleDeleteScenario(s.id) }}
                          className="p-3 rounded-2xl border border-white/5 hover:border-rose-500/40 text-white/20 hover:text-rose-400 transition-all"
                          title="Delete Scenario"
                        >
                          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
                        </button>

                        {(campaignsMap[s.id] || []).length > 0 && (
                          <button
                            onClick={(e) => { e.stopPropagation(); handleDeleteAdventures(s.id) }}
                            className="p-3 rounded-2xl border border-white/5 hover:border-rose-500/40 text-white/20 hover:text-rose-400 transition-all"
                            title="Delete all adventures"
                          >
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M3 6h18"></path><path d="M8 6V4h8v2"></path><path d="M5 6l1 14h12l1-14"></path><line x1="10" y1="11" x2="10" y2="17"></line><line x1="14" y1="11" x2="14" y2="17"></line></svg>
                          </button>
                        )}

                        <button
                          onClick={(e) => { e.stopPropagation(); exportScenario(s.id, s.title).catch(() => alert('Export failed.')) }}
                          className="p-3 rounded-2xl border border-white/5 hover:border-white/20 text-white/20 hover:text-white transition-all"
                          title="Export"
                        >
                          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>
                        </button>

                        {(campaignsMap[s.id] || []).length > 0 && (
                          <button
                            onClick={() => startNewCampaign(s)}
                            className="px-5 py-3 rounded-2xl border border-white/10 hover:border-white/30 text-white/40 hover:text-white transition-all text-[10px] font-bold tracking-[0.15em] uppercase"
                            title="Start a fresh adventure"
                          >
                            New
                          </button>
                        )}

                        <button
                          onClick={() => playCampaign(s)}
                          className="px-8 py-3 rounded-2xl bg-white/5 hover:bg-white text-white/80 hover:text-black transition-all text-xs font-bold tracking-[0.2em] uppercase flex items-center gap-3"
                        >
                          Play
                          <PowerIcon />
                        </button>
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default function App() {
  useEffect(() => {
    useGameStore.getState().restoreSettings()
  }, [])

  return (
    <ErrorBoundary>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/create" element={<ScenarioBuilder onCreated={() => window.location.href = '/'} />} />
          <Route path="/play" element={<GameCanvas />} />
        </Routes>
      </BrowserRouter>
    </ErrorBoundary>
  )
}
