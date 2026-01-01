# Jarvis Talking Head Avatar

> **Status**: Exploration / Research  
> **Vision**: A Max Headroom / Iron Man J.A.R.V.I.S. style talking hologram interface  
> **Inspiration**: SillyTavern character expressions, Vtuber avatars, AI assistants

---

## 🎯 Vision

Create a visual "talking head" avatar for Jarvis that:
- **Lip syncs** with TTS audio output
- Has **idle animations** (head movement, blinking, breathing) when not speaking
- **Sleep/wake states** (hide when sleeping, show on wake word)
- Eventually: **eye tracking** to follow user movement
- Displays on dedicated monitor (headless Ubuntu server) or TV

Think: Max Headroom meets J.A.R.V.I.S. - a persistent, animated presence.

---

## 📋 Table of Contents

1. [Architecture Options](#architecture-options)
2. [Existing Projects](#existing-projects)
3. [Technical Approaches](#technical-approaches)
4. [Lip Sync Technologies](#lip-sync-technologies)
5. [Display Options](#display-options)
6. [Implementation Phases](#implementation-phases)
7. [Recommended Stack](#recommended-stack)
8. [Resources](#resources)

---

## 🏗️ Architecture Options

### Option A: Web Browser (Recommended for Start)
```
┌─────────────────────────────────────────────────────────────┐
│                    DEDICATED DISPLAY                         │
│  ┌─────────────────────────────────────────────────────┐   │
│  │           Chrome/Firefox Kiosk Mode                  │   │
│  │  ┌─────────────────────────────────────────────┐    │   │
│  │  │         Jarvis Avatar Canvas                │    │   │
│  │  │                                             │    │   │
│  │  │              ┌─────────┐                    │    │   │
│  │  │              │  🤖👤   │ ← Animated Avatar  │    │   │
│  │  │              │ Jarvis  │                    │    │   │
│  │  │              └─────────┘                    │    │   │
│  │  │                                             │    │   │
│  │  └─────────────────────────────────────────────┘    │   │
│  │                    ↑                                 │   │
│  │            WebSocket Connection                      │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                           │
                           ▼
         ┌─────────────────────────────────────┐
         │          JARVIS SERVER              │
         │  • Sends TTS events via WebSocket   │
         │  • Sends state changes (sleep/wake) │
         │  • Sends audio URL or stream        │
         └─────────────────────────────────────┘
```

**Pros:**
- Works on any display device with a browser
- Easy development with web technologies
- Hot-reload during development
- Cross-platform (Linux, Windows, Mac, Raspberry Pi)

**Cons:**
- Browser overhead
- May need GPU for advanced effects

### Option B: Native Application (Godot/Python)
- **Godot Engine** - Free, open source game engine with excellent 2D/3D support
- **Python + PyGame** - Lightweight, good for simple animations
- **Electron** - Web tech wrapped in native app

### Option C: AI-Generated Video (Heavy GPU)
- **SadTalker** - Generate talking head video from single image + audio
- **Wav2Lip** - Neural network lip sync
- Requires significant GPU resources (not real-time on CPU)

---

## 🛠️ Existing Projects

### AI/ML Talking Head Generators

| Project | Type | Real-Time? | Requirements | Best For |
|---------|------|------------|--------------|----------|
| **[SadTalker](https://github.com/OpenTalker/SadTalker)** | AI video gen | ❌ | GPU (RTX 3060+) | High-quality pre-rendered |
| **[Wav2Lip](https://github.com/Rudrabha/Wav2Lip)** | Neural lip sync | ❌ | GPU | Accurate lip sync |
| **[Audio2Face](https://www.nvidia.com/en-us/omniverse/apps/audio2face/)** | NVIDIA | ✅ | RTX GPU | Professional quality |
| **[MakeItTalk](https://github.com/yzhou359/MakeItTalk)** | AI animation | ❌ | GPU | Research/experimental |

### Web-Based Avatar Systems

| Project | Type | Real-Time? | Best For |
|---------|------|------------|----------|
| **[Live2D Cubism](https://www.live2d.com/)** | 2D character | ✅ | VTuber-style, SillyTavern |
| **[VRM/Three.js](https://threejs.org/)** | 3D WebGL | ✅ | 3D humanoid avatars |
| **[Ready Player Me](https://readyplayer.me/)** | 3D avatars | ✅ | Customizable 3D humans |
| **[PixiJS](https://pixijs.com/)** | 2D sprites | ✅ | Simple 2D animations |
| **[Kalidokit](https://github.com/yeemachine/kalidokit)** | Face tracking | ✅ | Motion capture to avatar |

### VTuber / Streaming Software

| Project | Type | Open Source? | Notes |
|---------|------|--------------|-------|
| **[VTube Studio](https://denchisoft.com/)** | Live2D viewer | Free (not OSS) | Popular for VTubers |
| **[Inochi2D](https://github.com/Inochi2D/inochi2d)** | 2D rigging | ✅ | Open source Live2D alternative |
| **[VSeeFace](https://www.vseeface.icu/)** | VRM viewer | Free | 3D avatar with tracking |

### Lip Sync Tools

| Project | Type | Output | Notes |
|---------|------|--------|-------|
| **[Rhubarb Lip Sync](https://github.com/DanielSWolf/rhubarb-lip-sync)** | Audio analysis | JSON/XML timing | Open source, CPU-based |
| **[Gentle](https://github.com/lowerquality/gentle)** | Forced aligner | Word timing | Good for subtitles too |
| **[Piper TTS](https://github.com/rhasspy/piper)** | TTS with phonemes | Phoneme data | Already have phoneme info |

---

## 🔧 Technical Approaches

### Approach 1: Sprite-Based (Simplest)

Pre-render mouth shapes (visemes) as PNG images, switch based on audio analysis.

```
Visemes (mouth shapes):
├── mouth_closed.png      (silence, M, B, P)
├── mouth_ah.png          (A, E)
├── mouth_ee.png          (I)
├── mouth_oh.png          (O)
├── mouth_oo.png          (U)
├── mouth_th.png          (TH, DH)
├── mouth_f.png           (F, V)
├── mouth_l.png           (L)
└── mouth_w.png           (W, R)
```

**Animation loop:**
1. Receive TTS audio URL from Jarvis
2. Run Rhubarb Lip Sync to get phoneme timing
3. Play audio + switch sprites at correct times
4. Add idle animations between speech

**Pros:** Simple, low CPU, works everywhere  
**Cons:** Less smooth, limited expressions

### Approach 2: Live2D Model

Use Live2D Cubism for smooth 2D animation with physics.

```javascript
// Example: Live2D web integration
import { Live2DModel } from 'pixi-live2d-display';

const model = await Live2DModel.from('jarvis.model.json');
app.stage.addChild(model);

// Lip sync via parameter
model.internalModel.coreModel.setParameterValueById('ParamMouthOpenY', mouthValue);
```

**Pros:** Professional quality, physics simulation, widely used  
**Cons:** Need to create/buy model, proprietary SDK

### Approach 3: 3D WebGL (Three.js + GLB)

Use Three.js with a rigged 3D model (GLB/GLTF format).

```javascript
// Example: Three.js morph target lip sync
const headMesh = model.getObjectByName('Head');

// Viseme blend shapes
headMesh.morphTargetInfluences[viseme_AA] = 0.8;  // "Ah" sound
headMesh.morphTargetInfluences[viseme_EE] = 0.0;
// etc.
```

**Models with viseme support:**
- Ready Player Me (free, customizable)
- Mixamo characters (free)
- VRM format models (VTuber standard)

**Pros:** Full 3D, rotation, lighting effects  
**Cons:** More complex, need 3D model with blend shapes

### Approach 4: AI Video Generation (Most Realistic)

Generate video frames using AI from a static image.

```bash
# SadTalker example
python inference.py \
  --driven_audio audio.wav \
  --source_image jarvis_face.png \
  --result_dir output/
```

**Pros:** Photorealistic, minimal art assets needed  
**Cons:** Heavy GPU requirement, latency (not true real-time)

---

## 🎤 Lip Sync Technologies

### Viseme Mapping

Standard 15 visemes for English:

| Viseme | Phonemes | Mouth Shape |
|--------|----------|-------------|
| sil | (silence) | Closed |
| PP | p, b, m | Closed, tight |
| FF | f, v | Lower lip tucked |
| TH | th, dh | Tongue between teeth |
| DD | t, d, n | Tongue at teeth |
| kk | k, g | Back tongue up |
| CH | ch, j, sh | Teeth together |
| SS | s, z | Teeth together, narrow |
| nn | n, l | Tongue up |
| RR | r | Lips rounded |
| aa | a, ah | Wide open |
| E | e, eh | Mid open |
| ih | i, ih | Narrow, smile |
| oh | o | Rounded, mid |
| ou | u, oo | Rounded, small |

### Integration with Jarvis TTS

**Option A: Pre-analyze audio file**
```python
# After TTS generates audio, run Rhubarb
subprocess.run(['rhubarb', '-f', 'json', 'output.wav', '-o', 'lipsync.json'])
# Send lipsync.json to avatar client along with audio URL
```

**Option B: Real-time audio analysis in browser**
```javascript
// Web Audio API - analyze in real-time
const analyser = audioContext.createAnalyser();
source.connect(analyser);

function animate() {
  const data = new Uint8Array(analyser.frequencyBinCount);
  analyser.getByteFrequencyData(data);
  
  // Simple: use volume for mouth open
  const volume = data.reduce((a, b) => a + b) / data.length;
  setMouthOpen(volume / 255);
}
```

**Option C: Azure/Google TTS viseme events**
Some TTS providers return viseme timing data directly.

---

## 🖥️ Display Options

### Option 1: Headless Ubuntu Server Monitor (Recommended)

Your dedicated monitor on the headless Ubuntu server:

```bash
# Auto-start browser in kiosk mode on boot
# /etc/xdg/autostart/jarvis-avatar.desktop

[Desktop Entry]
Type=Application
Name=Jarvis Avatar
Exec=chromium-browser --kiosk --disable-infobars http://localhost:5001/avatar
X-GNOME-Autostart-enabled=true
```

**Requirements:**
- X11 or Wayland display server
- Chromium/Firefox
- Auto-login to desktop session

### Option 2: Raspberry Pi + HDMI

Cheap, low-power display solution:

```bash
# Raspberry Pi OS Lite + browser kiosk
sudo apt install chromium-browser xserver-xorg
# Boot to kiosk mode
```

### Option 3: Smart TV Browser

Most smart TVs have built-in browsers:
- Samsung Tizen - WebKit browser
- LG WebOS - Built-in browser
- Android TV - Chrome

### Option 4: Dedicated Tablet/Old Phone

Mount a tablet as dedicated Jarvis display.

---

## 📈 Implementation Phases

### Phase 1: Basic Prototype (Week 1-2)
- [ ] Static avatar image with simple mouth animation
- [ ] WebSocket connection from Jarvis Web UI
- [ ] Volume-based mouth open/close
- [ ] Basic idle animation (blinking)

### Phase 2: Proper Lip Sync (Week 3-4)
- [ ] Integrate Rhubarb Lip Sync
- [ ] Viseme sprite switching
- [ ] Sync timing with audio playback
- [ ] Head movement during speech

### Phase 3: Rich Animation (Week 5-6)
- [ ] Live2D or Three.js model
- [ ] Physics-based idle (breathing, sway)
- [ ] Expression changes based on context
- [ ] Sleep/wake animations

### Phase 4: Advanced Features (Future)
- [ ] Eye tracking (webcam + MediaPipe)
- [ ] Motion following
- [ ] Multiple avatar styles/skins
- [ ] Web UI toggle for avatar visibility
- [ ] Hologram effect (transparent OLED?)

---

## 💡 Recommended Stack

For Jarvis integration, I recommend starting with:

### Minimum Viable Avatar
```
Technology: HTML Canvas + Sprite Animation
Lip Sync: Web Audio API volume detection
Complexity: Low
Time to MVP: 1-2 days
```

### Better Quality Avatar
```
Technology: PixiJS + Spine/Sprite sheets
Lip Sync: Rhubarb pre-analysis
Complexity: Medium
Time to MVP: 1 week
```

### Professional Avatar
```
Technology: Three.js + VRM/Ready Player Me model
Lip Sync: Viseme blend shapes + Rhubarb timing
Complexity: High
Time to MVP: 2-3 weeks
```

---

## 📁 Proposed File Structure

```
jarvis-voice/
├── jarvis-avatar/                    # New avatar service
│   ├── server/
│   │   ├── app.py                    # Flask/FastAPI server
│   │   └── lipsync_processor.py      # Rhubarb integration
│   ├── client/
│   │   ├── index.html                # Avatar display page
│   │   ├── css/
│   │   │   └── avatar.css
│   │   ├── js/
│   │   │   ├── avatar.js             # Main avatar controller
│   │   │   ├── lipsync.js            # Lip sync logic
│   │   │   └── idle.js               # Idle animations
│   │   └── assets/
│   │       ├── models/               # 3D models (if using)
│   │       ├── sprites/              # 2D sprites
│   │       └── visemes/              # Mouth shape images
│   ├── bin/
│   │   └── jarvis-avatar             # Launcher script
│   └── config/
│       └── avatar_config.json        # Avatar settings
│
├── docs/talking-head/
│   ├── README.md                     # This document
│   ├── IMPLEMENTATION.md             # Detailed build guide
│   └── MODELS.md                     # Avatar model options
```

---

## 🔗 Resources

### Open Source Projects
- [SadTalker](https://github.com/OpenTalker/SadTalker) - AI talking face from image
- [Rhubarb Lip Sync](https://github.com/DanielSWolf/rhubarb-lip-sync) - Audio to lip sync
- [Inochi2D](https://github.com/Inochi2D/inochi2d) - Open source 2D animation
- [Three.js](https://threejs.org/) - 3D WebGL library
- [PixiJS](https://pixijs.com/) - 2D WebGL renderer
- [Kalidokit](https://github.com/yeemachine/kalidokit) - Face tracking for avatars

### Avatar Assets
- [Ready Player Me](https://readyplayer.me/) - Free customizable 3D avatars
- [Mixamo](https://www.mixamo.com/) - Free rigged characters
- [VRoid Hub](https://hub.vroid.com/) - Free VRM models
- [Live2D Sample Models](https://www.live2d.com/en/download/sample-data/)

### Tutorials
- [Three.js Morph Targets](https://threejs.org/docs/#api/en/objects/Mesh.morphTargetInfluences)
- [Web Audio API](https://developer.mozilla.org/en-US/docs/Web/API/Web_Audio_API)
- [PixiJS Live2D Display](https://github.com/guansss/pixi-live2d-display)

### Commercial APIs (If needed)
- [D-ID](https://www.d-id.com/) - Talking avatar API
- [HeyGen](https://www.heygen.com/) - Video avatar platform
- [Synthesia](https://www.synthesia.io/) - AI video generation

---

## 🤔 Questions to Consider

1. **Avatar Style**: Realistic human? Stylized 2D? Abstract geometric?
2. **Performance**: What GPU resources are available on the display device?
3. **Art Assets**: Create custom? Use existing models? Commission artist?
4. **Latency**: How much delay is acceptable between TTS and lip sync?
5. **Network**: Wired vs WiFi between Jarvis server and display?

---

## 🚀 Quick Start Experiment

Want to test the concept quickly? Try this minimal prototype:

```html
<!-- jarvis-avatar-prototype.html -->
<!DOCTYPE html>
<html>
<head>
  <style>
    body { 
      background: #000; 
      display: flex; 
      justify-content: center; 
      align-items: center; 
      height: 100vh;
      margin: 0;
    }
    .avatar {
      width: 300px;
      height: 400px;
      background: radial-gradient(circle at 50% 30%, #1a1a2e 0%, #000 100%);
      border-radius: 150px 150px 100px 100px;
      position: relative;
      animation: float 3s ease-in-out infinite;
    }
    .eyes {
      position: absolute;
      top: 120px;
      left: 50%;
      transform: translateX(-50%);
      display: flex;
      gap: 60px;
    }
    .eye {
      width: 30px;
      height: 30px;
      background: #00d4ff;
      border-radius: 50%;
      box-shadow: 0 0 20px #00d4ff;
      animation: blink 4s infinite;
    }
    .mouth {
      position: absolute;
      bottom: 100px;
      left: 50%;
      transform: translateX(-50%);
      width: 60px;
      height: 10px;
      background: #00d4ff;
      border-radius: 20px;
      box-shadow: 0 0 15px #00d4ff;
      transition: height 0.05s;
    }
    .mouth.speaking {
      height: 30px;
      border-radius: 30px;
    }
    @keyframes float {
      0%, 100% { transform: translateY(0); }
      50% { transform: translateY(-10px); }
    }
    @keyframes blink {
      0%, 45%, 55%, 100% { transform: scaleY(1); }
      50% { transform: scaleY(0.1); }
    }
  </style>
</head>
<body>
  <div class="avatar">
    <div class="eyes">
      <div class="eye"></div>
      <div class="eye"></div>
    </div>
    <div class="mouth" id="mouth"></div>
  </div>
  
  <script>
    // Connect to Jarvis WebSocket
    const ws = new WebSocket('ws://localhost:5001/socket.io/?transport=websocket');
    const mouth = document.getElementById('mouth');
    
    // Simple audio-based mouth animation
    let audioContext, analyser, source;
    
    async function playAudioWithLipSync(audioUrl) {
      const response = await fetch(audioUrl);
      const arrayBuffer = await response.arrayBuffer();
      
      audioContext = new AudioContext();
      analyser = audioContext.createAnalyser();
      source = audioContext.createBufferSource();
      
      const audioBuffer = await audioContext.decodeAudioData(arrayBuffer);
      source.buffer = audioBuffer;
      source.connect(analyser);
      analyser.connect(audioContext.destination);
      
      source.start();
      animateMouth();
    }
    
    function animateMouth() {
      const data = new Uint8Array(analyser.frequencyBinCount);
      analyser.getByteFrequencyData(data);
      
      const volume = data.slice(0, 10).reduce((a, b) => a + b, 0) / 10;
      mouth.classList.toggle('speaking', volume > 50);
      
      if (source.context.state === 'running') {
        requestAnimationFrame(animateMouth);
      }
    }
    
    // Listen for TTS events from Jarvis
    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.audio_url) {
        playAudioWithLipSync(data.audio_url);
      }
    };
  </script>
</body>
</html>
```

This gives you a floating, blinking, lip-syncing avatar in ~100 lines!

---

*Document created: December 31, 2025*  
*Status: Research & Exploration*
