/* ─── Global State ──────────────────────────────────────────────────── */
const state = {
  leads: [],
  leadId: null,
  callId: null,
  selectedSlot: null,

  // Capabilities from backend
  sttConfigured: false,
  ttsConfigured: false,
  voices: [],

  // Live call state machine: 'idle' | 'starting' | 'listening' | 'processing' | 'speaking'
  callActive: false,
  callState: 'idle',
  callSeq: 0,
  muted: false,
  callStartedAt: 0,
  callTimerId: null,

  // Persistent Web Audio & Mic resources for active call
  micStream: null,
  audioCtx: null,
  micSource: null,
  micAnalyser: null,
  ttsSource: null,
  ttsAnalyser: null,
  activeRecorder: null,
  activeAbort: null,
  vadTimer: null,
  speechRecognition: null,
  browserFallbackTtsTimer: null,
  liveAudioLevel: 0,

  // One-shot clip & text flags
  clipRecording: false,
  clipRecorder: null,
  sending: false,
  startingSession: false,
  orbRafId: null,
};

const $ = (id) => document.getElementById(id);

/* ─── Utilities ─────────────────────────────────────────────────────── */
function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]),
  );
}

function showToast(message) {
  const el = $('toast');
  el.textContent = message;
  el.classList.add('show');
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => el.classList.remove('show'), 3600);
}

async function api(path, options = {}) {
  const headers = {
    ...(options.body && !(options.body instanceof FormData)
      ? { 'Content-Type': 'application/json' }
      : {}),
    ...(options.headers || {}),
  };
  const response = await fetch(path, { ...options, headers });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || `Request failed (${response.status})`);
  return data;
}

function pickSupportedRecorderMime() {
  const candidates = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg;codecs=opus', ''];
  if (typeof MediaRecorder === 'undefined' || typeof MediaRecorder.isTypeSupported !== 'function') {
    return { mimeType: '', ext: '.webm' };
  }
  for (const mime of candidates) {
    if (!mime || MediaRecorder.isTypeSupported(mime)) {
      const ext = mime.includes('mp4') ? '.mp4' : mime.includes('ogg') ? '.ogg' : '.webm';
      return { mimeType: mime, ext };
    }
  }
  return { mimeType: '', ext: '.webm' };
}

function base64ToArrayBuffer(b64) {
  const binary = atob(b64);
  const len = binary.length;
  const bytes = new Uint8Array(len);
  for (let i = 0; i < len; i++) bytes[i] = binary.charCodeAt(i);
  return bytes.buffer;
}

function setCaption(htmlText) {
  $('liveCaption').innerHTML = htmlText;
}

