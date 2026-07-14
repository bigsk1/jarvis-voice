(() => {
  'use strict';

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  const boot = $('.boot-screen');
  const finishBoot = () => boot?.classList.add('done');
  window.addEventListener('load', () => window.setTimeout(finishBoot, reducedMotion ? 0 : 950));
  window.setTimeout(finishBoot, 1800);

  // Inline the real Jarvis SVG marks so their embedded animations run.
  // Elements keep their "J" fallback until the markup is fetched and parsed.
  const svgSources = {
    hal: 'jarvis-web/client/assets/jarvis-hal-eye.svg',
    hud: 'jarvis-web/client/assets/jarvis-hud-logo.svg'
  };
  const svgMarkup = {};
  $$('[data-inline-svg]').forEach((el) => {
    const [key, state] = el.dataset.inlineSvg.split(':');
    const url = svgSources[key];
    if (!url) return;
    svgMarkup[key] ||= fetch(url).then((response) => {
      if (!response.ok) throw new Error(response.status);
      return response.text();
    });
    svgMarkup[key].then((markup) => {
      const parsed = new DOMParser().parseFromString(markup, 'image/svg+xml').documentElement;
      if (parsed.nodeName.toLowerCase() !== 'svg') return;
      const svg = document.importNode(parsed, true);
      svg.removeAttribute('class');
      if (state) svg.classList.add(state);
      svg.setAttribute('aria-hidden', 'true');
      svg.setAttribute('focusable', 'false');
      el.replaceChildren(svg);
      el.classList.add('svg-loaded');
    }).catch(() => {});
  });

  const header = $('[data-header]');
  const setHeader = () => header?.classList.toggle('scrolled', window.scrollY > 24);
  setHeader();
  window.addEventListener('scroll', setHeader, { passive: true });

  const revealObserver = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        entry.target.classList.add('visible');
        revealObserver.unobserve(entry.target);
      }
    });
  }, { threshold: 0.12, rootMargin: '0px 0px -5% 0px' });
  $$('[data-reveal]').forEach((el) => revealObserver.observe(el));

  const navLinks = $$('[data-nav-link]');
  const sections = navLinks.map((link) => $(link.getAttribute('href'))).filter(Boolean);
  const navObserver = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (!entry.isIntersecting) return;
      navLinks.forEach((link) => link.classList.toggle('active', link.getAttribute('href') === `#${entry.target.id}`));
    });
  }, { rootMargin: '-35% 0px -60%', threshold: 0 });
  sections.forEach((section) => navObserver.observe(section));

  const menuToggle = $('[data-menu-toggle]');
  const closeMenu = () => {
    document.body.classList.remove('menu-open');
    menuToggle?.setAttribute('aria-expanded', 'false');
  };
  menuToggle?.addEventListener('click', () => {
    const open = document.body.classList.toggle('menu-open');
    menuToggle.setAttribute('aria-expanded', String(open));
  });
  navLinks.forEach((link) => link.addEventListener('click', closeMenu));

  if (!reducedMotion && window.matchMedia('(pointer: fine)').matches) {
    const glow = $('.cursor-light');
    let targetX = innerWidth / 2, targetY = innerHeight / 2, x = targetX, y = targetY;
    window.addEventListener('pointermove', (event) => { targetX = event.clientX; targetY = event.clientY; }, { passive: true });
    const moveGlow = () => {
      x += (targetX - x) * .09; y += (targetY - y) * .09;
      if (glow) glow.style.transform = `translate3d(${x - 260}px,${y - 260}px,0)`;
      requestAnimationFrame(moveGlow);
    };
    moveGlow();

    $$('.magnetic').forEach((button) => {
      button.addEventListener('pointermove', (event) => {
        const rect = button.getBoundingClientRect();
        button.style.transform = `translate(${(event.clientX - rect.left - rect.width / 2) * .08}px, ${(event.clientY - rect.top - rect.height / 2) * .12}px)`;
      });
      button.addEventListener('pointerleave', () => { button.style.transform = ''; });
    });
  }

  const field = $('#ambientField');
  if (field && !reducedMotion) {
    const ctx = field.getContext('2d');
    let dots = [];
    const resize = () => {
      const dpr = Math.min(devicePixelRatio, 2);
      field.width = innerWidth * dpr; field.height = innerHeight * dpr;
      field.style.width = `${innerWidth}px`; field.style.height = `${innerHeight}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      dots = Array.from({ length: Math.min(65, Math.floor(innerWidth / 22)) }, () => ({
        x: Math.random() * innerWidth, y: Math.random() * innerHeight,
        r: Math.random() * 1.1 + .25, v: Math.random() * .12 + .025, a: Math.random() * .35 + .08
      }));
    };
    const draw = () => {
      ctx.clearRect(0, 0, innerWidth, innerHeight);
      dots.forEach((dot) => {
        dot.y -= dot.v; if (dot.y < -5) dot.y = innerHeight + 5;
        ctx.beginPath(); ctx.arc(dot.x, dot.y, dot.r, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(104,224,245,${dot.a})`; ctx.fill();
      });
      requestAnimationFrame(draw);
    };
    resize(); draw(); window.addEventListener('resize', resize);
  }

  const waveform = $('[data-waveform]');
  if (waveform) {
    Array.from({ length: 48 }, (_, index) => {
      const bar = document.createElement('i');
      bar.style.setProperty('--i', index);
      bar.style.setProperty('--h', `${5 + Math.sin(index * .72) * 8 + Math.random() * 10}px`);
      waveform.append(bar);
    });
  }

  const voiceCore = $('[data-voice-core]');
  const coreStatus = $('[data-core-status]');
  let voiceTimer;
  voiceCore?.addEventListener('click', () => {
    const listening = !voiceCore.classList.contains('listening');
    voiceCore.classList.toggle('listening', listening);
    if (coreStatus) coreStatus.lastChild.textContent = listening ? ' Simulated listening · no audio captured' : ' Interactive preview · no microphone';
    clearTimeout(voiceTimer);
    if (listening) voiceTimer = setTimeout(() => {
      voiceCore.classList.remove('listening');
      if (coreStatus) coreStatus.lastChild.textContent = ' Preview complete · no audio captured';
    }, 3200);
  });

  const demos = {
    brief: {
      prompt: 'Jarvis, brief me for the day.', timer: '00:01.284',
      response: 'Your morning brief is ready. I checked weather, market movement, open alerts, and the health of your core services. I also saved the visual report to Canvas.',
      trace: [['ROUTE', 'Matched /status workflow', '12ms'], ['GATHER', 'Weather · markets · alerts · system', '804ms'], ['VALIDATE', 'Required signals present', '31ms'], ['DELIVER', 'Canvas report created', '437ms']]
    },
    research: {
      prompt: 'Research solid-state battery breakthroughs.', timer: '00:04.912',
      response: 'I compared current reporting across multiple sources, crawled the strongest results, validated the evidence, and created a cited research brief in Canvas.',
      trace: [['ROUTE', 'Matched /research workflow', '18ms'], ['SEARCH', 'Multi-source discovery', '1.4s'], ['CRAWL', 'Full-text evidence captured', '2.7s'], ['DELIVER', 'Cited Canvas brief created', '794ms']]
    },
    remember: {
      prompt: 'Remember that I prefer concise morning briefs.', timer: '00:00.486',
      response: 'Remembered. I stored the preference in the active mode’s knowledge base and made it available to future conversations through hybrid retrieval.',
      trace: [['ROUTE', 'Selected memory path', '9ms'], ['NORMALIZE', 'Preference extracted', '41ms'], ['STORE', 'Knowledge + embedding saved', '392ms'], ['CONFIRM', 'Memory available for recall', '44ms']]
    },
    build: {
      prompt: 'Build a focused test harness for this module.', timer: '00:08.610',
      response: 'I prepared the task context and handed the implementation to the coding workspace. Progress, tool activity, and the final patch remain visible from the Jarvis interface.',
      trace: [['PLAN', 'Repository context prepared', '194ms'], ['DELEGATE', 'Coding workspace started', '511ms'], ['EXECUTE', 'Edit · test · inspect', '7.3s'], ['RETURN', 'Patch and verification received', '605ms']]
    }
  };

  const traceList = $('[data-trace-list]');
  const renderDemo = (key) => {
    const demo = demos[key]; if (!demo) return;
    $('[data-demo-prompt]').textContent = demo.prompt;
    $('[data-demo-response]').textContent = demo.response;
    $('[data-demo-timer]').textContent = demo.timer;
    if (traceList) {
      traceList.innerHTML = '';
      demo.trace.forEach(([title, copy, time], index) => {
        const item = document.createElement('div'); item.className = 'trace-item'; item.style.animationDelay = `${index * 90}ms`;
        item.innerHTML = `<i>✓</i><div><strong>${title}</strong><span>${copy}</span></div><small>${time}</small>`;
        traceList.append(item);
      });
    }
  };
  $$('[data-intent]').forEach((button) => button.addEventListener('click', () => {
    $$('[data-intent]').forEach((item) => item.classList.toggle('active', item === button));
    renderDemo(button.dataset.intent);
  }));
  renderDemo('brief');

  const systemData = {
    voice: ['01', 'Voice native', 'Wake-word entry, streaming transcription, mode-aware speech, and progress updates make the system feel present before a screen is involved.', 'Wake word · microphone · API', 'Speech · status · actions'],
    web: ['02', 'Conversational workbench', 'A streaming chat surface for tools, files, images, workflows, voice playback, conversation search, exports, and live execution logs.', 'Text · files · images · speech', 'Streams · media · tool traces'],
    workflows: ['03', 'Deterministic workflows', 'Repeatable JSON pipelines lock tool order, retries, validation, and delivery so recurring tasks remain predictable and inspectable.', 'Command · schedule · API', 'Validated artifacts · alerts'],
    canvas: ['04', 'Durable Canvas', 'Research briefs, notes, status boards, and generated reports become organized artifacts instead of disappearing into a chat transcript.', 'Workflow · chat · API', 'Pages · visuals · collections'],
    memory: ['05', 'Persistent memory', 'Hybrid keyword and semantic retrieval spans knowledge, conversations, reminders, and scheduled work with separate cloud and local data boundaries.', 'Facts · history · schedules', 'Relevant context · reminders'],
    intelligence: ['06', 'Learning layer', 'Jarvis reflects on execution outcomes, records evidence-backed procedural insights, tracks tool performance, and learns from repairs without hiding provenance.', 'Experiences · feedback · traces', 'Insights · preferred sequences'],
    dashboard: ['07', 'Command center', 'The terminal dashboard brings service health, launch controls, logs, maintenance, and more than seventy operational commands into one navigable surface.', 'Keyboard · host state', 'Control · status · logs'],
    docs: ['08', 'Grounded documentation', 'A dedicated viewer makes the project’s documentation searchable and pairs it with an assistant grounded in the local docs tree.', 'Project documentation', 'Answers · source context']
  };
  const detail = $('[data-system-detail]');
  const renderSystem = (key) => {
    const data = systemData[key]; if (!data || !detail) return;
    detail.innerHTML = `<span class="detail-index">SURFACE / ${data[0]}</span><h3>${data[1]}</h3><p>${data[2]}</p><div><span>Input</span><b>${data[3]}</b></div><div><span>Output</span><b>${data[4]}</b></div>`;
  };
  $$('[data-system]').forEach((button) => button.addEventListener('click', () => {
    $$('[data-system]').forEach((item) => item.classList.toggle('active', item === button));
    renderSystem(button.dataset.system);
  }));

  const gallery = [
    { src: 'site/images/jarvis-web.webp', alt: 'Current Jarvis Web conversational interface', title: 'Conversational workbench', copy: 'Chat, tools, files, images, voice, and live execution telemetry—composed into one focused surface.' },
    { src: 'site/images/jarvis-canvas.webp', alt: 'Jarvis Canvas daily status report', title: 'Durable Canvas', copy: 'Living reports, notes, dashboards, and visual artifacts that remain useful after the conversation ends.' },
    { src: 'site/images/jarvis-tui.webp', alt: 'Jarvis terminal command dashboard', title: 'Terminal control center', copy: 'Search commands, inspect system output, and operate the entire stack without leaving the terminal.' },
    { src: 'site/images/jarvis-gallery.webp', alt: 'Jarvis generated asset gallery', title: 'Artifact gallery', copy: 'A polished, searchable home for generated media and the reports that use it.' },
    { src: 'site/images/jarvis-images.webp', alt: 'Jarvis image gallery with generated artwork', title: 'Image intelligence', copy: 'Generate, organize, inspect, and reuse visual output from one integrated surface.' },
    { src: 'site/images/jarvis-videos.webp', alt: 'Jarvis generated video gallery', title: 'Motion library', copy: 'Generated video stays browsable, playable, and connected to the system that created it.' }
  ];
  let galleryIndex = 0;
  const stageImage = $('[data-showcase-image]');
  const renderGallery = (index) => {
    galleryIndex = (index + gallery.length) % gallery.length;
    const item = gallery[galleryIndex];
    if (stageImage) { stageImage.style.opacity = '0'; setTimeout(() => { stageImage.src = item.src; stageImage.alt = item.alt; stageImage.style.opacity = '1'; }, 120); }
    $('[data-showcase-index]').textContent = `${String(galleryIndex + 1).padStart(2, '0')} / ${String(gallery.length).padStart(2, '0')}`;
    $('[data-showcase-title]').textContent = item.title; $('[data-showcase-copy]').textContent = item.copy;
    $$('[data-gallery-index]').forEach((button) => button.classList.toggle('active', Number(button.dataset.galleryIndex) === galleryIndex));
  };
  $$('[data-gallery-index]').forEach((button) => button.addEventListener('click', () => renderGallery(Number(button.dataset.galleryIndex))));

  const galleryDialog = $('[data-gallery-dialog]');
  const openGallery = () => {
    const item = gallery[galleryIndex];
    $('[data-dialog-image]').src = item.src; $('[data-dialog-image]').alt = item.alt; $('[data-dialog-caption]').textContent = item.title;
    if (galleryDialog && !galleryDialog.open) galleryDialog.showModal();
    document.body.classList.add('dialog-open');
  };
  const closeGallery = () => { galleryDialog?.close(); document.body.classList.remove('dialog-open'); };
  $('[data-gallery-open]')?.addEventListener('click', openGallery);
  $('[data-gallery-close]')?.addEventListener('click', closeGallery);
  $('[data-gallery-prev]')?.addEventListener('click', () => { renderGallery(galleryIndex - 1); openGallery(); });
  $('[data-gallery-next]')?.addEventListener('click', () => { renderGallery(galleryIndex + 1); openGallery(); });
  galleryDialog?.addEventListener('click', (event) => { if (event.target === galleryDialog) closeGallery(); });
  galleryDialog?.addEventListener('close', () => document.body.classList.remove('dialog-open'));

  const modeData = {
    local: [['MODEL PATH', 'Self-hosted Ollama'], ['SPEECH PATH', 'Local STT + TTS'], ['DATA BOUNDARY', 'Your machine'], 'Offline-capable profile'],
    cloud: [['MODEL PATH', 'xAI · OpenAI · Anthropic · Ollama Cloud'], ['SPEECH PATH', 'Cloud or self-hosted'], ['DATA BOUNDARY', 'Mode-isolated state'], 'Provider-aware routing']
  };
  const modeDisplay = $('[data-mode-display]');
  $$('[data-mode]').forEach((button) => button.addEventListener('click', () => {
    $$('[data-mode]').forEach((tab) => { const active = tab === button; tab.classList.toggle('active', active); tab.setAttribute('aria-selected', String(active)); });
    const data = modeData[button.dataset.mode];
    modeDisplay.innerHTML = `${data.slice(0,3).map(([label,value]) => `<div><span>${label}</span><b>${value}</b></div>`).join('')}<p><i></i>${data[3]}</p>`;
  }));

  const commandDialog = $('[data-command-dialog]');
  const commandInput = $('[data-command-input]');
  const commandItems = $$('[data-command-item]');
  let selectedCommand = 0;
  const selectCommand = (index) => {
    const visible = commandItems.filter((item) => !item.hidden);
    if (!visible.length) return;
    selectedCommand = (index + visible.length) % visible.length;
    commandItems.forEach((item) => item.classList.remove('selected'));
    visible[selectedCommand].classList.add('selected');
  };
  const openCommand = () => { commandDialog?.showModal(); document.body.classList.add('dialog-open'); setTimeout(() => commandInput?.focus(), 30); selectCommand(0); };
  const closeCommand = () => { commandDialog?.close(); document.body.classList.remove('dialog-open'); };
  $('[data-command-open]')?.addEventListener('click', openCommand);
  document.addEventListener('keydown', (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); commandDialog?.open ? closeCommand() : openCommand(); }
    if (commandDialog?.open && event.key === 'ArrowDown') { event.preventDefault(); selectCommand(selectedCommand + 1); }
    if (commandDialog?.open && event.key === 'ArrowUp') { event.preventDefault(); selectCommand(selectedCommand - 1); }
    if (commandDialog?.open && event.key === 'Enter') { const visible = commandItems.filter((item) => !item.hidden); if (visible[selectedCommand]) { event.preventDefault(); visible[selectedCommand].click(); } }
  });
  commandInput?.addEventListener('input', () => {
    const query = commandInput.value.trim().toLowerCase();
    commandItems.forEach((item) => { item.hidden = !item.textContent.toLowerCase().includes(query); });
    selectCommand(0);
  });
  commandItems.forEach((item) => item.addEventListener('click', closeCommand));
  commandDialog?.addEventListener('click', (event) => { if (event.target === commandDialog) closeCommand(); });
  commandDialog?.addEventListener('close', () => document.body.classList.remove('dialog-open'));

  $('[data-year]').textContent = String(new Date().getFullYear());
})();
