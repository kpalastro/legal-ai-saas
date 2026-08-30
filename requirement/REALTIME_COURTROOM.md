# LexSim AI — Real-Time Courtroom & Voice Features (REVISED)

## Overview
Enhanced user experience with **live courtroom visualization**, **pause/intervention controls**, and **free browser-based TTS/STT** (Web Speech API).

**Research-Backed Changes:**
- ❌ **Removed:** Paid voice features (ElevenLabs, Whisper) — not justified for MVP
- ✅ **Added:** Free browser Web Speech API for basic TTS/STT
- 📅 **Phase 3:** Premium voice monetization (after product-market fit)

---

## 1. Real-Time Courtroom Viewer

### 1.1 Visual Layout
```
┌─────────────────────────────────────────────────────────────────────────────┐
│  LexSim AI — Case #12345: Smith v Jones (Contract Breach)                   │
│  ⏱️ Turn 4 of 9 | ⏸️ PAUSED | Judge Confidence: 62% (Plaintiff favored)     │
└─────────────────────────────────────────────────────────────────────────────┘

┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│   YOUR AGENT     │    │      JUDGE       │    │    OPPONENT      │
│   (Barrister)    │    │   (Adjudicator)  │    │   (Adversary)    │
│                  │    │                  │    │                  │
│  [Avatar] 🧑‍⚖️     │    │  [Avatar] ⚖️      │    │  [Avatar] 🧑‍💼     │
│                  │    │                  │    │                  │
│  "The defendant  │    │  *Listening*     │    │                  │
│  clearly breached│    │                  │    │                  │
│  clause 7.2 of   │    │  Confidence:     │    │                  │
│  the contract    │    │  ████████░░ 62%  │    │                  │
│  when they..."   │    │                  │    │                  │
│                  │    │  Key Issues:     │    │                  │
│                  │    │  • Duty of care  │    │                  │
│                  │    │  • Breach        │    │                  │
│                  │    │  • Damages       │    │                  │
│                  │    │                  │    │                  │
│  [Speaking...]   │    │  [Neutral]       │    │  [Waiting]       │
└──────────────────┘    └──────────────────┘    └──────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│  CONTROLS                                                                   │
│  ⏸️ Pause  ▶️ Resume  ⏭️ Skip Turn  💬 Intervene  📊 Judge View  🔊 Audio   │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│  DEBATE TRANSCRIPT (Live)                                                   │
│  ─────────────────────────────────────────────────────────────────────────  │
│  Turn 1 — Plaintiff Opening (Your Agent)                                    │
│  "Your Honour, the plaintiff contends that the defendant breached clause    │
│   7.2 of the Services Agreement dated 15 March 2024 by failing to..."       │
│                                                                             │
│  Turn 2 — Defendant Opening (Opponent)                                      │
│  "The defendant denies any breach. The failure to deliver was due to        │
│   force majeure events beyond our control, specifically the..."             │
│                                                                             │
│  Turn 3 — Judge Initial Belief                                              │
│  "I note the plaintiff has established a prima facie case. However, the     │
│   force majeure defence requires examination. Confidence: 55% plaintiff."   │
│                                                                             │
│  Turn 4 — Plaintiff Rebuttal (Your Agent) — [CURRENT, PAUSED]               │
│  "The defendant's force majeure claim fails because..."                     │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 1.2 Component Architecture (Frontend)

**React Component Tree:**
```
CourtroomViewer/
├── DebateHeader/
│   ├── TurnCounter (4/9)
│   ├── ProgressBar
│   ├── JudgeConfidenceMeter
│   └── StatusBadge (LIVE / PAUSED / COMPLETED)
├── AgentPanel/ (×3)
│   ├── Avatar (with speaking indicator)
│   ├── AgentName + Role
│   ├── DialogueText (typewriter animation)
│   ├── SpeakingIndicator (pulsing border)
│   └── AgentStatus (Speaking / Listening / Waiting)
├── ControlBar/
│   ├── PauseButton
│   ├── ResumeButton
│   ├── SkipTurnButton
│   ├── InterveneButton
│   ├── JudgeDetailViewButton
│   └── AudioToggleButton (free browser TTS)
├── DebateTranscript/
│   ├── TranscriptEntry (×N)
│   │   ├── TurnLabel
│   │   ├── AgentBadge
│   │   └── Content (expandable)
│   └── AutoScrollToBottom
└── InterventionModal/ (overlay)
    ├── InterventionTypeSelector
    ├── TextInput / VoiceInput (browser STT)
    ├── SubmitButton
    └── CancelButton