/* ─── Animated Voice Orb Visualizer (Canvas 60fps) ──────────────────── */
function startOrbRenderer() {
  if (state.orbRafId) return;
  const canvas = $('voiceOrbCanvas');
  const ctx = canvas.getContext('2d');
  const W = canvas.width;
  const H = canvas.height;
  const cx = W / 2;
  const cy = H / 2;

  const micBuf = new Uint8Array(128);
  const ttsBuf = new Uint8Array(128);
  let phase = 0;
  let smoothAmp = 0;

  function sampleAnalyser(analyser, buf) {
    if (!analyser) return 0;
    analyser.getByteFrequencyData(buf);
    let sum = 0;
    const count = Math.min(buf.length, 48);
    for (let i = 0; i < count; i++) sum += buf[i];
    return Math.min(1, sum / (count * 125));
  }

  function frame() {
    phase += 0.038;
    let targetAmp = 0.06;

    if (state.callState === 'listening' && !state.muted) {
      targetAmp = Math.max(0.14, sampleAnalyser(state.micAnalyser, micBuf), state.liveAudioLevel * 2.4);
    } else if (state.callState === 'speaking') {
      const ttsAmp = sampleAnalyser(state.ttsAnalyser, ttsBuf);
      targetAmp = ttsAmp > 0.01 ? Math.max(0.18, ttsAmp * 1.15) : 0.24 + Math.sin(phase * 3.1) * 0.14;
    } else if (state.callState === 'processing' || state.callState === 'starting') {
      targetAmp = 0.18 + Math.sin(phase * 2.4) * 0.06;
    }

    smoothAmp += (targetAmp - smoothAmp) * 0.22;

    ctx.clearRect(0, 0, W, H);

    const palettes = {
      idle: ['#6366f1', '#4f46e5', 'rgba(99, 102, 241, 0.28)'],
      starting: ['#818cf8', '#6366f1', 'rgba(129, 140, 248, 0.35)'],
      listening: ['#22d3ee', '#10b981', 'rgba(34, 211, 238, 0.38)'],
      processing: ['#f59e0b', '#a855f7', 'rgba(245, 158, 11, 0.35)'],
      speaking: ['#a78bfa', '#6366f1', 'rgba(167, 139, 250, 0.44)'],
    };
    const [c1, c2, glow] = state.muted && state.callActive
      ? ['#64748b', '#475569', 'rgba(100, 116, 139, 0.22)']
      : palettes[state.callState] || palettes.idle;

    const baseR = 72 + smoothAmp * 26;

    // Outer ambient halo
    const halo = ctx.createRadialGradient(cx, cy, baseR * 0.35, cx, cy, baseR * 1.75);
    halo.addColorStop(0, glow);
    halo.addColorStop(1, 'rgba(11, 17, 33, 0)');
    ctx.fillStyle = halo;
    ctx.beginPath();
    ctx.arc(cx, cy, baseR * 1.75, 0, Math.PI * 2);
    ctx.fill();

    // Two organic harmonic waveform rings
    for (let ring = 0; ring < 2; ring++) {
      ctx.beginPath();
      const points = 72;
      const ringOffset = ring * 10;
      const speed = ring === 0 ? phase : -phase * 1.3;
      const amp = (4 + smoothAmp * 18) * (ring === 0 ? 1 : 0.72);
      for (let i = 0; i <= points; i++) {
        const a = (i / points) * Math.PI * 2;
        const wobble =
          Math.sin(a * 3 + speed * 2) * amp * 0.55 +
          Math.cos(a * 5 - speed * 1.5) * amp * 0.45;
        const r = baseR + ringOffset + wobble;
        const x = cx + Math.cos(a) * r;
        const y = cy + Math.sin(a) * r;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.closePath();
      ctx.strokeStyle = ring === 0 ? c1 : c2;
      ctx.lineWidth = ring === 0 ? 2.6 : 1.5;
      ctx.globalAlpha = ring === 0 ? 0.72 : 0.42;
      ctx.stroke();
    }
    ctx.globalAlpha = 1;

    // Processing rotating arc
    if (state.callState === 'processing' || state.callState === 'starting') {
      ctx.beginPath();
      ctx.arc(cx, cy, baseR + 18, phase * 2.2, phase * 2.2 + Math.PI * 0.85);
      ctx.strokeStyle = '#fbbf24';
      ctx.lineWidth = 3.2;
      ctx.lineCap = 'round';
      ctx.stroke();
    }

    // Core luminous orb
    const coreGrad = ctx.createRadialGradient(cx - 18, cy - 22, 8, cx, cy, baseR);
    coreGrad.addColorStop(0, '#ffffff');
    coreGrad.addColorStop(0.24, c1);
    coreGrad.addColorStop(0.75, c2);
    coreGrad.addColorStop(1, 'rgba(15, 23, 42, 0.92)');
    ctx.fillStyle = coreGrad;
    ctx.beginPath();
    ctx.arc(cx, cy, baseR * 0.86, 0, Math.PI * 2);
    ctx.fill();

    state.orbRafId = requestAnimationFrame(frame);
  }
  state.orbRafId = requestAnimationFrame(frame);
}

/* ─── Call UI State Synchronizer ───────────────────────────────────── */
function setCallStageState(nextState, centerText, badgeText) {
  state.callState = nextState;
  $('callStage').dataset.state = nextState;
  $('orbCenterLabel').textContent = state.muted && state.callActive ? 'MUTED' : centerText;
  $('callStateText').textContent = state.muted && state.callActive ? 'MIC MUTED' : badgeText;

  const chip = $('voiceChip');
  if (state.callActive) {
    chip.classList.add('live');
    chip.innerHTML = '<i></i> LIVE CALL';
  } else {
    chip.classList.remove('live');
    chip.innerHTML = '<i></i> READY';
  }

  $('startVoiceCallBtn').hidden = state.callActive;
  $('activeCallBar').hidden = !state.callActive;

  // Update Interrupt / Send Now button label dynamically
  if (nextState === 'speaking') {
    $('interruptLabel').textContent = 'Interrupt (Space)';
    $('interruptCallBtn').disabled = false;
  } else if (nextState === 'listening') {
    $('interruptLabel').textContent = 'Send Now (Space)';
    $('interruptCallBtn').disabled = false;
  } else {
    $('interruptLabel').textContent = 'Interrupt';
    $('interruptCallBtn').disabled = true;
  }
}

function startCallTimer() {
  clearInterval(state.callTimerId);
  state.callStartedAt = Date.now();
  $('callTimer').textContent = '00:00';
  state.callTimerId = setInterval(() => {
    const secs = Math.floor((Date.now() - state.callStartedAt) / 1000);
    const m = String(Math.floor(secs / 60)).padStart(2, '0');
    const s = String(secs % 60).padStart(2, '0');
    $('callTimer').textContent = `${m}:${s}`;
  }, 1000);
}

function stopCallTimer() {
  clearInterval(state.callTimerId);
  state.callTimerId = null;
  $('callTimer').textContent = '00:00';
}

/* ─── Health, Voices & Knowledge Docs ───────────────────────────────── */
async function loadCapabilities() {
  try {
    const [health, voiceInfo] = await Promise.all([
      api('/api/health'),
      api('/api/voice/voices'),
    ]);
    state.sttConfigured = Boolean(voiceInfo.stt_configured);
    state.ttsConfigured = Boolean(voiceInfo.tts_configured);
    state.voices = voiceInfo.voices || [];

    const voiceSelect = $('voiceSelect');
    if (state.voices.length) {
      voiceSelect.innerHTML =
        '<option value="">Auto (Best for Language)</option>' +
        state.voices.map((v) => `<option value="${escapeHtml(v.id)}">${escapeHtml(v.name)}</option>`).join('');
    } else {
      voiceSelect.innerHTML = '<option value="">Browser Speech</option>';
    }

    const sttSelect = $('sttEngineSelect');
    if (!state.sttConfigured) {
      sttSelect.value = 'browser';
      sttSelect.querySelector('option[value="auto"]').textContent = 'Browser Speech (Whisper N/A)';
    } else {
      sttSelect.value = 'auto';
      sttSelect.querySelector('option[value="auto"]').textContent = 'Local Whisper (Fast)';
    }

    const caps = [];
    caps.push(state.sttConfigured ? 'Whisper STT' : 'Browser STT');
    caps.push(state.ttsConfigured ? 'Local Voice' : 'Browser TTS');
    if (health.gemini_configured) caps.push(`Gemini (${health.gemini_model})`);
    else if (health.local_llm_reachable) caps.push('Local LLM');
    $('sidebarCapabilities').textContent = caps.join(' · ');
    $('healthPill').innerHTML = `<i></i> ${escapeHtml(caps.slice(0, 2).join(' · ').toUpperCase())}`;

    updateGeminiPill(Boolean(health.gemini_configured), health.gemini_model || 'gemini-3.1-flash-lite');
  } catch (_) {
    $('sidebarCapabilities').textContent = 'Local workflow active';
  }
}

function updateGeminiPill(connected, model) {
  const btn = $('geminiStatusBtn');
  if (!btn) return;
  btn.classList.toggle('connected', connected);
  btn.textContent = connected ? `✦ Gemini · ${model}` : '✦ Connect Gemini AI';
  const select = $('geminiModelSelect');
  if (select && [...select.options].some((o) => o.value === model)) {
    select.value = model;
  }
}

async function loadKnowledgeDocuments() {
  try {
    const res = await api('/api/knowledge/documents');
    const docs = res.documents || [];
    if (!docs.length) {
      $('knowledgeResults').innerHTML = '<span class="muted-empty">No knowledge files indexed in knowledge_base/.</span>';
      return;
    }
    $('knowledgeResults').innerHTML = docs
      .map(
        (doc) => `
      <div class="knowledge-source" data-source="${escapeHtml(doc.source)}">
        <span class="source-icon">${escapeHtml(doc.source.split('.').pop().toUpperCase())}</span>
        <div>
          <strong>${escapeHtml(doc.source)}</strong>
          <small>${doc.chunks} indexed passage${doc.chunks === 1 ? '' : 's'} · Click to search</small>
        </div>
        <span class="source-state">LOADED</span>
      </div>`,
      )
      .join('');
    $('knowledgeResults').querySelectorAll('.knowledge-source').forEach((card) => {
      card.addEventListener('click', () => {
        const src = card.dataset.source.replace(/\.[^.]+$/, '').replaceAll('_', ' ');
        $('knowledgeQuery').value = src === 'product faq' ? 'SalesPilot product overview' : 'pricing qualification demo';
        $('knowledgeSearchForm').dispatchEvent(new Event('submit', { cancelable: true }));
      });
    });
  } catch (_) {
    // Keep silent if endpoint unavailable
  }
}

/* ─── Lead Management & Transcript Hydration ────────────────────────── */
function setSelectedLead(id) {
  if (state.callActive) endLiveCall();
  state.leadId = id;
  state.callId = null;
  state.selectedSlot = null;
  $('leadSelect').value = id || '';
  $('callStatus').textContent = 'No active session';
  $('transcript').innerHTML =
    '<div class="empty-transcript"><div class="empty-wave">〰</div>' +
    '<strong>Your conversation starts here</strong>' +
    '<span>Press Start Live Call above or type a customer message below.</span></div>';

  // Highlight active row in CRM table
  document.querySelectorAll('#leadTable .lead-row').forEach((tr) => {
    tr.classList.toggle('selected-row', tr.dataset.leadId === id);
  });
  renderLeadDetail();
}

async function loadLeads() {
  state.leads = await api('/api/leads');
  const select = $('leadSelect');
  select.innerHTML = state.leads
    .map(
      (l) =>
        `<option value="${escapeHtml(l.id)}">${escapeHtml(l.name)}${l.company ? ' · ' + escapeHtml(l.company) : ''}</option>`,
    )
    .join('');

  $('leadCount').textContent = `${state.leads.length} lead${state.leads.length === 1 ? '' : 's'}`;
  $('leadTable').innerHTML = state.leads.length
    ? state.leads
        .map(
          (l) => `
    <tr class="lead-row ${l.id === state.leadId ? 'selected-row' : ''}" data-lead-id="${escapeHtml(l.id)}">
      <td>
        <div class="lead-cell">
          <span class="lead-avatar">${escapeHtml((l.name || '?').charAt(0).toUpperCase())}</span>
          <div>
            <div class="lead-name">${escapeHtml(l.name)}</div>
            <div class="lead-email">${escapeHtml(l.email || l.phone || 'Synthetic demo profile')}</div>
          </div>
        </div>
      </td>
      <td>${escapeHtml(l.company || '—')}</td>
      <td>${escapeHtml(l.requirement || 'Not captured')}</td>
      <td><span class="score-mini">${l.score}/100</span></td>
      <td><span class="status-pill ${escapeHtml(l.status)}">${escapeHtml(l.status)}</span></td>
      <td>${escapeHtml(new Date(l.updated_at).toLocaleDateString())}</td>
    </tr>`,
        )
        .join('')
    : '<tr><td colspan="6" class="table-empty">No leads found.</td></tr>';

  document.querySelectorAll('#leadTable .lead-row').forEach((row) => {
    row.addEventListener('click', () => {
      if (row.dataset.leadId !== state.leadId) {
        setSelectedLead(row.dataset.leadId);
        $('voice-workspace').scrollIntoView({ behavior: 'smooth' });
      }
    });
  });

  if (!state.leadId || !state.leads.some((l) => l.id === state.leadId)) {
    setSelectedLead(state.leads[0]?.id || null);
  } else {
    $('leadSelect').value = state.leadId;
  }
}

async function loadStats() {
  const s = await api('/api/dashboard/stats');
  $('statLeads').textContent = s.total_leads;
  $('statHot').textContent = s.hot_leads;
  $('statAppointments').textContent = s.appointments_booked;
  $('statHandoffs').textContent = s.human_handoffs;
  $('insightAvgScore').textContent = `${s.avg_score ?? 0} / 100`;
  $('insightHotRate').textContent = `${s.hot_rate_pct ?? 0}% (${s.hot_leads}/${s.total_leads})`;
  const sb = s.sentiment_breakdown || { positive: 0, neutral: 0, negative: 0 };
  $('insightSentiment').textContent = `${sb.positive} pos · ${sb.neutral} neu · ${sb.negative} neg`;
  const reqs = s.top_requirements || [];
  $('insightTopNeeds').innerHTML = reqs.length
    ? reqs.map((r) => `<span class="insight-chip">${escapeHtml(r.requirement)} (${r.count})</span>`).join('')
    : '<span class="muted-empty">Capturing demand signals…</span>';
}

async function renderLeadDetail() {
  if (!state.leadId) {
    $('leadScore').textContent = '0';
    $('ringScore').textContent = '0';
    $('leadStatus').textContent = 'COLD';
    $('evidenceTable').innerHTML =
      '<tr><td colspan="4" class="table-empty">Create or select a lead to begin.</td></tr>';
    $('scoreBreakdown').innerHTML = '<div class="muted-empty">No lead selected.</div>';
    return;
  }
  try {
    const data = await api(`/api/leads/${encodeURIComponent(state.leadId)}`);
    const score = data.score;
    $('leadScore').textContent = score;
    $('ringScore').textContent = score;
    $('leadStatus').textContent = data.status.toUpperCase();
    $('leadStatus').className = `lead-status ${data.status}`;
    $('scoreProgress').style.width = `${score}%`;
    $('scoreRing').style.background = `conic-gradient(#4f67f5 ${score * 3.6}deg, #e2e8f0 ${score * 3.6}deg)`;

    $('scoreBreakdown').innerHTML = data.score_breakdown
      .map(
        (item) => `
      <div class="score-item">
        <span class="score-item-title">${escapeHtml(item.criterion)}</span>
        <span class="score-item-points">${item.points}/${item.maximum}</span>
        <span class="score-item-reason">${escapeHtml(item.reason)}</span>
        <span class="score-item-track"><span style="width:${(item.points / item.maximum) * 100}%"></span></span>
      </div>`,
      )
      .join('');

    const missing = data.score_breakdown.find((x) => x.points < x.maximum);
    $('nextStep').textContent =
      score >= 75
        ? 'Lead is sales-qualified. Offer a 30-minute demo slot and confirm next steps.'
        : missing
          ? `Collect missing detail: ${missing.criterion.toLowerCase()}.`
          : 'Review the conversation and confirm an appointment.';

    $('evidenceCount').textContent = `${data.evidence.length} fact${data.evidence.length === 1 ? '' : 's'}`;
    $('evidenceTable').innerHTML = data.evidence.length
      ? data.evidence
          .map(
            (ev) => `
          <tr>
            <td class="fact-field">${escapeHtml(ev.field.replaceAll('_', ' '))}</td>
            <td class="fact-value">${escapeHtml(formatEvidenceValue(ev.field, ev.value))}</td>
            <td class="quote">“${escapeHtml(ev.quote)}”</td>
            <td><span class="verified-chip">VERIFIED</span></td>
          </tr>`,
          )
          .join('')
      : '<tr><td colspan="4" class="table-empty">No verified facts yet. Start a conversation to capture evidence.</td></tr>';

    // Hydrate latest call transcript if we haven't started one yet in this view
    if (!state.callId && data.calls?.length && data.latest_messages?.length) {
      const latestCall = data.calls[0];
      state.callId = latestCall.id;
      $('callStatus').textContent = `Session ${latestCall.id.slice(-6)}`;
      $('sentimentChip').textContent = (latestCall.sentiment || 'neutral').toUpperCase();
      $('sentimentChip').className = `sentiment-chip ${latestCall.sentiment || 'neutral'}`;
      $('callSummary').textContent = latestCall.summary || 'Conversation started; collecting qualification facts.';
      $('transcript').innerHTML = '';
      data.latest_messages.forEach((m) => {
        const timeStr = new Date(m.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        addMessage(m.role, m.content, timeStr);
      });
    } else if (!state.callId) {
      $('callSummary').textContent = 'No call summary yet. Start a conversation to generate a structured summary.';
    }

    renderAppointments(data.appointments);
  } catch (err) {
    showToast(err.message);
  }
}

function formatEvidenceValue(field, value) {
  if (field === 'budget_amount') return `₹${Number(value).toLocaleString('en-IN')}`;
  if (field === 'timeline_days') return `${value} days`;
  if (field === 'decision_maker') return value === 'True' || value === '1' ? 'Yes' : 'No';
  return value;
}

function renderAppointments(items) {
  const future = (items || [])
    .filter((a) => a.status === 'booked')
    .sort((a, b) => a.start_time.localeCompare(b.start_time));
  $('upcomingAppointments').innerHTML = future.length
    ? future
        .slice(0, 4)
        .map(
          (a) => `
        <div class="appointment-row">
          <div>
            <strong>Product demonstration</strong>
            <small>${escapeHtml(new Date(a.start_time).toLocaleString())}</small>
          </div>
          <div class="appointment-actions">
            <span class="appointment-date">BOOKED</span>
            <button class="cancel-appt-btn" data-appt-id="${escapeHtml(a.id)}">Cancel</button>
          </div>
        </div>`,
        )
        .join('')
    : '<span class="muted-empty">No appointments booked for this lead yet.</span>';

  $('upcomingAppointments').querySelectorAll('.cancel-appt-btn').forEach((btn) => {
    btn.addEventListener('click', () => cancelAppointment(btn.dataset.apptId, btn));
  });
}

/* ─── Transcript Rendering ─────────────────────────────────────────── */
function addMessage(role, content, timeLabel = 'Now') {
  const transcript = $('transcript');
  const empty = transcript.querySelector('.empty-transcript');
  if (empty) empty.remove();
  const bubble = document.createElement('div');
  bubble.className = `message ${role}`;
  const label = role === 'customer' ? 'CUSTOMER' : 'SALESPILOT AI';
  bubble.innerHTML =
    `<div class="message-meta"><span>${label}</span><span>${escapeHtml(timeLabel)}</span></div>` +
    `<div class="message-bubble">${escapeHtml(content).replaceAll('\n', '<br>')}</div>`;
  transcript.appendChild(bubble);
  transcript.scrollTop = transcript.scrollHeight;
}

/* ─── Manual Session & Text Chat ────────────────────────────────────── */
async function startNewSession() {
  if (state.startingSession) return null;
  if (!state.leadId) {
    showToast('Create or select a lead first.');
    return null;
  }
  state.startingSession = true;
  $('startCallButton').disabled = true;
  try {
    const lang = $('speechLanguage').value;
    const result = await api('/api/calls', {
      method: 'POST',
      body: JSON.stringify({ lead_id: state.leadId, language: lang }),
    });
    state.callId = result.id;
    $('callStatus').textContent = `Session ${result.id.slice(-6)}`;
    $('transcript').innerHTML = '';
    const leadObj = state.leads.find((l) => l.id === state.leadId);
    const firstName = leadObj?.name ? ` ${leadObj.name.split(' ')[0]}` : '';
    const greeting = lang.startsWith('hi')
      ? `Namaste${firstName}! Main SalesPilot AI hoon. Aaj aap apne business mein kaunsa workflow automate karna chahte hain?`
      : `Hello${firstName}! I’m SalesPilot, your AI sales assistant. What business challenge are you looking to solve today?`;
    addMessage('agent', greeting);
    return greeting;
  } catch (err) {
    showToast(err.message);
    return null;
  } finally {
    state.startingSession = false;
    $('startCallButton').disabled = false;
  }
}

async function applyChatResult(result) {
  state.callId = result.call_id;
  $('callStatus').textContent = `Session ${result.call_id.slice(-6)}`;
  addMessage('agent', result.response);
  $('sentimentChip').textContent = result.sentiment.toUpperCase();
  $('sentimentChip').className = `sentiment-chip ${result.sentiment}`;
  if (result.summary) {
    $('callSummary').textContent = result.summary;
  }
  const langLabel = result.detected_language === 'hi-IN' ? 'Hindi / Hinglish' : $('speechLanguage').selectedOptions[0].text;
  const modeLabel = result.response_mode === 'gemini_assisted' ? ' · Gemini AI' : result.response_mode === 'local_model_assisted' ? ' · Local LLM' : '';
  $('conversationLanguage').textContent = `${langLabel}${modeLabel}`;

  if (result.handoff_required) showToast(`Human handoff flagged: ${result.handoff_reason}`);
  else if (result.appointment_booked) showToast('Demo appointment booked!');
  else if (result.citations?.length) showToast(`Grounded in ${result.citations[0].source}`);

  await Promise.all([loadStats(), loadLeads(), renderLeadDetail()]);
  if (result.appointment_booked) {
    await loadAvailability();
  }
}

async function sendMessage(overrideText = null) {
  const input = $('messageInput');
  const message = (overrideText !== null ? overrideText : input.value).trim();
  if (!message) return;
  if (!state.leadId) return showToast('Create or select a lead first.');
  if (state.sending) return;

  state.sending = true;
  const btn = $('sendButton');
  btn.disabled = true;
  btn.textContent = 'Thinking…';

  try {
    addMessage('customer', message);
    if (overrideText === null) input.value = '';
    const result = await api('/api/agent/chat', {
      method: 'POST',
      body: JSON.stringify({
        lead_id: state.leadId,
        call_id: state.callId,
        message,
        language: $('speechLanguage').value,
      }),
    });
    await applyChatResult(result);

    if ($('speakToggle').checked) {
      const spoken = result.spoken_response || result.response;
      if (state.callActive) {
        const mySeq = state.callSeq;
        await playAgentAudio(spoken, null, result.detected_language || $('speechLanguage').value, mySeq);
      } else {
        await playTextOnce(spoken, result.detected_language || $('speechLanguage').value);
      }
    }
  } catch (err) {
    showToast(err.message);
  } finally {
    state.sending = false;
    btn.disabled = false;
    btn.innerHTML = 'Send message <span>→</span>';
  }
}

/* ─── Audio Playback (Local WAV via Web Audio + Browser Fallback) ───── */
function stopCurrentTts() {
  if (state.ttsSource) {
    try {
      state.ttsSource.onended = null;
      state.ttsSource.stop();
    } catch (_) {}
    state.ttsSource = null;
  }
  clearTimeout(state.browserFallbackTtsTimer);
  if ('speechSynthesis' in window) {
    try { window.speechSynthesis.cancel(); } catch (_) {}
  }
}

async function playTextOnce(text, language) {
  stopCurrentTts();
  if (state.ttsConfigured) {
    try {
      const resp = await fetch('/api/voice/tts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, voice: $('voiceSelect').value || null, language }),
      });
      if (resp.ok) {
        const buf = await resp.arrayBuffer();
        const ctx = new (window.AudioContext || window.webkitAudioContext)();
        const decoded = await ctx.decodeAudioData(buf);
        const src = ctx.createBufferSource();
        src.buffer = decoded;
        src.connect(ctx.destination);
        src.onended = () => ctx.close().catch(() => {});
        src.start();
        return;
      }
    } catch (_) {}
  }
  speakBrowserOnly(text, language);
}

function speakBrowserOnly(text, language, onDone) {
  if (!('speechSynthesis' in window)) {
    onDone?.();
    return;
  }
  try {
    window.speechSynthesis.cancel();
  } catch (_) {}
  const utter = new SpeechSynthesisUtterance(text);
  utter.lang = language || $('speechLanguage').value;
  utter.rate = 1.02;
  let settled = false;
  const finish = () => {
    if (settled) return;
    settled = true;
    clearTimeout(state.browserFallbackTtsTimer);
    onDone?.();
  };
  utter.onend = finish;
  utter.onerror = finish;
  // Watchdog in case Chrome/Safari drops onend
  state.browserFallbackTtsTimer = setTimeout(finish, Math.max(4500, text.length * 95));
  window.speechSynthesis.speak(utter);
}

async function playAgentAudio(spokenText, audioBase64, language, mySeq) {
  if (!state.callActive || state.callSeq !== mySeq) return;
  stopCurrentTts();

  if (!$('speakToggle').checked) {
    listenForNextTurn(mySeq);
    return;
  }

  setCallStageState('speaking', 'SPEAKING', 'SALESPILOT SPEAKING');
  setCaption(`<strong>SalesPilot:</strong> ${escapeHtml(spokenText)}`);

  let wavBuffer = null;
  if (audioBase64) {
    wavBuffer = base64ToArrayBuffer(audioBase64);
  } else if (state.ttsConfigured) {
    try {
      const controller = new AbortController();
      state.activeAbort = controller;
      const resp = await fetch('/api/voice/tts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          text: spokenText,
          voice: $('voiceSelect').value || null,
          language: language || $('speechLanguage').value,
        }),
        signal: controller.signal,
      });
      if (resp.ok) wavBuffer = await resp.arrayBuffer();
    } catch (_) {
      if (!state.callActive || state.callSeq !== mySeq) return;
    } finally {
      state.activeAbort = null;
    }
  }

  if (!state.callActive || state.callSeq !== mySeq) return;

  if (wavBuffer && state.audioCtx) {
    try {
      if (state.audioCtx.state === 'suspended') await state.audioCtx.resume();
      const decoded = await state.audioCtx.decodeAudioData(wavBuffer);
      if (!state.callActive || state.callSeq !== mySeq) return;

      const src = state.audioCtx.createBufferSource();
      src.buffer = decoded;
      if (!state.ttsAnalyser) {
        state.ttsAnalyser = state.audioCtx.createAnalyser();
        state.ttsAnalyser.fftSize = 256;
      }
      src.connect(state.ttsAnalyser);
      state.ttsAnalyser.connect(state.audioCtx.destination);
      state.ttsSource = src;

      // Optional auto barge-in monitor (for headphone users)
      let bargeCount = 0;
      const bargeBuf = new Uint8Array(2048);
      const bargeMonitor = setInterval(() => {
        if (!state.callActive || state.callSeq !== mySeq || state.callState !== 'speaking') {
          clearInterval(bargeMonitor);
          return;
        }
        if (!$('bargeInToggle').checked || state.muted || !state.micAnalyser) return;
        state.micAnalyser.getByteTimeDomainData(bargeBuf);
        let peak = 0;
        for (let i = 0; i < bargeBuf.length; i += 4) {
          peak = Math.max(peak, Math.abs(bargeBuf[i] - 128) / 128);
        }
        if (peak > 0.065) bargeCount += 1;
        else bargeCount = 0;
        if (bargeCount >= 4) {
          clearInterval(bargeMonitor);
          interruptAndListen();
        }
      }, 65);

      src.onended = () => {
        clearInterval(bargeMonitor);
        state.ttsSource = null;
        if (state.callActive && state.callSeq === mySeq) {
          listenForNextTurn(mySeq);
        }
      };
      src.start();
      return;
    } catch (_) {
      // Fallback to browser TTS if decode fails
    }
  }

  speakBrowserOnly(spokenText, language, () => {
    if (state.callActive && state.callSeq === mySeq) {
      listenForNextTurn(mySeq);
    }
  });
}

