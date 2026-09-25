/**
 * Laya AI TU Sofia Web Explorer Frontend Controller
 * Handles live queries, model-to-model payload generation, ECTS inspection,
 * and dynamic rendering of university entities.
 */

let globalKB = null;
let globalSchemas = [];

document.addEventListener('DOMContentLoaded', async () => {
  setupEventListeners();
  await loadInitialData();
  // Run default query
  executeSearch("ФКСТ");
});

async function loadInitialData() {
  try {
    // 1. Fetch Knowledge Base
    const kbRes = await fetch('/api/kb');
    globalKB = await kbRes.json();
    renderFaculties(globalKB.faculties || []);
    renderTimeline(globalKB.admissions?.calendar_2026 || []);

    // Update stats
    if (globalKB.faculties) {
      document.getElementById('stat-faculties').innerText = globalKB.faculties.length;
    }
    if (globalKB.curricula) {
      document.getElementById('stat-curricula').innerText = globalKB.curricula.length;
    }

    // 2. Fetch Tool Schemas
    const schemasRes = await fetch('/api/schemas');
    const schemasData = await schemasRes.json();
    globalSchemas = schemasData.schemas || [];
    renderSchemaTabs(globalSchemas);

  } catch (err) {
    console.error("Failed to load initial university data:", err);
  }
}

function setupEventListeners() {
  setupChatBot();

  const queryInput = document.getElementById('ai-query-input');
  const btnRun = document.getElementById('btn-run-query');
  const btnCopy = document.getElementById('btn-copy-json');
  const modal = document.getElementById('modal-backdrop');
  const modalClose = document.getElementById('btn-close-modal');

  btnRun.addEventListener('click', () => {
    executeSearch(queryInput.value.trim());
  });

  queryInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      executeSearch(queryInput.value.trim());
    }
  });

  // Quick Chips
  document.querySelectorAll('.chip').forEach(chip => {
    chip.addEventListener('click', () => {
      const q = chip.getAttribute('data-q');
      queryInput.value = q;
      executeSearch(q);
    });
  });

  // Filter Buttons
  document.querySelectorAll('.filter-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      filterFaculties(btn.getAttribute('data-filter'));
    });
  });

  // Copy JSON Button
  btnCopy.addEventListener('click', () => {
    const jsonText = document.getElementById('m2m-json-code').innerText;
    navigator.clipboard.writeText(jsonText).then(() => {
      btnCopy.innerText = "Копирано! ✓";
      setTimeout(() => { btnCopy.innerText = "Копирай JSON"; }, 2000);
    });
  });

  // Modal Close
  modalClose.addEventListener('click', () => modal.classList.remove('open'));
  modal.addEventListener('click', (e) => {
    if (e.target === modal) modal.classList.remove('open');
  });
}

async function executeSearch(query) {
  if (!query) return;

  const reasoningText = document.getElementById('reasoning-text');
  const responseContent = document.getElementById('response-content');
  const m2mCode = document.getElementById('m2m-json-code');

  // 1. Simulate Laya Decoder Thought Process
  reasoningText.innerHTML = generateLayaReasoning(query);
  responseContent.innerHTML = `<div style="color: #94a3b8; padding: 20px; text-align: center;">Извличане на верифицирани данни от семантичния граф...</div>`;

  try {
    // 2. Fetch Search Results
    const searchRes = await fetch(`/api/search?q=${encodeURIComponent(query)}`);
    const searchData = await searchRes.json();

    // 3. Fetch M2M Envelope
    const m2mRes = await fetch(`/api/m2m?q=${encodeURIComponent(query)}`);
    const m2mData = await m2mRes.json();

    // 4. Render Formatted Output
    renderSearchResults(searchData.results || []);

    // 5. Render M2M JSON
    m2mCode.innerText = JSON.stringify(m2mData, null, 2);

  } catch (err) {
    responseContent.innerHTML = `<div style="color: #ef4444; padding: 20px;">Грешка при изпълнение на заявката: ${err.message}</div>`;
  }
}

