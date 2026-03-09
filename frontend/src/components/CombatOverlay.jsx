import { useEffect, useState } from 'react'

export default function CombatOverlay({ active }) {
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    if (active) {
      setVisible(true)
    } else {
      const timer = setTimeout(() => setVisible(false), 500)
      return () => clearTimeout(timer)
    }
  }, [active])

  if (!visible) return null

  return (
    <>
      {/* Top/bottom combat bars */}
      <div
        className={`fixed top-0 left-0 right-0 h-1 z-40 transition-all duration-500
          ${active ? 'opacity-100' : 'opacity-0'}`}
      >
        <div className="h-full bg-gradient-to-r from-transparent via-rose-500 to-transparent animate-pulse" />
      </div>
      <div
        className={`fixed bottom-0 left-0 right-0 h-1 z-40 transition-all duration-500
          ${active ? 'opacity-100' : 'opacity-0'}`}
      >
        <div className="h-full bg-gradient-to-r from-transparent via-rose-500 to-transparent animate-pulse" />
      </div>

      {/* Side glow */}
      <div
        className={`fixed top-0 left-0 bottom-0 w-1 z-40 transition-all duration-500
          ${active ? 'opacity-100' : 'opacity-0'}`}
      >
        <div className="w-full h-full bg-gradient-to-b from-transparent via-rose-500 to-transparent animate-pulse" />
      </div>
      <div
        className={`fixed top-0 right-0 bottom-0 w-1 z-40 transition-all duration-500
          ${active ? 'opacity-100' : 'opacity-0'}`}
      >
        <div className="w-full h-full bg-gradient-to-b from-transparent via-rose-500 to-transparent animate-pulse" />
      </div>

      {/* Combat mode badge */}
      <div
        className={`fixed top-16 left-1/2 -translate-x-1/2 z-50 transition-all duration-500
          ${active ? 'opacity-100 translate-y-0' : 'opacity-0 -translate-y-4'}`}
      >
        <div className="flex items-center gap-2 px-4 py-1.5 rounded-full bg-rose-950/80 backdrop-blur-xl border border-rose-500/40 shadow-[0_0_20px_rgba(244,63,94,0.3)]">
          <div className="w-2 h-2 bg-rose-400 rounded-full animate-pulse shadow-[0_0_8px_rgba(244,63,94,0.8)]" />
          <span className="text-rose-300 text-[10px] font-bold uppercase tracking-[0.2em]">Combat Active</span>
        </div>
      </div>

      {/* Corner vignettes */}
      <div
        className={`fixed inset-0 pointer-events-none z-30 transition-opacity duration-500
          ${active ? 'opacity-100' : 'opacity-0'}`}
        style={{
          background: 'radial-gradient(ellipse at center, transparent 50%, rgba(159,18,57,0.08) 100%)',
        }}
      />
    </>
  )
}