/* ─── Live Voice Call Loop (Zero Repeated Clicks!) ──────────────────── */
function stopListeningHardware() {
  clearInterval(state.vadTimer);
  state.vadTimer = null;
  state.liveAudioLevel = 0;

  if (state.activeRecorder && state.activeRecorder.state !== 'inactive') {
    try {
      state.activeRecorder._discard = true;
      state.activeRecorder.stop();
    } catch (_) {}
  }
  state.activeRecorder = null;

  if (state.speechRecognition) {
    try {
      state.speechRecognition._manualStop = true;
      state.speechRecognition.abort();
    } catch (_) {}
    state.speechRecognition = null;
  }
}

async function startLiveCall() {
  if (state.callActive || state.callState === 'starting') return;
  if (!state.leadId) return showToast('Create or select a lead first.');
  if (!navigator.mediaDevices?.getUserMedia) {
    return showToast('Microphone access is not available in this browser.');
  }

  const mySeq = ++state.callSeq;
  state.muted = false;
  $('muteCallBtn').classList.remove('muted');
  $('muteLabel').textContent = 'Mute';
  $('muteIcon').textContent = '🎙';

  state.callActive = true;
  setCallStageState('starting', 'CONNECTING', 'CONNECTING MIC');
  setCaption('Requesting microphone permission once for the whole call…');

  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    if (!state.callActive || state.callSeq !== mySeq) {
      stream.getTracks().forEach((t) => t.stop());
      return;
    }
    state.micStream = stream;
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    state.audioCtx = new AudioCtx();
    state.micSource = state.audioCtx.createMediaStreamSource(stream);
    state.micAnalyser = state.audioCtx.createAnalyser();
    state.micAnalyser.fftSize = 2048;
    state.micSource.connect(state.micAnalyser);

    startCallTimer();
    startOrbRenderer();

    // Ensure session exists and greet customer
    let greeting = null;
    if (!state.callId) {
      greeting = await startNewSession();
    } else {
      const leadObj = state.leads.find((l) => l.id === state.leadId);
      const firstName = leadObj?.name ? ` ${leadObj.name.split(' ')[0]}` : '';
      greeting = $('speechLanguage').value.startsWith('hi')
        ? `Haan${firstName}, bataiye main aapki kya madad kar sakta hoon?`
        : `Hi${firstName}, I’m listening — how can I help you next?`;
    }

    if (!state.callActive || state.callSeq !== mySeq) return;
    if (greeting && $('speakToggle').checked) {
      await playAgentAudio(greeting, null, $('speechLanguage').value, mySeq);
    } else {
      listenForNextTurn(mySeq);
    }
  } catch (err) {
    endLiveCall();
    showToast(`Could not start live call: ${err.message}`);
  }
}