```

### 1.3 WebSocket Protocol

**Client → Server Messages:**
```typescript
// Subscribe to simulation stream
{
  "type": "subscribe",
  "simulation_id": "uuid",
  "user_id": "uuid"
}

// Pause debate
{
  "type": "pause",
  "simulation_id": "uuid",
  "reason": "user_intervention" | "manual_pause"
}

// Resume debate
{
  "type": "resume",
  "simulation_id": "uuid"
}

// Skip turn
{
  "type": "skip_turn",
  "simulation_id": "uuid"
}

// Submit intervention
{
  "type": "intervene",
  "simulation_id": "uuid",
  "intervention_type": "add_evidence" | "correct_error" | "emphasize_point" | "custom",
  "user_input": "The defendant admitted in email dated 2024-05-12 that..."
}

// Enable audio (free browser TTS)
{
  "type": "audio_enable",
  "simulation_id": "uuid",
  "audio_mode": "tts_only" // STT via browser only
}
```

**Server → Client Messages:**
```typescript
// Debate turn started
{
  "type": "turn_start",
  "turn_number": 4,
  "turn_name": "PLAINTIFF_REBUTTAL",
  "agent": "USER_ADVOCATE",
  "estimated_duration_seconds": 45
}

// Streaming token (typewriter effect)
{
  "type": "token",
  "token": "The",
  "is_word_boundary": true
}

// Turn completed
{
  "type": "turn_complete",
  "turn_number": 4,
  "full_content": "The defendant's force majeure claim fails because...",
  "metadata": {
    "tokens_used": 150,
    "latency_ms": 2300
  }
}

// Judge belief update
{
  "type": "judge_belief",
  "plaintiff_win_prob": 0.62,
  "confidence": 0.75,
  "key_issues": ["duty_of_care", "breach", "damages"],
  "evidence_gaps": ["no witness statement for event date"]
}

// Debate paused
{
  "type": "paused",
  "paused_at_turn": 4,
  "reason": "user_intervention"
}

// Debate resumed
{
  "type": "resumed",
  "resumed_at_turn": 4
}

// Intervention acknowledged
{
  "type": "intervention_ack",
  "intervention_id": "uuid",
  "will_incorporate_in_turn": 4
}

// Simulation complete
{
  "type": "simulation_complete",
  "outcome": {
    "winner": "plaintiff",
    "confidence": 0.68,
    "reasoning": "..."
  },
  "weakness_report": [...],
  "hallucination_score": 0.02
}
```

---

## 2. Pause & Intervention System

### 2.1 User Intervention Workflow

```
User clicks "Pause Debate"
         │
         ▼
┌─────────────────────────────────────┐
│  Debate Paused at Turn 4            │
│  Your Agent was about to argue      │
│                                     │
│  What would you like to add?        │
│                                     │
│  ○ Add evidence not yet mentioned   │
│  ○ Correct factual error            │
│  ○ Emphasize weak point             │
│  ○ Custom argument                  │
│                                     │
│  [Text input field...]              │
│                                     │
│  🎤 [Hold to Speak] (browser STT)   │
│                                     │
│  [Cancel]  [Resume Debate]          │
└─────────────────────────────────────┘
         │
         │ User submits intervention
         ▼
┌─────────────────────────────────────┐
│  Intervention Sent                  │
│  "Your argument will be             │
│   incorporated into the next        │
│   Plaintiff Rebuttal."              │
│                                     │
│  [Resume Debate]                    │
└─────────────────────────────────────┘
         │
         │ User clicks Resume
         ▼