function generateLayaReasoning(query) {
  const q = query.toLowerCase();
  let reasoning = "";

  if (/\b(фкст|fkst|кст|kst|компютърни|kompyutarni)\b/i.test(q)) {
    reasoning = `<strong>[Intent: Faculty Lookup]</strong> Разпознат факултет <code>ФКСТ / FKST</code>. Каноничен обект: <em>Факултет по компютърни системи и технологии</em>. Декан: проф. д-р инж. Румен Трифонов.`;
  } else if (/\b(фа|fa|автоматика|avtomatika)\b/i.test(q)) {
    reasoning = `<strong>[Intent: Faculty Lookup]</strong> Разпознат факултет <code>ФА / FA</code>. Каноничен обект: <em>Факултет по автоматика</em>. Декан: доц. д-р инж. Цоньо Славов.`;
  } else if (/\b(сф|sf|стопански|stopanski|мениджмънт)\b/i.test(q)) {
    reasoning = `<strong>[Intent: Faculty Lookup]</strong> Разпознат факултет <code>СФ / SF</code>. Каноничен обект: <em>Стопански факултет</em>. Декан: проф. д-р инж. Младен Велев.`;
  } else if (/\b(фпми|fpmi|фпм|fpm|математика|информатика)\b/i.test(q)) {
    reasoning = `<strong>[Intent: Faculty Lookup]</strong> Разпознат факултет <code>ФПМИ / FPMI</code>. Каноничен обект: <em>Факултет по приложна математика и информатика</em>. Декан: проф. д-р инж. Десислава Иванова.`;
  } else if (/\b(мф|mf|машиностроителен|mashinostroitelen)\b/i.test(q)) {
    reasoning = `<strong>[Intent: Faculty Lookup]</strong> Разпознат факултет <code>МФ / MF</code>. Каноничен обект: <em>Машиностроителен факултет</em>. Декан: проф. д-р инж. Стилиян Николов.`;
  } else if (/\b(еф|ef|електро|elektro|електротехника)\b/i.test(q)) {
    reasoning = `<strong>[Intent: Faculty Lookup]</strong> Разпознат факултет <code>ЕФ / EF</code>. Каноничен обект: <em>Електротехнически факултет</em>. Декан: доц. д-р инж. Николай Матанов.`;
  } else if (/\b(фетт|fett|електроника|elektronika)\b/i.test(q)) {
    reasoning = `<strong>[Intent: Faculty Lookup]</strong> Разпознат факултет <code>ФЕТТ / FETT</code>. Каноничен обект: <em>Факултет по електронна техника и технологии</em>. Декан: доц. д-р инж. Маринела Йорданова.`;
  } else if (/\b(фт|ft|транспорт|transport)\b/i.test(q)) {
    reasoning = `<strong>[Intent: Faculty Lookup]</strong> Разпознат факултет <code>ФТ / FT</code>. Каноничен обект: <em>Факултет по транспорта</em>. Декан: доц. д-р инж. Симеон Ананиев.`;
  } else if (q.includes("такса") || q.includes("такси") || q.includes("цена") || q.includes("taksi") || q.includes("taksa")) {
    reasoning = `<strong>[Intent: Admissions Fees]</strong> Разпозната заявка за такси. Извличане на данни от <em>priem.tu-sofia.bg</em>: 30 евро за изпит / признаване на матура, субсидирани такси за държавна поръчка.`;
  } else if (q.includes("график") || q.includes("срок") || q.includes("прием") || q.includes("календар") || q.includes("priem")) {
    reasoning = `<strong>[Intent: Admissions Calendar]</strong> Разпознато запитване за кампания 2026/2027 г. Извличане на календарни срокове за подаване на документи и предварителни тестове от Учебен отдел ТУ-София.`;
  } else if (q.includes("общежити") || q.includes("стол") || q.includes("пссо") || q.includes("dorm")) {
    reasoning = `<strong>[Intent: Campus Services]</strong> Разпознато звено <em>Поделение „Студентски столове и общежития“ (ПССО)</em>. База: над 6000 места в Студентски град, блокове 1, 2, 3, 4, 8, 9, 10...`;
  } else if (q.includes("декан") || q.includes("шеф") || q.includes("dekan") || q.includes("shef")) {
    reasoning = `<strong>[Intent: Leadership Disambiguation]</strong> Запитване за ръководство. В ТУ-София има 17 факултета с отделни декани. Извличане на опции за избор.`;
  } else {
    reasoning = `<strong>[Intent: General Semantic Search]</strong> Нормализиране на Кирилица/Шльокавица, филтриране на стоп думи, морфологично стемване за ТУ-София екосистема.`;
  }

  return reasoning;
}

