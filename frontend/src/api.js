const BASE = '/api'  // proxied to http://localhost:8000 via vite proxy

export async function fetchScenarios() {
  const r = await fetch(`${BASE}/scenarios/`)
  if (!r.ok) throw new Error('Failed to fetch scenarios')
  return r.json()
}

export async function createScenario(data) {
  const r = await fetch(`${BASE}/scenarios/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!r.ok) throw new Error('Failed to create scenario')
  return r.json()
}

export async function getStoryCards(scenarioId) {
  const r = await fetch(`${BASE}/scenarios/${scenarioId}/story-cards`)
  if (!r.ok) throw new Error('Failed to fetch story cards')
  return r.json()
}

export async function addStoryCard(scenarioId, data) {
  const r = await fetch(`${BASE}/scenarios/${scenarioId}/story-cards`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!r.ok) throw new Error('Failed to add story card')
  return r.json()
}

export function streamAction({
  campaignId,
  scenarioTone,
  language,
  action,
  onChunk,
  onJournal,
  onMode,
  onCrystal,
  onPlotAuto,
  onInventory,
  onDone,
  onError,
}) {
  fetch(`${BASE}/game/action`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      campaign_id: campaignId,
      scenario_tone: scenarioTone,
      language,
      action,
    }),
  })
    .then(async (res) => {
      if (!res.ok) throw new Error('Action request failed')
      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      const handleData = (data) => {
        const control = data.trim()
        if (control === '[DONE]') {
          onDone?.()
          return true
        }
        if (control.startsWith('[JOURNAL]')) {
          try {
            const entry = JSON.parse(control.slice(9))
            onJournal?.(entry)
          } catch {}
          return false
        }
        if (control.startsWith('[MODE]')) {
          onMode?.(control.slice(6))
          return false
        }
        if (control.startsWith('[CRYSTAL]')) {
          try {
            const crystal = JSON.parse(control.slice(9))
            onCrystal?.(crystal)
          } catch {}
          return false
        }
        if (control.startsWith('[PLOT_AUTO]')) {
          try {
            const plot = JSON.parse(control.slice(11))
            onPlotAuto?.(plot)
          } catch {}
          return false
        }
        if (control.startsWith('[INVENTORY]')) {
          try {
            const item = JSON.parse(control.slice(11))
            onInventory?.(item)
          } catch {}
          return false
        }
        // Strip inventory tags from narrative display
        const cleaned = data
          .replace(/\[ITEM_ADD:[^\]]+\]/g, '')
          .replace(/\[ITEM_USE:[^\]]+\]/g, '')
          .replace(/\[ITEM_LOSE:[^\]]+\]/g, '')
        if (cleaned.trim()) {
          onChunk?.(cleaned)
        }
        return false
      }

      const handleEventBlock = (eventBlock) => {
        if (!eventBlock) return false
        const dataLines = []
        const lines = eventBlock.split('\n')
        for (const rawLine of lines) {
          const line = rawLine.replace(/\r$/, '')
          if (!line.startsWith('data:')) continue
          let payload = line.slice(5)
          if (payload.startsWith(' ')) payload = payload.slice(1)
          dataLines.push(payload)
        }
        if (dataLines.length === 0) return false
        return handleData(dataLines.join('\n'))
      }

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        let sepIndex = buffer.indexOf('\n\n')
        while (sepIndex !== -1) {
          const eventBlock = buffer.slice(0, sepIndex)
          buffer = buffer.slice(sepIndex + 2)
          if (handleEventBlock(eventBlock)) return
          sepIndex = buffer.indexOf('\n\n')
        }
      }

      buffer += decoder.decode()
      if (buffer && handleEventBlock(buffer)) {
        return
      }
      onDone?.()
    })
    .catch((err) => onError?.(err))
}

export async function exportScenario(scenarioId, title) {
  const r = await fetch(`${BASE}/scenarios/${scenarioId}/export`)
  if (!r.ok) throw new Error('Failed to export scenario')
  const blob = await r.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${title || scenarioId}.json`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

export async function fetchJournal(campaignId) {
  const r = await fetch(`${BASE}/game/${campaignId}/journal`)
  if (!r.ok) throw new Error('Failed to fetch journal')
  return r.json()
}

export async function fetchWorldGraph(campaignId) {
  const r = await fetch(`${BASE}/game/${campaignId}/world-graph`)
  if (!r.ok) throw new Error('Failed to fetch world graph')
  return r.json()
}

export async function searchWorldGraph(campaignId, query) {
  const res = await fetch(`${BASE}/game/${campaignId}/graph-search?q=${encodeURIComponent(query)}`)
  if (!res.ok) throw new Error('Failed to search world graph')
  return res.json()
}

export async function fetchInventory(campaignId) {
  const r = await fetch(`${BASE}/game/${campaignId}/inventory`)
  if (!r.ok) throw new Error('Failed to fetch inventory')
  return r.json()
}

export async function updateInventoryItem(campaignId, name, action) {
  const r = await fetch(`${BASE}/game/${campaignId}/inventory`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, action }),
  })
  if (!r.ok) throw new Error('Failed to update inventory')
  return r.json()
}

export async function importScenario(data) {
  const r = await fetch(`${BASE}/scenarios/import`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!r.ok) throw new Error('Failed to import scenario')
  return r.json()
}
