Implemente melhorias no sistema de memória e suporte a Anthropic no Project Lunar (RPG narrativo).

CONTEXTO: Após ~20 ações, a IA esquece eventos anteriores e alucina porque a janela de contexto é muito pequena e a cristalização de memória é infrequente e perde detalhes. O projeto usa litellm como router de LLM.

Arquivos principais:
- backend/app/engines/memory_engine.py — constantes, cristalização e build_context_window
- backend/app/engines/narrator_engine.py — stream_narrative e build_system_prompt
- backend/app/services/game_session.py — _handle_narrative e montagem de contexto
- backend/app/engines/llm_router.py — LLM router (já usa litellm, já tem enum ANTHROPIC)
- frontend/src/components/SettingsPanel.jsx — UI de configurações
- backend/app/main.py — endpoint /api/settings (já aceita qualquer provider)

=== PARTE 1: SUPORTE A ANTHROPIC NO FRONTEND ===

1) SettingsPanel.jsx — Adicionar Anthropic e OpenAI como providers selecionáveis:
   Mudar o array PROVIDERS de:
   ```
   [{ id: 'deepseek', label: 'DeepSeek', models: ['deepseek-chat', 'deepseek-reasoner'] }]
   ```
   Para:
   ```
   [
     { id: 'deepseek', label: 'DeepSeek', models: ['deepseek-chat', 'deepseek-reasoner'] },
     { id: 'anthropic', label: 'Anthropic', models: ['claude-sonnet-4-6', 'claude-haiku-4-5-20251001'] },
     { id: 'openai', label: 'OpenAI', models: ['gpt-5.6-sol'] },
   ]
   ```

   Também transformar o provider de um div estático para um <select> funcional que permite trocar entre providers. Quando trocar provider, auto-selecionar o primeiro modelo da lista.

2) llm_router.py — Ajustar o _build_model_string para Anthropic:
   O litellm espera "anthropic/claude-sonnet-4-6" para Anthropic. Verificar se o método _build_model_string já faz isso corretamente (deve fazer, pois usa f"{provider.value}/{model}"). Se estiver correto, não precisa mudar.

=== PARTE 2: JANELA DE HISTÓRICO ===

3) narrator_engine.py — No método stream_narrative(), mudar:
   history[-10:] → history[-30:]

   Com Sonnet 4.6 (1M de contexto) e DeepSeek (200k), 30 mensagens cabe tranquilo. Isso é o fix MAIS IMPACTANTE — triplica a conversa visível pro LLM.

=== PARTE 3: CRISTALIZAÇÃO MAIS FREQUENTE ===

4) memory_engine.py — Mudar constantes:
   AUTO_CRYSTALLIZE_THRESHOLD: 8 → 4 (cristalizar mais cedo)
   RAW_LIMIT: 6 → 10 (mais eventos crus no contexto)

5) memory_engine.py — Melhorar o prompt de cristalização no método crystallize():
   O prompt atual diz "Preserve decisions, relationship shifts, world state, conflicts, unresolved hooks."

   Melhorar para ser MUITO mais específico:
   ```
   "Rules:\n"
   "- ai_memory: machine-oriented structured memory for LLM context.\n"
   "- Use this EXACT format for ai_memory:\n"
   "  RELATIONSHIPS: [who knows who and how they met, e.g. 'CharA MET CharB (context of meeting)']\n"
   "  PROMISES: [agreements, pacts, deals the player made]\n"
   "  KEY_EVENTS: [major plot points in chronological order]\n"
   "  PLAYER_STATE: [current emotional state, goals, grudges]\n"
   "  WORLD_STATE: [faction standings, location changes, threats]\n"
   "- player_summary: short executive summary for UI (2-4 sentences).\n"
   "- NEVER omit relationship details. WHO met WHO and WHAT they discussed is critical.\n"
   "- Focus on net-new changes from NEW_EVENTS; do not restate stable facts unless changed."
   ```

=== PARTE 4: NPC MINDS E JOURNAL NO CONTEXTO ===

6) game_session.py — No _handle_narrative(), APÓS a seção de narrator_hints, adicionar NPC minds como contexto:
   ```python
   npc_ctx = ""
   if self._npc_minds:
       minds = self._npc_minds.get_all_minds(self.campaign_id)
       if minds:
           lines = ["NPC STATES (what each NPC is currently thinking/feeling):"]
           for m in minds[:10]:
               thoughts = ", ".join(f"{k}={t.value}" for k, t in list(m.thoughts.items())[:4])
               lines.append(f"- {m.name}: {thoughts}")
           npc_ctx = "\n".join(lines)
   ```

   Passar npc_context=npc_ctx pro build_system_prompt.

7) game_session.py — Também adicionar journal resumido:
   ```python
   journal_ctx = ""
   if self._journal:
       entries = self._journal.get_journal(self.campaign_id)
       if entries:
           lines = ["STORY LOG (key events so far):"]
           for e in entries[-8:]:
               lines.append(f"- {e.summary}")
           journal_ctx = "\n".join(lines)
   ```

   Passar journal_context=journal_ctx pro build_system_prompt.

8) narrator_engine.py — Adicionar os novos parâmetros em build_system_prompt():
   Adicionar npc_context: str = "" e journal_context: str = "" como parâmetros.
   Incluir como seções no prompt, ANTES das narrator rules.

=== PARTE 5: PRIORIZAÇÃO DE CONTEXTO ===

9) narrator_engine.py — No build_system_prompt(), adicionar lógica de prioridade:
   Se o prompt total (todas as seções juntas) ultrapassar 6000 caracteres:
   - Primeiro cortar graph_context
   - Depois cortar journal_context
   - Depois cortar npc_context
   - NUNCA cortar: tone_instructions, memory_context, narrator_hints

   Com DeepSeek (200k) e Anthropic/Sonnet (1M), na prática raramente vai cortar.
   O budget existe como proteção, não como limitação ativa.

IMPORTANTE:
- Ler cada arquivo ANTES de editar
- Rodar os testes após todas as mudanças: cd backend && python -m pytest tests/ -x -q
- Buildar o frontend após: cd frontend && npx vite build
- NÃO mudar lógica de combate, plot generator ou world reactor
- NÃO criar arquivos novos
- O projeto usa litellm que já suporta Anthropic nativamente