function renderSearchResults(results) {
  const container = document.getElementById('response-content');
  if (!results || results.length === 0) {
    container.innerHTML = `<div style="color: #94a3b8; padding: 20px;">Няма намерени съвпадения за тази заявка в базата от знания.</div>`;
    return;
  }

  container.innerHTML = results.map(item => `
    <div class="ai-entity-card">
      <div class="ai-entity-title">
        <span>${item.title}</span>
        ${item.acronym ? `<span class="ai-entity-badge">${item.acronym}</span>` : `<span class="ai-entity-badge">${item.type.toUpperCase()}</span>`}
      </div>
      <div class="ai-entity-snippet">${item.snippet}</div>
      <div class="ai-entity-meta">
        <span>Съвпадение: <strong>${item.score} pts</strong></span>
        ${item.url ? `<a href="${item.url}" target="_blank" class="ai-link">Официален източник ↗</a>` : ''}
      </div>
    </div>
  `).join('');
}

function renderFaculties(faculties) {
  const grid = document.getElementById('faculties-grid');
  grid.innerHTML = faculties.map(f => {
    const acronym = f.acronym || 'ТУ';
    const deptPreview = f.departments && f.departments.length > 0 
      ? `Катедри: ${f.departments.slice(0, 3).join(', ')}${f.departments.length > 3 ? '...' : ''}`
      : 'Обучение по инженерни направления';

    return `
      <div class="faculty-card" data-slug="${f.slug}" data-acronym="${acronym}">
        <div>
          <div class="faculty-card-header">
            <h4 class="faculty-name">${f.name_bg}</h4>
            <span class="faculty-acronym-badge">${acronym}</span>
          </div>

          <div class="faculty-dean-row">
            <span class="dean-icon">👨‍🏫</span>
            <div class="dean-text">
              <span class="dean-label">ДЕКАН</span>
              <strong>${f.dean || 'Ръководство ТУ-София'}</strong>
            </div>
          </div>

          <div class="faculty-departments-preview">
            ${deptPreview}
          </div>
        </div>

        <div class="faculty-card-footer">
          <span style="font-size: 11.5px; color: var(--text-dim);">${f.block || 'ТУ-София'}</span>
          <button class="btn-inspect" onclick="openFacultyModal('${f.slug}')">Детайли & ECTS</button>
        </div>
      </div>
    `;
  }).join('');
}

function filterFaculties(filter) {
  const cards = document.querySelectorAll('.faculty-card');
  cards.forEach(card => {
    const acronym = card.getAttribute('data-acronym');
    const slug = card.getAttribute('data-slug');

    if (filter === 'all') {
      card.style.display = 'flex';
    } else if (filter === 'tech') {
      const isTech = ['ФКСТ', 'ФА', 'ФЕТТ', 'ФТК', 'ФПМИ', 'ФИТ', 'МФ', 'ЕФ', 'ЕМФ'].includes(acronym);
      card.style.display = isTech ? 'flex' : 'none';
    } else if (filter === 'foreign') {
      const isForeign = ['ФаГИОПМ', 'ФФИО', 'ФАИО'].includes(acronym);
      card.style.display = isForeign ? 'flex' : 'none';
    } else if (filter === 'branches') {
      const isBranch = ['ФЕА', 'ИПФ', 'ФМУ'].includes(acronym) || slug.includes('sliven') || slug.includes('plovdiv');
      card.style.display = isBranch ? 'flex' : 'none';
    }
  });
}