function endLiveCall() {
  state.callSeq += 1;
  state.callActive = false;
  state.muted = false;

  if (state.activeAbort) {
    try { state.activeAbort.abort(); } catch (_) {}
    state.activeAbort = null;
  }
  stopCurrentTts();
  stopListeningHardware();

  if (state.micStream) {
    state.micStream.getTracks().forEach((t) => t.stop());
    state.micStream = null;
  }
  if (state.audioCtx) {
    state.audioCtx.close().catch(() => {});
    state.audioCtx = null;
    state.micSource = null;
    state.micAnalyser = null;
    state.ttsAnalyser = null;
  }

  stopCallTimer();
  setCallStageState('idle', 'TAP CALL', 'STANDBY');
  setCaption('Call ended. Press <strong>Start Live Call</strong> anytime to resume.');
}

function toggleMute() {
  if (!state.callActive) return;
  state.muted = !state.muted;
  if (state.micStream) {
    state.micStream.getAudioTracks().forEach((t) => { t.enabled = !state.muted; });
  }
  $('muteCallBtn').classList.toggle('muted', state.muted);
  $('muteLabel').textContent = state.muted ? 'Unmute' : 'Mute';
  $('muteIcon').textContent = state.muted ? '🔇' : '🎙';

  if (state.muted) {
    if (state.callState === 'listening') {
      state.callSeq += 1;
      stopListeningHardware();
      setCallStageState('listening', 'MUTED', 'MIC MUTED');
      setCaption('Microphone muted. Click <strong>Unmute</strong> when ready to speak.');
    }
  } else if (state.callState === 'listening') {
    const mySeq = ++state.callSeq;
    listenForNextTurn(mySeq);
  }
}

