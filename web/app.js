(() => {
  'use strict';
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const state = { file: null, previewUrl: null, nativePhotoToken: null, classes: [], model: null, activeView: 'diagnose', requestPending: false, managedPhotos: false };
  let pickerOpen = false;
  const native = window.LeafwiseNative || null;
  const tokenKey = 'leafwise.client-token.v1';
  const imageInput = $('#fileInput');
  const cameraInput = $('#cameraInput');
  const MAX_BYTES = 10 * 1024 * 1024;

  function clientToken() {
    let token = localStorage.getItem(tokenKey);
    if (!token) {
      const bytes = new Uint8Array(32);
      crypto.getRandomValues(bytes);
      token = [...bytes].map((x) => x.toString(16).padStart(2, '0')).join('');
      localStorage.setItem(tokenKey, token);
    }
    return token;
  }

  function apiHeaders(extra = {}) { return { 'X-Client-Token': clientToken(), ...extra }; }
  async function requestJson(url, options = {}) {
    const response = await fetch(url, options);
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.detail || 'The request could not be completed.');
    return body;
  }

  function showToast(message) {
    const toast = $('#toast');
    toast.textContent = message;
    toast.classList.add('is-visible');
    clearTimeout(showToast.timer);
    showToast.timer = setTimeout(() => toast.classList.remove('is-visible'), 3200);
  }

  function setError(message) {
    const error = $('#uploadError');
    error.textContent = message || '';
    error.classList.toggle('is-hidden', !message);
  }

  function setPickerOpen(open) {
    pickerOpen = open;
    const disabled = open || state.requestPending;
    $('#browseButton').disabled = disabled;
    $('#cameraButton').disabled = disabled;
  }

  function setPhotoPreview(url, name = 'Photo selected', file = null, nativePhotoToken = null) {
    if (state.previewUrl && state.previewUrl.startsWith('blob:')) URL.revokeObjectURL(state.previewUrl);
    if (native && state.nativePhotoToken && state.nativePhotoToken !== nativePhotoToken && typeof native.releaseSelectedPhoto === 'function') {
      try { native.releaseSelectedPhoto(state.nativePhotoToken); } catch { /* A cache cleanup must not block a new selection. */ }
    }
    state.file = file;
    state.nativePhotoToken = nativePhotoToken;
    state.previewUrl = url;
    $('#previewImage').src = url;
    $('#previewName').textContent = name;
    $('#dropPrompt').classList.add('is-hidden');
    $('#photoPreview').classList.remove('is-hidden');
    $('#analyzeButton').disabled = false;
    setError('');
  }

  function clearPhoto() {
    setPickerOpen(false);
    if (state.previewUrl && state.previewUrl.startsWith('blob:')) URL.revokeObjectURL(state.previewUrl);
    if (native && state.nativePhotoToken && typeof native.releaseSelectedPhoto === 'function') {
      try { native.releaseSelectedPhoto(state.nativePhotoToken); } catch { /* The selection is already cleared from the UI. */ }
    }
    state.file = null; state.previewUrl = null; state.nativePhotoToken = null;
    $('#previewImage').removeAttribute('src');
    $('#photoPreview').classList.add('is-hidden');
    $('#dropPrompt').classList.remove('is-hidden');
    $('#analyzeButton').disabled = true;
    $('#fileInput').value = ''; $('#cameraInput').value = '';
  }

  function selectFile(file) {
    if (!file) return;
    if (!file.type.startsWith('image/')) { setError('Choose an image file such as JPEG, PNG, or WebP.'); return; }
    if (file.size > MAX_BYTES) { setError('Choose a photo that is 10 MB or smaller.'); return; }
    setPhotoPreview(URL.createObjectURL(file), file.name || 'Selected photo', file, null);
  }

  function setLoading(loading) {
    state.requestPending = loading;
    $('#loadingState').classList.toggle('is-hidden', !loading);
    $('#analyzeButton').classList.toggle('is-loading', loading);
    $('#analyzeButton').disabled = loading || (!state.file && !state.nativePhotoToken);
    $('#browseButton').disabled = loading || pickerOpen;
    $('#cameraButton').disabled = loading || pickerOpen;
  }

  let pendingNativeAnalysis = null;
  function settleNativeAnalysis(requestId, result, error = null) {
    const pending = pendingNativeAnalysis;
    if (!pending || pending.requestId !== requestId) return;
    pendingNativeAnalysis = null;
    clearTimeout(pending.timeout);
    if (error) pending.reject(error); else pending.resolve(result);
  }
  window.onNativeAnalysis = (requestId, result) => settleNativeAnalysis(requestId, result);
  window.onNativeFailure = (requestId, message) => settleNativeAnalysis(requestId, null, new Error(message || 'On-device analysis failed. Please try again.'));
  window.onNativePickerFailure = (message) => {
    setPickerOpen(false);
    const text = message || 'The photo could not be opened. Please try again.';
    setError(text); showToast(text);
  };
  window.onNativePickerClosed = () => setPickerOpen(false);

  function openPhotoPicker(kind) {
    if (state.requestPending || pickerOpen) return;
    setPickerOpen(true);
    if (native && typeof native.openGallery === 'function' && typeof native.openCamera === 'function') {
      try { kind === 'camera' ? native.openCamera() : native.openGallery(); }
      catch (error) { window.onNativePickerFailure(error.message || 'Could not open the photo picker. Please try again.'); }
      return;
    }
    const input = kind === 'camera' ? cameraInput : imageInput;
    input.value = '';
    input.click();
  }

  function textElement(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    element.textContent = text || '';
    return element;
  }

  function safeHttps(url) {
    try { const parsed = new URL(url); return parsed.protocol === 'https:' ? parsed.href : null; } catch { return null; }
  }

  function renderPrediction(result) {
    const primary = result.primary;
    if (!primary || !result.care) throw new Error('The API returned an incomplete prediction.');
    $('#resultEmpty').classList.add('is-hidden');
    $('#resultContent').classList.remove('is-hidden');
    $('#resultHeading').textContent = primary.healthy ? 'A healthy-looking result' : 'A possible condition';
    $('#resultCrop').textContent = primary.crop;
    $('#resultDisease').textContent = primary.disease;
    $('#scoreValue').textContent = `${Math.round(primary.score * 100)}%`;
    $('#resultNotice').textContent = result.notice || 'Model scores rank supported classes; they do not confirm a diagnosis.';
    const meter = document.querySelector('.score-ring');
    meter.style.setProperty('--score-angle', `${Math.max(0, Math.min(360, primary.score * 360))}deg`);
    const ranked = $('#rankedResults'); ranked.replaceChildren();
    result.predictions.forEach((item, index) => {
      const row = document.createElement('div'); row.className = 'ranked-row';
      const label = textElement('span', 'rank-label', `${String(index + 1).padStart(2, '0')}  ${item.display_name}`);
      const score = textElement('span', 'rank-score', `${Math.round(item.score * 100)}%`);
      row.append(label, score); ranked.append(row);
    });
    const care = result.care;
    $('#careTitle').textContent = care.healthy ? 'Routine care — no disease treatment indicated' : care.display_name;
    $('#oneMethod').textContent = care.one_method;
    $('#careCaution').textContent = care.caution;
    const details = $('#careDetails'); details.replaceChildren();
    const immediateHeading = textElement('h5', 'care-subheading', 'What to do now');
    const immediate = document.createElement('ul');
    (care.immediate_steps || []).forEach((step) => immediate.append(textElement('li', '', step)));
    if (immediate.children.length) details.append(immediateHeading, immediate);
    const preventionHeading = textElement('h5', 'care-subheading', 'Prevention and follow-up');
    const prevention = document.createElement('ul');
    (care.prevention || []).forEach((step) => prevention.append(textElement('li', '', step)));
    if (prevention.children.length) details.append(preventionHeading, prevention);
    const sources = $('#careSources'); sources.replaceChildren();
    (care.references || []).forEach((reference) => {
      const url = safeHttps(reference.url);
      if (!url) return;
      const link = document.createElement('a'); link.href = url; link.target = '_blank'; link.rel = 'noopener noreferrer';
      if (native) link.addEventListener('click', (event) => { event.preventDefault(); native.openExternal(url); });
      link.textContent = reference.title || 'Agricultural extension source';
      link.append(textElement('span', 'source-arrow', ' ↗'));
      sources.append(link);
    });
    $('#resultPanel').scrollIntoView({ behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start' });
    if (result.saved) showToast('Report and photo saved to My history.');
    else if (result.save_warning) showToast(result.save_warning);
  }

  async function analyze() {
    if (state.requestPending || (!state.file && !state.nativePhotoToken)) return;
    setError(''); setLoading(true);
    try {
      let result;
      if (native && state.nativePhotoToken) {
        const requestId = `leafwise-${Date.now()}-${Math.random().toString(36).slice(2)}`;
        result = await new Promise((resolve, reject) => {
          const timeout = setTimeout(() => {
            if (pendingNativeAnalysis?.requestId === requestId) {
              pendingNativeAnalysis = null;
              reject(new Error('On-device inference took too long. Please try again.'));
            }
          }, 45000);
          pendingNativeAnalysis = { requestId, resolve, reject, timeout };
          try { native.analyzeImage(state.nativePhotoToken, $('#saveToggle').checked ? 'true' : 'false', requestId); }
          catch (error) { settleNativeAnalysis(requestId, null, new Error(error.message || 'On-device analysis failed.')); }
        });
      } else {
        const body = new FormData();
        body.append('image', state.file, state.file.name || 'leaf-photo');
        body.append('top_k', '3');
        body.append('save_to_history', String($('#saveToggle').checked));
        result = await requestJson('/api/predict', { method: 'POST', headers: apiHeaders(), body });
      }
      renderPrediction(result);
    } catch (error) {
      setError(error.message || 'We could not analyze that photo. Try another clear image.');
      showToast('Analysis did not finish. Check the photo and try again.');
    } finally { setLoading(false); }
  }

  function showView(name) {
    if (!document.querySelector(`[data-view="${name}"]`)) return;
    state.activeView = name;
    $$('[data-view]').forEach((view) => view.classList.toggle('is-active', view.dataset.view === name));
    $$('[data-view-link]').forEach((button) => button.classList.toggle('is-active', button.dataset.viewLink === name));
    if (name === 'history') loadHistory();
    if (name === 'library') renderClasses();
    window.scrollTo({ top: 0, behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
  }

  function renderClasses() {
    const query = ($('#classSearch').value || '').trim().toLowerCase();
    const cropFilter = $('#cropFilter').value;
    const matches = state.classes.filter((item) => (!cropFilter || item.crop === cropFilter) && (!query || `${item.crop} ${item.disease} ${item.display_name}`.toLowerCase().includes(query)));
    const list = $('#classList'); list.replaceChildren();
    matches.forEach((item) => {
      const card = document.createElement('article'); card.className = 'class-card';
      const badge = textElement('span', 'class-crop', item.crop);
      const title = textElement('h3', '', item.disease);
      const summary = textElement('p', '', item.summary);
      const method = document.createElement('div'); method.className = 'class-method';
      method.append(textElement('span', 'method-label', item.healthy ? 'ROUTINE CARE' : 'ONE SUGGESTED METHOD'), textElement('p', '', item.one_method));
      const sources = document.createElement('div'); sources.className = 'class-source-count';
      sources.textContent = `${(item.references || []).length} source${(item.references || []).length === 1 ? '' : 's'} · ${item.healthy ? 'healthy class' : 'condition class'}`;
      card.append(badge, title, summary, method, sources); list.append(card);
    });
    $('#filteredCount').textContent = `${matches.length} of ${state.classes.length} classes`;
    $('#classCount').textContent = state.classes.length;
  }

  async function loadHistory() {
    const list = $('#historyList');
    list.innerHTML = '<div class="history-loading"><span class="spinner"></span> Loading saved reports…</div>';
    try {
      let records;
      if (native) records = JSON.parse(native.getHistory() || '[]');
      else {
        const data = await requestJson('/api/history', { headers: apiHeaders() });
        records = data.items || [];
      }
      list.replaceChildren();
      if (!records.length) {
        const empty = document.createElement('div'); empty.className = 'history-empty';
        empty.append(textElement('span', 'empty-history-glyph', '↗'), textElement('h3', '', 'No saved reports yet'), textElement('p', '', 'Turn on “Save this report and photo” when you analyze a leaf to keep a report here.'));
        list.append(empty); return;
      }
      records.forEach((record) => {
        const item = document.createElement('article'); item.className = 'history-card';
        const date = new Date(record.created_at || Date.now());
        const title = textElement('h3', '', record.display_name || record.primary?.display_name || record.label || 'Saved diagnosis');
        const stamp = textElement('span', 'history-date', date.toLocaleString());
        const score = textElement('span', 'history-score', `${Math.round((record.score ?? record.primary?.score ?? 0) * 100)}% model score`);
        const method = textElement('p', '', record.care?.one_method || record.one_method || 'Care guidance is available in the class library.');
        const remove = textElement('button', 'text-button history-remove', state.managedPhotos ? 'Hide' : 'Remove'); remove.type = 'button'; remove.title = state.managedPhotos ? 'Hide this report; the stored photo remains in project storage.' : 'Remove this report and its local photo.'; remove.addEventListener('click', () => removeHistory(record.id));
        const body = document.createElement('div'); body.className = 'history-body'; body.append(stamp, title, score, method);
        const actions = document.createElement('div'); actions.className = 'history-actions';
        if (record.image_available) {
          const view = textElement('button', 'text-button', 'View photo'); view.type = 'button';
          const photo = document.createElement('div'); photo.className = 'history-photo is-hidden';
          view.addEventListener('click', () => showHistoryPhoto(record, photo, view));
          actions.append(view, remove); item.append(body, actions, photo);
        } else item.append(body, remove);
        list.append(item);
      });
    } catch (error) {
      list.replaceChildren(textElement('p', 'error-message', error.message || 'History could not be loaded.'));
    }
  }

  async function removeHistory(id) {
    try {
      let outcome;
      if (native) {
        if (!native.deleteHistory(String(id))) throw new Error('Could not remove the report or its photo from this device.');
        outcome = { photo_removed: true };
      }
      else outcome = await requestJson(`/api/history/${encodeURIComponent(id)}`, { method: 'DELETE', headers: apiHeaders() });
      showToast(outcome.photo_removed ? 'Saved report and photo removed.' : 'Report hidden from history; its photo remains in project storage.');
      await loadHistory();
    } catch (error) { showToast(error.message || 'Could not remove this report.'); }
  }

  async function showHistoryPhoto(record, container, button) {
    if (!container.classList.contains('is-hidden')) {
      container.classList.add('is-hidden'); button.textContent = 'View photo'; return;
    }
    try {
      let source;
      if (native) {
        const encoded = native.getHistoryImage(String(record.id));
        if (!encoded) throw new Error('Saved photo not found.');
        source = `data:image/jpeg;base64,${encoded}`;
      } else {
        const response = await fetch(`/api/history/${encodeURIComponent(record.id)}/image`, { headers: apiHeaders() });
        if (!response.ok) { const body = await response.json().catch(() => ({})); throw new Error(body.detail || 'Could not load the saved photo.'); }
        source = URL.createObjectURL(await response.blob());
      }
      const image = document.createElement('img'); image.src = source; image.alt = 'Saved plant photo';
      container.replaceChildren(image); container.classList.remove('is-hidden'); button.textContent = 'Hide photo';
    } catch (error) { showToast(error.message || 'Could not load the saved photo.'); }
  }

  async function initialize() {
    try {
      let data;
      if (native) {
        data = JSON.parse(native.getClasses());
        const consentNote = $('#saveToggle').parentElement.querySelector('small');
        if (consentNote) consentNote.textContent = 'Optional. Kept in this app’s private storage; removing the report erases its saved photo.';
        $('#retentionNote').textContent = 'Saved reports and photos stay in this app’s private storage. Remove a report to erase both.';
        $('.api-card')?.classList.add('is-hidden');
      }
      else data = await requestJson('/api/classes');
      state.classes = data.classes || data;
      const crops = [...new Set(state.classes.map((item) => item.crop))].sort((a, b) => a.localeCompare(b));
      const filter = $('#cropFilter');
      crops.forEach((crop) => { const option = document.createElement('option'); option.value = crop; option.textContent = crop; filter.append(option); });
      renderClasses();
      if (!native) {
        const [health, model] = await Promise.all([requestJson('/api/health'), requestJson('/api/model')]);
        state.model = model;
        state.managedPhotos = Boolean(health.managed_image_storage);
        const consentNote = $('#saveToggle').parentElement.querySelector('small');
        if (consentNote) consentNote.textContent = state.managedPhotos
          ? 'Optional. Saved to project storage; hiding the report does not erase its photo.'
          : 'Optional. Saved on this server; removing the report also deletes its local photo.';
        $('#retentionNote').textContent = state.managedPhotos
          ? 'Managed photos remain in project storage when you hide a report; a project owner must remove the stored object.'
          : 'Removing a local report also deletes its saved photo.';
        $('#modelStatus').textContent = health.model_ready ? '38-class model ready' : 'Model unavailable';
        const reported = model.metrics?.accuracy ?? model.metrics?.reported_validation_accuracy;
        if (reported) $('#classCount').title = `Repository-reported validation accuracy: ${reported}; not independently reproduced.`;
      } else $('#modelStatus').textContent = 'On-device model · offline';
    } catch (error) {
      $('#modelStatus').textContent = 'Model unavailable';
      setError(error.message || 'The model service is not reachable. Start the local API and refresh.');
    }
  }

  $('#browseButton').addEventListener('click', (event) => { event.stopPropagation(); openPhotoPicker('gallery'); });
  $('#cameraButton').addEventListener('click', (event) => { event.stopPropagation(); openPhotoPicker('camera'); });
  $('#dropzone').addEventListener('click', (event) => { if (!state.requestPending && !event.target.closest('button') && !event.target.closest('.text-button')) openPhotoPicker('gallery'); });
  $('#dropzone').addEventListener('keydown', (event) => { if (!state.requestPending && (event.key === 'Enter' || event.key === ' ') && !event.target.closest('button')) { event.preventDefault(); openPhotoPicker('gallery'); } });
  const handleFileInputChange = (event) => { setPickerOpen(false); selectFile(event.target.files?.[0]); event.target.value = ''; };
  imageInput.addEventListener('change', handleFileInputChange);
  cameraInput.addEventListener('change', handleFileInputChange);
  window.addEventListener('focus', () => { if (pickerOpen) setTimeout(() => setPickerOpen(false), 500); });
  $('#removePhoto').addEventListener('click', clearPhoto);
  $('#analyzeButton').addEventListener('click', analyze);
  $('#newAnalysis').addEventListener('click', () => { clearPhoto(); window.scrollTo({ top: 0, behavior: 'smooth' }); });
  $('#classSearch').addEventListener('input', renderClasses);
  $('#cropFilter').addEventListener('change', renderClasses);
  $('#refreshHistory').addEventListener('click', loadHistory);
  $$('[data-view-link]').forEach((button) => button.addEventListener('click', () => showView(button.dataset.viewLink)));
  ['dragenter', 'dragover'].forEach((eventName) => $('#dropzone').addEventListener(eventName, (event) => { event.preventDefault(); $('#dropzone').classList.add('is-dragging'); }));
  ['dragleave', 'drop'].forEach((eventName) => $('#dropzone').addEventListener(eventName, (event) => { event.preventDefault(); $('#dropzone').classList.remove('is-dragging'); }));
  $('#dropzone').addEventListener('drop', (event) => selectFile(event.dataTransfer?.files?.[0]));
  window.onNativeImage = (token, mime = 'image/jpeg', name = 'Camera photo') => {
    setPickerOpen(false);
    if (!native || !/^[0-9a-f-]{36}$/i.test(token)) { window.onNativePickerFailure('The selected photo could not be loaded. Choose it again.'); return; }
    const extension = mime === 'image/png' ? 'png' : 'jpg';
    setPhotoPreview(`https://appassets.androidplatform.net/selected/${encodeURIComponent(token)}.${extension}`, name, null, token);
  };
  document.addEventListener('keydown', (event) => { if (event.key === 'Escape' && (state.file || state.nativePhotoToken)) clearPhoto(); });
  initialize();
})();
