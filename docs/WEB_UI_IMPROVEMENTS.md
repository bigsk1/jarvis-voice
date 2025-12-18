# Jarvis Web UI - Design Improvements

## Holographic Glow Refinements

### Current State
- Bright cyan (#00FFFF) glow around assistant messages
- High intensity can cause eye strain
- Applied uniformly regardless of context

### Proposed Changes

#### 1. **Subtle, Context-Aware Glow**

```css
/* Instead of always-on bright glow, use: */

/* Resting state - minimal glow */
.message.assistant .message-bubble {
  background: var(--bg-card);
  border: 1px solid rgba(0, 255, 255, 0.15);  /* Subtle cyan tint */
  box-shadow: 
    0 0 1px rgba(0, 255, 255, 0.2),
    0 2px 8px rgba(0, 0, 0, 0.4);  /* Depth, not glow */
}

/* Hover state - gentle glow appears */
.message.assistant .message-bubble:hover {
  border-color: rgba(0, 255, 255, 0.3);
  box-shadow: 
    0 0 12px rgba(0, 255, 255, 0.15),  /* Softer glow */
    0 4px 12px rgba(0, 0, 0, 0.5);
}

/* Active/New message - brief bright glow that fades */
@keyframes message-arrival {
  0% {
    box-shadow: 0 0 20px rgba(0, 255, 255, 0.6);
    border-color: rgba(0, 255, 255, 0.5);
  }
  100% {
    box-shadow: 0 0 1px rgba(0, 255, 255, 0.2);
    border-color: rgba(0, 255, 255, 0.15);
  }
}

.message.assistant.new-message .message-bubble {
  animation: message-arrival 2s ease-out forwards;
}
```

#### 2. **Strategic Glow Application**

```css
/* Only apply glow to specific elements that benefit from it */

/* Tool cards - minimal glow on success */
.tool-card.success {
  border-left: 2px solid rgba(16, 185, 129, 0.5);  /* Green accent */
  /* NO glow - just colored border */
}

/* Status indicators - subtle pulse */
.status-dot.connected {
  background: var(--success);
  box-shadow: 
    0 0 4px rgba(16, 185, 129, 0.4),  /* Smaller radius */
    0 0 8px rgba(16, 185, 129, 0.2);  /* Softer outer glow */
  animation: pulse-dot 2s ease-in-out infinite;
}

@keyframes pulse-dot {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.7; }
}

/* Input focus - cyan accent without full glow */
.chat-input:focus {
  border-color: rgba(0, 255, 255, 0.4);
  box-shadow: 
    0 0 0 2px rgba(0, 255, 255, 0.1),  /* Focus ring */
    0 2px 8px rgba(0, 0, 0, 0.3);  /* Depth */
}
```

#### 3. **Refined Color Palette**

```css
:root {
  /* Tone down the cyan */
  --cyber-cyan-bright: #00FFFF;      /* Reserve for accents only */
  --cyber-cyan: #00D9FF;             /* Slightly darker, less harsh */
  --cyber-cyan-muted: #00B8D4;       /* Main UI elements */
  --cyber-cyan-subtle: rgba(0, 216, 255, 0.15);  /* Borders/glows */
  
  /* Add complementary accent */
  --cyber-purple: #B24BF3;           /* For variety */
  --cyber-blue: #4A90E2;             /* Cooler tone */
}
```

#### 4. **Hierarchy Through Subtle Differences**

```css
/* User messages - clean, no glow */
.message.user .message-bubble {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);  /* Depth only */
}

/* Assistant messages - very subtle glow */
.message.assistant .message-bubble {
  background: var(--bg-card);
  border: 1px solid rgba(0, 216, 255, 0.12);
  box-shadow: 
    inset 0 1px 0 rgba(255, 255, 255, 0.03),  /* Inner highlight */
    0 0 1px rgba(0, 216, 255, 0.15),  /* Tiny glow */
    0 2px 8px rgba(0, 0, 0, 0.4);  /* Shadow for depth */
}

/* System messages - no glow at all */
.message.system .message-bubble {
  background: rgba(255, 255, 255, 0.03);
  border: 1px dashed var(--border-secondary);
  box-shadow: none;
}
```

#### 5. **Grid Background Adjustments**

```css
/* Tone down grid so it doesn't compete with content */
body::before {
  content: '';
  position: fixed;
  inset: 0;
  background-image: 
    linear-gradient(rgba(0, 216, 255, 0.03) 1px, transparent 1px),
    linear-gradient(90deg, rgba(0, 216, 255, 0.03) 1px, transparent 1px);
  background-size: 20px 20px;
  pointer-events: none;
  opacity: 0.4;  /* Reduce overall visibility */
}

/* Add vignette to focus attention on content */
body::after {
  content: '';
  position: fixed;
  inset: 0;
  background: radial-gradient(
    ellipse at center,
    transparent 30%,
    rgba(10, 10, 15, 0.6) 100%
  );
  pointer-events: none;
}
```

## Additional UI Enhancements

### 6. **Smooth Transitions**

```css
/* Add transitions to all glow effects */
.message-bubble,
.tool-card,
.status-dot {
  transition: 
    box-shadow 0.3s ease,
    border-color 0.3s ease,
    transform 0.2s ease;
}
```

### 7. **Accessibility - Reduced Motion**

```css
@media (prefers-reduced-motion: reduce) {
  * {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
  
  /* No glow animations for users who prefer reduced motion */
  .message.assistant .message-bubble {
    animation: none;
  }
}
```

### 8. **Dark Mode Intensity Control**

```css
/* Add a data attribute for glow intensity */
[data-glow-intensity="off"] .message.assistant .message-bubble {
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.4);
  border-color: var(--border-primary);
}

[data-glow-intensity="low"] .message.assistant .message-bubble {
  box-shadow: 
    0 0 2px rgba(0, 216, 255, 0.1),
    0 2px 8px rgba(0, 0, 0, 0.4);
}

[data-glow-intensity="medium"] .message.assistant .message-bubble {
  box-shadow: 
    0 0 8px rgba(0, 216, 255, 0.2),
    0 2px 12px rgba(0, 0, 0, 0.5);
}

[data-glow-intensity="high"] .message.assistant .message-bubble {
  box-shadow: 
    0 0 16px rgba(0, 216, 255, 0.4),
    0 4px 16px rgba(0, 0, 0, 0.6);
}
```

## Implementation Priority

### Phase 1 (Quick Wins)
1. ✅ Reduce glow opacity from 0.6 to 0.15-0.2
2. ✅ Add hover state for glow (off by default)
3. ✅ Tone down grid background
4. ✅ Add smooth transitions

### Phase 2 (Polish)
5. ⏳ Implement new message arrival animation
6. ⏳ Add glow intensity control (user preference)
7. ⏳ Refine color palette
8. ⏳ Add vignette effect

### Phase 3 (Advanced)
9. 🔮 Context-aware glow (more glow for important messages)
10. 🔮 Accessibility improvements
11. 🔮 Performance optimization (CSS containment)

## Visual Inspiration

The goal is **Blade Runner subtlety**, not **Las Vegas casino**:
- Cyberpunk aesthetic without being overwhelming
- Sci-fi feel that's easy on the eyes for long sessions
- Strategic use of glow for emphasis, not decoration
- Focus on content, not effects

## Testing Checklist

- [ ] View in different lighting conditions
- [ ] Test with colorblind simulation
- [ ] Long session test (1+ hours) - check eye strain
- [ ] Multiple messages on screen - check visual clutter
- [ ] Mobile/tablet view - do glows work at small sizes?
- [ ] Performance - does glow impact frame rate?

