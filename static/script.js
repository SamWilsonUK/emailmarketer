(() => {
  // ── Elements ──
  const briefEl       = document.getElementById('brief');
  const brandUrlEl    = document.getElementById('brand-url');
  const btnExtract    = document.getElementById('btn-extract');
  const colorStatus   = document.getElementById('color-status');
  const swatchesEl    = document.getElementById('color-swatches');
  const btnGenerate   = document.getElementById('btn-generate');
  const genStatus     = document.getElementById('generate-status');
  const frame         = document.getElementById('preview-frame');
  const emptyState    = document.getElementById('preview-empty');
  const btnDownload   = document.getElementById('btn-download');
  const viewBtns      = document.querySelectorAll('.view-btn');

  let extractedColors = {};
  let currentHtml     = '';

  // ── Utilities ──
  function setStatus(el, msg, type) {
    el.textContent = msg;
    el.className   = `color-status status--${type}`;
    el.classList.remove('hidden');
  }

  function spinner(label) {
    return `<span class="spinner"></span> ${label}`;
  }

  function renderSwatches(colors) {
    swatchesEl.innerHTML = '';
    colors.forEach(hex => {
      const div = document.createElement('div');
      div.className = 'swatch';
      div.style.backgroundColor = hex;
      div.setAttribute('data-color', hex);
      div.title = hex;
      swatchesEl.appendChild(div);
    });
    swatchesEl.classList.toggle('hidden', colors.length === 0);
  }

  // ── Extract colours ──
  async function extractColors() {
    const url = brandUrlEl.value.trim();
    if (!url) {
      setStatus(colorStatus, 'Please enter a website URL first.', 'error');
      return;
    }

    btnExtract.disabled = true;
    btnExtract.innerHTML = spinner('Extracting…');
    setStatus(colorStatus, 'Fetching brand colours…', 'loading');
    swatchesEl.classList.add('hidden');

    try {
      const res  = await fetch('/api/extract-colors', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ url }),
      });
      const data = await res.json();

      if (data.error) throw new Error(data.error);

      extractedColors = data;

      if (data.colors && data.colors.length > 0) {
        setStatus(colorStatus, `Found ${data.colors.length} brand colour${data.colors.length !== 1 ? 's' : ''}.`, 'success');
        renderSwatches(data.colors);
      } else {
        setStatus(colorStatus, 'No distinct brand colours found — Claude will choose.', 'success');
      }
    } catch (err) {
      setStatus(colorStatus, `Error: ${err.message}`, 'error');
      extractedColors = {};
    } finally {
      btnExtract.disabled = false;
      btnExtract.innerHTML = `<svg viewBox="0 0 20 20" fill="currentColor" width="16" height="16"><path d="M10 2a8 8 0 100 16A8 8 0 0010 2zm1 11H9v-2h2v2zm0-4H9V7h2v2z"/></svg> Extract`;
    }
  }

  // ── Generate email ──
  async function generateEmail() {
    const brief    = briefEl.value.trim();
    const brandUrl = brandUrlEl.value.trim();

    if (!brief) {
      setStatus(genStatus, 'Please enter a marketing brief.', 'error');
      genStatus.classList.remove('hidden');
      briefEl.focus();
      return;
    }

    // If a URL is entered but colours haven't been extracted, do it now
    if (brandUrl && !extractedColors.colors) {
      await extractColors();
    }

    btnGenerate.disabled = true;
    btnGenerate.innerHTML = spinner('Generating email…');
    genStatus.innerHTML   = '';
    genStatus.classList.add('hidden');

    try {
      const res  = await fetch('/api/generate', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({
          brief,
          brand_url: brandUrl,
          colors:    extractedColors,
        }),
      });
      const data = await res.json();

      if (!res.ok || data.error) throw new Error(data.error || 'Unknown error');

      currentHtml = data.html;
      showPreview(currentHtml);
      btnDownload.disabled = false;

    } catch (err) {
      setStatus(genStatus, `Error: ${err.message}`, 'error');
    } finally {
      btnGenerate.disabled = false;
      btnGenerate.innerHTML = `<svg viewBox="0 0 20 20" fill="currentColor" width="18" height="18"><path d="M13.586 3.586a2 2 0 112.828 2.828l-.793.793-2.828-2.828.793-.793zM11.379 5.793L3 14.172V17h2.828l8.38-8.379-2.83-2.828z"/></svg> Generate Email`;
    }
  }

  // ── Preview rendering ──
  function showPreview(html) {
    emptyState.classList.add('hidden');
    frame.classList.remove('hidden');

    const blob = new Blob([html], { type: 'text/html' });
    const blobUrl = URL.createObjectURL(blob);
    frame.src = blobUrl;

    // Set initial height after load
    frame.onload = () => {
      try {
        const doc = frame.contentDocument || frame.contentWindow.document;
        const h = doc.documentElement.scrollHeight || doc.body.scrollHeight;
        frame.style.height = Math.max(h, 400) + 'px';
      } catch (_) {
        frame.style.height = '600px';
      }
    };
  }

  // ── Viewport toggle ──
  viewBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      viewBtns.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      const w = btn.dataset.width;
      frame.style.width = w + 'px';
    });
  });

  // Set initial frame width
  frame.style.width = '600px';

  // ── Download ──
  btnDownload.addEventListener('click', () => {
    if (!currentHtml) return;
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([currentHtml], { type: 'text/html' }));
    a.download = 'email-design.html';
    a.click();
  });

  // ── Event listeners ──
  btnExtract.addEventListener('click', extractColors);
  btnGenerate.addEventListener('click', generateEmail);

  // Allow Enter in URL field to trigger extraction
  brandUrlEl.addEventListener('keydown', e => {
    if (e.key === 'Enter') { e.preventDefault(); extractColors(); }
  });

  // Prompt for URL if user clicks Generate without one
  btnGenerate.addEventListener('click', () => {
    const url = brandUrlEl.value.trim();
    const brief = briefEl.value.trim();
    if (brief && !url) {
      brandUrlEl.placeholder = 'Enter your brand website to extract colours (or leave blank)';
      brandUrlEl.focus();
    }
  }, { capture: true });
})();