function interruptAndListen() {
  if (!state.callActive) return;
  if (state.callState === 'speaking') {
    const mySeq = ++state.callSeq;
    if (state.activeAbort) {
      try { state.activeAbort.abort(); } catch (_) {}
      state.activeAbort = null;
    }
    stopCurrentTts();
    if (state.muted) toggleMute();
    else listenForNextTurn(mySeq);
    return;
  }
  if (state.callState === 'listening') {
    // User pressed Send Now / Space while speaking -> stop recorder immediately and submit!
    if (state.activeRecorder && state.activeRecorder.state === 'recording') {
      clearInterval(state.vadTimer);
      state.vadTimer = null;
      state.activeRecorder._forceSubmit = true;
      state.activeRecorder.stop();
    } else if (state.speechRecognition) {
      state.speechRecognition.stop();
    }
  }
}

function listenForNextTurn(mySeq) {
  if (!state.callActive || state.callSeq !== mySeq) return;
  stopListeningHardware();

  if (state.muted) {
    setCallStageState('listening', 'MUTED', 'MIC MUTED');
    setCaption('Microphone muted. Click <strong>Unmute</strong> to speak.');
    return;
  }

  const engine = $('sttEngineSelect').value;
  const hasBrowserStt = Boolean(window.SpeechRecognition || window.webkitSpeechRecognition);
  if (engine === 'browser' && hasBrowserStt) {
    runBrowserSttTurn(mySeq);
  } else if (state.sttConfigured) {
    runWhisperVadTurn(mySeq);
  } else if (hasBrowserStt) {
    runBrowserSttTurn(mySeq);
  } else {
    endLiveCall();
    showToast('No speech recognition engine available. Enable Whisper or use Chrome/Edge.');
  }
}

