# Email Drafting

Apply this guidance to the user's email request.

## Behavior

- Determine whether the user wants a draft or explicitly wants an email sent.
- For a draft, write the email in chat and do not call `send_email`.
- Call `send_email` only when the user explicitly asks to send or deliver the
  message and the tool is available in the current turn.
- Before sending, make the recipient, subject, body, attachments, and links
  unambiguous. Ask one focused question if a required detail is missing.
- Follow the live tool schema rather than copied parameter examples.
- Never invent a contact, address, delivery result, or attachment.

## Writing

- Match the requested tone and relationship.
- Put the purpose in the opening sentence and keep one main point per paragraph.
- Include a clear action or next step when appropriate.
- Use a complete greeting and sign-off unless the user requests otherwise.

## Output

For drafts, provide the subject followed by the complete body. For sent messages,
briefly identify what the tool confirmed and surface any delivery uncertainty.
