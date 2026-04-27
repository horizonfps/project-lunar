const BASE = '/api'  // proxied to http://localhost:8000 via vite proxy

export async function checkNeo4j() {
  try {
    const r = await fetch(`${BASE}/health/neo4j`)
    if (!r.ok) return false
    const data = await r.json()
    return data.status === 'ok'
  } catch {
    return false
  }
}

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

export async function fetchCampaigns(scenarioId) {
  const r = await fetch(`${BASE}/scenarios/${scenarioId}/campaigns`)
  if (!r.ok) throw new Error('Failed to fetch campaigns')
  return r.json()
}

export async function createCampaign(scenarioId, playerName = 'Player') {
  const r = await fetch(`${BASE}/scenarios/${scenarioId}/campaigns`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ player_name: playerName }),
  })
  if (!r.ok) throw new Error('Failed to create campaign')
  return r.json()
}

export async function fetchCharacters(campaignId, query = '') {
  const params = query ? `?q=${encodeURIComponent(query)}` : ''
  const r = await fetch(`${BASE}/game/${campaignId}/characters${params}`)
  if (!r.ok) return []
  return r.json()
}

export async function fetchHistory(campaignId) {
  const r = await fetch(`${BASE}/game/${campaignId}/history`)
  if (!r.ok) throw new Error('Failed to fetch history')
  return r.json()
}

export function streamAction({
  campaignId,
  scenarioTone,
  language,
  action,
  openingNarrative,
  maxTokens,
  provider,
  model,
  temperature,
  onChunk,
  onJournal,
  onMode,
  onCrystal,
  onPlotAuto,
  onInventory,
  onTruncateClean,
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
      opening_narrative: openingNarrative || '',
      max_tokens: maxTokens || 2000,
      provider: provider || 'deepseek',
      model: model || 'deepseek-v4-flash',
      temperature: temperature ?? 0.85,
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
        if (control.startsWith('[TRUNCATE_CLEAN]')) {
          const cleanText = control.slice(16)
          onTruncateClean?.(cleanText)
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

export async function rewindLastAction(campaignId) {
  const r = await fetch(`${BASE}/game/${campaignId}/rewind`, {
    method: 'POST',
  })
  if (!r.ok) throw new Error('Failed to rewind')
  return r.json()
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

export async function deleteCampaign(scenarioId, campaignId) {
  const r = await fetch(`${BASE}/scenarios/${scenarioId}/campaigns/${campaignId}`, {
    method: 'DELETE',
  })
  if (!r.ok) throw new Error('Failed to delete campaign')
  return r.json()
}

export async function deleteScenario(scenarioId) {
  const r = await fetch(`${BASE}/scenarios/${scenarioId}`, {
    method: 'DELETE',
  })
  if (!r.ok) throw new Error('Failed to delete scenario')
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

export async function fetchMemoryCrystals(campaignId) {
  const r = await fetch(`${BASE}/game/${campaignId}/memory-crystals`)
  if (!r.ok) throw new Error('Failed to fetch memory crystals')
  return r.json()
}

export async function crystallizeMemory(campaignId) {
  const r = await fetch(`${BASE}/game/${campaignId}/crystallize`, { method: 'POST' })
  if (!r.ok) throw new Error('Failed to crystallize')
  return r.json()
}

export async function fetchNpcMinds(campaignId) {
  const r = await fetch(`${BASE}/game/${campaignId}/npc-minds`)
  if (!r.ok) throw new Error('Failed to fetch NPC minds')
  return r.json()
}

export async function deleteNpcMind(campaignId, npcName) {
  const r = await fetch(`${BASE}/game/${campaignId}/npc-minds/${encodeURIComponent(npcName)}`, {
    method: 'DELETE',
  })
  if (!r.ok) throw new Error('Failed to delete NPC mind')
  return r.json()
}

export async function updateNpcMind(campaignId, npcName, thoughts) {
  const r = await fetch(`${BASE}/game/${campaignId}/npc-minds/${encodeURIComponent(npcName)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ thoughts }),
  })
  if (!r.ok) throw new Error('Failed to update NPC mind')
  return r.json()
}

export async function generateContent(campaignId, type, language = 'en') {
  const r = await fetch(`${BASE}/game/${campaignId}/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ type, language }),
  })
  if (!r.ok) throw new Error('Generation failed')
  return r.json()
}

export async function timeskip(campaignId, seconds) {
  const r = await fetch(`${BASE}/game/${campaignId}/timeskip`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ seconds }),
  })
  if (!r.ok) throw new Error('Timeskip failed')
  return r.json()
}

export async function fetchSetupState(campaignId) {
  const r = await fetch(`${BASE}/game/${campaignId}/setup-state`)
  if (!r.ok) throw new Error('Failed to fetch setup state')
  return r.json()
}

export async function saveSetupAnswers(campaignId, answers) {
  const r = await fetch(`${BASE}/game/${campaignId}/setup-answers`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ answers }),
  })
  if (!r.ok) throw new Error('Failed to save setup answers')
  return r.json()
}

export async function fetchScenarioView(campaignId) {
  const r = await fetch(`${BASE}/game/${campaignId}/scenario-view`)
  if (!r.ok) throw new Error('Failed to fetch scenario view')
  return r.json()
}

export async function previewOpening({
  language,
  tone,
  lore,
  directive,
  setup_questions,
  sample_answers,
}) {
  const r = await fetch(`${BASE}/scenarios/preview-opening`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      language: language || 'en',
      tone: tone || '',
      lore: lore || '',
      directive: directive || '',
      setup_questions: setup_questions || [],
      sample_answers: sample_answers || {},
    }),
  })
  if (!r.ok) throw new Error('Failed to preview opening')
  return r.json()
}

export async function regenerateOpening(campaignId) {
  const r = await fetch(`${BASE}/game/${campaignId}/regenerate-opening`, {
    method: 'POST',
  })
  if (!r.ok) {
    const err = new Error('Failed to regenerate opening')
    err.status = r.status
    try {
      err.detail = (await r.json()).detail
    } catch {}
    throw err
  }
  return r.json()
}