function runWhisperVadTurn(mySeq) {
  if (!state.callActive || state.callSeq !== mySeq || !state.micStream || !state.micAnalyser) return;

  setCallStageState('listening', 'LISTENING', 'LISTENING');
  setCaption('Listening… speak naturally. I will reply automatically when you pause.');

  const { mimeType, ext } = pickSupportedRecorderMime();
  let recorder;
  try {
    recorder = mimeType
      ? new MediaRecorder(state.micStream, { mimeType })
      : new MediaRecorder(state.micStream);
  } catch (_) {
    recorder = new MediaRecorder(state.micStream);
  }

  const chunks = [];
  recorder._discard = false;
  recorder._forceSubmit = false;
  state.activeRecorder = recorder;

  const samples = new Uint8Array(state.micAnalyser.fftSize);
  let heardSpeech = false;
  let speechMs = 0;
  let silenceMs = 0;
  let noiseSamples = [];
  let threshold = 0.022;
  const startedAt = Date.now();

  recorder.ondataavailable = (ev) => {
    if (ev.data && ev.data.size > 0) chunks.push(ev.data);
  };

  recorder.onstop = async () => {
    clearInterval(state.vadTimer);
    state.vadTimer = null;
    state.liveAudioLevel = 0;
    if (state.activeRecorder === recorder) state.activeRecorder = null;

    if (!state.callActive || state.callSeq !== mySeq || recorder._discard) return;
    if (!heardSpeech && !recorder._forceSubmit) {
      // Silently recycle segment without network call or toast
      runWhisperVadTurn(mySeq);
      return;
    }

    const blob = new Blob(chunks, { type: recorder.mimeType || mimeType || 'audio/webm' });
    if (blob.size < 800) {
      runWhisperVadTurn(mySeq);
      return;
    }

    setCallStageState('processing', 'THINKING', 'UNDERSTANDING');
    setCaption('Processing your voice…');

    const form = new FormData();
    form.append('audio', blob, `turn${ext}`);
    form.append('lead_id', state.leadId);
    if (state.callId) form.append('call_id', state.callId);
    form.append('language', $('speechLanguage').value);
    if ($('voiceSelect').value) form.append('voice', $('voiceSelect').value);
    form.append('tts', $('speakToggle').checked ? 'true' : 'false');

    const controller = new AbortController();
    state.activeAbort = controller;
    try {
      const resp = await fetch('/api/voice/turn', { method: 'POST', body: form, signal: controller.signal });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) throw new Error(data.detail || `Voice turn failed (${resp.status})`);
      if (!state.callActive || state.callSeq !== mySeq) return;

      if (data.empty || !data.transcript) {
        setCaption('Didn’t catch any words — go ahead, I’m listening…');
        listenForNextTurn(mySeq);
        return;
      }

      addMessage('customer', data.transcript);
      setCaption(`<strong>You:</strong> “${escapeHtml(data.transcript)}”`);
      await applyChatResult(data.chat);

      if (!state.callActive || state.callSeq !== mySeq) return;
      const spoken = data.chat.spoken_response || data.chat.response;
      await playAgentAudio(
        spoken,
        data.audio_base64 || null,
        data.chat.detected_language || $('speechLanguage').value,
        mySeq,
      );
    } catch (err) {
      if (err.name === 'AbortError' || !state.callActive || state.callSeq !== mySeq) return;
      showToast(err.message);
      listenForNextTurn(mySeq);
    } finally {
      if (state.activeAbort === controller) state.activeAbort = null;
    }
  };

  recorder.start(200);

  state.vadTimer = setInterval(() => {
    if (!state.callActive || state.callSeq !== mySeq || recorder.state !== 'recording') {
      clearInterval(state.vadTimer);
      return;
    }
    state.micAnalyser.getByteTimeDomainData(samples);
    let peak = 0;
    for (let i = 0; i < samples.length; i += 2) {
      peak = Math.max(peak, Math.abs(samples[i] - 128) / 128);
    }
    state.liveAudioLevel = peak;
    const elapsed = Date.now() - startedAt;

    // Calibrate room noise floor in the first 250ms
    if (elapsed < 260 && !heardSpeech) {
      noiseSamples.push(peak);
      const avgNoise = noiseSamples.reduce((a, b) => a + b, 0) / noiseSamples.length;
      threshold = Math.min(0.055, Math.max(0.02, avgNoise * 2.2));
      return;
    }

    if (peak > threshold) {
      heardSpeech = true;
      speechMs += 60;
      silenceMs = 0;
      setCaption('Hearing you… keep going.');
    } else if (heardSpeech) {
      silenceMs += 60;
    }

    // Recycle silent clips every 4.5s so Whisper never processes dead air
    if (!heardSpeech && elapsed >= 4500) {
      recorder._discard = true;
      recorder.stop();
      setTimeout(() => runWhisperVadTurn(mySeq), 20);
      return;
    }

    if ((heardSpeech && speechMs >= 240 && silenceMs >= 950) || elapsed >= 20000) {
      recorder.stop();
    }
  }, 60);
}

function runBrowserSttTurn(mySeq) {
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!Recognition) {
    if (state.sttConfigured) {
      $('sttEngineSelect').value = 'auto';
      runWhisperVadTurn(mySeq);
    }
    return;
  }

  setCallStageState('listening', 'LISTENING', 'LIVE CAPTIONS');
  setCaption('Listening with live captions… speak naturally.');

  const recognition = new Recognition();
  state.speechRecognition = recognition;
  recognition._manualStop = false;
  recognition.lang = $('speechLanguage').value;
  recognition.continuous = false;
  recognition.interimResults = true;
  recognition.maxAlternatives = 1;

  let finalTranscript = '';
  let fallbackToWhisper = false;

  // Keep mic orb reactive via Web Audio micAnalyser
  const samples = new Uint8Array(state.micAnalyser?.fftSize || 1024);
  state.vadTimer = setInterval(() => {
    if (!state.micAnalyser) return;
    state.micAnalyser.getByteTimeDomainData(samples);
    let peak = 0;
    for (let i = 0; i < samples.length; i += 4) peak = Math.max(peak, Math.abs(samples[i] - 128) / 128);
    state.liveAudioLevel = peak;
  }, 60);

  recognition.onresult = (ev) => {
    let interim = '';
    for (let i = ev.resultIndex; i < ev.results.length; i++) {
      const t = ev.results[i][0].transcript;
      if (ev.results[i].isFinal) finalTranscript += t + ' ';
      else interim += t;
    }
    const text = `${finalTranscript}${interim}`.trim();
    if (text) setCaption(`<strong>You:</strong> ${escapeHtml(text)}`);
  };

  recognition.onerror = (ev) => {
    if (ev.error === 'network' || ev.error === 'service-not-allowed') {
      fallbackToWhisper = true;
    } else if (ev.error !== 'aborted' && ev.error !== 'no-speech') {
      showToast(`Speech recognition note: ${ev.error}`);
    }
  };

  recognition.onend = async () => {
    clearInterval(state.vadTimer);
    state.vadTimer = null;
    state.liveAudioLevel = 0;
    if (state.speechRecognition === recognition) state.speechRecognition = null;

    if (!state.callActive || state.callSeq !== mySeq || recognition._manualStop) return;

    if (fallbackToWhisper && state.sttConfigured) {
      showToast('Browser speech service unavailable — switched seamlessly to Local Whisper.');
      $('sttEngineSelect').value = 'auto';
      runWhisperVadTurn(mySeq);
      return;
    }

    const clean = finalTranscript.trim();
    if (!clean) {
      // Auto-restart listening instead of dying on no-speech!
      runBrowserSttTurn(mySeq);
      return;
    }

    setCallStageState('processing', 'THINKING', 'RESPONDING');
    addMessage('customer', clean);
    try {
      const result = await api('/api/agent/chat', {
        method: 'POST',
        body: JSON.stringify({
          lead_id: state.leadId,
          call_id: state.callId,
          message: clean,
          language: $('speechLanguage').value,
        }),
      });
      if (!state.callActive || state.callSeq !== mySeq) return;
      await applyChatResult(result);
      const spoken = result.spoken_response || result.response;
      await playAgentAudio(spoken, null, result.detected_language || $('speechLanguage').value, mySeq);
    } catch (err) {
      showToast(err.message);
      listenForNextTurn(mySeq);
    }
  };

  try {
    recognition.start();
  } catch (_) {
    if (state.sttConfigured) runWhisperVadTurn(mySeq);
  }
}

