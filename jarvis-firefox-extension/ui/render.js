import { displayTime, inlineParts, messageBlocks, safePreviewUrl } from './view-model.js';

function element(document, tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

export function renderMessageContent(document, content) {
  const fragment = document.createDocumentFragment();
  for (const block of messageBlocks(content)) {
    if (block.type === 'code') {
      const wrapper = element(document, 'div', 'code-block');
      const heading = element(document, 'div', 'code-heading');
      heading.append(element(document, 'span', '', block.language || 'Code'));
      const pre = element(document, 'pre');
      pre.append(element(document, 'code', '', block.text));
      wrapper.append(heading, pre);
      fragment.append(wrapper);
      continue;
    }
    for (const paragraph of block.text.split(/\n\s*\n/).filter(text => text.trim())) {
      const p = element(document, 'p');
      for (const part of inlineParts(paragraph)) {
        if (part.type === 'text') p.append(document.createTextNode(part.text));
        else {
          const node = element(document, part.type === 'link' ? 'a' : part.type, '', part.text);
          if (part.type === 'link') {
            node.href = part.href;
            node.target = '_blank';
            node.rel = 'noopener noreferrer';
          }
          p.append(node);
        }
      }
      fragment.append(p);
    }
  }
  return fragment;
}

export function renderMessage(document, message) {
  const role = message.role === 'user' ? 'user' : message.role === 'assistant' ? 'assistant' : 'system';
  const article = element(document, 'article', 'message');
  article.dataset.role = role;
  const header = element(document, 'div', 'message-header');
  const avatar = element(document, 'span', 'message-avatar');
  avatar.setAttribute('aria-hidden', 'true');
  if (role === 'assistant') {
    const icon = element(document, 'img');
    icon.src = '../assets/jarvis.svg';
    icon.alt = '';
    avatar.append(icon);
  } else avatar.textContent = role === 'user' ? 'Y' : '•';
  header.append(avatar, element(document, 'span', '', role === 'user' ? 'You' : role === 'assistant' ? 'Jarvis' : 'Notice'));
  const time = displayTime(message.createdAt || message.created_at || message.timestamp);
  if (time) header.append(element(document, 'span', 'message-time', time));
  article.append(header);
  if (Array.isArray(message.attachments) && message.attachments.length) {
    const attachments = element(document, 'div', 'message-attachments');
    for (const attachment of message.attachments) {
      const item = element(document, 'div', 'message-attachment');
      const preview = safePreviewUrl(attachment?.previewUrl);
      if (preview) {
        const image = element(document, 'img');
        image.src = preview;
        image.alt = attachment.filename || attachment.title || 'Attached screenshot';
        item.append(image);
      } else item.textContent = attachment?.filename || attachment?.title || attachment?.label || 'Attached source';
      attachments.append(item);
    }
    article.append(attachments);
  }
  const body = element(document, 'div', 'message-body');
  body.append(renderMessageContent(document, message.content));
  article.append(body);
  return article;
}