Agent generates argument incorporating
user intervention → Debate continues
```

### 2.2 Intervention Limits by Tier

| Tier | Interventions per Simulation | Cost per Extra |
|------|------------------------------|----------------|
| **Guest (Free)** | 1 | $9 each |
| **Individual ($49/case)** | 2 | $9 each |
| **Individual ($149/case)** | 5 | $5 each |
| **Lawyer ($99/mo)** | 5 | Included |
| **Lawyer ($299/mo)** | Unlimited | Included |
| **Clinic (Enterprise)** | Unlimited | Included |

### 2.3 Backend State Machine

```python
class DebateStateMachine:
    def __init__(self, simulation_id: str):
        self.simulation_id = simulation_id
        self.current_turn = 0
        self.status = "running"  # running | paused | completed
        self.pause_reason = None
        self.interventions = []
        self.websocket_connections = set()
    
    async def pause(self, reason: str, user_id: str):
        """Pause debate and notify all connected clients"""
        self.status = "paused"
        self.pause_reason = reason
        self.pause_timestamp = datetime.utcnow()
        
        # Broadcast pause event
        await self.broadcast({
            "type": "paused",
            "paused_at_turn": self.current_turn,
            "reason": reason
        })
        
        # Log for analytics
        await self.log_pause_event(user_id, reason)
    
    async def resume(self, user_id: str):
        """Resume debate from paused state"""
        if self.status != "paused":
            raise ValueError("Debate is not paused")
        
        self.status = "running"
        self.resume_timestamp = datetime.utcnow()
        
        # Calculate pause duration for analytics
        pause_duration = (self.resume_timestamp - self.pause_timestamp).total_seconds()
        
        await self.broadcast({
            "type": "resumed",
            "resumed_at_turn": self.current_turn
        })
        
        # Continue agent generation
        await self._generate_current_turn()
    
    async def submit_intervention(self, user_id: str, intervention_type: str, user_input: str):
        """Accept user intervention and incorporate into next turn"""
        intervention = {
            "id": str(uuid4()),
            "user_id": user_id,
            "turn": self.current_turn,
            "type": intervention_type,
            "input": user_input,
            "timestamp": datetime.utcnow()
        }
        
        # Check intervention limit
        user_tier = await get_user_tier(user_id)
        intervention_count = await self.get_intervention_count(user_id)
        
        if intervention_count >= self.get_intervention_limit(user_tier):
            raise InterventionLimitExceeded(
                f"You've used all {self.get_intervention_limit(user_tier)} interventions for this tier."
            )
        
        self.interventions.append(intervention)
        
        await self.broadcast({
            "type": "intervention_ack",
            "intervention_id": intervention["id"],
            "will_incorporate_in_turn": self.current_turn
        })
    
    def get_intervention_limit(self, user_tier: str) -> int:
        limits = {
            "guest": 1,
            "individual_basic": 2,
            "individual_premium": 5,
            "lawyer_basic": 5,
            "lawyer_premium": 999,  # unlimited
            "clinic": 999
        }
        return limits.get(user_tier, 1)
```

---

## 3. Audio Features (Free Browser-Based)

### 3.1 Architecture (No Paid APIs)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Browser-Native Audio Pipeline (FREE)                                       │
└─────────────────────────────────────────────────────────────────────────────┘

┌──────────────┐      ┌──────────────┐      ┌──────────────┐
│   Browser    │      │   Backend    │      │   LLM        │
│   (Client)   │      │   (FastAPI)  │      │  Agent       │
│              │      │              │      │              │
│  🎤 Mic      │─────▶│  WebSocket   │      │              │
│  (STT)       │      │  Server      │      │              │
│  Web Speech  │      │              │      │              │
│  API         │      │              │      │              │
│              │      │              │      │              │
│  🔊 Speaker  │◀─────│  Response    │      │              │
│  (TTS)       │      │  Stream      │      │              │
│  Web Speech  │      │              │      │              │
│  API         │      │              │      │              │
└──────────────┘      └──────────────┘      └──────────────┘
```

**Key Change:** No ElevenLabs, no Whisper API, no Azure Speech. All browser-native.

### 3.2 Text-to-Speech (TTS) — Free

**Implementation:** Web Speech API (`speechSynthesis`)
```typescript
// components/simulation/useBrowserTTS.ts
export function useBrowserTTS() {
  const speak = (text: string, voice: string = 'default') => {
    const utterance = new SpeechSynthesisUtterance(text);
    
    // Select voice (Australian English if available)
    const voices = speechSynthesis.getVoices();
    const selectedVoice = voices.find(v => 
      v.lang.includes('en-AU') || v.lang.includes('en-GB')
    );
    if (selectedVoice) utterance.voice = selectedVoice;
    
    // Playback speed
    utterance.rate = 1.0; // 0.5x - 2.0x
    
    speechSynthesis.speak(utterance);
  };
  
  const pause = () => speechSynthesis.pause();
  const resume = () => speechSynthesis.resume();
  const cancel = () => speechSynthesis.cancel();
  
  return { speak, pause, resume, cancel };
}
```