/* ─── One-Shot Voice Clip (Outside Live Call) ──────────────────────── */
async function toggleOneShotRecording() {
  if (state.callActive) {
    return showToast('You are already in a live voice call.');
  }
  if (state.clipRecording) {
    state.clipRecorder?.stop();
    return;
  }
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
    return showToast('Audio recording is not supported in this browser.');
  }
  const btn = $('recordButton');
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const { mimeType, ext } = pickSupportedRecorderMime();
    const recorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream);
    const chunks = [];
    state.clipRecorder = recorder;
    state.clipRecording = true;

    btn.innerHTML = '■ <span>Stop &amp; Transcribe</span>';
    btn.classList.add('voice-active');

    recorder.ondataavailable = (ev) => {
      if (ev.data.size) chunks.push(ev.data);
    };
    recorder.onstop = async () => {
      state.clipRecording = false;
      state.clipRecorder = null;
      stream.getTracks().forEach((t) => t.stop());
      btn.innerHTML = '◌ <span>Transcribing…</span>';
      btn.classList.remove('voice-active');
      btn.disabled = true;

      try {
        const blob = new Blob(chunks, { type: recorder.mimeType || mimeType || 'audio/webm' });
        const form = new FormData();
        form.append('audio', blob, `clip${ext}`);
        form.append('language', $('speechLanguage').value);
        const res = await api('/api/voice/transcribe', { method: 'POST', body: form });
        $('messageInput').value = res.transcript;
        if ($('autoSendToggle').checked) await sendMessage();
        else showToast('Transcript ready — review or press Send.');
      } catch (err) {
        showToast(err.message);
      } finally {
        btn.disabled = false;
        btn.innerHTML = '◌ <span>One-shot Voice Clip</span>';
      }
    };
    recorder.start(200);
  } catch (err) {
    state.clipRecording = false;
    btn.classList.remove('voice-active');
    showToast(`Microphone error: ${err.message}`);
  }
}

/* ─── Lead Creation, Appointments & Knowledge Base ──────────────────── */
async function createLead(event) {
  event.preventDefault();
  const formEl = event.currentTarget;
  const form = new FormData(formEl);
  const payload = Object.fromEntries(form.entries());
  const btn = formEl.querySelector('button[type="submit"]');
  btn.disabled = true;
  try {
    const lead = await api('/api/leads', { method: 'POST', body: JSON.stringify(payload) });
    $('createLeadMessage').style.color = '#129466';
    $('createLeadMessage').textContent = `Created ${lead.name}.`;
    formEl.reset();
    await loadLeads();
    setSelectedLead(lead.id);
    await loadStats();
    showToast(`Switched workspace to ${lead.name}.`);
  } catch (err) {
    $('createLeadMessage').style.color = '#dc3f59';
    $('createLeadMessage').textContent = err.message;
    showToast(err.message);
  } finally {
    btn.disabled = false;
  }
}

async function loadAvailability() {
  const value = $('bookingDate').value;
  if (!value) return;
  state.selectedSlot = null;
  $('bookButton').disabled = true;
  $('slotGrid').innerHTML = '<span class="muted-empty">Loading slots…</span>';
  try {
    const result = await api(`/api/appointments/availability?for_date=${encodeURIComponent(value)}`);
    $('slotGrid').innerHTML = result.slots.length
      ? result.slots
          .map(
            (slot) =>
              `<button type="button" class="slot-button" data-slot="${escapeHtml(slot.start_time)}">${escapeHtml(slot.label)}</button>`,
          )
          .join('')
      : '<span class="muted-empty">No available slots (demos run weekdays 10 AM–4 PM IST).</span>';
    $('slotGrid').querySelectorAll('.slot-button').forEach((button) =>
      button.addEventListener('click', () => {
        state.selectedSlot = button.dataset.slot;
        $('slotGrid').querySelectorAll('.slot-button').forEach((x) => x.classList.remove('selected'));
        button.classList.add('selected');
        $('bookButton').disabled = !state.leadId;
      }),
    );
  } catch (err) {
    $('slotGrid').innerHTML = `<span class="muted-empty">${escapeHtml(err.message)}</span>`;
  }
}

async function bookAppointment() {
  if (!state.leadId || !state.selectedSlot) return;
  $('bookButton').disabled = true;
  try {
    const result = await api('/api/appointments', {
      method: 'POST',
      body: JSON.stringify({
        lead_id: state.leadId,
        start_time: state.selectedSlot,
        duration_minutes: 30,
        notes: 'Product demonstration booked through SalesPilot dashboard',
        idempotency_key: `${state.leadId}:${state.selectedSlot}`,
      }),
    });
    $('bookingMessage').textContent = result.idempotent_replay
      ? 'This booking was already confirmed.'
      : 'Appointment confirmed and saved locally.';
    showToast('Appointment booked successfully.');
    await Promise.all([loadStats(), renderLeadDetail(), loadAvailability()]);
  } catch (err) {
    $('bookingMessage').textContent = err.message;
    showToast(err.message);
  } finally {
    $('bookButton').disabled = !state.selectedSlot;
  }
}

async function cancelAppointment(appointmentId, btn) {
  btn.disabled = true;
  try {
    await api(`/api/appointments/${encodeURIComponent(appointmentId)}/cancel`, {
      method: 'POST',
      body: JSON.stringify({ reason: 'Cancelled from dashboard' }),
    });
    showToast('Appointment cancelled.');
    await Promise.all([loadStats(), renderLeadDetail(), loadAvailability()]);
  } catch (err) {
    showToast(err.message);
    btn.disabled = false;
  }
}

async function searchKnowledge(event) {
  event.preventDefault();
  const query = $('knowledgeQuery').value.trim();
  if (!query) {
    await loadKnowledgeDocuments();
    return;
  }
  const hasGemini = $('geminiStatusBtn')?.classList.contains('connected');
  $('knowledgeResults').innerHTML = `<span class="muted-empty">${hasGemini ? 'Searching local docs & asking Gemini AI…' : 'Searching local knowledge…'}</span>`;
  try {
    const result = await api(`/api/knowledge/search?q=${encodeURIComponent(query)}`);
    const chunks = [];
    if (result.ai_answer) {
      const supported = result.ai_supported !== false;
      const sourceChips = (result.ai_sources || [])
        .map((s) => `<span class="knowledge-source-chip">${escapeHtml(s)}</span>`)
        .join('');
      chunks.push(`
        <div class="knowledge-ai-card ${supported ? '' : 'unsupported'}">
          <div class="knowledge-ai-head">
            <span>✦ ${result.ai_mode === 'gemini_assisted' ? 'Gemini Grounded Answer' : 'AI Grounded Answer'}</span>
            <div>${sourceChips}</div>
          </div>
          <p>${escapeHtml(result.ai_answer)}</p>
        </div>
      `);
    }
    if (result.results?.length) {
      chunks.push(
        ...result.results.map(
          (hit) =>
            `<div class="knowledge-hit"><strong>${escapeHtml(hit.source)} · relevance ${hit.score}</strong><p>${escapeHtml(hit.content)}</p></div>`,
        ),
      );
    } else if (!result.ai_answer) {
      chunks.push('<span class="muted-empty">No relevant passages found. SalesPilot will escalate instead of guessing.</span>');
    }
    chunks.push('<button type="button" class="text-button kb-back-link" id="kbBackDocsBtn">← Back to indexed documents</button>');
    $('knowledgeResults').innerHTML = chunks.join('');
    $('kbBackDocsBtn')?.addEventListener('click', () => {
      $('knowledgeQuery').value = '';
      loadKnowledgeDocuments();
    });
  } catch (err) {
    $('knowledgeResults').textContent = err.message;
  }
}

