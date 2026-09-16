const button = document.getElementById('allow-microphone');
const status = document.getElementById('microphone-status');
let activeStream = null;
let pending = false;
let closed = false;

// Same-extension views can use this tab's native capture context. No audio is
// passed to another origin or uploaded by this helper.
window.jarvisRequestMicrophone = async (constraints, {signal} = {}) => {
  if (pending || activeStream?.getTracks().some(track => track.readyState === 'live')) {
    throw new Error('Microphone is already in use. Pause Talk before checking it.');
  }
  pending = true;
  let previousTab = null;
  let ownTab = null;
  let switched = false;
  const restoreTab = async () => {
    if (!switched) return;
    switched = false;
    try {
      const [active] = await browser.tabs.query({active: true, windowId: ownTab.windowId});
      // Respect a tab change the user made while answering a permission prompt.
      if (active?.id === ownTab.id) await browser.tabs.update(previousTab.id, {active: true});
    } catch { /* The user may have closed the previous tab or its window. */ }
  };
  const abort = () => { void restoreTab(); };
  const assertCurrent = () => {
    if (closed || signal?.aborted) throw new DOMException('Talk stopped', 'AbortError');
  };
  try {
    assertCurrent();
    ownTab = await browser.tabs.getCurrent();
    [previousTab] = await browser.tabs.query({active: true, windowId: ownTab.windowId});
    assertCurrent();
    if (previousTab && previousTab.id !== ownTab.id) {
      // Firefox defers even remembered capture grants until this tab is selected.
      switched = true;
      await browser.tabs.update(ownTab.id, {active: true});
    }
    signal?.addEventListener('abort', abort, {once: true});
    assertCurrent();
    const stream = await navigator.mediaDevices.getUserMedia(constraints);
    if (closed || signal?.aborted) {
      stream.getTracks().forEach(track => track.stop());
      throw new DOMException('Talk stopped', 'AbortError');
    }
    activeStream = stream;
    return stream;
  } finally {
    signal?.removeEventListener('abort', abort);
    await restoreTab();
    pending = false;
  }
};
window.addEventListener('pagehide', () => {
  closed = true;
  activeStream?.getTracks().forEach(track => track.stop());
});

button.addEventListener('click', async () => {
  button.disabled = true;
  status.textContent = 'Choose Allow in the Firefox microphone prompt.';
  try {
    const stream = await window.jarvisRequestMicrophone({audio: true});
    stream.getTracks().forEach(track => track.stop());
    activeStream = null;
    status.textContent = 'Microphone ready. Keep this tab open, return to the Jarvis sidebar, and press Talk or Resume.';
  } catch (error) {
    status.textContent = error.name === 'NotAllowedError' ? 'Microphone access was not allowed. Try again when ready.' : error.message || 'The microphone is unavailable. Check your device and Firefox settings.';
  } finally { button.disabled = false; }
});