**Voice Options (Browser-Dependent):**
| Voice | Availability | Quality |
|-------|--------------|---------|
| **System Default** | All browsers | Basic |
| **Google UK English** | Chrome | Good |
| **Microsoft Australia** | Edge | Good |
| **Samantha (en-AU)** | Safari | Excellent |

**Settings:**
- Playback speed: 0.5x – 2.0x (slider)
- Auto-scroll transcript with audio
- Background audio mode (continues when tab inactive)

**Cost:** $0 (free browser API)

### 3.3 Speech-to-Text (STT) — Free

**Implementation:** Web Speech API (`SpeechRecognition`)
```typescript
// components/simulation/useBrowserSTT.ts
export function useBrowserSTT() {
  const [isRecording, setIsRecording] = useState(false);
  const [transcript, setTranscript] = useState('');
  
  const recognition = useRef<SpeechRecognition | null>(null);
  
  useEffect(() => {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (SpeechRecognition) {
      recognition.current = new SpeechRecognition();
      recognition.current.continuous = false;
      recognition.current.interimResults = true;
      recognition.current.lang = 'en-AU'; // Australian English
      
      recognition.current.onresult = (event) => {
        const final = Array.from(event.results)
          .map(result => result[0].transcript)
          .join('');
        setTranscript(final);
      };
    }
  }, []);
  
  const startRecording = () => {
    recognition.current?.start();
    setIsRecording(true);
  };
  
  const stopRecording = () => {
    recognition.current?.stop();
    setIsRecording(false);
  };
  
  return { isRecording, transcript, startRecording, stopRecording };
}
```

**Features:**
- **Australian Accent Support:** `lang='en-AU'`
- **Legal Terminology:** Add custom phrases via `recognition.addPhrase()`
  - "Smith versus Jones [2020] FCA 123"
  - "stare decisis", "obiter dicta", "prima facie"
  - "negligence", "breach of contract", "force majeure"
- **Voice Commands:** Parse transcript for commands:
  - "Pause debate" → Triggers pause
  - "Resume" → Resumes debate
  - "Show judge confidence" → Opens judge detail view

**Cost:** $0 (free browser API)

### 3.4 Voice Session Management (No Billing)

```python
# No paid voice APIs = no billing complexity
class AudioSessionManager:
    def __init__(self, user_id: str, simulation_id: str):
        self.user_id = user_id
        self.simulation_id = simulation_id
        self.audio_enabled = False
    
    async def enable_audio(self):
        """Enable browser audio (no payment required)"""
        self.audio_enabled = True
        
        # Log for analytics only
        await self.log_audio_session_start()
    
    async def disable_audio(self):
        """Disable browser audio"""
        self.audio_enabled = False
        await self.log_audio_session_end()
    
    # No quota tracking, no billing, no overage fees
```

---

## 4. Updated Database Schema

```sql
-- Users (managed by Clerk.dev, mirrored locally)
CREATE TABLE users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  clerk_user_id TEXT UNIQUE NOT NULL,
  email TEXT UNIQUE NOT NULL,
  role TEXT CHECK (role IN ('individual', 'lawyer', 'clinic')) NOT NULL,
  subscription_tier TEXT,
  audio_enabled BOOLEAN DEFAULT TRUE, -- Free browser audio
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Add intervention tracking to simulations
ALTER TABLE simulations ADD COLUMN interventions JSONB DEFAULT '[]'::jsonb;
ALTER TABLE simulations ADD COLUMN pause_history JSONB DEFAULT '[]'::jsonb;
ALTER TABLE simulations ADD COLUMN total_interventions INTEGER DEFAULT 0;
ALTER TABLE simulations ADD COLUMN total_pause_seconds INTEGER DEFAULT 0;

-- Remove voice_usage table (no paid APIs)
-- DROP TABLE IF EXISTS voice_usage;

-- Create intervention_log table
CREATE TABLE intervention_log (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  simulation_id UUID REFERENCES simulations(id) ON DELETE CASCADE,
  user_id UUID REFERENCES users(id),
  turn_number INTEGER NOT NULL,
  intervention_type TEXT NOT NULL,
  user_input TEXT NOT NULL,
  incorporated BOOLEAN DEFAULT FALSE,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for performance
CREATE INDEX idx_simulations_user_id ON simulations(user_id);
CREATE INDEX idx_intervention_log_simulation_id ON intervention_log(simulation_id);
```

---

## 5. Updated Pricing Tiers (No Voice Add-On)

### 5.1 Pay-Per-Case (Individual)