function renderTimeline(timelineItems) {
  const container = document.getElementById('timeline-list');
  if (!timelineItems || timelineItems.length === 0) return;

  container.innerHTML = timelineItems.map(item => `
    <div class="timeline-item">
      <div class="timeline-marker"></div>
      <div class="timeline-content">
        <span class="timeline-deadline">${item.deadline}</span>
        <p class="timeline-activity">${item.activity}</p>
      </div>
    </div>
  `).join('');
}

function renderSchemaTabs(schemas) {
  const container = document.getElementById('schema-tabs');
  const codeBox = document.getElementById('active-schema-code');

  container.innerHTML = schemas.map((s, idx) => `
    <button class="schema-tab-btn ${idx === 0 ? 'active' : ''}" data-idx="${idx}">
      ${s.name}()
    </button>
  `).join('');

  if (schemas.length > 0) {
    codeBox.innerText = JSON.stringify(schemas[0], null, 2);
  }

  container.querySelectorAll('.schema-tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      container.querySelectorAll('.schema-tab-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      const idx = parseInt(btn.getAttribute('data-idx'));
      codeBox.innerText = JSON.stringify(schemas[idx], null, 2);
    });
  });
}

window.openFacultyModal = function(slug) {
  if (!globalKB || !globalKB.faculties) return;
  const faculty = globalKB.faculties.find(f => f.slug === slug);
  if (!faculty) return;

  const modal = document.getElementById('modal-backdrop');
  document.getElementById('modal-faculty-title').innerText = faculty.name_bg;

  const body = document.getElementById('modal-faculty-body');
  
  const deptsHtml = faculty.departments && faculty.departments.length > 0
    ? faculty.departments.map(d => `<li style="margin-bottom: 4px;">Катедра „${d}“</li>`).join('')
    : '<li>Информацията се актуализира от факултета</li>';

  const specsHtml = faculty.specialties && faculty.specialties.length > 0
    ? faculty.specialties.map(s => `<li style="margin-bottom: 4px;">${s}</li>`).join('')
    : '<li>Бакалавърски и магистърски специалности по акредитирано направление</li>';

  let ectsHtml = '<p style="color: var(--text-dim); font-size: 13px;">Няма налични директни ECTS линкове в момента.</p>';
  if (faculty.ects_data && faculty.ects_data.bachelor_programs) {
    ectsHtml = faculty.ects_data.bachelor_programs.slice(0, 8).map(p => `
      <div style="margin-bottom: 8px;">
        <a href="${p.url}" target="_blank" style="color: var(--accent-cyan); text-decoration: none; font-size: 13px;">
          📄 ${p.title} ↗
        </a>
      </div>
    `).join('');
  }

  body.innerHTML = `
    <div style="background: rgba(255, 255, 255, 0.03); padding: 16px; border-radius: 8px;">
      <p style="margin-bottom: 6px;"><strong>Декан:</strong> ${faculty.dean || 'Н/А'}</p>
      <p style="margin-bottom: 6px;"><strong>Локация:</strong> ${faculty.block || 'Кампус ТУ-София'}, ${faculty.cabinet || ''}</p>
      <p style="margin-bottom: 6px;"><strong>Телефон:</strong> ${faculty.phone || 'Централа 02 965 21 11'}</p>
      <p><strong>Email:</strong> <a href="mailto:${faculty.email}" style="color: var(--accent-cyan);">${faculty.email || 'delovodstvo@tu-sofia.bg'}</a></p>
    </div>

    <div>
      <h4 style="color: #fff; margin-bottom: 10px; font-size: 15px;">Катедри към факултета</h4>
      <ul style="color: var(--text-muted); font-size: 13.5px; padding-left: 20px;">
        ${deptsHtml}
      </ul>
    </div>

    <div>
      <h4 style="color: #fff; margin-bottom: 10px; font-size: 15px;">Акредитирани специалности</h4>
      <ul style="color: var(--text-muted); font-size: 13.5px; padding-left: 20px;">
        ${specsHtml}
      </ul>
    </div>

    <div>
      <h4 style="color: #fff; margin-bottom: 10px; font-size: 15px;">Учебни планове и ECTS пакети</h4>
      <div>${ectsHtml}</div>
    </div>

    <div style="padding-top: 14px; border-top: 1px solid var(--border-glass); display: flex; justify-content: space-between; align-items: center;">
      <a href="${faculty.url}" target="_blank" style="color: var(--accent-primary); font-weight: 600; font-size: 13px; text-decoration: none;">
        Официална страница на факултета ↗
      </a>
      <span style="font-size: 12px; color: var(--text-dim);">Код: ${faculty.acronym || 'ТУ'}</span>
    </div>
  `;

  modal.classList.add('open');
};

