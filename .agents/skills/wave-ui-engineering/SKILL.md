---
name: wave-ui-engineering
description: >-
  Frontend engineering, UI/UX design, and client-side architecture standards for the Wave Music application.
  Use when creating, styling, updating, or refactoring Wave's HTML, CSS, and JavaScript modules
  (app.js, player.js, auth.js, library.js, extract.js), implementing audio player controls,
  queues, modals, views, or responsive layouts.
---

# Wave Music App — Frontend UI Engineering Guidelines

These standards govern frontend code structure, interface design, playback state management, and user interaction in the Wave Music web client.

---

## 1. Modular Client Architecture

The frontend follows a clean, modular vanilla JavaScript architecture without heavy external frameworks:

```
frontend/
├── index.html          # Single Page Application markup shell
├── css/
│   ├── style.css       # Core typography, reset, grid layouts, glassmorphism tokens
│   ├── components.css  # Buttons, modals, cards, tabs, search dropdowns
│   └── player.css      # Bottom player bar, progress sliders, queue panel, visualizer
└── js/
    ├── app.js          # App initialization, view switcher, global search, notifications
    ├── player.js       # Audio playback controller, Web Audio API, queue state machine
    ├── auth.js         # JWT token management, automatic refresh, login/register modals
    ├── library.js      # Playlists, liked songs, listening history, top tracks views
    └── extract.js      # Media downloader, format selector, progress indicators
```

---

## 2. Audio Player State Machine & UX Standards

### 2.1 State Lifecycle & HTML5 `<audio>` Safety
- Maintain clear audio state transitions:
  `IDLE -> LOADING -> READY -> PLAYING <-> PAUSED -> ERROR`
- Always configure `audio.crossOrigin = "anonymous"` before assigning `src`, allowing Web Audio API analysis and canvas visualization without tainted cross-origin security exceptions.
- Implement defensive error handling for playback stalls:
  - If playback fails with a 403 or network error, attempt one silent token/URL refresh before displaying an error toast.
- Preserve seek position when pausing/resuming.

### 2.2 Smooth Seeking & Scrubbing
- Detach active `timeupdate` listeners while the user is actively dragging the seek slider to prevent thumb stutter or jitter.
- Commit the seek to `audio.currentTime` only on the `change` or `pointerup` event.
- Display buffered time ranges (`audio.buffered`) visually behind the current progress thumb.

---

## 3. UI Aesthetics & Minimalist Design System

### 3.1 Design Tokens & Colors
- **Background Base**: `#08090c` (deep midnight black).
- **Surface Elevation / Cards**: `rgba(255, 255, 255, 0.03)` with `backdrop-filter: blur(16px)` and `border: 1px solid rgba(255, 255, 255, 0.07)`.
- **Primary Accent**: `#6366f1` (Indigo) / `#818cf8` (Light Indigo hover).
- **Text Scale**:
  - Primary Headlines: `#ffffff`, 600 weight.
  - Track Titles: `#f1f5f9`, 500 weight.
  - Artist / Album Subtitles: `#94a3b8`, 400 weight.
  - Duration & Meta Tags: `#64748b`, 400 weight.

### 3.2 Negative Design Constraints (Strict Minimalist Rules)
- **No Decorative Icons**: Do not prefix clean buttons, table columns, or menu pills with decorative emojis or icons unless strictly necessary for operational controls (e.g., play/pause, volume, close).
- **No Country Flags or Regional Badges**: Represent language or locale with concise text codes (`TEL`, `TAM`, `HIN`, `ENG`).
- **No Visual Clutter**: Status badges should use subdued text with subtle backgrounds rather than saturated bright badges.

---

## 4. XSS Prevention & Defensive DOM Updates

### 4.1 Safe String Escaping
- Never inject untrusted external metadata (song titles, artist names, search queries, user input) directly into `innerHTML`.
- Always pass strings through the centralized `escapeHtml()` utility:
  ```javascript
  function escapeHtml(str) {
      if (!str) return '';
      return String(str)
          .replace(/&/g, '&amp;')
          .replace(/</g, '&lt;')
          .replace(/>/g, '&gt;')
          .replace(/"/g, '&quot;')
          .replace(/'/g, '&#39;');
  }
  ```

### 4.2 Safe Attribute Quoting
- When attaching event handlers or data attributes in template strings, strictly escape quotes or use DOM `addEventListener` with dataset properties:
  ```javascript
  // CORRECT: Using DOM binding or escaped data attributes
  card.addEventListener('click', () => player.playTrack(track));
  ```

---

## 5. View Management & Mobile Responsiveness

- All main views (`#home-view`, `#search-view`, `#library-view`, `#extract-view`, `#artist-view`) are managed via `showView(viewName)` in `app.js`.
- On mobile screens (<768px):
  - Sidebar collapses into an off-canvas drawer or bottom navigation bar.
  - Bottom audio player bar adapts to a compact layout with expandable full-screen now-playing sheet.
  - Tap targets must measure at least 44x44px.