| Tier | Price | Simulations | Interventions | Audio | Best For |
|------|-------|-------------|---------------|-------|----------|
| **Basic** | $49/case | 1 simulation | 2 interventions | ✅ Free | Quick case assessment |
| **Premium** | $149/case | 1 simulation + documents | 5 interventions | ✅ Free | Full case prep |
| **Ultimate** | $299/case | Unlimited simulations + lawyer review | Unlimited | ✅ Free | High-stakes cases |

### 5.2 Subscription (Lawyer)

| Tier | Price/Month | Simulations | Interventions | Audio | Best For |
|------|-------------|-------------|---------------|-------|----------|
| **Solo** | $99/mo | 10 cases/mo | 5 per case | ✅ Free | Solo practitioners |
| **Unlimited** | $299/mo | Unlimited cases | Unlimited | ✅ Free | Small firms |

### 5.3 Enterprise (Clinic)

| Tier | Price/Month | Simulations | Interventions | Audio | Best For |
|------|-------------|-------------|---------------|-------|----------|
| **Clinic** | $2,500/mo | Unlimited | Unlimited | ✅ Free | Legal aid clinics |

**Note:** Audio is **free for all tiers** (browser Web Speech API).

---

## 6. Frontend Implementation (React)

### 6.1 Courtroom Viewer Component

```tsx
// components/simulation/CourtroomViewer.tsx
import { useState, useEffect } from 'react';
import { useWebSocket } from '@/hooks/useWebSocket';
import { useBrowserTTS } from '@/hooks/useBrowserTTS';
import { useBrowserSTT } from '@/hooks/useBrowserSTT';
import { AgentPanel } from './AgentPanel';
import { ControlBar } from './ControlBar';
import { DebateTranscript } from './DebateTranscript';
import { InterventionModal } from './InterventionModal';

interface CourtroomViewerProps {
  simulationId: string;
  userId: string;
  userTier: string;
}

export function CourtroomViewer({ simulationId, userId, userTier }: CourtroomViewerProps) {
  const [debateState, setDebateState] = useState({
    currentTurn: 0,
    totalTurns: 9,
    status: 'running' as 'running' | 'paused' | 'completed',
    judgeConfidence: 0.5,
  });
  
  const [isPaused, setIsPaused] = useState(false);
  const [showInterventionModal, setShowInterventionModal] = useState(false);
  const [audioEnabled, setAudioEnabled] = useState(false);
  
  const { lastMessage, sendMessage } = useWebSocket(`/ws/simulation/${simulationId}`);
  const { speak, pause: pauseTTS, resume: resumeTTS } = useBrowserTTS();
  const { transcript, startRecording, stopRecording } = useBrowserSTT();
  
  useEffect(() => {
    if (!lastMessage) return;
    
    const data = JSON.parse(lastMessage.data);
    
    switch (data.type) {
      case 'turn_start':
        setDebateState(prev => ({
          ...prev,
          currentTurn: data.turn_number,
        }));
        break;
      
      case 'paused':
        setIsPaused(true);
        setDebateState(prev => ({ ...prev, status: 'paused' }));
        break;
      
      case 'resumed':
        setIsPaused(false);
        setDebateState(prev => ({ ...prev, status: 'running' }));
        break;
      
      case 'judge_belief':
        setDebateState(prev => ({
          ...prev,
          judgeConfidence: data.plaintiff_win_prob,
        }));
        break;
      
      case 'token':
        // Stream TTS audio (free browser API)
        if (audioEnabled) {
          speak(data.token, 'default');
        }
        break;
      
      case 'simulation_complete':
        setDebateState(prev => ({ ...prev, status: 'completed' }));
        break;
    }
  }, [lastMessage, audioEnabled, speak]);
  
  const handlePause = () => {
    sendMessage(JSON.stringify({
      type: 'pause',
      simulation_id: simulationId,
      reason: 'manual_pause',
    }));
  };
  
  const handleResume = () => {
    sendMessage(JSON.stringify({
      type: 'resume',
      simulation_id: simulationId,
    }));
  };
  
  const handleIntervene = (interventionType: string, userInput: string) => {
    sendMessage(JSON.stringify({
      type: 'intervene',
      simulation_id: simulationId,
      intervention_type: interventionType,
      user_input: userInput,
    }));
    setShowInterventionModal(false);
  };
  
  const handleAudioToggle = () => {
    setAudioEnabled(!audioEnabled);
    if (!audioEnabled) {
      sendMessage(JSON.stringify({
        type: 'audio_enable',
        simulation_id: simulationId,
        audio_mode: 'tts_only',
      }));
    }
  };
  
  const handleVoiceIntervention = () => {
    if (transcript) {
      // Parse voice commands
      if (transcript.toLowerCase().includes('pause')) {
        handlePause();
      } else if (transcript.toLowerCase().includes('resume')) {
        handleResume();
      } else {
        // Submit as intervention
        handleIntervene('custom', transcript);
      }
    }
  };
  
  return (
    <div className="courtroom-viewer">
      <DebateHeader
        currentTurn={debateState.currentTurn}
        totalTurns={debateState.totalTurns}
        status={debateState.status}
        judgeConfidence={debateState.judgeConfidence}
      />
      
      <div className="agent-panels">
        <AgentPanel agent="USER_ADVOCATE" status={debateState.status} />
        <AgentPanel agent="JUDGE" status={debateState.status} confidence={debateState.judgeConfidence} />
        <AgentPanel agent="OPPONENT" status={debateState.status} />
      </div>
      
      <ControlBar
        isPaused={isPaused}
        onPause={handlePause}
        onResume={handleResume}
        onIntervene={() => setShowInterventionModal(true)}
        onAudioToggle={handleAudioToggle}
        audioEnabled={audioEnabled}
        userTier={userTier}
      />
      
      <DebateTranscript simulationId={simulationId} />
      
      {showInterventionModal && (
        <InterventionModal
          onClose={() => setShowInterventionModal(false)}
          onSubmit={handleIntervene}
          userTier={userTier}
          onVoiceInput={startRecording}
          voiceTranscript={transcript}
        />
      )}
    </div>
  );
}
```

