---
tool_hints:
  - generate_video
---

# Image-to-Video Face Consistency

## Core Directive

Maintain **exact facial features, structure, eyes, hair, and clothing** from the reference image throughout all frames. No changes to appearance. The character must remain visually identical to the source image from start to finish.

## Preservation Rules

- Keep face structure, bone geometry, and proportions locked to reference
- Eyes: same shape, color, spacing, and expression baseline
- Hair: identical style, length, color, and movement physics
- Skin: consistent tone, texture, and lighting response
- Clothing: unchanged design, fit, and colors

## Motion Guidelines

- Prefer subtle, controlled movements over aggressive action
- Limit head rotation to minimize angle-induced distortion
- Front-facing or 3/4 view preferred for face stability
- Allow environmental/background motion while character stays anchored
- Camera movement (pan, zoom, orbit) should be smooth and gradual

## Recommended Techniques

- **Static pose + dynamic scene**: Character holds position while background animates
- **Slow zoom**: Gradual zoom on unchanging face with shifting background
- **Minimal expression change**: Subtle movements only (blink, slight smile)
- **Camera orbit**: Fixed character, camera moves around them

## Technical Specs

- Photorealistic, high fidelity
- Cinematic lighting with no facial distortions
- Consistent character from reference across entire duration
- No morphing, warping, or feature drift

---

Apply these strategies to the user's request below: 