async function reloadKnowledge() {
  const btn = $('reloadKnowledgeButton');
  btn.disabled = true;
  try {
    const result = await api('/api/knowledge/reload', { method: 'POST' });
    showToast(`Knowledge base re-indexed: ${result.chunks} chunks.`);
    await loadKnowledgeDocuments();
  } catch (err) {
    showToast(err.message);
  } finally {
    btn.disabled = false;
  }
}

async function refreshAll() {
  const prevLeadId = state.leadId;
  await Promise.all([loadStats(), loadLeads(), loadKnowledgeDocuments()]);
  if (state.leadId && state.leadId === prevLeadId) await renderLeadDetail();
}

/* ─── Event Listeners & Keyboard Shortcuts ──────────────────────────── */
$('leadSelect').addEventListener('change', (e) => setSelectedLead(e.target.value));
$('startCallButton').addEventListener('click', async () => {
  const ok = await startNewSession();
  if (ok) showToast('New conversation session started.');
});
$('sendButton').addEventListener('click', () => sendMessage());
$('messageInput').addEventListener('keydown', (event) => {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    sendMessage();
  }
});
$('createLeadForm').addEventListener('submit', createLead);
$('bookingDate').addEventListener('change', loadAvailability);
$('bookButton').addEventListener('click', bookAppointment);
$('knowledgeSearchForm').addEventListener('submit', searchKnowledge);
$('reloadKnowledgeButton').addEventListener('click', reloadKnowledge);

$('startVoiceCallBtn').addEventListener('click', startLiveCall);
$('endVoiceCallBtn').addEventListener('click', endLiveCall);
$('muteCallBtn').addEventListener('click', toggleMute);
$('interruptCallBtn').addEventListener('click', interruptAndListen);
$('recordButton').addEventListener('click', toggleOneShotRecording);

$('speechLanguage').addEventListener('change', () => {
  $('conversationLanguage').textContent = $('speechLanguage').selectedOptions[0].text;
});
$('refreshButton').addEventListener('click', () =>
  refreshAll()
    .then(() => showToast('Workspace refreshed.'))
    .catch((err) => showToast(err.message)),
);
$('newLeadScroll').addEventListener('click', () =>
  $('createLeadPanel').scrollIntoView({ behavior: 'smooth' }),
);

/* ─── Gemini Configuration Modal ────────────────────────────────────── */
function openGeminiModal() {
  $('geminiStatusMsg').textContent = '';
  $('geminiModal').hidden = false;
  setTimeout(() => $('geminiKeyInput').focus(), 40);
}
function closeGeminiModal() {
  $('geminiModal').hidden = true;
}

$('geminiStatusBtn')?.addEventListener('click', openGeminiModal);
$('closeGeminiModal')?.addEventListener('click', closeGeminiModal);
$('geminiModal')?.addEventListener('click', (e) => {
  if (e.target === $('geminiModal')) closeGeminiModal();
});
$('geminiForm')?.addEventListener('submit', async (e) => {
  e.preventDefault();
  const apiKey = $('geminiKeyInput').value.trim();
  const model = $('geminiModelSelect').value;
  if (!apiKey) {
    $('geminiStatusMsg').style.color = '#dc3f59';
    $('geminiStatusMsg').textContent = 'Paste your Gemini API key first (starts with AIza...).';
    return;
  }
  const btn = $('saveGeminiBtn');
  btn.disabled = true;
  btn.textContent = 'Verifying…';
  $('geminiStatusMsg').style.color = '#64748b';
  $('geminiStatusMsg').textContent = 'Testing connection to Gemini API…';
  try {
    const res = await api('/api/settings/gemini', {
      method: 'POST',
      body: JSON.stringify({ api_key: apiKey, model }),
    });
    updateGeminiPill(res.gemini_configured, res.gemini_model);
    await loadCapabilities();
    $('geminiKeyInput').value = '';
    $('geminiStatusMsg').style.color = '#129466';
    $('geminiStatusMsg').textContent = res.message;
    showToast(`Gemini connected (${res.gemini_model}).`);
    setTimeout(closeGeminiModal, 900);
  } catch (err) {
    $('geminiStatusMsg').style.color = '#dc3f59';
    $('geminiStatusMsg').textContent = err.message;
  } finally {
    btn.disabled = false;
    btn.textContent = 'Verify & Save';
  }
});
$('disconnectGeminiBtn')?.addEventListener('click', async () => {
  const btn = $('disconnectGeminiBtn');
  btn.disabled = true;
  try {
    const res = await api('/api/settings/gemini', {
      method: 'POST',
      body: JSON.stringify({ api_key: '', model: $('geminiModelSelect').value }),
    });
    updateGeminiPill(false, res.gemini_model);
    await loadCapabilities();
    $('geminiKeyInput').value = '';
    showToast('Switched back to deterministic local mode.');
    closeGeminiModal();
  } catch (err) {
    $('geminiStatusMsg').style.color = '#dc3f59';
    $('geminiStatusMsg').textContent = err.message;
  } finally {
    btn.disabled = false;
  }
});

document.querySelectorAll('.nav-link').forEach((link) =>
  link.addEventListener('click', (e) => {
    document.querySelectorAll('.nav-link').forEach((x) => x.classList.remove('active'));
    link.classList.add('active');
    const target = link.getAttribute('href');
    if (target && target.startsWith('#')) {
      e.preventDefault();
      const section = document.querySelector(target);
      if (section) section.scrollIntoView({ behavior: 'smooth' });
    }
  }),
);

// Spacebar = interrupt AI / send spoken utterance; M = mute/unmute during active call
document.addEventListener('keydown', (event) => {
  if (!state.callActive) return;
  const tag = (event.target?.tagName || '').toLowerCase();
  if (tag === 'input' || tag === 'textarea' || tag === 'select') return;
  if (event.code === 'Space') {
    event.preventDefault();
    interruptAndListen();
  } else if (event.key === 'm' || event.key === 'M') {
    event.preventDefault();
    toggleMute();
  }
});

/* ─── Init ──────────────────────────────────────────────────────────── */
(async function init() {
  startOrbRenderer();
  try {
    await Promise.all([loadCapabilities(), refreshAll()]);
    const tomorrow = new Date();
    tomorrow.setDate(tomorrow.getDate() + 1);
    // Skip weekend by default so slots appear immediately!
    while (tomorrow.getDay() === 0 || tomorrow.getDay() === 6) {
      tomorrow.setDate(tomorrow.getDate() + 1);
    }
    $('bookingDate').value = `${tomorrow.getFullYear()}-${String(tomorrow.getMonth() + 1).padStart(2, '0')}-${String(tomorrow.getDate()).padStart(2, '0')}`;
    await loadAvailability();
  } catch (err) {
    showToast(`Could not load workspace: ${err.message}`);
  }
})();
