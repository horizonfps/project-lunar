import { create } from 'zustand'

export const useGameStore = create((set) => ({
  // Scenario state
  scenarios: [],
  activeScenario: null,
  activeCampaignId: null,

  // Narrative state
  messages: [],
  isStreaming: false,
  combatMode: false,

  // Journal state
  journal: [],

  // Inventory state
  inventory: [],

  // Settings
  llmProvider: 'deepseek',
  llmModel: 'deepseek-v4-flash',
  temperature: 0.85,
  maxTokens: 2000,
  combatEnabled: true,

  // Actions
  setScenarios: (scenarios) => set({ scenarios }),
  setActiveScenario: (scenario) => {
    try { localStorage.setItem('lunar_activeScenario', JSON.stringify(scenario)) } catch {}
    return set({ activeScenario: scenario })
  },
  setActiveCampaignId: (id) => {
    try { localStorage.setItem('lunar_activeCampaignId', id) } catch {}
    return set({ activeCampaignId: id })
  },
  setStreaming: (isStreaming) => set({ isStreaming }),
  setCombatMode: (combatMode) => set({ combatMode }),

  appendMessage: (msg) =>
    set((s) => {
      const updated = [...s.messages, msg]
      try { localStorage.setItem('lunar_messages', JSON.stringify(updated)) } catch {}
      return { messages: updated }
    }),

  appendToLastMessage: (chunk) =>
    set((s) => {
      const messages = [...s.messages]
      const last = messages[messages.length - 1]
      if (last && last.role === 'assistant') {
        messages[messages.length - 1] = { ...last, content: last.content + chunk }
      } else {
        messages.push({ role: 'assistant', content: chunk })
      }
      try { localStorage.setItem('lunar_messages', JSON.stringify(messages)) } catch {}
      return { messages }
    }),

  replaceLastAssistantMessage: (content) =>
    set((s) => {
      const messages = [...s.messages]
      for (let i = messages.length - 1; i >= 0; i--) {
        if (messages[i].role === 'assistant') {
          messages[i] = { ...messages[i], content }
          break
        }
      }
      try { localStorage.setItem('lunar_messages', JSON.stringify(messages)) } catch {}
      return { messages }
    }),

  popLastPair: () =>
    set((s) => {
      const messages = [...s.messages]
      // Remove last assistant message
      if (messages.length > 0 && messages[messages.length - 1].role === 'assistant') {
        messages.pop()
      }
      // Remove last user message
      if (messages.length > 0 && messages[messages.length - 1].role === 'user') {
        messages.pop()
      }
      try { localStorage.setItem('lunar_messages', JSON.stringify(messages)) } catch {}
      return { messages }
    }),

  clearMessages: () => {
    try { localStorage.removeItem('lunar_messages') } catch {}
    return set({ messages: [] })
  },

  addJournalEntry: (entry) =>
    set((s) => ({ journal: [...s.journal, entry] })),

  setJournal: (journal) => set({ journal }),

  setInventory: (inventory) => set({ inventory }),
  addInventoryItem: (item) =>
    set((s) => ({ inventory: [...s.inventory, item] })),
  updateInventoryItem: (name, status) =>
    set((s) => ({
      inventory: s.inventory.map((i) =>
        i.name === name ? { ...i, status } : i
      ),
    })),

  updateSettings: (settings) => {
    try {
      const current = JSON.parse(localStorage.getItem('lunar_settings') || '{}')
      const merged = { ...current, ...settings }
      localStorage.setItem('lunar_settings', JSON.stringify(merged))
    } catch {}
    return set(settings)
  },

  // Session persistence
  restoreSession: () => {
    try {
      const scenarioJson = localStorage.getItem('lunar_activeScenario')
      const campaignId = localStorage.getItem('lunar_activeCampaignId')
      const messagesJson = localStorage.getItem('lunar_messages')
      const settingsJson = localStorage.getItem('lunar_settings')
      const restored = {}
      if (scenarioJson) restored.activeScenario = JSON.parse(scenarioJson)
      if (campaignId) restored.activeCampaignId = campaignId
      if (messagesJson) restored.messages = JSON.parse(messagesJson)
      if (settingsJson) {
        const s = JSON.parse(settingsJson)
        if (s.llmProvider) restored.llmProvider = s.llmProvider
        if (s.llmModel) restored.llmModel = s.llmModel
        if (s.temperature != null) restored.temperature = s.temperature
        if (s.maxTokens != null) restored.maxTokens = s.maxTokens
        if (s.combatEnabled != null) restored.combatEnabled = s.combatEnabled
      }
      if (Object.keys(restored).length > 0) set(restored)
      return Object.keys(restored).length > 0
    } catch {
      return false
    }
  },

  clearSession: () => {
    try {
      localStorage.removeItem('lunar_activeScenario')
      localStorage.removeItem('lunar_activeCampaignId')
      localStorage.removeItem('lunar_messages')
    } catch {}
    set({ activeScenario: null, activeCampaignId: null, messages: [], journal: [], inventory: [] })
  },

  // Restore settings on app load (called independently of restoreSession)
  restoreSettings: () => {
    try {
      const settingsJson = localStorage.getItem('lunar_settings')
      if (settingsJson) {
        const s = JSON.parse(settingsJson)
        const restored = {}
        if (s.llmProvider) restored.llmProvider = s.llmProvider
        if (s.llmModel) restored.llmModel = s.llmModel
        if (s.temperature != null) restored.temperature = s.temperature
        if (s.maxTokens != null) restored.maxTokens = s.maxTokens
        if (s.combatEnabled != null) restored.combatEnabled = s.combatEnabled
        if (Object.keys(restored).length > 0) set(restored)
      }
    } catch {}
  },
}))
