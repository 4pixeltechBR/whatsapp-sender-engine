/**
 * WhatsApp Sender Engine — Desktop Client Application
 * Gestão de Contatos, Sanitização E.164, Editor com Spintax,
 * Telemetria SSE em Tempo Real, Controles de Fila e Exportação Executiva.
 */

(function () {
  'use strict';

  // ============================================================================
  // Estado da Aplicação
  // ============================================================================
  const state = {
    contacts: [],          // Lista de contatos válidos/carregados
    filteredContacts: [],  // Contatos após filtros e busca
    processedLogs: [],     // Histórico estruturado de envios (Tempo Real)
    metrics: {
      total: 0,
      valid: 0,
      duplicates: 0,
      invalid: 0,
      efficiency: 0,
    },
    pagination: {
      page: 1,
      pageSize: 25,
      totalPages: 1,
    },
    selectedContact: null,
    attachmentPath: null,
    attachmentFilename: null,
    queueState: 'IDLE',
    sseConnected: false,
    sessionStatus: 'DESCONECTADO',
  };

  // 67 DDDs Oficiais da Anatel para validação instantânea no cliente
  const ANATEL_DDDS = new Set([
    11, 12, 13, 14, 15, 16, 17, 18, 19, 21, 22, 24, 27, 28, 31, 32, 33, 34, 35,
    37, 38, 41, 42, 43, 44, 45, 46, 47, 48, 49, 51, 53, 54, 55, 61, 62, 63, 64,
    65, 66, 67, 68, 69, 71, 73, 74, 75, 77, 79, 81, 82, 83, 84, 85, 86, 87, 88,
    89, 91, 92, 93, 94, 95, 96, 97, 98, 99
  ]);

  // ============================================================================
  // Elementos DOM
  // ============================================================================
  const dom = {
    themeToggleBtn: document.getElementById('themeToggleBtn'),
    navItems: document.querySelectorAll('.nav-item'),
    tabPanes: document.querySelectorAll('.tab-pane'),
    pageTitle: document.getElementById('pageTitle'),
    pageSubtitle: document.getElementById('pageSubtitle'),
    quickCountBadge: document.getElementById('quickCountBadge'),

    // Dropzone e Ingestão
    dropzone: document.getElementById('dropzone'),
    fileInput: document.getElementById('fileInput'),
    selectFileBtn: document.getElementById('selectFileBtn'),
    manualTextarea: document.getElementById('manualTextarea'),
    processManualBtn: document.getElementById('processManualBtn'),
    loadDemoBtn: document.getElementById('loadDemoBtn'),
    clearListBtn: document.getElementById('clearListBtn'),
    mappingCard: document.getElementById('mappingCard'),
    phoneColSelect: document.getElementById('phoneColSelect'),
    nameColSelect: document.getElementById('nameColSelect'),
    reapplyMappingBtn: document.getElementById('reapplyMappingBtn'),

    // KPIs Ingestão
    metricTotalRows: document.getElementById('metricTotalRows'),
    metricValidCount: document.getElementById('metricValidCount'),
    metricDuplicateCount: document.getElementById('metricDuplicateCount'),
    metricInvalidCount: document.getElementById('metricInvalidCount'),
    metricEfficiency: document.getElementById('metricEfficiency'),

    // Tabela e Filtros
    contactsTableBody: document.getElementById('contactsTableBody'),
    tableSearchInput: document.getElementById('tableSearchInput'),
    statusFilterSelect: document.getElementById('statusFilterSelect'),
    pageSizeSelect: document.getElementById('pageSizeSelect'),
    paginationInfo: document.getElementById('paginationInfo'),
    currentPageNum: document.getElementById('currentPageNum'),
    prevPageBtn: document.getElementById('prevPageBtn'),
    nextPageBtn: document.getElementById('nextPageBtn'),

    // Editor de Mensagem
    messageTemplate: document.getElementById('messageTemplate'),
    charCount: document.getElementById('charCount'),
    wordCount: document.getElementById('wordCount'),
    estimatedTypingTime: document.getElementById('estimatedTypingTime'),
    tagButtons: document.querySelectorAll('.tag-btn'),
    spintaxButtons: document.querySelectorAll('.spintax-sample-btn'),
    testSpintaxBtn: document.getElementById('testSpintaxBtn'),
    attachmentInput: document.getElementById('attachmentInput'),
    selectAttachmentBtn: document.getElementById('selectAttachmentBtn'),
    attachmentName: document.getElementById('attachmentName'),
    removeAttachmentBtn: document.getElementById('removeAttachmentBtn'),

    // Preview do WhatsApp
    whatsappPreviewText: document.getElementById('whatsappPreviewText'),
    previewContactName: document.getElementById('previewContactName'),
    previewContactPhone: document.getElementById('previewContactPhone'),
    previewTimestamp: document.getElementById('previewTimestamp'),

    // Disparador e Fila
    startCampaignBtn: document.getElementById('startCampaignBtn'),
    pauseCampaignBtn: document.getElementById('pauseCampaignBtn'),
    resumeCampaignBtn: document.getElementById('resumeCampaignBtn'),
    abortCampaignBtn: document.getElementById('abortCampaignBtn'),
    queueStateBadge: document.getElementById('queueStateBadge'),
    queueEtaDisplay: document.getElementById('queueEtaDisplay'),
    progressBarFill: document.getElementById('progressBarFill'),
    progressPercentLabel: document.getElementById('progressPercentLabel'),
    progressFractionLabel: document.getElementById('progressFractionLabel'),
    currentContactText: document.getElementById('currentContactText'),
    quickExportXlsxBtn: document.getElementById('quickExportXlsxBtn'),
    quickExportCsvBtn: document.getElementById('quickExportCsvBtn'),
    campaignTitleInput: document.getElementById('campaignTitleInput'),
    jitterMinInput: document.getElementById('jitterMinInput'),
    jitterMaxInput: document.getElementById('jitterMaxInput'),
    batchSizeInput: document.getElementById('batchSizeInput'),
    batchPauseInput: document.getElementById('batchPauseInput'),

    // Contadores de Telemetria
    telemetrySent: document.getElementById('telemetrySent'),
    telemetryFailed: document.getElementById('telemetryFailed'),
    telemetryPending: document.getElementById('telemetryPending'),
    telemetrySpeed: document.getElementById('telemetrySpeed'),

    // Tabela de Logs ao Vivo e Terminal
    liveContactsLogBody: document.getElementById('liveContactsLogBody'),
    liveContactLogBadge: document.getElementById('liveContactLogBadge'),
    logTerminal: document.getElementById('logTerminal'),

    // Sessão WhatsApp
    sidebarSessionStatus: document.getElementById('sidebarSessionStatus'),
    connectionBadge: document.getElementById('connectionBadge'),
    qrContainer: document.getElementById('qrContainer'),
    qrPlaceholder: document.getElementById('qrPlaceholder'),
    openBrowserBtn: document.getElementById('openBrowserBtn'),
    checkSessionBtn: document.getElementById('checkSessionBtn'),
    closeBrowserBtn: document.getElementById('closeBrowserBtn'),

    // Relatórios
    exportXlsxBtn: document.getElementById('exportXlsxBtn'),
    exportCsvBtn: document.getElementById('exportCsvBtn'),
    reportCampaignTitleBadge: document.getElementById('reportCampaignTitleBadge'),
    reportTotalContacts: document.getElementById('reportTotalContacts'),
    reportSentSuccess: document.getElementById('reportSentSuccess'),
    reportFailed: document.getElementById('reportFailed'),
    reportCancelled: document.getElementById('reportCancelled'),
    reportDeliveryRate: document.getElementById('reportDeliveryRate'),
  };

  // ============================================================================
  // Sanitizador Telefônico E.164 Client-Side
  // ============================================================================
  function sanitizeClientPhone(val) {
    if (val === null || val === undefined) return { valid: false, error: 'Vazio' };
    let s = String(val).trim();
    if (s.endsWith('.0')) s = s.slice(0, -2);
    let digits = s.replace(/\D/g, '');

    if (!digits) return { valid: false, error: 'Sem dígitos' };
    if (digits.length >= 8 && digits[0].repeat(digits.length) === digits) {
      return { valid: false, error: 'Número fictício repetido' };
    }
    if (digits.length < 10) return { valid: false, error: 'Incompleto (sem DDD)' };

    // Remove CSP (015, 021) ou 0 de longa distância
    if (digits.startsWith('0') && (digits.length === 13 || digits.length === 14)) {
      digits = digits.slice(3);
    } else if (digits.startsWith('0') && (digits.length === 11 || digits.length === 12)) {
      digits = digits.slice(1);
    }

    // 11 dígitos (DDD + 9 celular)
    if (digits.length === 11) {
      const ddd = parseInt(digits.slice(0, 2), 10);
      if (!ANATEL_DDDS.has(ddd)) return { valid: false, error: `DDD ${ddd} inválido` };
      if (digits[2] === '9') {
        return { valid: true, canonical: `55${digits}`, ddd: String(ddd), type: 'MOBILE' };
      }
      return { valid: false, error: 'Celular sem 9º dígito' };
    }

    // 13 dígitos (55 + DDD + 9 celular)
    if (digits.length === 13) {
      if (!digits.startsWith('55')) return { valid: false, error: 'DDI diferente de 55' };
      const ddd = parseInt(digits.slice(2, 4), 10);
      if (!ANATEL_DDDS.has(ddd)) return { valid: false, error: `DDD ${ddd} inválido` };
      if (digits[4] === '9') {
        return { valid: true, canonical: digits, ddd: String(ddd), type: 'MOBILE' };
      }
      return { valid: false, error: 'Celular sem 9º dígito' };
    }

    // 10 dígitos (DDD + 8 fixo ou celular legado)
    if (digits.length === 10) {
      const ddd = parseInt(digits.slice(0, 2), 10);
      if (!ANATEL_DDDS.has(ddd)) return { valid: false, error: `DDD ${ddd} inválido` };
      const first = digits[2];
      if ('2345'.includes(first)) {
        return { valid: true, canonical: `55${digits}`, ddd: String(ddd), type: 'LANDLINE' };
      }
      if ('6789'.includes(first)) {
        return { valid: true, canonical: `55${ddd}9${digits.slice(2)}`, ddd: String(ddd), type: 'MOBILE' };
      }
      return { valid: false, error: 'Prefixo local inválido' };
    }

    // 12 dígitos (55 + DDD + 8 fixo ou celular legado)
    if (digits.length === 12 && digits.startsWith('55')) {
      const ddd = parseInt(digits.slice(2, 4), 10);
      if (!ANATEL_DDDS.has(ddd)) return { valid: false, error: `DDD ${ddd} inválido` };
      const first = digits[4];
      if ('2345'.includes(first)) {
        return { valid: true, canonical: digits, ddd: String(ddd), type: 'LANDLINE' };
      }
      if ('6789'.includes(first)) {
        return { valid: true, canonical: `55${ddd}9${digits.slice(4)}`, ddd: String(ddd), type: 'MOBILE' };
      }
      return { valid: false, error: 'Prefixo local inválido' };
    }

    return { valid: false, error: `Comprimento ${digits.length} inválido` };
  }

  // ============================================================================
  // Processamento e Ingestão de Contatos
  // ============================================================================

  function setIngestedContacts(validContacts, rawMetrics) {
    state.contacts = validContacts.map((c, idx) => ({
      id: c.id || `c_${idx + 1}`,
      rawPhone: c.raw_phone || c.rawPhone || '',
      canonicalPhone: c.canonical_phone || c.canonicalPhone || '',
      name: c.name || `Contato ${idx + 1}`,
      variables: c.variables || {},
      status: 'VALID',
      ddd: (c.canonical_phone || c.canonicalPhone || '').slice(2, 4),
    }));

    state.metrics = {
      total: rawMetrics.total_rows || state.contacts.length,
      valid: state.contacts.length,
      duplicates: rawMetrics.duplicate_count || 0,
      invalid: rawMetrics.invalid_count || 0,
      efficiency: rawMetrics.efficiency_percentage || 100,
    };

    if (state.contacts.length > 0) {
      state.selectedContact = state.contacts[0];
    }

    // Popula Mapeamento Inteligente de Colunas se disponível na resposta
    if (rawMetrics && Array.isArray(rawMetrics.detected_columns) && rawMetrics.detected_columns.length > 0) {
      if (dom.mappingCard) dom.mappingCard.classList.remove('hidden');
      if (dom.phoneColSelect) {
        dom.phoneColSelect.innerHTML = rawMetrics.detected_columns
          .map((col) => `<option value="${escapeHtml(col)}" ${col === rawMetrics.phone_column ? 'selected' : ''}>${escapeHtml(col)}</option>`)
          .join('');
      }
      if (dom.nameColSelect) {
        const nameOpts = ['<option value="">-- Sem Coluna de Nome --</option>'].concat(
          rawMetrics.detected_columns.map(
            (col) => `<option value="${escapeHtml(col)}" ${col === rawMetrics.name_column ? 'selected' : ''}>${escapeHtml(col)}</option>`
          )
        );
        dom.nameColSelect.innerHTML = nameOpts.join('');
      }
    }

    updateMetricsView();
    applyTableFilters();
    updateMessagePreview();
  }

  function updateMetricsView() {
    if (dom.metricTotalRows) dom.metricTotalRows.textContent = state.metrics.total.toLocaleString('pt-BR');
    if (dom.metricValidCount) dom.metricValidCount.textContent = state.metrics.valid.toLocaleString('pt-BR');
    if (dom.metricDuplicateCount) dom.metricDuplicateCount.textContent = state.metrics.duplicates.toLocaleString('pt-BR');
    if (dom.metricInvalidCount) dom.metricInvalidCount.textContent = state.metrics.invalid.toLocaleString('pt-BR');
    if (dom.metricEfficiency) dom.metricEfficiency.textContent = `${state.metrics.efficiency}%`;
    if (dom.quickCountBadge) dom.quickCountBadge.textContent = `${state.metrics.valid.toLocaleString('pt-BR')} aptos para disparo`;
  }

  // ============================================================================
  // Tabela, Busca e Paginação
  // ============================================================================

  function applyTableFilters() {
    const query = dom.tableSearchInput ? dom.tableSearchInput.value.toLowerCase().trim() : '';
    const statusFilter = dom.statusFilterSelect ? dom.statusFilterSelect.value : 'ALL';

    state.filteredContacts = state.contacts.filter((c) => {
      if (statusFilter !== 'ALL' && c.status !== statusFilter) return false;
      if (!query) return true;
      const matchName = c.name.toLowerCase().includes(query);
      const matchPhone = String(c.rawPhone).includes(query) || (c.canonicalPhone && c.canonicalPhone.includes(query));
      const matchVars = Object.values(c.variables).some((v) => String(v).toLowerCase().includes(query));
      return matchName || matchPhone || matchVars;
    });

    state.pagination.page = 1;
    updatePagination();
    renderTableRows();
  }

  function updatePagination() {
    const total = state.filteredContacts.length;
    const pageSize = state.pagination.pageSize;
    state.pagination.totalPages = Math.ceil(total / pageSize) || 1;

    if (dom.currentPageNum) dom.currentPageNum.textContent = state.pagination.page;
    if (dom.prevPageBtn) dom.prevPageBtn.disabled = state.pagination.page <= 1;
    if (dom.nextPageBtn) dom.nextPageBtn.disabled = state.pagination.page >= state.pagination.totalPages;

    const startIdx = total === 0 ? 0 : (state.pagination.page - 1) * pageSize + 1;
    const endIdx = Math.min(state.pagination.page * pageSize, total);
    if (dom.paginationInfo) dom.paginationInfo.textContent = `Mostrando ${startIdx}-${endIdx} de ${total.toLocaleString('pt-BR')}`;
  }

  function renderTableRows() {
    const tbody = dom.contactsTableBody;
    if (!tbody) return;
    tbody.innerHTML = '';

    if (state.filteredContacts.length === 0) {
      tbody.innerHTML = `
        <tr class="empty-row">
          <td colspan="7" class="text-center py-5">
            <div class="empty-state">
              <span class="empty-icon">🔍</span>
              <p>Nenhum registro encontrado para os filtros selecionados.</p>
            </div>
          </td>
        </tr>`;
      return;
    }

    const start = (state.pagination.page - 1) * state.pagination.pageSize;
    const end = start + state.pagination.pageSize;
    const pageSlice = state.filteredContacts.slice(start, end);

    pageSlice.forEach((c, idx) => {
      const tr = document.createElement('tr');
      tr.style.cursor = 'pointer';
      tr.addEventListener('click', () => {
        state.selectedContact = c;
        updateMessagePreview();
      });

      let statusBadge = '<span class="badge badge-success">Válido</span>';
      if (c.status === 'DUPLICATE') statusBadge = '<span class="badge badge-warning">Duplicado</span>';
      else if (c.status === 'INVALID') statusBadge = `<span class="badge badge-danger" title="${c.errorDetail || ''}">Inválido</span>`;

      const varsText = Object.entries(c.variables || {}).map(([k, v]) => `${k}: ${v}`).join(' | ');

      tr.innerHTML = `
        <td>${start + idx + 1}</td>
        <td><strong>${escapeHtml(c.name)}</strong></td>
        <td><span class="phone-raw">${escapeHtml(c.rawPhone)}</span></td>
        <td><span class="phone-canonical">${c.canonicalPhone || '—'}</span></td>
        <td>${c.ddd ? `DDD ${c.ddd}` : '—'}</td>
        <td>${statusBadge}</td>
        <td><small class="text-muted">${escapeHtml(varsText) || '—'}</small></td>
      `;
      tbody.appendChild(tr);
    });
  }

  // ============================================================================
  // Editor de Mensagem e Resolução Spintax
  // ============================================================================

  function resolveSpintax(text) {
    const spintaxRegex = /\{([^{}]+)\}/g;
    let resolved = text;
    while (spintaxRegex.test(resolved)) {
      resolved = resolved.replace(spintaxRegex, (match, choices) => {
        if (choices.startsWith('nome') || choices.startsWith('primeiro_nome') || choices.startsWith('saudacao') || choices.startsWith('telefone') || choices.startsWith('empresa') || choices.startsWith('valor')) {
          return match;
        }
        const options = choices.split('|');
        return options[Math.floor(Math.random() * options.length)];
      });
    }
    return resolved;
  }

  function getGreeting() {
    const hour = new Date().getHours();
    if (hour >= 5 && hour < 12) return 'Bom dia';
    if (hour >= 12 && hour < 18) return 'Boa tarde';
    return 'Boa noite';
  }

  function updateMessagePreview() {
    if (!dom.messageTemplate || !dom.whatsappPreviewText) return;
    const template = dom.messageTemplate.value;
    const contact = state.selectedContact || {
      name: 'João Silva',
      canonicalPhone: '5562994912937',
      variables: { empresa: 'Fractal', valor: 'R$ 1.500,00' },
    };

    if (dom.previewContactName) dom.previewContactName.textContent = contact.name;
    if (dom.previewContactPhone) dom.previewContactPhone.textContent = contact.canonicalPhone ? `+${contact.canonicalPhone}` : 'Sem número';

    let rendered = resolveSpintax(template);
    const firstName = contact.name.split(' ')[0] || contact.name;
    rendered = rendered
      .replace(/\{nome\}/gi, contact.name)
      .replace(/\{primeiro_nome\}/gi, firstName)
      .replace(/\{saudacao\}/gi, getGreeting())
      .replace(/\{telefone\}/gi, contact.canonicalPhone || contact.rawPhone || '');

    if (contact.variables) {
      Object.entries(contact.variables).forEach(([k, v]) => {
        const regex = new RegExp(`\\{${k}\\}`, 'gi');
        rendered = rendered.replace(regex, v);
      });
    }

    dom.whatsappPreviewText.innerHTML = escapeHtml(rendered).replace(/\n/g, '<br>');

    const chars = template.length;
    const words = template.trim() ? template.trim().split(/\s+/).length : 0;
    if (dom.charCount) dom.charCount.textContent = `${chars} caracteres`;
    if (dom.wordCount) dom.wordCount.textContent = `${words} palavras`;

    const estSeconds = Math.round((chars / 5) * 0.85);
    if (dom.estimatedTypingTime) dom.estimatedTypingTime.textContent = `~${estSeconds}s digitação humana`;

    const now = new Date();
    if (dom.previewTimestamp) dom.previewTimestamp.textContent = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`;
  }

  // ============================================================================
  // Telemetria ao Vivo via Server-Sent Events (SSE) e Polling Fallback
  // ============================================================================

  function setupTelemetrySSE() {
    if (!window.EventSource) {
      appendLog('[AVISO] EventSource não suportado. Ativando telemetria por polling.');
      setInterval(pollTelemetrySnapshot, 2000);
      return;
    }

    appendLog('[INFO] Conectando ao canal de telemetria em tempo real (SSE)...');
    const evtSource = new EventSource('/api/telemetry/stream');

    evtSource.addEventListener('telemetry', (e) => {
      try {
        const data = JSON.parse(e.data);
        updateTelemetryUI(data);
      } catch (err) {
        console.error('Erro ao processar telemetria SSE:', err);
      }
    });

    evtSource.addEventListener('contact_log', (e) => {
      try {
        const log = JSON.parse(e.data);
        appendLiveContactLog(log);
      } catch (err) {
        console.error('Erro ao processar log de contato SSE:', err);
      }
    });

    evtSource.addEventListener('system_log', (e) => {
      try {
        const log = JSON.parse(e.data);
        appendLog(`[${log.level}] ${log.message}`);
      } catch (err) {
        console.error('Erro ao processar log de sistema SSE:', err);
      }
    });

    evtSource.onopen = () => {
      state.sseConnected = true;
      appendLog('[SUCESSO] Canal de Telemetria SSE conectado e ativo.');
    };

    evtSource.onerror = () => {
      state.sseConnected = false;
      // Fallback gracioso por snapshot
      pollTelemetrySnapshot();
    };
  }

  async function pollTelemetrySnapshot() {
    try {
      const res = await fetch('/api/telemetry/snapshot');
      if (res.ok) {
        const data = await res.json();
        updateTelemetryUI(data);
      }
    } catch (err) {
      console.debug('Aviso ao consultar snapshot de telemetria:', err);
    }
  }

  function updateTelemetryUI(data) {
    state.queueState = data.state_raw || data.state;

    // Atualiza barra de progresso
    const total = data.total_contacts || 0;
    const sent = data.sent_count || 0;
    const failed = data.failed_count || 0;
    const pending = data.pending_count || 0;
    const mpm = data.messages_per_minute || 0.0;
    const progress = data.progress_percentage || (total > 0 ? (((sent + failed) / total) * 100).toFixed(1) : 0);

    if (dom.progressBarFill) dom.progressBarFill.style.width = `${progress}%`;
    if (dom.progressPercentLabel) dom.progressPercentLabel.textContent = `Progresso: ${progress}%`;
    if (dom.progressFractionLabel) dom.progressFractionLabel.textContent = `${sent + failed} / ${total} processados`;

    // Atualiza contadores
    if (dom.telemetrySent) dom.telemetrySent.textContent = sent.toLocaleString('pt-BR');
    if (dom.telemetryFailed) dom.telemetryFailed.textContent = failed.toLocaleString('pt-BR');
    if (dom.telemetryPending) dom.telemetryPending.textContent = pending.toLocaleString('pt-BR');
    if (dom.telemetrySpeed) dom.telemetrySpeed.textContent = Number(mpm).toFixed(1);

    // ETA dinâmico e Badge de Estado
    if (dom.queueEtaDisplay) dom.queueEtaDisplay.textContent = `ETA: ${data.eta_formatted || '--:--:--'}`;
    if (dom.queueStateBadge) {
      dom.queueStateBadge.textContent = data.state || 'FILA OCIOSA';
      dom.queueStateBadge.className = 'status-badge-lg ' + getBadgeClassForState(state.queueState);
    }

    // Contato em trânsito
    if (dom.currentContactText) {
      if (data.current_contact) {
        dom.currentContactText.textContent = `Disparando para ${data.current_contact}...`;
      } else if (state.queueState === 'COMPLETED' || state.queueState === 'CONCLUIDO') {
        dom.currentContactText.textContent = 'Campanha Concluída com Sucesso!';
      } else if (state.queueState === 'ABORTED' || state.queueState === 'ABORTADO') {
        dom.currentContactText.textContent = 'Campanha Abortada pelo Operador.';
      } else if (state.queueState === 'PAUSED' || state.queueState === 'PAUSADO') {
        dom.currentContactText.textContent = 'Fila Pausada pelo Operador.';
      } else {
        dom.currentContactText.textContent = 'Aguardando início do disparo...';
      }
    }

    // Gerenciamento do estado dos botões de controle
    updateButtonStates();

    // Atualiza aba de relatórios se visível
    updateReportsSummary(data);
  }

  function getBadgeClassForState(st) {
    switch (st) {
      case 'RUNNING':
      case 'EXECUTANDO':
        return 'badge-running';
      case 'PAUSED':
      case 'PAUSADO':
      case 'PAUSING':
        return 'badge-paused';
      case 'COMPLETED':
      case 'CONCLUIDO':
        return 'badge-completed';
      case 'ABORTED':
      case 'ABORTADO':
        return 'badge-aborted';
      default:
        return 'badge-idle';
    }
  }

  function updateButtonStates() {
    const isRunning = state.queueState === 'RUNNING' || state.queueState === 'EXECUTANDO';
    const isPaused = state.queueState === 'PAUSED' || state.queueState === 'PAUSADO';

    if (dom.startCampaignBtn) dom.startCampaignBtn.disabled = isRunning || isPaused;
    if (dom.pauseCampaignBtn) dom.pauseCampaignBtn.disabled = !isRunning;
    if (dom.resumeCampaignBtn) dom.resumeCampaignBtn.disabled = !isPaused;
    if (dom.abortCampaignBtn) dom.abortCampaignBtn.disabled = !(isRunning || isPaused);
  }

  function appendLiveContactLog(log) {
    state.processedLogs.push(log);
    const tbody = dom.liveContactsLogBody;
    if (!tbody) return;

    // Remove empty row se presente
    const empty = tbody.querySelector('.empty-row');
    if (empty) empty.remove();

    const tr = document.createElement('tr');
    let statusClass = 'badge-success';
    if (log.Status === 'FALHA' || log.Status === 'FAILED') statusClass = 'badge-danger';
    else if (log.Status === 'CANCELADO' || log.Status === 'CANCELLED') statusClass = 'badge-warning';

    tr.innerHTML = `
      <td>${state.processedLogs.length}</td>
      <td><strong>${escapeHtml(log.Numero)}</strong></td>
      <td>${escapeHtml(log.Nome || '—')}</td>
      <td><small>${escapeHtml(log.DataHora)}</small></td>
      <td><span class="badge ${statusClass}">${escapeHtml(log.Status)}</span></td>
      <td><small>${escapeHtml(log.Detalhes)}</small></td>
    `;

    tbody.insertBefore(tr, tbody.firstChild);

    if (dom.liveContactLogBadge) {
      dom.liveContactLogBadge.textContent = `${state.processedLogs.length} processados`;
    }
  }

  function updateReportsSummary(data) {
    if (dom.reportTotalContacts) dom.reportTotalContacts.textContent = (data.total_contacts || 0).toLocaleString('pt-BR');
    if (dom.reportSentSuccess) dom.reportSentSuccess.textContent = (data.sent_count || 0).toLocaleString('pt-BR');
    if (dom.reportFailed) dom.reportFailed.textContent = (data.failed_count || 0).toLocaleString('pt-BR');
    if (dom.reportCancelled) dom.reportCancelled.textContent = (data.cancelled_count || 0).toLocaleString('pt-BR');

    const total = data.total_contacts || 0;
    const sent = data.sent_count || 0;
    const rate = total > 0 ? ((sent / total) * 100).toFixed(1) : '0.0';
    if (dom.reportDeliveryRate) dom.reportDeliveryRate.textContent = `${rate}%`;
    if (dom.reportCampaignTitleBadge && data.campaign_title) {
      dom.reportCampaignTitleBadge.textContent = data.campaign_title;
    }
  }

  // ============================================================================
  // Controles de Fila e Disparo Anti-Ban
  // ============================================================================

  function setupQueueControls() {
    // Iniciar Disparo
    if (dom.startCampaignBtn) {
      dom.startCampaignBtn.addEventListener('click', async () => {
        if (state.contacts.length === 0) {
          appendLog('[AVISO] Nenhum contato carregado. Importe uma planilha ou cole números antes de disparar.');
          alert('Por favor, carregue uma lista de contatos na aba "Gestão de Contatos" antes de iniciar o disparo.');
          return;
        }

        const template = dom.messageTemplate ? dom.messageTemplate.value.trim() : '';
        if (!template) {
          alert('Por favor, defina um texto de mensagem na aba "Editor de Mensagem".');
          return;
        }

        if (state.sessionStatus !== 'CONECTADO_PRONTO') {
          const confirmSim = window.confirm(
            'A sessão do WhatsApp Web está DESCONECTADA.\n\n' +
            'Deseja executar o disparo em MODO SIMULAÇÃO / DEMONSTRAÇÃO (sem envio real pelo WhatsApp)?\n' +
            'Clique em "Cancelar" se preferir conectar o QR Code na aba "Sessão WhatsApp" primeiro.'
          );
          if (!confirmSim) return;
        }

        const jitterMin = dom.jitterMinInput ? parseFloat(dom.jitterMinInput.value) || 10.0 : 10.0;
        const jitterMax = dom.jitterMaxInput ? parseFloat(dom.jitterMaxInput.value) || 25.0 : 25.0;
        const batchSize = dom.batchSizeInput ? parseInt(dom.batchSizeInput.value, 10) || 20 : 20;
        const batchPause = dom.batchPauseInput ? parseFloat(dom.batchPauseInput.value) || 120.0 : 120.0;
        const campaignTitle = dom.campaignTitleInput && dom.campaignTitleInput.value.trim()
          ? dom.campaignTitleInput.value.trim()
          : 'Campanha WhatsApp Bulk';

        appendLog('[INFO] Solicitando início de campanha ao servidor...');
        try {
          const payload = {
            template: template,
            contacts: state.contacts.map((c) => ({
              telefone: c.canonicalPhone || c.rawPhone,
              nome: c.name,
              variables: c.variables,
            })),
            jitter_min: Math.min(jitterMin, jitterMax),
            jitter_max: Math.max(jitterMin, jitterMax),
            batch_size: batchSize,
            batch_pause_seconds: batchPause,
            attachment_path: state.attachmentPath || null,
            campaign_title: campaignTitle,
          };

          const res = await fetch('/api/queue/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
          });

          const data = await res.json();
          if (res.ok) {
            appendLog(`[SUCESSO] ${data.message} (${data.total_contacts} contatos na fila).`);
            state.processedLogs = [];
            if (dom.liveContactsLogBody) dom.liveContactsLogBody.innerHTML = '';
          } else {
            appendLog(`[ERRO] Falha ao iniciar fila: ${data.detail || data.message}`);
            alert(`Erro ao iniciar disparo: ${data.detail || data.message}`);
          }
        } catch (err) {
          appendLog(`[ERRO] Falha na requisição de início: ${err.message}`);
        }
      });
    }

    // Pausar
    if (dom.pauseCampaignBtn) {
      dom.pauseCampaignBtn.addEventListener('click', async () => {
        appendLog('[INFO] Solicitando pausa atômica da fila...');
        try {
          const res = await fetch('/api/queue/pause', { method: 'POST' });
          const data = await res.json();
          if (res.ok && data.success) {
            appendLog('[AVISO] Fila pausada com sucesso. Nenhum contato foi perdido.');
          } else {
            appendLog(`[AVISO] Não foi possível pausar: ${data.message}`);
          }
        } catch (err) {
          appendLog(`[ERRO] Erro ao pausar: ${err.message}`);
        }
      });
    }

    // Continuar
    if (dom.resumeCampaignBtn) {
      dom.resumeCampaignBtn.addEventListener('click', async () => {
        appendLog('[INFO] Solicitando retomada da fila...');
        try {
          const res = await fetch('/api/queue/resume', { method: 'POST' });
          const data = await res.json();
          if (res.ok && data.success) {
            appendLog('[SUCESSO] Fila retomada a partir do contato pendente.');
          } else {
            appendLog(`[AVISO] Não foi possível retomar: ${data.message}`);
          }
        } catch (err) {
          appendLog(`[ERRO] Erro ao retomar: ${err.message}`);
        }
      });
    }

    // Abortar
    if (dom.abortCampaignBtn) {
      dom.abortCampaignBtn.addEventListener('click', async () => {
        if (!confirm('Deseja realmente abortar a campanha? Os contatos pendentes restantes serão cancelados.')) {
          return;
        }
        appendLog('[AVISO] Solicitando cancelamento emergencial da fila...');
        try {
          const res = await fetch('/api/queue/abort', { method: 'POST' });
          const data = await res.json();
          if (res.ok && data.success) {
            appendLog('[AVISO] Fila abortada com sucesso. Relatório parcial pronto para exportação.');
          } else {
            appendLog(`[AVISO] Não foi possível abortar: ${data.message}`);
          }
        } catch (err) {
          appendLog(`[ERRO] Erro ao abortar: ${err.message}`);
        }
      });
    }
  }

  // ============================================================================
  // Exportação Executiva em 1 Clique (Excel .xlsx e CSV)
  // ============================================================================

  function triggerDownload(url, defaultFilename) {
    appendLog(`[INFO] Solicitando download do arquivo: ${defaultFilename}...`);
    const a = document.createElement('a');
    a.href = url;
    a.download = defaultFilename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    appendLog(`[SUCESSO] Download de '${defaultFilename}' disparado com sucesso.`);
  }

  function setupExportButtons() {
    const handleExcelExport = () => {
      triggerDownload('/api/reports/export/excel', `relatorio_disparos_${formatTimestampForFile()}.xlsx`);
    };

    const handleCsvExport = () => {
      triggerDownload('/api/reports/export/csv', `relatorio_disparos_${formatTimestampForFile()}.csv`);
    };

    if (dom.exportXlsxBtn) dom.exportXlsxBtn.addEventListener('click', handleExcelExport);
    if (dom.quickExportXlsxBtn) dom.quickExportXlsxBtn.addEventListener('click', handleExcelExport);

    if (dom.exportCsvBtn) dom.exportCsvBtn.addEventListener('click', handleCsvExport);
    if (dom.quickExportCsvBtn) dom.quickExportCsvBtn.addEventListener('click', handleCsvExport);
  }

  function formatTimestampForFile() {
    const d = new Date();
    const pad = (n) => String(n).padStart(2, '0');
    return `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}_${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}`;
  }

  // ============================================================================
  // Sessão WhatsApp Web (R2)
  // ============================================================================

  function setupSessionControls() {
    if (dom.openBrowserBtn) {
      dom.openBrowserBtn.addEventListener('click', async () => {
        appendLog('[INFO] Abrindo navegador WhatsApp Web...');
        dom.openBrowserBtn.disabled = true;
        try {
          const res = await fetch('/api/session/start', { method: 'POST' });
          const data = await res.json();
          if (res.ok && data.success) {
            appendLog(`[SUCESSO] Navegador iniciado. Status: ${data.status}`);
            checkSessionStatus();
          } else {
            appendLog(`[ERRO] Falha ao iniciar navegador: ${data.error || 'Erro desconhecido'}`);
          }
        } catch (err) {
          appendLog(`[ERRO] Erro ao comunicar com servidor: ${err.message}`);
        } finally {
          dom.openBrowserBtn.disabled = false;
        }
      });
    }

    if (dom.checkSessionBtn) {
      dom.checkSessionBtn.addEventListener('click', checkSessionStatus);
    }

    if (dom.closeBrowserBtn) {
      dom.closeBrowserBtn.addEventListener('click', async () => {
        appendLog('[INFO] Encerrando sessão do navegador...');
        try {
          await fetch('/api/session/close', { method: 'POST' });
          checkSessionStatus();
        } catch (err) {
          appendLog(`[ERRO] Erro ao fechar navegador: ${err.message}`);
        }
      });
    }

    // Verificação inicial de sessão
    checkSessionStatus();
  }

  async function checkSessionStatus() {
    try {
      const res = await fetch('/api/session/status');
      if (res.ok) {
        const data = await res.json();
        state.sessionStatus = data.status;
        updateSessionUI(data);

        // Se estiver aguardando QR Code, busca a imagem
        if (data.status === 'AGUARDANDO_QR') {
          fetchQRCode();
        }
      }
    } catch (err) {
      console.debug('Aviso ao checar sessão:', err);
    }
  }

  function updateSessionUI(data) {
    const isConn = data.is_connected && data.status === 'CONECTADO_PRONTO';

    if (dom.sidebarSessionStatus) {
      dom.sidebarSessionStatus.className = 'session-badge ' + (isConn ? 'connected' : 'disconnected');
      const textSpan = dom.sidebarSessionStatus.querySelector('.status-text');
      if (textSpan) textSpan.textContent = isConn ? 'Conectado' : data.status || 'Desconectado';
    }

    if (dom.connectionBadge) {
      dom.connectionBadge.className = 'badge ' + (isConn ? 'badge-success' : 'badge-danger');
      dom.connectionBadge.textContent = data.status || 'Desconectado';
    }

    if (dom.closeBrowserBtn) {
      dom.closeBrowserBtn.classList.toggle('hidden', !data.is_connected);
    }
  }

  async function fetchQRCode() {
    try {
      const res = await fetch('/api/session/qr');
      if (res.ok) {
        const data = await res.json();
        const qrSrc = data.qr_code && (data.qr_code.qr_image_base64 || data.qr_code.screenshot_base64);
        if (data.has_qr && qrSrc && dom.qrContainer) {
          dom.qrContainer.innerHTML = `
            <img src="${qrSrc}" alt="QR Code WhatsApp" style="max-width: 250px; border-radius: var(--radius-sm); border: 2px solid var(--border-color);" />
            <p style="margin-top: 8px; font-size: 0.8rem; color: var(--text-muted);">Escaneie o QR Code com seu WhatsApp móvel</p>
          `;
        }
      }
    } catch (err) {
      console.debug('Aviso ao consultar QR Code:', err);
    }
  }

  // ============================================================================
  // Event Listeners e Navegação
  // ============================================================================

  function setupNavigation() {
    const tabHeaders = {
      contacts: { title: 'Gestão de Contatos', subtitle: 'Importação em streaming, sanitização E.164 e deduplicação determinística' },
      editor: { title: 'Editor de Mensagem', subtitle: 'Personalização dinâmica, rotação de Spintax e preview em tempo real' },
      dispatcher: { title: 'Fila & Disparo', subtitle: 'Simulação de digitação humana, jitter estocástico e monitoramento ao vivo' },
      connection: { title: 'Sessão WhatsApp Web', subtitle: 'Autenticação visual por QR Code e persistência de sessão' },
      reports: { title: 'Relatórios Executivos', subtitle: 'Exportação em 1 clique em formatos Excel (.xlsx) e CSV' },
    };

    dom.navItems.forEach((btn) => {
      btn.addEventListener('click', () => {
        const targetTab = btn.getAttribute('data-tab');
        dom.navItems.forEach((b) => b.classList.remove('active'));
        dom.tabPanes.forEach((p) => p.classList.remove('active'));

        btn.classList.add('active');
        const targetPane = document.getElementById(`tab-${targetTab}`);
        if (targetPane) targetPane.classList.add('active');

        if (tabHeaders[targetTab]) {
          dom.pageTitle.textContent = tabHeaders[targetTab].title;
          dom.pageSubtitle.textContent = tabHeaders[targetTab].subtitle;
        }

        if (targetTab === 'connection') {
          checkSessionStatus();
        } else if (targetTab === 'reports') {
          pollTelemetrySnapshot();
        }
      });
    });

    if (dom.themeToggleBtn) {
      dom.themeToggleBtn.addEventListener('click', () => {
        document.documentElement.classList.toggle('light');
        const isLight = document.documentElement.classList.contains('light');
        localStorage.setItem('wse_theme', isLight ? 'light' : 'dark');
      });
    }

    if (localStorage.getItem('wse_theme') === 'light') {
      document.documentElement.classList.add('light');
    }
  }

  function setupIngestionEvents() {
    if (dom.dropzone) {
      dom.dropzone.addEventListener('click', () => dom.fileInput.click());
    }
    if (dom.selectFileBtn) {
      dom.selectFileBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        dom.fileInput.click();
      });
    }

    if (dom.dropzone) {
      ['dragenter', 'dragover'].forEach((eventName) => {
        dom.dropzone.addEventListener(eventName, (e) => {
          e.preventDefault();
          dom.dropzone.classList.add('drag-over');
        });
      });

      ['dragleave', 'drop'].forEach((eventName) => {
        dom.dropzone.addEventListener(eventName, (e) => {
          e.preventDefault();
          dom.dropzone.classList.remove('drag-over');
        });
      });

      dom.dropzone.addEventListener('drop', (e) => {
        if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
          handleFileUpload(e.dataTransfer.files[0]);
        }
      });
    }

    if (dom.fileInput) {
      dom.fileInput.addEventListener('change', (e) => {
        if (e.target.files && e.target.files.length > 0) {
          handleFileUpload(e.target.files[0]);
        }
      });
    }

    // Ingestão Manual
    if (dom.processManualBtn) {
      dom.processManualBtn.addEventListener('click', async () => {
        const text = dom.manualTextarea ? dom.manualTextarea.value.trim() : '';
        if (!text) return;

        appendLog('[INFO] Enviando contatos manuais para sanitização no backend...');
        try {
          const res = await fetch('/api/contacts/manual', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text: text, default_name_prefix: 'Contato' }),
          });

          if (res.ok) {
            const data = await res.json();
            setIngestedContacts(data.valid_contacts, data);
            appendLog(`[SUCESSO] ${data.valid_count} contatos válidos processados pelo servidor.`);
          } else {
            appendLog('[ERRO] Falha na ingestão manual no servidor.');
          }
        } catch (err) {
          appendLog(`[ERRO] Falha de comunicação: ${err.message}`);
        }
      });
    }

    if (dom.loadDemoBtn) {
      dom.loadDemoBtn.addEventListener('click', () => {
        const demoContacts = [
          { name: 'João Silva', canonical_phone: '5562994912937', raw_phone: '62994912937', variables: { empresa: 'Fractal Tech', valor: 'R$ 2.400' } },
          { name: 'Maria Santos', canonical_phone: '5511988887777', raw_phone: '(11) 98888-7777', variables: { empresa: 'Anglo Educação', valor: 'R$ 1.800' } },
          { name: 'Escritório Central', canonical_phone: '556232015000', raw_phone: '6232015000', variables: { departamento: 'Financeiro' } },
        ];
        setIngestedContacts(demoContacts, {
          total_rows: 4,
          valid_count: 3,
          duplicate_count: 1,
          invalid_count: 0,
          efficiency_percentage: 75.0,
        });
        appendLog('[INFO] Contatos de demonstração carregados na tabela.');
      });
    }

    if (dom.reapplyMappingBtn) {
      dom.reapplyMappingBtn.addEventListener('click', async () => {
        const phoneCol = dom.phoneColSelect ? dom.phoneColSelect.value : '';
        const nameCol = dom.nameColSelect ? dom.nameColSelect.value : '';
        appendLog(`[INFO] Remapeando colunas: Telefone='${phoneCol}', Nome='${nameCol || 'Padrão'}'...`);
        try {
          const res = await fetch('/api/contacts/remap', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ phone_column: phoneCol, name_column: nameCol }),
          });
          const data = await res.json();
          if (res.ok) {
            setIngestedContacts(data.valid_contacts, data);
            appendLog(`[SUCESSO] Colunas remapeadas: ${data.valid_count} contatos válidos identificados.`);
          } else {
            alert(data.detail || 'Erro ao remapear colunas.');
          }
        } catch (err) {
          appendLog(`[ERRO] Falha ao remapear colunas: ${err.message}`);
        }
      });
    }

    if (dom.clearListBtn) {
      dom.clearListBtn.addEventListener('click', async () => {
        if (dom.manualTextarea) dom.manualTextarea.value = '';
        if (dom.mappingCard) dom.mappingCard.classList.add('hidden');
        state.contacts = [];
        state.filteredContacts = [];
        state.selectedContact = null;
        state.metrics = { total: 0, valid: 0, duplicates: 0, invalid: 0, efficiency: 0 };
        try {
          await fetch('/api/contacts', { method: 'DELETE' });
        } catch (e) {}
        updateMetricsView();
        applyTableFilters();
        updateMessagePreview();
        appendLog('[INFO] Lista de contatos limpa.');
      });
    }

    // Filtros e Busca na Tabela (com debounce para alta performance em listas longas)
    if (dom.tableSearchInput) dom.tableSearchInput.addEventListener('input', debounce(applyTableFilters, 250));
    if (dom.statusFilterSelect) dom.statusFilterSelect.addEventListener('change', applyTableFilters);
    if (dom.pageSizeSelect) {
      dom.pageSizeSelect.addEventListener('change', (e) => {
        state.pagination.pageSize = parseInt(e.target.value, 10);
        state.pagination.page = 1;
        updatePagination();
        renderTableRows();
      });
    }

    if (dom.prevPageBtn) {
      dom.prevPageBtn.addEventListener('click', () => {
        if (state.pagination.page > 1) {
          state.pagination.page--;
          updatePagination();
          renderTableRows();
        }
      });
    }

    if (dom.nextPageBtn) {
      dom.nextPageBtn.addEventListener('click', () => {
        if (state.pagination.page < state.pagination.totalPages) {
          state.pagination.page++;
          updatePagination();
          renderTableRows();
        }
      });
    }
  }

  async function handleFileUpload(file) {
    appendLog(`[INFO] Enviando arquivo '${file.name}' (${(file.size / 1024).toFixed(1)} KB) para streaming no backend...`);

    const formData = new FormData();
    formData.append('file', file);

    try {
      const res = await fetch('/api/contacts/upload', {
        method: 'POST',
        body: formData,
      });

      if (res.ok) {
        const data = await res.json();
        setIngestedContacts(data.valid_contacts, data);
        appendLog(
          `[SUCESSO] Ingestão concluída: ${data.total_rows} lidos, ${data.valid_count} válidos, ` +
          `${data.duplicate_count} duplicatas descartadas (${data.efficiency_percentage}% aproveitamento).`
        );
      } else {
        const errData = await res.json();
        appendLog(`[ERRO] Erro no processamento: ${errData.detail || 'Falha ao processar arquivo'}`);
        alert(`Erro no upload: ${errData.detail || 'Falha ao processar arquivo'}`);
      }
    } catch (err) {
      appendLog(`[ERRO] Falha no upload: ${err.message}`);
    }
  }

  function setupEditorEvents() {
    if (dom.messageTemplate) {
      dom.messageTemplate.addEventListener('input', debounce(updateMessagePreview, 150));
    }

    dom.tagButtons.forEach((btn) => {
      btn.addEventListener('click', () => {
        const tag = btn.getAttribute('data-tag');
        insertAtCursor(dom.messageTemplate, tag);
        updateMessagePreview();
      });
    });

    dom.spintaxButtons.forEach((btn) => {
      btn.addEventListener('click', () => {
        const spintax = btn.getAttribute('data-spintax');
        insertAtCursor(dom.messageTemplate, spintax);
        updateMessagePreview();
      });
    });

    if (dom.testSpintaxBtn) {
      dom.testSpintaxBtn.addEventListener('click', () => {
        updateMessagePreview();
      });
    }

    // Upload e remoção de Anexo de Mídia
    if (dom.selectAttachmentBtn && dom.attachmentInput) {
      dom.selectAttachmentBtn.addEventListener('click', () => {
        dom.attachmentInput.click();
      });

      dom.attachmentInput.addEventListener('change', async (e) => {
        if (!e.target.files || e.target.files.length === 0) return;
        const file = e.target.files[0];
        const formData = new FormData();
        formData.append('file', file);

        appendLog(`[INFO] Enviando anexo '${file.name}' para a campanha...`);
        try {
          const res = await fetch('/api/attachments/upload', {
            method: 'POST',
            body: formData,
          });
          const data = await res.json();
          if (res.ok && data.success) {
            state.attachmentPath = data.attachment_path;
            state.attachmentFilename = data.filename;
            if (dom.attachmentName) dom.attachmentName.textContent = `📎 ${data.filename}`;
            if (dom.removeAttachmentBtn) dom.removeAttachmentBtn.classList.remove('hidden');
            appendLog(`[SUCESSO] Anexo '${data.filename}' pronto para envio.`);
          } else {
            alert(data.detail || 'Falha ao enviar anexo.');
          }
        } catch (err) {
          appendLog(`[ERRO] Falha ao enviar anexo: ${err.message}`);
        }
      });
    }

    if (dom.removeAttachmentBtn) {
      dom.removeAttachmentBtn.addEventListener('click', () => {
        state.attachmentPath = null;
        state.attachmentFilename = null;
        if (dom.attachmentInput) dom.attachmentInput.value = '';
        if (dom.attachmentName) dom.attachmentName.textContent = 'Nenhum arquivo anexado';
        dom.removeAttachmentBtn.classList.add('hidden');
        appendLog('[INFO] Anexo removido da campanha.');
      });
    }
  }

  function insertAtCursor(textarea, text) {
    if (!textarea) return;
    const start = textarea.selectionStart;
    const end = textarea.selectionEnd;
    const val = textarea.value;
    textarea.value = val.substring(0, start) + text + val.substring(end);
    textarea.selectionStart = textarea.selectionEnd = start + text.length;
    textarea.focus();
  }

  function appendLog(msg) {
    if (!dom.logTerminal) return;
    const div = document.createElement('div');
    const isSuccess = msg.includes('SUCESSO') || msg.includes('[SUCCESS]');
    const isError = msg.includes('ERRO') || msg.includes('[ERROR]');
    const isWarn = msg.includes('AVISO') || msg.includes('[WARNING]');
    div.className = 'log-line ' + (isSuccess ? 'log-success' : isError ? 'log-error' : isWarn ? 'log-warning' : 'log-info');
    div.textContent = `[${new Date().toLocaleTimeString()}] ${msg}`;
    dom.logTerminal.appendChild(div);
    dom.logTerminal.scrollTop = dom.logTerminal.scrollHeight;
  }

  function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  function debounce(fn, wait) {
    let timeout;
    return function (...args) {
      clearTimeout(timeout);
      timeout = setTimeout(() => fn.apply(this, args), wait);
    };
  }

  // ============================================================================
  // Inicialização
  // ============================================================================
  async function init() {
    setupNavigation();
    setupIngestionEvents();
    setupEditorEvents();
    setupQueueControls();
    setupExportButtons();
    setupSessionControls();
    setupTelemetrySSE();

    // Consulta contatos já carregados no backend (inicia limpo se não houver contatos)
    try {
      const res = await fetch('/api/contacts');
      if (res.ok) {
        const data = await res.json();
        if (data.contacts && data.contacts.length > 0) {
          setIngestedContacts(data.contacts, data.metrics || {});
        } else {
          updateMetricsView();
          applyTableFilters();
          updateMessagePreview();
        }
      }
    } catch (e) {
      console.debug('Servidor local offline ou iniciando...', e);
    }

    appendLog('[OK] WhatsApp Sender Engine M4 — Telemetria, Monitoramento e Relatórios pronto.');
  }

  document.addEventListener('DOMContentLoaded', init);
})();
