    const state = {
      team: '',
      panX: -20,
      panY: -40,
      scale: 0.95,
      isPanning: false,
      panStartX: 0,
      panStartY: 0,
      dragCardId: null,
      dragOffsetX: 0,
      dragOffsetY: 0,
      resizeCardId: null,
      resizeStartX: 0,
      resizeStartY: 0,
      resizeStartW: 0,
      resizeStartH: 0,
      targetIndex: 0,
      targets: ['@all', '@lead'],
      cards: {},
      allTeams: []
    };

    const viewport = document.getElementById('canvasViewport');
    const world = document.getElementById('canvasWorld');
    const cardsLayer = document.getElementById('cardsLayer');
    const wiresGroup = document.getElementById('wiresGroup');
    const zoomLevelDisplay = document.getElementById('zoomLevelDisplay');
    const masterInput = document.getElementById('masterInput');
    const currentTargetBadge = document.getElementById('currentTargetBadge');

    // ----------------- Team Data & Setup -----------------

    async function loadTeamsList() {
      try {
        const res = await fetch('/api/teams');
        const data = await res.json();
        if (data.success && data.teams) {
          state.allTeams = data.teams;
          renderTeamsDropdown();
        }
      } catch (e) {
        console.error('Failed to load teams', e);
      }
    }

    function renderTeamsDropdown() {
      const menu = document.getElementById('teamsDropdownMenu');
      menu.innerHTML = '';
      state.allTeams.forEach(t => {
        const item = document.createElement('div');
        item.className = `team-menu-item ${t.name === state.team ? 'active' : ''}`;
        item.innerHTML = `
          <span>${t.name}</span>
          <span style="font-size:0.68rem; color:${t.is_running ? 'var(--emerald)' : 'var(--text-dim)'}">
            ${t.is_running ? '● running' : '○ stopped'}
          </span>
        `;
        item.onclick = () => switchTeam(t.name);
        menu.appendChild(item);
      });
    }

    function toggleTeamMenu() {
      const menu = document.getElementById('teamsDropdownMenu');
      menu.classList.toggle('show');
    }

    window.addEventListener('click', (e) => {
      if (!e.target.closest('.team-select-dropdown')) {
        document.getElementById('teamsDropdownMenu').classList.remove('show');
      }
    });

    function setTeamLabels(teamName) {
      state.team = teamName;
      localStorage.setItem('hiveTeam', teamName);
      document.getElementById('currentTeamDisplay').innerText = teamName;
      document.getElementById('hubTeamInfo').innerText = `team: ${teamName}`;
      document.getElementById('categoryLabel').innerText = `${teamName.toUpperCase()} WORKSPACE`;
      document.getElementById('clusterTeamLabel').innerText = `${teamName.toUpperCase()} WORKERS`;
    }

    async function switchTeam(teamName) {
      if (teamName === state.team) return;
      setTeamLabels(teamName);
      document.getElementById('teamsDropdownMenu').classList.remove('show');

      // Clear existing cards
      cardsLayer.innerHTML = '';
      state.cards = {};

      // Load team info and re-init
      await loadTeamData(teamName);
      reconnectWebSocket();
      resetCanvasView();
    }



    // ----------------- Token Analytics & Resource Management -----------------
    let latestTokenData = null;

    function formatTokens(num) {
      if (num === undefined || num === null || isNaN(num)) return '0';
      const n = Number(num);
      if (Math.abs(n) >= 1000000000) return (n / 1000000000).toFixed(1).replace(/\.0$/, '') + 'B';
      if (Math.abs(n) >= 1000000) return (n / 1000000).toFixed(1).replace(/\.0$/, '') + 'M';
      if (Math.abs(n) >= 1000) return (n / 1000).toFixed(1).replace(/\.0$/, '') + 'k';
      return String(n);
    }

    function updateTokenNavbarDisplay(tokens) {
      if (!tokens) return;
      latestTokenData = tokens;
      const spentLabel = document.getElementById('navTokenSpentLabel');
      const barFill = document.getElementById('navTokenBarFill');
      const remBadge = document.getElementById('navTokenRemainingBadge');

      const totalSpent = tokens.total_tokens || 0;
      const totalRem = tokens.total_remaining_tokens || 0;
      const totalPct = tokens.total_context_pct || 0;

      if (spentLabel) spentLabel.innerText = `${formatTokens(totalSpent)} harcandı`;
      if (remBadge) remBadge.innerText = `${formatTokens(totalRem)} boş (${totalPct}%)`;
      if (barFill) {
        barFill.style.width = `${Math.min(100, Math.max(0, totalPct))}%`;
        if (totalPct > 80) {
          barFill.style.background = '#f43f5e';
        } else if (totalPct > 50) {
          barFill.style.background = '#f59e0b';
        } else {
          barFill.style.background = 'var(--emerald)';
        }
      }
    }

    function toggleTokenDrawer() {
      const d = document.getElementById('tokenDrawer');
      d.classList.toggle('open');
      if (d.classList.contains('open')) {
        document.getElementById('brainDrawer').classList.remove('open');
        document.getElementById('kanbanDrawer').classList.remove('open');
        document.getElementById('locksDrawer').classList.remove('open');
        document.getElementById('toolsDrawer').classList.remove('open');
        refreshTokenData();
      }
    }

    async function refreshTokenData() {
      const body = document.getElementById('tokenDrawerBody');
      try {
        const res = await fetch(`/api/team/${state.team}/tokens`);
        const data = await res.json();
        if (data.success && data.tokens) {
          latestTokenData = data.tokens;
          updateTokenNavbarDisplay(data.tokens);
          renderTokenDrawerBody(data.tokens);
        } else {
          body.innerHTML = `<div style="color:var(--text-dim); font-size:0.75rem; text-align:center; padding:30px 0;">Token verisi alınamadı: ${escapeHtml(data.error || 'Bilinmeyen hata')}</div>`;
        }
      } catch (e) {
        body.innerHTML = `<div style="color:var(--text-dim); font-size:0.75rem; text-align:center; padding:30px 0;">Token telemetrisi yüklenirken hata oluştu.</div>`;
      }
    }

    function renderTokenDrawerBody(tokens) {
      const body = document.getElementById('tokenDrawerBody');
      if (!tokens || !tokens.agents) {
        body.innerHTML = '<div style="color:var(--text-dim); font-size:0.75rem; text-align:center; padding:30px 0;">Henüz token tüketim verisi bulunmuyor.</div>';
        return;
      }

      const totalSpent = tokens.total_tokens || 0;
      const totalContext = tokens.total_context_tokens || 0;
      const totalLimit = tokens.total_context_limit || 1;
      const totalRemaining = tokens.total_remaining_tokens || 0;
      const totalPct = tokens.total_context_pct || 0;
      const cachePct = tokens.cache_hit_pct || 0;
      const topConsumer = tokens.top_consumer;

      let html = `
        <div class="token-kpi-grid">
          <div class="token-kpi-card">
            <span class="token-kpi-label">Toplam Harcanan</span>
            <span class="token-kpi-value" style="color:var(--amber);">${formatTokens(totalSpent)}</span>
            <span class="token-kpi-sub">Giriş: ${formatTokens(tokens.total_input_tokens || 0)} • Çıkış: ${formatTokens(tokens.total_output_tokens || 0)}</span>
          </div>

          <div class="token-kpi-card">
            <span class="token-kpi-label">Kalan Kapasite</span>
            <span class="token-kpi-value" style="color:var(--emerald);">${formatTokens(totalRemaining)}</span>
            <span class="token-kpi-sub">Aktif: ${formatTokens(totalContext)} / ${formatTokens(totalLimit)} (%${totalPct})</span>
          </div>

          <div class="token-kpi-card">
            <span class="token-kpi-label">Önbellek İsabeti</span>
            <span class="token-kpi-value" style="color:#38bdf8;">%${cachePct}</span>
            <span class="token-kpi-sub">${formatTokens(tokens.total_cache_tokens || 0)} cache token tasarrufu</span>
          </div>

          <div class="token-kpi-card">
            <span class="token-kpi-label">Aktif Ajan Sayısı</span>
            <span class="token-kpi-value" style="color:#fff;">${tokens.agents.length}</span>
            <span class="token-kpi-sub">Ortalama: ${formatTokens(Math.round(totalSpent / Math.max(1, tokens.agents.length)))} / ajan</span>
          </div>
        </div>
      `;

      if (topConsumer) {
        html += `
          <div style="background:rgba(245,158,11,0.08); border:1px solid rgba(245,158,11,0.25); border-radius:8px; padding:9px 12px; margin-bottom:12px; display:flex; justify-content:space-between; align-items:center; font-size:0.73rem;">
            <span style="color:var(--text-muted);">⚡ En Yüksek Tüketim: <strong style="color:var(--amber);">${escapeHtml(topConsumer.target)} (${escapeHtml(topConsumer.name)})</strong></span>
            <span style="font-family:var(--font-mono); font-weight:700; color:#fff;">${formatTokens(topConsumer.cum_total_tokens)} (%${topConsumer.pct_of_team_tokens})</span>
          </div>
        `;
      }

      html += `<div style="font-size:0.7rem; font-weight:700; color:var(--text-muted); text-transform:uppercase; letter-spacing:0.05em; margin-bottom:8px;">Ajan Bazlı Harcama & Bağlam Durumu</div>`;

      tokens.agents.forEach(ag => {
        const agPct = ag.context_pct || 0;
        let barColor = 'var(--emerald)';
        if (agPct > 80) barColor = '#f43f5e';
        else if (agPct > 50) barColor = '#f59e0b';

        html += `
          <div class="agent-token-card">
            <div class="agent-token-header">
              <div class="agent-token-identity">
                <span class="agent-token-target">${escapeHtml(ag.target)}</span>
                <span class="agent-token-name">${escapeHtml(ag.name)}</span>
                <span class="runtime-badge ${escapeHtml(ag.runtime || 'agy')}" style="padding:1px 4px; font-size:0.6rem;">${escapeHtml(ag.runtime || 'agy').toUpperCase()}</span>
              </div>
              <div>
                <span class="agent-token-total">${formatTokens(ag.cum_total_tokens)}</span>
                <span class="agent-token-pct">(%${ag.pct_of_team_tokens})</span>
              </div>
            </div>

            <div class="agent-bar-track" title="Bağlam: ${ag.context_tokens.toLocaleString()} / ${ag.context_limit.toLocaleString()} (%${agPct})">
              <div class="agent-bar-fill" style="width:${Math.min(100, Math.max(0, agPct))}%; background:${barColor};"></div>
            </div>

            <div class="agent-context-info">
              <span>Bağlam: <strong style="color:#fff;">${formatTokens(ag.context_tokens)}</strong> / ${formatTokens(ag.context_limit)} (<strong style="color:${barColor};">%${agPct}</strong>)</span>
              <span>Kalan: <strong style="color:var(--emerald);">${formatTokens(ag.remaining_tokens)}</strong></span>
            </div>

            <div style="display:flex; justify-content:space-between; font-size:0.65rem; color:var(--text-dim); font-family:var(--font-mono); border-top:1px solid rgba(255,255,255,0.04); padding-top:4px;">
              <span>Giriş: ${formatTokens(ag.cum_input_tokens)} • Cache: ${formatTokens(ag.cum_cache_tokens)} • Çıkış: ${formatTokens(ag.cum_output_tokens)}</span>
              <span>#${ag.steps || 0} Adım</span>
            </div>
          </div>
        `;
      });

      body.innerHTML = html;
    }

    // ----------------- Project Brain & Asynchronous Notes (/btw) -----------------
    let projectBrainData = [];

    function toggleBrainDrawer() {
      const d = document.getElementById('brainDrawer');
      d.classList.toggle('open');
      if (d.classList.contains('open')) {
        document.getElementById('tokenDrawer').classList.remove('open');
        document.getElementById('kanbanDrawer').classList.remove('open');
        document.getElementById('locksDrawer').classList.remove('open');
        document.getElementById('toolsDrawer').classList.remove('open');
        refreshBrainView();
      }
    }

    function refreshBrainView() {
      const container = document.getElementById('brainSectionsList');
      if (!projectBrainData || projectBrainData.length === 0) {
        container.innerHTML = '<div style="color:var(--text-dim); font-size:0.75rem; text-align:center; padding:30px 0;">Hafıza kaydı bulunamadı.<br>TEAM_MEMORY.md mevcut olduğunda mimari başlıklar burada görünür.</div>';
        return;
      }

      let html = '';
      projectBrainData.forEach((sec, idx) => {
        html += `
          <div class="brain-section-card">
            <div class="brain-section-title">
              <span>●</span> ${escapeHtml(sec.title)}
            </div>
            <div class="brain-section-content">${escapeHtml(sec.content)}</div>
          </div>
        `;
      });
      container.innerHTML = html;
    }

    function openSendNoteModal(defaultTarget = null, defaultSender = null) {
      const targetSelect = document.getElementById('noteTargetSelect');
      const senderSelect = document.getElementById('noteSenderSelect');
      
      targetSelect.innerHTML = '';
      senderSelect.innerHTML = '<option value="Tech Lead">Tech Lead</option>';

      // Populate options
      targetSelect.innerHTML += '<option value="@all">@all (Tüm Takım)</option>';
      if (state.cards['lead']) {
        targetSelect.innerHTML += '<option value="@lead">@lead (Tech Lead)</option>';
      }

      Object.values(state.cards).forEach(c => {
        if (c.type === 'worker') {
          targetSelect.innerHTML += `<option value="${c.target}">${c.name} (${c.target})</option>`;
          senderSelect.innerHTML += `<option value="${c.target}">${c.name} (${c.target})</option>`;
        }
      });

      if (defaultTarget) targetSelect.value = defaultTarget;
      if (defaultSender) senderSelect.value = defaultSender;

      document.getElementById('noteTextInput').value = '';
      document.getElementById('modalSendNote').classList.add('show');
      document.getElementById('noteTextInput').focus();
    }

    async function submitSendNote() {
      const sender = document.getElementById('noteSenderSelect').value;
      const target = document.getElementById('noteTargetSelect').value;
      const note = document.getElementById('noteTextInput').value.trim();

      if (!note) {
        alert('Not metni girmelisiniz!');
        return;
      }

      try {
        const res = await fetch('/api/note', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ team: state.team, target, sender, note })
        });
        const data = await res.json();
        if (data.success) {
          closeModals();
          triggerWirePulseAnimation();
          // Provide instant feedback in input placeholder
          masterInput.placeholder = `Not iletildi: [${sender} -> ${target}]: "${note.slice(0, 35)}..."`;
          setTimeout(() => { masterInput.placeholder = "Type command to direct agents..."; }, 4000);
        } else {
          alert(`Hata: ${data.error}`);
        }
      } catch (e) {
        alert('Not gönderilemedi.');
      }
    }

    function triggerWirePulseAnimation() {
      const hub = document.getElementById('centralHub');
      if (hub) {
        hub.style.transform = 'scale(1.1)';
        hub.style.borderColor = 'var(--amber)';
        setTimeout(() => {
          hub.style.transform = 'scale(1)';
          hub.style.borderColor = 'rgba(255, 255, 255, 0.12)';
        }, 800);
      }
    }

    // ----------------- Ecosystem, Tools & MCP Hub Logic -----------------
    let ecosystemData = { tools: [], skills: [], plugins: [], mcp_servers: [], personas: [] };

    async function loadEcosystem() {
      try {
        const res = await fetch('/api/ecosystem');
        const data = await res.json();
        if (data.success) {
          ecosystemData = data;
          // Re-render tool strips on existing cards
          Object.keys(state.cards).forEach(cid => renderCardToolsStrip(cid));
        }
      } catch (e) {
        console.error('Failed to load ecosystem', e);
      }
    }

    function getToolMeta(toolId) {
      return (ecosystemData.tools || []).find(t => t.id === toolId) || { id: toolId, name: toolId, icon: '⚡', description: '' };
    }

    function toggleToolsDrawer() {
      const d = document.getElementById('toolsDrawer');
      d.classList.toggle('open');
      if (d.classList.contains('open')) {
        document.getElementById('tokenDrawer').classList.remove('open');
        document.getElementById('brainDrawer').classList.remove('open');
        document.getElementById('kanbanDrawer').classList.remove('open');
        document.getElementById('locksDrawer').classList.remove('open');
        refreshToolsDrawer();
      }
    }

    function refreshToolsDrawer() {
      const container = document.getElementById('toolsDrawerBody');
      const tools = ecosystemData.tools || [];
      const mcps = ecosystemData.mcp_servers || [];
      const plugins = ecosystemData.plugins || [];

      let targetOptions = `<option value="@lead">@lead (Tech Lead)</option><option value="@all">@all (Tüm Takım)</option>`;
      Object.values(state.cards).forEach(c => {
        if (c.type === 'worker') {
          targetOptions += `<option value="${c.target}">${escapeHtml(c.name)} (${c.target})</option>`;
        }
      });

      let html = `
        <div class="brain-section-card" style="border-color:rgba(245,158,11,0.3);">
          <div class="brain-section-title">⚡ Hızlı Araç Çalıştırıcı (Hedef Ajana Uygula)</div>
          <div style="display:flex; gap:6px; align-items:center; margin-top:4px;">
            <span style="font-size:0.72rem; color:var(--text-muted);">Hedef:</span>
            <select id="hubToolTargetSelect" class="modal-form-input" style="height:28px; font-size:0.75rem; flex:1;">${targetOptions}</select>
          </div>
          <div style="display:flex; flex-direction:column; gap:6px; margin-top:6px;">
      `;

      tools.forEach(t => {
        html += `
          <div style="background:#090a0c; border:1px solid var(--border-subtle); border-radius:7px; padding:8px 10px; display:flex; flex-direction:column; gap:4px;">
            <div style="display:flex; justify-content:space-between; align-items:center;">
              <span style="font-size:0.77rem; font-weight:600; color:#f3f4f6;">${t.icon || '🔧'} ${escapeHtml(t.name)}</span>
              <div style="display:flex; gap:4px;">
                <button class="card-btn active" onclick="runToolFromHub('${t.id}', false)" title="Aracı çalıştır ve çıktısını gör">Çalıştır</button>
                <button class="card-btn" onclick="runToolFromHub('${t.id}', true)" title="Çıktıyı doğrudan hedef ajana görev olarak ilet">Ajana İlet</button>
              </div>
            </div>
            <div style="font-size:0.69rem; color:var(--text-muted);">${escapeHtml(t.description)}</div>
            <div style="font-size:0.65rem; font-family:var(--font-mono); color:var(--text-dim);">${escapeHtml(t.command_or_prompt.slice(0, 85))}</div>
          </div>
        `;
      });

      html += `
          </div>
        </div>

        <div class="brain-section-card">
          <div class="brain-section-title">➕ Yeni Özel Araç (Custom Tool) Tanımla</div>
          <input type="text" id="customToolName" class="modal-form-input" style="height:30px; font-size:0.75rem;" placeholder="Araç Adı (Örn: CapRover Deploy Check)">
          <input type="text" id="customToolDesc" class="modal-form-input" style="height:30px; font-size:0.75rem;" placeholder="Kısa açıklama">
          <div style="display:grid; grid-template-columns: 1fr 1fr; gap:6px;">
            <select id="customToolType" class="modal-form-input" style="height:30px; font-size:0.74rem; background:#0c0d0e; color:#fff;">
              <option value="shell_context">Terminal Komutu (Shell)</option>
              <option value="prompt_template">Ajan Direktif Şablonu</option>
            </select>
            <input type="text" id="customToolIcon" class="modal-form-input" style="height:30px; font-size:0.75rem;" placeholder="İkon (🚀, 🧪, 🔍)" value="🚀">
          </div>
          <input type="text" id="customToolCmd" class="modal-form-input" style="height:30px; font-size:0.75rem; font-family:var(--font-mono);" placeholder="Komut veya direktif metni...">
          <button class="modal-btn confirm" style="height:30px; font-size:0.75rem; margin-top:4px;" onclick="submitCreateCustomTool()">Aracı Sisteme Kaydet</button>
        </div>

        <div class="brain-section-card">
          <div class="brain-section-title">🔌 Aktif MCP Sunucuları (${mcps.length})</div>
          ${mcps.map(m => `
            <div style="display:flex; justify-content:space-between; align-items:center; background:#090a0c; padding:6px 10px; border-radius:6px; border:1px solid var(--border-subtle); font-size:0.73rem;">
              <span style="font-family:var(--font-mono); color:var(--emerald); font-weight:600;">● ${escapeHtml(m.name)} (${escapeHtml(m.type)})</span>
              <span style="font-family:var(--font-mono); font-size:0.65rem; color:var(--text-dim);">${escapeHtml(m.command)}</span>
            </div>
          `).join('')}
        </div>

        <div class="brain-section-card">
          <div class="brain-section-title">🧩 Yüklü Antigravity Eklenti & Skill Paketleri (${plugins.length} paket, ${(ecosystemData.skills || []).length} skill)</div>
          <div style="display:flex; flex-wrap:wrap; gap:5px;">
            ${plugins.map(p => `<span class="skill-chip-tag" title="${(p.skills || []).join(', ')}">${escapeHtml(p.name)} (${p.skills_count})</span>`).join('')}
          </div>
        </div>
      `;

      container.innerHTML = html;
    }

    async function submitCreateCustomTool() {
      const name = document.getElementById('customToolName').value.trim();
      const description = document.getElementById('customToolDesc').value.trim();
      const tool_type = document.getElementById('customToolType').value;
      const icon = document.getElementById('customToolIcon').value.trim() || '🔧';
      const command_or_prompt = document.getElementById('customToolCmd').value.trim();

      if (!name || !command_or_prompt) {
        alert('Araç adı ve komut/şablon girmelisiniz!');
        return;
      }

      const res = await fetch('/api/tools/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, description, tool_type, icon, command_or_prompt })
      });
      const data = await res.json();
      if (data.success) {
        await loadEcosystem();
        refreshToolsDrawer();
      } else {
        alert(`Hata: ${data.error}`);
      }
    }

    async function runToolFromHub(toolId, sendToAgent = false) {
      const sel = document.getElementById('hubToolTargetSelect');
      const target = sel ? sel.value : '@lead';
      await triggerAgentTool(target, toolId, sendToAgent);
    }

    async function triggerAgentTool(target, toolId, sendToAgent = false) {
      const tMeta = getToolMeta(toolId);
      let prompt = '__TOOL_ONLY__';
      if (sendToAgent || tMeta.tool_type === 'prompt_template') {
        const extra = window.prompt(`[${tMeta.name} -> ${target}] Ek talimatınız (isteğe bağlı):`, 'Sonuçları analiz et ve gerekli düzeltmeleri uygula.');
        if (extra === null) return;
        prompt = extra || 'Analiz et ve uygula.';
      }

      try {
        const res = await fetch('/api/agent/run-tool', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ team: state.team, target, tool_id: toolId, prompt })
        });
        const data = await res.json();
        if (data.tool_only) {
          // Put output directly into the target card's Term view and switch to Term!
          const card = Object.values(state.cards).find(c => c.target === target) || state.cards['lead'];
          if (card) {
            card.termLog = `=== [${tMeta.icon} ${tMeta.name} Çıktısı] ===\n${data.output}\n\n` + (card.termLog || '');
            toggleCardMode(card.id, 'term');
            updateCardContent(card.id);
          }
        } else if (data.success) {
          triggerWirePulseAnimation();
        } else {
          alert(`Araç hatası: ${data.error}`);
        }
      } catch (e) {
        alert('Araç çalıştırılamadı.');
      }
    }

    // ----------------- Kanban & Locks Logic -----------------
    let teamLocks = [];
    let teamTasks = [];

    function toggleKanbanDrawer() {
      const d = document.getElementById('kanbanDrawer');
      d.classList.toggle('open');
      if (d.classList.contains('open')) {
        document.getElementById('tokenDrawer').classList.remove('open');
        document.getElementById('locksDrawer').classList.remove('open');
        document.getElementById('brainDrawer').classList.remove('open');
        document.getElementById('toolsDrawer').classList.remove('open');
        refreshKanbanView();
      }
    }

    function toggleLocksDrawer() {
      const d = document.getElementById('locksDrawer');
      d.classList.toggle('open');
      if (d.classList.contains('open')) {
        document.getElementById('tokenDrawer').classList.remove('open');
        document.getElementById('kanbanDrawer').classList.remove('open');
        document.getElementById('brainDrawer').classList.remove('open');
        document.getElementById('toolsDrawer').classList.remove('open');
        refreshLocksView();
      }
    }

    function refreshKanbanView() {
      const container = document.getElementById('kanbanTasksList');
      if (!teamTasks || teamTasks.length === 0) {
        container.innerHTML = '<div style="color:var(--text-dim); font-size:0.75rem; text-align:center; padding:30px 0;">Aktif görev bulunamadı.<br>TEAM_MEMORY.md içinde - [ ] formatında görev ekleyebilirsiniz.</div>';
        document.getElementById('kanbanCountBadge').innerText = '0';
        return;
      }

      document.getElementById('kanbanCountBadge').innerText = teamTasks.length;
      let html = '';
      teamTasks.forEach((t, i) => {
        const st = t.status || 'todo';
        const stLabel = st === 'done' ? '✓ TAMAMLANDI' : (st === 'in_progress' ? '⚡ SÜRÜYOR' : (st === 'blocked' ? '▲ ENGEL' : '○ BEKLİYOR'));
        html += `
          <div class="kanban-task-card">
            <div class="kanban-task-header">
              <span class="kanban-status-pill ${st}">${stLabel}</span>
              <span style="font-size:0.65rem; color:var(--text-dim);">${escapeHtml(t.source || '')}</span>
            </div>
            <div class="kanban-task-title">${escapeHtml(t.title)}</div>
          </div>
        `;
      });
      container.innerHTML = html;
    }

    function refreshLocksView() {
      const container = document.getElementById('locksListBody');
      if (!teamLocks || teamLocks.length === 0) {
        container.innerHTML = '<div style="color:var(--text-dim); font-size:0.75rem; text-align:center; padding:30px 0;">Şu anda hiçbir dosyada aktif kilit yok.<br><span style="color:var(--emerald);">Tüm repolar güvenli ve çakışmasız.</span></div>';
        document.getElementById('locksCountBadge').innerText = '0';
        document.getElementById('locksCountBadge').style.background = '#27272a';
        return;
      }

      document.getElementById('locksCountBadge').innerText = teamLocks.length;
      document.getElementById('locksCountBadge').style.background = 'rgba(245, 158, 11, 0.4)';
      let html = '';
      teamLocks.forEach(l => {
        html += `
          <div class="lock-card-item">
            <div class="lock-file-name">🔒 ${escapeHtml(l.file)}</div>
            <div class="lock-meta-row">
              <span>Ajan: <span class="lock-agent-tag">${escapeHtml(l.agent)}</span></span>
              <span>Scope: ${escapeHtml(l.scope || 'repo')}</span>
            </div>
          </div>
        `;
      });
      container.innerHTML = html;
    }

    function updateAgentStatusBadge(cardId, status) {
      const badge = document.getElementById(`badge-${cardId}`);
      const indicator = document.getElementById(`indicator-${cardId}`);
      if (!badge) return;

      badge.className = `agent-status-badge ${status}`;
      if (status === 'working') {
        badge.innerHTML = '● RUNNING';
        if (indicator) indicator.style.background = 'var(--amber)';
      } else if (status === 'error') {
        badge.innerHTML = '▲ ERROR';
        if (indicator) indicator.style.background = 'var(--rose)';
      } else {
        badge.innerHTML = '○ IDLE';
        if (indicator) indicator.style.background = 'var(--emerald)';
      }
    }

    async function loadTeamData(teamName) {
      try {
        const res = await fetch(`/api/team/${teamName}`);
        const data = await res.json();
        if (!data.success) return;

        cardsLayer.innerHTML = '';
        state.cards = {};
        state.targets = ['@all', '@lead'];

        // 1. Tech Lead Node
        const lead = data.lead;
        state.cards['lead'] = {
          id: 'lead',
          type: 'lead',
          name: lead.name,
          role: lead.role,
          sub: lead.cid,
          full_cid: lead.full_cid || '',
          runtime: lead.runtime || 'agy',
          model: '',
          persona: lead.persona || '',
          effort: lead.effort || 'high',
          workspace_dir: lead.workspace_dir || data.project_dir || '',
          skills: [],
          tools: ['git-status-diff', 'graphify-query', 'memory-sync'],
          target: '@lead',
          x: 120,
          y: 230,
          w: 410,
          h: 490,
          mode: 'md',
          rawLog: '',
          termLog: '',
          thinking: '',
          tool_calls: [],
          telemetry: lead.telemetry || { steps: 0, input_tokens: 0, cache_tokens: 0 }
        };

        // 2. Workers
        const savedLayout = loadSavedLayout();
        applySavedGeometry(state.cards['lead'], savedLayout);
        data.agents.forEach((ag) => {
          state.targets.push(ag.target);

          state.cards[ag.id] = {
            id: ag.id,
            pane: ag.pane,
            aid: ag.aid,
            type: 'worker',
            name: ag.name,
            role: ag.role,
            sub: ag.cid,
            full_cid: ag.full_cid || '',
            runtime: ag.runtime || 'agy',
            model: ag.model || '',
            persona: ag.persona || '',
            effort: ag.effort || 'medium',
            workspace_dir: ag.workspace_dir || data.project_dir || '',
            skills: ag.skills || [],
            tools: ag.tools || ['git-status-diff'],
            target: ag.target,
            x: 0,
            y: 0,
            w: 425,
            h: 300,
            mode: 'md',
            rawLog: '',
            termLog: '',
            thinking: '',
            tool_calls: [],
            telemetry: ag.telemetry || { steps: 0, input_tokens: 0, cache_tokens: 0 }
          };
        });
        placeWorkers(savedLayout);
        renderCardDOM(state.cards['lead']);
        updateCardContent('lead');
        data.agents.forEach((ag) => {
          renderCardDOM(state.cards[ag.id]);
          updateCardContent(ag.id);
        });

        // Update cluster size
        const workerCount = data.agents.length;
        document.getElementById('workersCountTag').innerText = `${workerCount} ACTIVE`;
        document.getElementById('livePanesCount').innerText = `${workerCount + 1} native`;
        document.getElementById('activeAgentsBadge').innerText = `${workerCount + 1} agents`;

        if (data.tokens) {
          latestTokenData = data.tokens;
          updateTokenNavbarDisplay(data.tokens);
        }

        if (data.locks) {
          teamLocks = data.locks;
          refreshLocksView();
        }
        if (data.tasks) {
          teamTasks = data.tasks;
          refreshKanbanView();
        }
        if (data.brain) {
          projectBrainData = data.brain;
        }

        updateWires();
      } catch (e) {
        console.error('Failed to load team data', e);
      }
    }

    // ----------------- DOM Rendering -----------------

    function renderCardDOM(card) {
      const el = document.createElement('div');
      el.id = `card-${card.id}`;
      el.className = 'agent-card';
      el.style.left = `${card.x}px`;
      el.style.top = `${card.y}px`;
      el.style.width = `${card.w}px`;
      el.style.height = `${card.h}px`;

      el.innerHTML = `
        <div class="card-header" onmousedown="onCardHeaderDown(event, '${card.id}')">
          <div class="card-title-group">
            <div class="status-indicator" id="indicator-${card.id}" style="background:${card.type === 'lead' ? 'var(--amber)' : 'var(--emerald)'}"></div>
            <div class="card-title-text" id="title-${card.id}" title="${escapeHtml(card.name)}">${escapeHtml(card.name)}</div>
            <span class="runtime-badge ${escapeHtml(card.runtime || 'agy')}">${escapeHtml(card.runtime || 'agy').toUpperCase()}</span>
            <div class="agent-status-badge ${card.status || 'idle'}" id="badge-${card.id}">
              ${card.status === 'working' ? '● RUNNING' : (card.status === 'error' ? '▲ ERROR' : '○ IDLE')}
            </div>
            <div class="card-badge-role" id="role-${card.id}">${escapeHtml(card.role)}</div>
          </div>
          <div class="card-actions">
            <button class="card-btn ${card.mode === 'md' ? 'active' : ''}" id="btn-md-${card.id}" onclick="toggleCardMode('${card.id}', 'md')" title="Saf Markdown Çıktısı">Doc</button>
            <button class="card-btn ${card.mode === 'think' ? 'active' : ''}" id="btn-think-${card.id}" onclick="toggleCardMode('${card.id}', 'think')" title="Düşünce Süreci, Araç Çağrıları & Telemetri">🧠 Think</button>
            <button class="card-btn ${card.mode === 'term' ? 'active' : ''}" id="btn-term-${card.id}" onclick="toggleCardMode('${card.id}', 'term')" title="Komut & Araç Çıktıları">Term</button>
            <button class="card-btn" onclick="openConfigAgentModal('${card.id}')" title="Araç, Skill & Persona Yapılandır">⚙️</button>
            ${card.type === 'worker' ? `<button class="card-btn danger" onclick="confirmDeleteAgent('${card.id}', '${escapeHtml(card.name)}', '${card.target}')" title="Ajanı Kaldır">✕</button>` : ''}
          </div>
        </div>
        <div class="card-tools-strip" id="tools-strip-${card.id}"></div>
        <div class="card-body" id="body-${card.id}">
          <div class="markdown-container" id="md-${card.id}" style="display:${card.mode === 'md' ? 'block' : 'none'}">
            <p style="color:var(--text-dim); font-size:0.75rem;">Brain JSONL verisi yükleniyor...</p>
          </div>
          <div class="markdown-container" id="think-${card.id}" style="display:${card.mode === 'think' ? 'block' : 'none'}">
            <p style="color:var(--text-dim); font-size:0.75rem;">Düşünce ve araç verisi bekleniyor...</p>
          </div>
          <div class="terminal-container" id="term-${card.id}" style="display:${card.mode === 'term' ? 'block' : 'none'}">
            Waiting for command output...
          </div>
        </div>
        <div class="card-footer">
          <span style="color:#6b7280;" id="footer-meta-${card.id}">CID: ${card.sub}</span>
          <div style="display:flex; align-items:center; gap:6px;">
            <span class="card-token-badge" id="token-badge-${card.id}" title="Aktif Bağlam / Kalan Kapasite">⚡ 0</span>
            <button class="card-btn" style="height:18px; padding:0 5px; font-size:0.62rem;" onclick="openSendNoteModal('${card.target}')" title="Bu ajana asenkron /btw notu ilet">/btw</button>
            <span style="color:${card.type === 'lead' ? 'var(--amber)' : '#9ca3af'}; font-weight:600;">${card.target}</span>
          </div>
        </div>
        <div class="card-resize-handle" onmousedown="onResizeDown(event, '${card.id}')"></div>
      `;

      cardsLayer.appendChild(el);
      renderCardToolsStrip(card.id);
    }

    function renderCardToolsStrip(cardId) {
      const card = state.cards[cardId];
      const strip = document.getElementById(`tools-strip-${cardId}`);
      if (!card || !strip) return;

      let html = '';
      if (card.persona) {
        html += `<span class="skill-chip-tag" style="background:rgba(56,189,248,0.12); border-color:rgba(56,189,248,0.3); color:#38bdf8;">👤 ${escapeHtml(card.persona)}</span>`;
      }
      (card.tools || []).forEach(tid => {
        const tm = getToolMeta(tid);
        html += `<button class="tool-quick-chip" onclick="triggerAgentTool('${card.target}', '${tid}', false)" title="Tek tıkla çalıştır: ${escapeHtml(tm.description || tm.name)}">${tm.icon || '⚡'} ${escapeHtml(tm.name)}</button>`;
      });
      (card.skills || []).slice(0, 3).forEach(sk => {
        html += `<span class="skill-chip-tag" title="Bağlı Skill: ${escapeHtml(sk)}">🧩 ${escapeHtml(sk)}</span>`;
      });
      html += `<button class="tool-quick-chip" style="background:rgba(255,255,255,0.04); border-color:var(--border-subtle); color:var(--text-muted);" onclick="openConfigAgentModal('${cardId}')" title="Araç & Skill Bağla">+ Araç</button>`;
      strip.innerHTML = html;
    }

    function updateWires() {
      const hub = document.getElementById('centralHub');
      const leadCard = state.cards['lead'];
      if (!hub || !leadCard) return;

      // Hub sits midway between the lead card and the leftmost worker, level with the lead's centre.
      const workers = Object.values(state.cards).filter(c => c.type === 'worker');
      const leadRight = leadCard.x + leadCard.w;
      const workersLeft = workers.length ? Math.min(...workers.map(c => c.x)) : leadRight + 250;
      const hubLeft = Math.round((leadRight + workersLeft) / 2 - 70);
      const hubY = Math.round(leadCard.y + leadCard.h / 2);
      hub.style.left = `${hubLeft}px`;
      hub.style.top = `${hubY - 35}px`;
      let svgHtml = '';

      // Lead to Hub
      svgHtml += makeBezier(leadRight, hubY, hubLeft, hubY, '#f59e0b');

      // Hub to Workers
      workers.forEach(c => {
        svgHtml += makeBezier(hubLeft + 140, hubY, c.x, c.y + 20, '#ff6b35');
      });

      wiresGroup.innerHTML = svgHtml;
      fitClusterFrames();
    }

    function makeBezier(x1, y1, x2, y2, color) {
      const dx = Math.abs(x2 - x1) * 0.5;
      const pathData = `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`;
      return `
        <path d="${pathData}" fill="none" stroke="${color}" stroke-width="2" stroke-dasharray="4,4" opacity="0.6"/>
        <circle cx="${x1}" cy="${y1}" r="3" fill="${color}"/>
        <circle cx="${x2}" cy="${y2}" r="3" fill="${color}"/>
      `;
    }

    function updateCanvasTransform() {
      world.style.transform = `translate(${state.panX}px, ${state.panY}px) scale(${state.scale})`;
      zoomLevelDisplay.innerText = `${Math.round(state.scale * 100)}%`;
      viewport.style.backgroundPosition = `${state.panX}px ${state.panY}px`;
      viewport.style.backgroundSize = `${32 * state.scale}px ${32 * state.scale}`;
    }

    function zoomCanvasBy(delta, clientX = window.innerWidth / 2, clientY = window.innerHeight / 2) {
      const oldScale = state.scale;
      let newScale = Math.min(Math.max(oldScale + delta, 0.25), 2.5);
      if (Math.abs(newScale - oldScale) < 0.001) return;

      const worldX = (clientX - state.panX) / oldScale;
      const worldY = (clientY - state.panY) / oldScale;

      state.scale = newScale;
      state.panX = clientX - worldX * newScale;
      state.panY = clientY - worldY * newScale;

      updateCanvasTransform();
    }

    // Fit every card on screen (between the top navbar and the bottom command dock), max 100% zoom.
    function resetCanvasView() {
      const cards = Object.values(state.cards);
      if (!cards.length) return;
      const pad = 40, top = 110, bottom = 150;
      const x1 = Math.min(...cards.map(c => c.x)) - pad, y1 = Math.min(...cards.map(c => c.y)) - 120;
      const x2 = Math.max(...cards.map(c => c.x + c.w)) + pad, y2 = Math.max(...cards.map(c => c.y + c.h)) + pad;
      const vw = viewport.clientWidth, vh = viewport.clientHeight - top - bottom;
      state.scale = Math.min(Math.max(Math.min(vw / (x2 - x1), vh / (y2 - y1), 1), 0.25), 2.5);
      state.panX = (vw - (x2 - x1) * state.scale) / 2 - x1 * state.scale;
      state.panY = top + Math.max(0, (vh - (y2 - y1) * state.scale) / 2) - y1 * state.scale;
      updateCanvasTransform();
    }

    // ----------------- Layout (saved per team in localStorage) -----------------

    const LEAD_X = 120, CARDS_Y = 230, WORKER_MAX_COLS = 4, CARD_GAP = 20, HUB_GAP = 250;

    // Workers start right of the lead card, leaving room for the hub in between.
    function workersOriginX() {
      const lead = state.cards['lead'];
      return lead ? lead.x + lead.w + HUB_GAP : LEAD_X;
    }

    const layoutKey = () => `hiveLayout:${state.team}`;

    function loadSavedLayout() {
      try { return JSON.parse(localStorage.getItem(layoutKey())) || {}; } catch { return {}; }
    }

    function saveLayout() {
      const out = {};
      Object.values(state.cards).forEach(c => { out[c.id] = { x: c.x, y: c.y, w: c.w, h: c.h }; });
      localStorage.setItem(layoutKey(), JSON.stringify(out));
    }

    function applySavedGeometry(card, saved) {
      const g = saved[card.id];
      if (!g) return false;
      Object.assign(card, { x: g.x, y: g.y, w: g.w, h: g.h });
      return true;
    }

    // Grid that fills a row first (up to WORKER_MAX_COLS columns), then wraps to a new row.
    // Column width = widest card in that column, row height = tallest card in that row.
    function gridLayout(cards, originX, originY) {
      const cols = Math.min(cards.length, WORKER_MAX_COLS);
      const colW = Array(cols).fill(0);
      cards.forEach((c, i) => { colW[i % cols] = Math.max(colW[i % cols], c.w); });
      let y = originY;
      for (let r = 0; r < cards.length; r += cols) {
        const row = cards.slice(r, r + cols);
        let x = originX;
        row.forEach((c, j) => { c.x = x; c.y = y; x += colW[j] + CARD_GAP; });
        y += Math.max(...row.map(c => c.h)) + CARD_GAP;
      }
    }

    // Saved workers keep their place; new/unsaved ones go into a grid below them.
    function placeWorkers(saved) {
      const workers = Object.values(state.cards).filter(c => c.type === 'worker');
      const placed = workers.filter(c => applySavedGeometry(c, saved));
      const fresh = workers.filter(c => !placed.includes(c));
      const startY = placed.length ? Math.max(...placed.map(c => c.y + c.h)) + CARD_GAP : CARDS_Y;
      gridLayout(fresh, workersOriginX(), startY);
    }

    function applyCardGeometry(c) {
      const el = document.getElementById(`card-${c.id}`);
      if (!el) return;
      Object.assign(el.style, { left: `${c.x}px`, top: `${c.y}px`, width: `${c.w}px`, height: `${c.h}px` });
    }

    // Team frames wrap their cards (header space on top), so they grow/shrink with them.
    function fitClusterFrame(frameId, cards) {
      const el = document.getElementById(frameId);
      if (!el || !cards.length) return;
      const x1 = Math.min(...cards.map(c => c.x)) - CARD_GAP;
      const y1 = Math.min(...cards.map(c => c.y)) - 60;
      const x2 = Math.max(...cards.map(c => c.x + c.w)) + CARD_GAP;
      const y2 = Math.max(...cards.map(c => c.y + c.h)) + CARD_GAP;
      Object.assign(el.style, { left: `${x1}px`, top: `${y1}px`, width: `${x2 - x1}px`, height: `${y2 - y1}px` });
    }

    function fitClusterFrames() {
      const cards = Object.values(state.cards);
      fitClusterFrame('clusterReviewers', cards.filter(c => c.type === 'lead'));
      fitClusterFrame('clusterTeam', cards.filter(c => c.type === 'worker'));
      // workspace title stays centred above everything
      const label = document.getElementById('categoryLabel');
      if (label && cards.length) {
        const x1 = Math.min(...cards.map(c => c.x)), x2 = Math.max(...cards.map(c => c.x + c.w));
        label.style.left = `${Math.round((x1 + x2) / 2)}px`;
        label.style.top = `${Math.min(...cards.map(c => c.y)) - 80}px`;
      }
    }

    function arrangeCardsGrid() {
      if (state.cards['lead']) {
        state.cards['lead'].x = LEAD_X;
        state.cards['lead'].y = CARDS_Y;
      }
      gridLayout(Object.values(state.cards).filter(c => c.type === 'worker'), workersOriginX(), CARDS_Y);
      Object.values(state.cards).forEach(applyCardGeometry);
      saveLayout();
      updateWires();
      resetCanvasView();
    }

    function onCardHeaderDown(e, cardId) {
      if (e.button !== 0) return;
      e.stopPropagation();
      state.dragCardId = cardId;
      state.dragOffsetX = (e.clientX - state.panX) / state.scale - state.cards[cardId].x;
      state.dragOffsetY = (e.clientY - state.panY) / state.scale - state.cards[cardId].y;

      document.querySelectorAll('.agent-card').forEach(el => el.classList.remove('focused'));
      const activeEl = document.getElementById(`card-${cardId}`);
      if (activeEl) activeEl.classList.add('focused');
    }

    function onResizeDown(e, cardId) {
      if (e.button !== 0) return;
      e.stopPropagation();
      state.resizeCardId = cardId;
      state.resizeStartX = e.clientX;
      state.resizeStartY = e.clientY;
      state.resizeStartW = state.cards[cardId].w;
      state.resizeStartH = state.cards[cardId].h;
    }

    function setupEventListeners() {
      viewport.addEventListener('mousedown', (e) => {
        if (e.button === 0 && !e.target.closest('.agent-card') && !e.target.closest('.central-hub-card') && !e.target.closest('.modal-backdrop')) {
          state.isPanning = true;
          state.panStartX = e.clientX - state.panX;
          state.panStartY = e.clientY - state.panY;
          viewport.classList.add('panning');
        }
      });

      window.addEventListener('mousemove', (e) => {
        if (state.isPanning) {
          state.panX = e.clientX - state.panStartX;
          state.panY = e.clientY - state.panStartY;
          updateCanvasTransform();
          return;
        }

        if (state.dragCardId) {
          const card = state.cards[state.dragCardId];
          const nx = Math.round((e.clientX - state.panX) / state.scale - state.dragOffsetX);
          const ny = Math.round((e.clientY - state.panY) / state.scale - state.dragOffsetY);
          card.x = nx;
          card.y = ny;
          const el = document.getElementById(`card-${card.id}`);
          if (el) {
            el.style.left = `${nx}px`;
            el.style.top = `${ny}px`;
          }
          updateWires();
          return;
        }

        if (state.resizeCardId) {
          const card = state.cards[state.resizeCardId];
          const dw = (e.clientX - state.resizeStartX) / state.scale;
          const dh = (e.clientY - state.resizeStartY) / state.scale;
          const nw = Math.max(300, Math.round(state.resizeStartW + dw));
          const nh = Math.max(200, Math.round(state.resizeStartH + dh));
          card.w = nw;
          card.h = nh;
          const el = document.getElementById(`card-${card.id}`);
          if (el) {
            el.style.width = `${nw}px`;
            el.style.height = `${nh}px`;
          }
          updateWires();
          return;
        }
      });

      window.addEventListener('mouseup', () => {
        if (state.isPanning) {
          state.isPanning = false;
          viewport.classList.remove('panning');
        }
        if (state.dragCardId || state.resizeCardId) {
          state.dragCardId = null;
          state.resizeCardId = null;
          saveLayout();
        }
      });

      viewport.addEventListener('wheel', (e) => {
        e.preventDefault();
        const delta = e.deltaY < 0 ? 0.08 : -0.08;
        zoomCanvasBy(delta, e.clientX, e.clientY);
      }, { passive: false });

      window.addEventListener('keydown', (e) => {
        if (e.code === 'Space' && document.activeElement !== masterInput && !document.querySelector('.modal-backdrop.show')) {
          e.preventDefault();
          resetCanvasView();
        }
      });
    }

    function toggleCardMode(cardId, mode) {
      const card = state.cards[cardId];
      if (!card) return;
      card.mode = mode;

      const btnMd = document.getElementById(`btn-md-${cardId}`);
      const btnThink = document.getElementById(`btn-think-${cardId}`);
      const btnTerm = document.getElementById(`btn-term-${cardId}`);
      const mdDiv = document.getElementById(`md-${cardId}`);
      const thinkDiv = document.getElementById(`think-${cardId}`);
      const termDiv = document.getElementById(`term-${cardId}`);

      if (btnMd) btnMd.classList.toggle('active', mode === 'md');
      if (btnThink) btnThink.classList.toggle('active', mode === 'think');
      if (btnTerm) btnTerm.classList.toggle('active', mode === 'term');

      if (mdDiv) mdDiv.style.display = mode === 'md' ? 'block' : 'none';
      if (thinkDiv) thinkDiv.style.display = mode === 'think' ? 'block' : 'none';
      if (termDiv) termDiv.style.display = mode === 'term' ? 'block' : 'none';
    }

    // ----------------- Clean Markdown & Output Parser -----------------

    function cleanAnsiAndShell(text) {
      if (!text) return '';
      return text
        .replace(/\x1b\[[0-9;?]*[a-zA-Z]/g, '')
        .replace(/\x1b\([a-zA-Z]/g, '')
        .replace(/\x1b\>[0-9;]*[a-zA-Z]/g, '')
        .replace(/\[\?2004[hl]/g, '')
        .replace(/\[\>4;2m/g, '')
        .replace(/\r/g, '');
    }

    function escapeHtml(str) {
      if (!str) return '';
      return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
    }

    function renderMarkdown(rawText) {
      const clean = cleanAnsiAndShell(rawText);
      const lines = clean.split('\n');
      let html = '';
      let inCodeBlock = false;
      let codeLang = '';
      let codeLines = [];
      let inTable = false;
      let tableRows = [];

      const flushTable = () => {
        if (!inTable || tableRows.length === 0) return;
        inTable = false;
        let tHtml = '<table>';
        tableRows.forEach((r, rIdx) => {
          if (/^[\s|:-]+$/.test(r)) return;
          const cells = r.split('|').slice(1, -1).map(c => c.trim());
          const tag = rIdx === 0 ? 'th' : 'td';
          tHtml += '<tr>' + cells.map(c => `<${tag}>${formatInlineMd(escapeHtml(c))}</${tag}>`).join('') + '</tr>';
        });
        tHtml += '</table>';
        html += tHtml;
        tableRows = [];
      };

      for (let i = 0; i < lines.length; i++) {
        let line = lines[i];
        let trimmed = line.trim();

        if (trimmed.startsWith('```')) {
          flushTable();
          if (!inCodeBlock) {
            inCodeBlock = true;
            codeLang = trimmed.replace('```', '').trim() || 'code';
            codeLines = [];
          } else {
            inCodeBlock = false;
            const codeContent = escapeHtml(codeLines.join('\n'));
            html += `
              <pre><div class="code-block-header"><span>${codeLang}</span><button class="copy-code-btn" onclick="navigator.clipboard.writeText(this.parentElement.nextElementSibling.innerText)">Copy</button></div><code>${codeContent}</code></pre>
            `;
          }
          continue;
        }

        if (inCodeBlock) {
          codeLines.push(line);
          continue;
        }

        if (trimmed.startsWith('|') && trimmed.endsWith('|')) {
          inTable = true;
          tableRows.push(trimmed);
          continue;
        } else if (inTable) {
          flushTable();
        }

        if (trimmed === '---' || trimmed.startsWith('───') || trimmed.startsWith('===')) {
          html += '<hr>';
          continue;
        }

        if (trimmed.startsWith('> ')) {
          html += `<blockquote>${formatInlineMd(escapeHtml(trimmed.slice(2)))}</blockquote>`;
          continue;
        }

        if (trimmed.startsWith('### ')) {
          html += `<h3>${formatInlineMd(escapeHtml(trimmed.slice(4)))}</h3>`;
          continue;
        }
        if (trimmed.startsWith('## ')) {
          html += `<h2>${formatInlineMd(escapeHtml(trimmed.slice(3)))}</h2>`;
          continue;
        }
        if (trimmed.startsWith('# ')) {
          html += `<h1>${formatInlineMd(escapeHtml(trimmed.slice(2)))}</h1>`;
          continue;
        }

        if (trimmed.startsWith('- [x]') || trimmed.startsWith('- [X]')) {
          html += `
            <div class="todo-item">
              <div class="todo-box checked">✓</div>
              <span style="text-decoration:line-through; color:var(--text-dim);">${formatInlineMd(escapeHtml(trimmed.slice(5)))}</span>
            </div>
          `;
          continue;
        }
        if (trimmed.startsWith('- [ ]')) {
          html += `
            <div class="todo-item">
              <div class="todo-box"></div>
              <span>${formatInlineMd(escapeHtml(trimmed.slice(5)))}</span>
            </div>
          `;
          continue;
        }

        if (trimmed.startsWith('• ') || trimmed.startsWith('- ') || trimmed.startsWith('* ')) {
          const bulletText = trimmed.replace(/^[•\-\*]\s*/, '');
          html += `<li style="margin-left: 14px; margin-bottom: 4px;">${formatInlineMd(escapeHtml(bulletText))}</li>`;
          continue;
        }

        if (/^\d+\.\s+/.test(trimmed)) {
          html += `<div style="margin-left: 6px; margin-bottom: 5px; font-weight:500;">${formatInlineMd(escapeHtml(trimmed))}</div>`;
          continue;
        }

        if (!trimmed) {
          html += `<div style="height: 5px;"></div>`;
          continue;
        }

        html += `<p>${formatInlineMd(escapeHtml(line))}</p>`;
      }

      flushTable();
      return html || '<p style="color:var(--text-dim);">Henüz çıktı yok.</p>';
    }

    function formatInlineMd(text) {
      return text
        .replace(/\[([^\]]+)\]\((file:\/\/[^)]+|https?:\/\/[^)]+)\)/g, '<span style="color:var(--amber); text-decoration:underline;">$1</span>')
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        .replace(/`([^`]+)`/g, '<code>$1</code>');
    }

    function renderThinkingAndTools(card) {
      const tel = card.telemetry || {};
      const cachePct = (tel.input_tokens + tel.cache_tokens) > 0
        ? Math.round((tel.cache_tokens / (tel.input_tokens + tel.cache_tokens)) * 100)
        : 0;

      const ctxTokens = tel.context_tokens || 0;
      const ctxLimit = tel.context_limit || 1000000;
      const remTokens = tel.remaining_tokens !== undefined ? tel.remaining_tokens : (ctxLimit - ctxTokens);
      const ctxPct = tel.context_pct || Math.round((ctxTokens / Math.max(1, ctxLimit)) * 100);
      let barColor = 'var(--emerald)';
      if (ctxPct > 80) barColor = '#f43f5e';
      else if (ctxPct > 50) barColor = '#f59e0b';

      let html = `
        <div style="background:#141518; border:1px solid var(--border-subtle); border-radius:8px; padding:8px 10px; margin-bottom:10px;">
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px; font-family:var(--font-mono); font-size:0.68rem;">
            <span>Bağlam: <strong style="color:#fff;">${formatTokens(ctxTokens)}</strong> / ${formatTokens(ctxLimit)} (<strong style="color:${barColor};">%${ctxPct}</strong>)</span>
            <span>Kalan Boşluk: <strong style="color:var(--emerald);">${formatTokens(remTokens)}</strong></span>
          </div>
          <div class="agent-bar-track" style="height:6px; margin-bottom:7px;">
            <div class="agent-bar-fill" style="width:${Math.min(100, Math.max(0, ctxPct))}%; background:${barColor};"></div>
          </div>
          <div style="display:flex; justify-content:space-between; align-items:center; font-family:var(--font-mono); font-size:0.65rem; color:var(--text-dim);">
            <span>Adım: <strong style="color:#fff;">#${tel.steps || 0}</strong></span>
            <span>Önbellek: <strong style="color:#38bdf8;">%${cachePct}</strong></span>
            <span>Kümülatif: <strong style="color:var(--amber);">${formatTokens(tel.cum_total_tokens || 0)}</strong></span>
          </div>
        </div>
      `;

      if (card.thinking) {
        html += `
          <div style="font-size:0.72rem; font-weight:700; color:var(--amber); margin-bottom:4px;">🧠 Son İçsel Düşünce (Reasoning Chain):</div>
          <div class="thinking-box">${escapeHtml(card.thinking)}</div>
        `;
      } else {
        html += `<div style="font-size:0.72rem; color:var(--text-dim); margin-bottom:10px;">Henüz aktif düşünce bloğu kaydedilmedi.</div>`;
      }

      html += `<div style="font-size:0.72rem; font-weight:700; color:#e5e7eb; margin:8px 0 5px 0;">⚡ Son Çağrılan Araçlar (Brain JSONL):</div>`;
      if (card.tool_calls && card.tool_calls.length > 0) {
        html += `<div>` + card.tool_calls.map(tc => `
          <span class="tool-call-pill">🔧 <strong>${escapeHtml(tc.name)}</strong> ${tc.detail ? `<span style="color:var(--text-muted);">(${escapeHtml(tc.detail)})</span>` : ''}</span>
        `).join('') + `</div>`;
      } else {
        html += `<div style="font-size:0.71rem; color:var(--text-dim);">Son adımda araç çağrısı yok.</div>`;
      }

      if (card.workspace_dir) {
        html += `<div style="margin-top:10px; font-size:0.68rem; font-family:var(--font-mono); color:var(--text-dim);">📁 Çalışma Dizini: ${escapeHtml(card.workspace_dir)}</div>`;
      }
      return html;
    }

    // ----------------- WebSocket Engine -----------------

    let ws = null;

    function initWebSocket() {
      const loc = window.location;
      const wsUrl = `ws://${loc.hostname}:${loc.port}/ws?team=${state.team}`;
      ws = new WebSocket(wsUrl);

      ws.onopen = () => {
        console.log('AGY-UI v3.0 Brain JSONL WebSocket connected');
      };

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);
          handleStreamMessage(msg);
        } catch(e) {
          console.error('WS Parse error', e);
        }
      };

      ws.onclose = () => {
        setTimeout(initWebSocket, 2000);
      };
    }

    function reconnectWebSocket() {
      if (ws) ws.close();
      initWebSocket();
    }

    // Runtime/model can change outside this page (CLI, another tab): keep card badge + config modal in sync.
    function syncCardRuntime(card, msg) {
      if (msg.model !== undefined) card.model = msg.model || '';
      if (!msg.runtime || msg.runtime === card.runtime) return;
      card.runtime = msg.runtime;
      const badge = document.querySelector(`#card-${card.id} .runtime-badge`);
      if (badge) {
        badge.className = `runtime-badge ${card.runtime}`;
        badge.textContent = card.runtime.toUpperCase();
      }
    }

    function handleStreamMessage(msg) {
      if (msg.type === 'tokens_snapshot') {
        if (msg.tokens) {
          latestTokenData = msg.tokens;
          updateTokenNavbarDisplay(msg.tokens);
          const td = document.getElementById('tokenDrawer');
          if (td && td.classList.contains('open')) {
            renderTokenDrawerBody(msg.tokens);
          }
        }
        return;
      }

      if (msg.type === 'pane_snapshot') {
        const cardId = msg.card_id || `agent_${msg.agent}`;
        if (!state.cards[cardId]) {
          state.cards[cardId] = {
            id: cardId,
            pane: msg.pane,
            aid: msg.agent,
            type: 'worker',
            name: msg.name || `Agent ${msg.agent}`,
            role: msg.role || `Worker #${msg.agent}`,
            sub: msg.cid || `agent-${msg.agent}`,
            full_cid: msg.full_cid || '',
            persona: msg.persona || '',
            effort: msg.effort || 'medium',
            workspace_dir: msg.workspace_dir || '',
            skills: msg.skills || [],
            tools: msg.tools || ['git-status-diff'],
            target: msg.target || `@${msg.agent}`,
            runtime: msg.runtime || 'agy',
            model: msg.model || '',
            x: 0,
            y: 0,
            w: 425,
            h: 300,
            mode: 'md',
            rawLog: '',
            termLog: '',
            thinking: '',
            tool_calls: [],
            telemetry: {}
          };
          placeWorkers(loadSavedLayout());
          renderCardDOM(state.cards[cardId]);
          Object.values(state.cards).forEach(applyCardGeometry);
          updateWires();
        }

        const c = state.cards[cardId];
        syncCardRuntime(c, msg);
        c.rawLog = msg.content || '';
        c.termLog = msg.terminal || '';
        c.thinking = msg.thinking || '';
        c.tool_calls = msg.tool_calls || [];
        c.telemetry = msg.telemetry || {};
        c.sub = msg.cid || c.sub;
        c.full_cid = msg.full_cid || c.full_cid;

        if (msg.status) {
          c.status = msg.status;
          updateAgentStatusBadge(cardId, msg.status);
        }
        updateCardContent(cardId);
      } else if (msg.type === 'lead_snapshot') {
        const c = state.cards['lead'];
        if (c) {
          syncCardRuntime(c, msg);
          c.rawLog = msg.content || '';
          c.termLog = msg.terminal || '';
          c.thinking = msg.thinking || '';
          c.tool_calls = msg.tool_calls || [];
          c.telemetry = msg.telemetry || {};
          c.sub = msg.cid || c.sub;
          c.full_cid = msg.full_cid || c.full_cid;
          if (msg.status) {
            c.status = msg.status;
            updateAgentStatusBadge('lead', msg.status);
          }
          updateCardContent('lead');
        }
      }
    }

    function updateCardContent(cardId) {
      const card = state.cards[cardId];
      if (!card) return;

      const mdDiv = document.getElementById(`md-${cardId}`);
      const thinkDiv = document.getElementById(`think-${cardId}`);
      const termDiv = document.getElementById(`term-${cardId}`);
      const footerMeta = document.getElementById(`footer-meta-${cardId}`);
      const tokenBadge = document.getElementById(`token-badge-${cardId}`);

      if (mdDiv) mdDiv.innerHTML = renderMarkdown(card.rawLog);
      if (thinkDiv) thinkDiv.innerHTML = renderThinkingAndTools(card);
      if (termDiv) termDiv.innerText = cleanAnsiAndShell(card.termLog || card.rawLog);
      if (footerMeta) {
        const steps = (card.telemetry && card.telemetry.steps) ? ` • #${card.telemetry.steps}` : '';
        footerMeta.innerText = `CID: ${card.sub}${steps}`;
      }
      if (tokenBadge && card.telemetry) {
        const ctx = card.telemetry.context_tokens || 0;
        const limit = card.telemetry.context_limit || 1000000;
        const rem = card.telemetry.remaining_tokens !== undefined ? card.telemetry.remaining_tokens : (limit - ctx);
        const pct = card.telemetry.context_pct || Math.round((ctx / Math.max(1, limit)) * 100);
        const cum = card.telemetry.cum_total_tokens || 0;
        let pColor = 'var(--emerald)';
        if (pct > 80) pColor = '#f43f5e';
        else if (pct > 50) pColor = '#f59e0b';
        tokenBadge.innerHTML = `⚡ ${formatTokens(ctx)} <span style="color:${pColor}; font-weight:700;">(%${pct})</span> • ${formatTokens(rem)} boş`;
        tokenBadge.title = `Aktif Bağlam: ${ctx.toLocaleString()} / ${limit.toLocaleString()} (%${pct})\nKalan Kapasite: ${rem.toLocaleString()}\nKümülatif Toplam Harcanan: ${cum.toLocaleString()}`;
      }
    }

    // ----------------- Modal & Agent Configurator Operations -----------------

    function openCreateTeamModal() {
      document.getElementById('newTeamName').value = '';
      document.getElementById('newTeamDir').value = '';
      document.getElementById('newTeamRole').value = '';
      document.getElementById('modalCreateTeam').classList.add('show');
      document.getElementById('newTeamName').focus();
    }

    function openAddAgentModal() {
      document.getElementById('modalAddAgentTeamName').innerText = state.team;
      document.getElementById('newAgentName').value = '';
      document.getElementById('newAgentTarget').value = '';
      document.getElementById('newAgentRole').value = '';
      document.getElementById('newAgentRuntime').value = 'agy';
      document.getElementById('newAgentModel').value = '';
      document.getElementById('newAgentDir').value = '';
      document.getElementById('modalAddAgent').classList.add('show');
      document.getElementById('newAgentName').focus();
    }

    function openConfigAgentModal(cardId) {
      const card = state.cards[cardId];
      if (!card) return;

      document.getElementById('cfgAgentTargetLabel').innerText = `${card.name} (${card.target})`;
      document.getElementById('cfgAgentTarget').value = card.target;
      document.getElementById('cfgAgentName').value = card.name || '';
      document.getElementById('cfgAgentRole').value = card.role || '';
      document.getElementById('cfgAgentRuntime').value = card.runtime || 'agy';
      document.getElementById('cfgAgentModel').value = card.model || '';
      document.getElementById('cfgAgentPersona').value = card.persona || '';
      document.getElementById('cfgAgentEffort').value = card.effort || 'medium';
      document.getElementById('cfgAgentDir').value = card.workspace_dir || '';
      document.getElementById('cfgAgentCid').value = card.full_cid || '';

      // Populate Tools Checkboxes
      const toolsGrid = document.getElementById('cfgToolsGrid');
      const boundTools = new Set(card.tools || []);
      toolsGrid.innerHTML = (ecosystemData.tools || []).map(t => `
        <label class="checkbox-row" title="${escapeHtml(t.description)}">
          <input type="checkbox" class="cfg-tool-cb" value="${t.id}" ${boundTools.has(t.id) ? 'checked' : ''}>
          <span>${t.icon || '⚡'} ${escapeHtml(t.name)}</span>
        </label>
      `).join('');

      // Populate Skills Checkboxes
      const skillsGrid = document.getElementById('cfgSkillsGrid');
      const boundSkills = new Set(card.skills || []);
      skillsGrid.innerHTML = (ecosystemData.skills || []).map(s => `
        <label class="checkbox-row">
          <input type="checkbox" class="cfg-skill-cb" value="${s.name}" ${boundSkills.has(s.name) ? 'checked' : ''}>
          <span>${escapeHtml(s.name)}</span>
        </label>
      `).join('');

      document.getElementById('modalConfigAgent').classList.add('show');
    }

    async function submitAgentConfig() {
      const target = document.getElementById('cfgAgentTarget').value;
      const name = document.getElementById('cfgAgentName').value.trim();
      const role = document.getElementById('cfgAgentRole').value.trim();
      const runtime = document.getElementById('cfgAgentRuntime').value;
      const model = document.getElementById('cfgAgentModel').value.trim();
      const persona = document.getElementById('cfgAgentPersona').value;
      const effort = document.getElementById('cfgAgentEffort').value;
      const workspace_dir = document.getElementById('cfgAgentDir').value.trim();
      const cid = document.getElementById('cfgAgentCid').value.trim();

      const tools = Array.from(document.querySelectorAll('.cfg-tool-cb:checked')).map(cb => cb.value);
      const skills = Array.from(document.querySelectorAll('.cfg-skill-cb:checked')).map(cb => cb.value);

      try {
        const res = await fetch('/api/agent/configure', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            team: state.team,
            target,
            name,
            role,
            runtime,
            model,
            persona,
            effort,
            workspace_dir,
            cid,
            tools,
            skills
          })
        });
        const data = await res.json();
        if (data.success) {
          closeModals();
          await loadTeamData(state.team);
        } else {
          alert(`Hata: ${data.error}`);
        }
      } catch (e) {
        alert('Yapılandırma kaydedilemedi.');
      }
    }

    function closeModals() {
      document.getElementById('modalCreateTeam').classList.remove('show');
      document.getElementById('modalAddAgent').classList.remove('show');
      document.getElementById('modalSendNote').classList.remove('show');
      document.getElementById('modalConfigAgent').classList.remove('show');
    }

    async function submitCreateTeam() {
      const name = document.getElementById('newTeamName').value.trim();
      const dir = document.getElementById('newTeamDir').value.trim();
      const role = document.getElementById('newTeamRole').value.trim();

      if (!name) {
        alert('Takım adı girmelisiniz!');
        return;
      }

      try {
        const res = await fetch('/api/team/create', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name, project_dir: dir, role, start: true })
        });
        const data = await res.json();
        if (data.success) {
          closeModals();
          await loadTeamsList();
          await switchTeam(name);
        } else {
          alert(`Hata: ${data.error}`);
        }
      } catch (e) {
        alert('Takım oluşturma isteği başarısız oldu.');
      }
    }

    async function confirmDeleteAgent(cardId, name, target) {
      if (!confirm(`'${name}' (${target}) ajanını takımdan kaldırmak istediğinize emin misiniz?`)) {
        return;
      }
      try {
        const res = await fetch('/api/team/remove-agent', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ team: state.team, target: target })
        });
        const data = await res.json();
        if (data.success) {
          await loadTeamData(state.team);
        } else {
          alert(`Hata: ${data.error}`);
        }
      } catch (e) {
        alert('Ajan kaldırma işlemi başarısız oldu.');
      }
    }

    async function submitAddAgent() {
      const name = document.getElementById('newAgentName').value.trim();
      const target = document.getElementById('newAgentTarget').value.trim();
      const role = document.getElementById('newAgentRole').value.trim();
      const runtime = document.getElementById('newAgentRuntime').value;
      const model = document.getElementById('newAgentModel').value.trim();
      const persona = document.getElementById('newAgentPersona').value;
      const effort = document.getElementById('newAgentEffort').value;
      const workspace_dir = document.getElementById('newAgentDir').value.trim();

      try {
        const res = await fetch('/api/team/add-agent', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            team: state.team,
            name,
            target,
            role,
            runtime,
            model,
            persona,
            effort,
            workspace_dir,
            tools: ['git-status-diff', 'memory-sync']
          })
        });
        const data = await res.json();
        if (data.success) {
          closeModals();
          await loadTeamData(state.team);
        } else {
          alert(`Hata: ${data.error}`);
        }
      } catch (e) {
        alert('Ajan ekleme isteği başarısız oldu.');
      }
    }

    // ----------------- Command Dispatch & Actions -----------------

    function cycleTarget() {
      state.targetIndex = (state.targetIndex + 1) % state.targets.length;
      currentTargetBadge.innerText = state.targets[state.targetIndex];
    }

    function sendQuickAction(target, message) {
      currentTargetBadge.innerText = target;
      dispatchPayload(target, message);
    }

    function handleInputKey(e) {
      if (e.key === 'Enter') {
        submitCommand();
      }
    }

    function submitCommand() {
      const msg = masterInput.value.trim();
      if (!msg) return;
      const target = currentTargetBadge.innerText;
      masterInput.value = '';
      dispatchPayload(target, msg);
    }

    async function dispatchPayload(target, message) {
      try {
        const res = await fetch('/api/dispatch', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            team: state.team,
            target: target,
            message: message
          })
        });
        const data = await res.json();
        if (data.success) {
          triggerWirePulseAnimation();
        } else {
          alert(`Dispatch Error: ${data.error}`);
        }
      } catch(e) {
        console.error('Dispatch failed', e);
      }
    }

    async function restoreAll() {
      try {
        const res = await fetch('/api/restore', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ team: state.team, target: 'all' })
        });
        const data = await res.json();
        await loadTeamData(state.team);
        alert(data.success ? data.output : `Restore failed: ${data.error}`);
      } catch(e) {
        alert('Restore request failed');
      }
    }

    window.addEventListener('DOMContentLoaded', async () => {
      setupEventListeners();
      await loadEcosystem();
      await loadTeamsList();
      const names = (state.allTeams || []).map(t => t.name);
      const saved = localStorage.getItem('hiveTeam');
      setTeamLabels(names.includes(saved) ? saved : (names[0] || ''));
      renderTeamsDropdown();
      await loadTeamData(state.team);
      initWebSocket();
      resetCanvasView();
    });
