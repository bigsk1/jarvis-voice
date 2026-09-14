import { resolveSource } from './source.js';

export const MAX_CAPTURE_DIMENSION = 1024;

export function scaledDimensions(width, height, maximum = MAX_CAPTURE_DIMENSION) {
  if (![width, height, maximum].every(value => Number.isFinite(value) && value > 0)) {
    throw new Error('The screenshot has invalid dimensions.');
  }
  const ratio = Math.min(1, maximum / Math.max(width, height));
  return {
    width: Math.max(1, Math.floor(width * ratio)),
    height: Math.max(1, Math.floor(height * ratio)),
  };
}

function decodeImage(dataUrl) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error('The captured screenshot could not be decoded. Try capturing again.'));
    image.src = dataUrl;
  });
}

/** Capture and stage locally. Sending or uploading is a separate user action. */
export async function captureSource(browserApi, source, helpers = {}) {
  if (!source) throw new Error('Select the source tab before capturing.');
  const before = await resolveSource(browserApi, source);
  let dataUrl;
  try {
    dataUrl = await browserApi.tabs.captureVisibleTab(before.windowId, { format: 'png' });
  } catch {
    throw new Error('Firefox could not capture this tab. Click the Jarvis toolbar icon or its page menu to grant access, then try again.');
  }
  // captureVisibleTab takes a window ID: recheck the tab and discard results if
  // its window was minimized during capture. There is no desktop capture fallback.
  const after = await resolveSource(browserApi, before);
  const image = await (helpers.decodeImage || decodeImage)(dataUrl);
  try {
    const { width, height } = scaledDimensions(
      image.naturalWidth ?? image.width,
      image.naturalHeight ?? image.height,
    );
    const canvas = (helpers.createCanvas || (() => document.createElement('canvas')))();
    canvas.width = width;
    canvas.height = height;
    const context = canvas.getContext('2d');
    if (!context) throw new Error('Firefox could not prepare the screenshot preview.');
    // Match Jarvis's JPEG upload contract and avoid black transparent areas.
    context.fillStyle = '#ffffff';
    context.fillRect(0, 0, width, height);
    context.drawImage(image, 0, 0, width, height);
    const previewUrl = canvas.toDataURL('image/jpeg', 0.85);
    if (!previewUrl.startsWith('data:image/jpeg;')) {
      throw new Error('Firefox could not encode the screenshot preview.');
    }
    return {
      previewUrl,
      width,
      height,
      source: after,
      capturedAt: (helpers.now || (() => new Date().toISOString()))(),
    };
  } finally {
    image.close?.();
  }
}