---

## 7. Security & Compliance for Audio

### 7.1 Privacy Considerations
- **No Third-Party Processing:** Browser Web Speech API processes audio locally (no external API calls)
- **No Data Storage:** Audio is not recorded or stored (only transcription used for interventions)
- **Encryption:** Not required (no audio leaves browser)

### 7.2 Legal Professional Privilege (LPP)
- **Advantage:** Browser-native audio = no third-party disclosure = lower LPP risk
- **Warning:** Still display: "Audio transcription uses browser APIs. Do not disclose privileged communications."

---

## 8. Testing Checklist

- [ ] WebSocket reconnection on network failure
- [ ] Pause state persists across page refresh
- [ ] Intervention limits enforced server-side
- [ ] Browser TTS works on Chrome, Firefox, Safari, Edge
- [ ] Browser STT accuracy with Australian accent >85%
- [ ] Legal terminology dictionary coverage
- [ ] Audio sync with transcript (typewriter effect)
- [ ] Background audio mode works on mobile
- [ ] Voice commands recognized in noisy environments
- [ ] Transcript sync with audio playback

---

## 9. Performance Targets

| Metric | Target |
|--------|--------|
| **WebSocket Latency** | <100ms (token to screen) |
| **Pause → Resume** | <500ms to continue generation |
| **STT Latency** | <1s (browser-native) |
| **TTS Latency** | <500ms (browser-native) |
| **Voice Command Recognition** | <500ms |
| **Audio-T Transcript Sync** | <200ms drift |

---

## 10. Phase 3: Premium Voice (Future Monetization)

**After product-market fit (10k+ users), consider:**

| Feature | Current (Free) | Premium (Phase 3+) |
|---------|----------------|--------------------|
| **TTS** | Browser Web Speech | ElevenLabs (studio quality, custom voices) |
| **STT** | Browser SpeechRecognition | Deepgram Nova-3 (99% accuracy, legal terminology) |
| **Voice Commands** | Basic parsing | Advanced NLP (contextual understanding) |
| **Audio Transcripts** | Text only | Timestamped audio + text sync |
| **Pricing** | Free | +$29/case or +$49/month |

**Decision Point:** Only build if users explicitly demand higher quality than browser provides.

---

## 11. Next Steps

1. **Backend:** Implement WebSocket server with pause/resume/intervention logic
2. **Frontend:** Build CourtroomViewer component with real-time streaming
3. **Audio:** Integrate browser Web Speech API (TTS/STT)
4. **Testing:** User testing with 10 lawyers (validate intervention workflow)
5. **Legal Review:** LPP warning copy + privacy policy updates

**This document extends REQUIREMENTS.md and ARCHITECTURE.md with research-backed real-time courtroom and free audio feature specifications.**
