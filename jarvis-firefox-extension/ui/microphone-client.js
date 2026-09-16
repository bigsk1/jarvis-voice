/** Firefox can leave sidebar getUserMedia pending, even with a saved grant.
 * Capture in our visible extension tab; the sidebar owns recording and playback.
 */
export async function requestMicrophone(constraints, {signal, onClosed} = {}) {
  if (!browser.extension.getViews({type: 'sidebar'}).includes(window)) {
    return navigator.mediaDevices.getUserMedia(constraints);
  }
  const url = browser.runtime.getURL('ui/microphone.html');
  const ownWindow = await browser.windows.getCurrent();
  const helper = browser.extension.getViews({type: 'tab', windowId: ownWindow.id}).find(view =>
    view.location.href === url && typeof view.jarvisRequestMicrophone === 'function');
  if (!helper) return Promise.reject(new DOMException('Open Microphone setup from Settings first.', 'NotAllowedError'));
  if (signal?.aborted) return Promise.reject(new DOMException('Talk stopped', 'AbortError'));
  if (onClosed) helper.addEventListener('pagehide', onClosed, {once: true, signal});
  return helper.jarvisRequestMicrophone(constraints, {signal});
}