/* =========================================================================
   LAYA + GEMMA 4:e4b CHATBOT CONTROLLER
   Gemma 4 handles natural user conversation and communicates ONLY the
   verified facts retrieved by Laya.
   ========================================================================= */

let isChatGenerating = false;

function setupChatBot() {
  const chatInput = document.getElementById('chat-user-input');
  const btnSend = document.getElementById('btn-send-chat');

  if (btnSend && chatInput) {
    btnSend.addEventListener('click', () => {
      sendChatMessage();
    });

    chatInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        sendChatMessage();
      }
    });
  }

  // Suggestion chips
  document.querySelectorAll('.chat-suggest-chip').forEach(chip => {
    chip.addEventListener('click', () => {
      const q = chip.getAttribute('data-q');
      if (chatInput) chatInput.value = q;
      sendChatMessage(q);
    });
  });
}

async function sendChatMessage(overrideText) {
  if (isChatGenerating) return;

  const chatInput = document.getElementById('chat-user-input');
  const btnSend = document.getElementById('btn-send-chat');
  const text = (overrideText || (chatInput ? chatInput.value : "")).trim();

  if (!text) return;

  isChatGenerating = true;
  if (chatInput) {
    chatInput.value = "";
    chatInput.disabled = true;
  }
  if (btnSend) btnSend.disabled = true;

  // 1. Render User message
  appendUserChatMessage(text);

  // 2. Show Typing Indicator with dynamic status
  showChatTyping();

  const statusTimer = setTimeout(() => {
    const statusEl = document.getElementById('typing-status');
    if (statusEl) {
      statusEl.innerText = "✦ ТУдор формулира точен отговор от фактите на Laya...";
    }
  }, 1800);

  try {
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text })
    });

    clearTimeout(statusTimer);

    if (!res.ok) {
      throw new Error(`HTTP ${res.status}: ${res.statusText}`);
    }

    const data = await res.json();
    hideChatTyping();

    // 3. Render Bot message with ТУдор response + Laya grounding
    appendBotChatMessage(data.gemma_response, data.laya_reasoning, data.laya_grounding);

  } catch (err) {
    clearTimeout(statusTimer);
    hideChatTyping();
    appendBotChatMessage(
      `Съжалявам, възникна проблем при връзката: ${err.message}. Моля, уверете се, че сървърът е стартиран.`,
      "Грешка при комуникация",
      null
    );
  } finally {
    isChatGenerating = false;
    if (chatInput) {
      chatInput.disabled = false;
      chatInput.focus();
    }
    if (btnSend) btnSend.disabled = false;
  }
}

function appendUserChatMessage(text) {
  const container = document.getElementById('chat-messages');
  if (!container) return;

  const msgDiv = document.createElement('div');
  msgDiv.className = 'chat-message user-message';
  msgDiv.innerHTML = `
    <div class="message-body">
      <div class="message-sender">
        <span class="sender-name">Вие</span>
      </div>
      <div class="message-text">${escapeHtml(text)}</div>
    </div>
    <div class="message-avatar">👤</div>
  `;
  container.appendChild(msgDiv);
  container.scrollTop = container.scrollHeight;
}

function appendBotChatMessage(text, reasoning, grounding) {
  const container = document.getElementById('chat-messages');
  if (!container) return;

  const hasGrounding = grounding && Object.keys(grounding).length > 0;
  const groundingSnippet = reasoning || "Семантично извлечени данни от Laya";

  const msgDiv = document.createElement('div');
  msgDiv.className = 'chat-message bot-message';
  msgDiv.innerHTML = `
    <div class="message-avatar">🎓</div>
    <div class="message-body">
      <div class="message-sender">
        <span class="sender-name">ТУдор</span>
        <span class="sender-role">AI Консултант на ТУ-София</span>
        <span class="grounded-by">✓ Проверено от Laya</span>
      </div>
      <div class="message-text">
        ${formatMessageMarkdown(text)}
      </div>
      ${hasGrounding ? `
      <div class="laya-grounded-pill">
        <span class="laya-pill-dot">✦</span>
        <span class="laya-pill-title">Фактическа основа от Laya:</span>
        <span class="laya-pill-text">${escapeHtml(groundingSnippet)}</span>
      </div>` : ''}
    </div>

  `;
  container.appendChild(msgDiv);
  container.scrollTop = container.scrollHeight;
}

function showChatTyping() {
  const container = document.getElementById('chat-messages');
  if (!container) return;

  hideChatTyping();

  const typingDiv = document.createElement('div');
  typingDiv.className = 'chat-message bot-message';
  typingDiv.id = 'chat-typing-row';
  typingDiv.innerHTML = `
    <div class="message-avatar">🎓</div>
    <div class="message-body">
      <div class="message-sender">
        <span class="sender-name">ТУдор</span>
        <span class="sender-role">AI Консултант на ТУ-София</span>
        <span class="typing-status" id="typing-status" style="color: var(--accent-cyan); font-size: 11.5px; font-weight: 500;">✦ Laya извлича факти от семантичната база...</span>
      </div>
      <div class="typing-indicator" style="padding: 10px 16px; background: rgba(17, 24, 39, 0.9); border-radius: 12px; border: 1px solid var(--border-glass); border-top-left-radius: 4px; display: inline-flex; width: fit-content;">
        <div class="typing-dots">
          <div class="typing-dot"></div>
          <div class="typing-dot"></div>
          <div class="typing-dot"></div>
        </div>
      </div>
    </div>
  `;
  container.appendChild(typingDiv);
  container.scrollTop = container.scrollHeight;
}

function hideChatTyping() {
  const typingRow = document.getElementById('chat-typing-row');
  if (typingRow) typingRow.remove();
}

window.toggleLayaAccordion = function(btn) {
  const content = btn.nextElementSibling;
  const arrow = btn.querySelector('.arrow-toggle');
  if (!content) return;
  if (content.classList.contains('open')) {
    content.classList.remove('open');
    if (arrow) arrow.innerText = '▼';
  } else {
    content.classList.add('open');
    if (arrow) arrow.innerText = '▲';
  }
};

function escapeHtml(str) {
  if (str === null || str === undefined) return "";
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function formatMessageMarkdown(text) {
  if (!text) return "";
  let html = escapeHtml(text);
  // Bold **text**
  html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
  // Italic *text*
  html = html.replace(/\*([^*\n]+)\*/g, '<em>$1</em>');
  // Bullet lists
  html = html.replace(/^\s*[-*•]\s+(.*)$/gm, '<li style="margin-left: 18px; margin-bottom: 4px;">$1</li>');
  // Numbered lists
  html = html.replace(/^\s*(\d+)\.\s+(.*)$/gm, '<li style="margin-left: 18px; margin-bottom: 4px; list-style-type: decimal;">$2</li>');
  // Newlines: preserve paragraph separation
  html = html.replace(/\n\n+/g, '<br><br>');
  // Clean up adjacent list items breaking with double br
  html = html.replace(/(<\/li>)\s*<br><br>\s*(<li)/g, '$1$2');
  html = html.replace(/\n/g, '<br>');
  return html;
}

