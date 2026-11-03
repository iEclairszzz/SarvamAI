# Sarvam Narrator 🎙️
> **Multilingual Text-to-Speech Content Reader (Hackathon MVP)**  
> Turn pasted text, uploaded documents (`.txt`, `.md`, `.pdf`), or web article URLs into natural narrated audio in Indian languages & English using **Sarvam AI's Bulbul TTS** and **Mayura Translation**.

---

## ⚡ Quickstart (3 Commands)

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure environment variables (copy example and insert key)
cp .env.example .env

# 3. Start the application
uvicorn app.main:app --reload
```

Open your browser at **`http://localhost:8000`** to start narrating!

---

## 🏗️ Architecture

```
                       ┌────────────────────────────────────────────────────────┐
                       │              Frontend (Single Page Web App)            │
                       │           (HTML5 / Tailwind CSS / Vanilla JS)          │
                       └───────────────────────────┬────────────────────────────┘
                                                   │
                                                   ▼
                       ┌────────────────────────────────────────────────────────┐
                       │               FastAPI Application (app/main.py)        │
                       │   POST /api/narrate  |  GET /api/jobs/{id}             │
                       │   GET /api/voices    |  GET /api/audio/{id}.wav        │
                       └───────────┬────────────────────────────────┬───────────┘
                                   │                                │
            ┌──────────────────────┴──────────────────────┐         │
            ▼                                             ▼         ▼
  ┌───────────────────┐                        ┌───────────────────────┐
  │ Content Extractor │                        │ In-Memory Jobs Store  │
  │  (app/extract.py) │                        │ (Status, Progress,    │
  │ • Pasted Text     │                        │  Transcript, Audio)   │
  │ • .txt, .md, .pdf │                        └───────────────────────┘
  │ • Trafilatura URL │                                    ▲
  └─────────┬─────────┘                                    │
            │                                              │
            ▼                                              │
  ┌──────────────────────────────────────────────────┐     │
  │ Translation Engine (Optional: app/sarvam_client) │     │
  │ • Sarvam Mayura:v1 (formal/colloquial/code-mixed)│     │
  │ • Chunked <=900 chars, Exponential Backoff       │     │
  └─────────┬────────────────────────────────────────┘     │
            │                                              │
            ▼                                              │
  ┌──────────────────────────────────────────────────┐     │
  │ Intelligent Chunker (app/chunker.py)             │     │
  │ • Strips Markdown syntax, code, URLs, badges     │     │
  │ • Splits on sentences: . ? ! । (Devanagari danda)│     │
  │ • Greedily packs chunks <=2000 chars for TTS     │     │
  │ • Tracks paragraph endings for natural silence   │     │
  └─────────┬────────────────────────────────────────┘     │
            │                                              │
            ▼                                              │
  ┌──────────────────────────────────────────────────┐     │
  │ Speech Synthesis (app/sarvam_client.py)          │     │
  │ • Bulbul v3 TTS (11 Indian languages + English)  │     │
  │ • Curated Speaker Personas (Shubh, Priya, etc.)  │     │
  │ • Pace control (0.5x – 2.0x), exponential retry  │     │
  └─────────┬────────────────────────────────────────┘     │
            │ (Base64 WAV chunks)                          │
            ▼                                              │
  ┌──────────────────────────────────────────────────┐     │
  │ Audio Concatenator (app/audio.py)                │     │
  │ • Lossless WAV stitching via stdlib `wave`       │     │
  │ • Inserts ~250ms silence between paragraphs      │─────┘
  │ • Outputs to `outputs/{job_id}.wav`              │
  └──────────────────────────────────────────────────┘
```

---

## 🎯 Architectural & Design Choices Made

1. **Exact SDK Parameters & Response Shapes**:
   - Used official `sarvamai` SDK (`sarvamai.SarvamAI`).
   - TTS parameter is verified as `language_code` (e.g. `hi-IN`), NOT `target_language_code`.
   - TTS output format returns base64-encoded audio strings in `response.audios[0]`, decoded to raw PCM WAV bytes.
2. **Listening Continuity & Bookmarks Without Browser LocalStorage**:
   - Designed for live deployment: playback positions, listening history, and timestamps are stored on the server via SQLite database (`app/db.py`) and REST APIs.
   - Users can resume playback from the exact second they left off on any device or page reload.
   - Timestamped bookmarks can be created with one click during listening.
3. **Synchronized Interactive Reading (Karaoke-Style Text Highlighting)**:
   - Chunk synthesis measures raw audio frames to compute exact start and end timestamps for every sentence across paragraphs.
   - Spoken sentences highlight in real-time as the audio plays, with optional automatic auto-scrolling into view.
   - Clicking any sentence in the transcript immediately jumps audio playback to that exact moment.
4. **Voice Audition & Multi-Persona Comparison**:
   - Instant 1-click preview button (`🔊 Preview`) plays a short sample greeting in the selected language.
   - Interactive **Voice Catalog Modal** (`🎭 Compare`) allows users to audition and compare all 11 Sarvam personas (Shubh, Priya, Ritu, Aditya, Rahul, Simran, etc.) side-by-side before generating.
5. **Model Selection**:
   - Primary TTS: `bulbul:v3` (stable default, supporting 11 Indian languages + Indian English, with 30+ curated voices).
   - Translation: `mayura:v1` (supports auto-language detection, 11 languages, and stylistic tones: `formal`, `modern-colloquial`, `classic-colloquial`, `code-mixed`).
   - Fallback translation: `sarvam-translate:v1` automatically selected if extended scheduled languages are used.
6. **Natural Indic Pacing Without SSML**:
   - Bulbul v3 does not support SSML. To achieve content styles without pseudo-tag workarounds:
     - **News**: Steady persona voice (`shubh`), standard pace `1.0x`.
     - **Story**: Warm, expressive persona voice (`priya`), slightly slower pace `0.9x`.
     - **Education**: Crisp, instructional persona voice (`ritu`), measured pace `0.85x`.
     - **Casual**: Modern, conversational voice (`aditya`), brisk pace `1.05x`.
   - Paragraph boundaries naturally insert **~250ms silence** using standard PCM frame zero-padding, producing natural breathing pauses between sections.
7. **Greedy Sentence Chunking & Indic Punctuation**:
   - Sentence splitting regex handles standard punctuation (`.`, `?`, `!`) and Devanagari danda (`।`, `॥`).
   - Oversized sentences split gracefully at commas, then words, preventing mid-word cuts.
   - Max 2,000 characters per TTS request (well below API 2,500 limit).
   - Max 900 characters per translation request (well below Mayura 1,000 limit).
8. **Zero-Build, Highly Responsive Frontend**:
   - Single static `index.html` served directly by FastAPI.
   - Tailwind CSS CDN + vanilla JS for instant setup without node/npm/vite overhead.
   - 1-second interval polling for background jobs with clear progress states and error toasts.

---

## ⚠️ Known Limits

- **No SSML Support**: Bulbul v3/v4-flash do not support SSML markup (pitch/loudness tags). Tone and emphasis are handled through persona voice selection, pace adjustments, and sentence punctuation.
- **20,000 Character Input Cap**: To ensure rapid processing within hackathon constraints, documents exceeding 20,000 characters are rejected with a clear user error prompt.
- **In-Memory Job Storage**: Narration jobs are tracked in an in-memory dictionary. A backend restart clears prior job logs (synthesized WAV files remain saved in `outputs/`).

---

## ⏱️ 2-Minute Demo Script

| Time | Action | What to Say / Notice |
|---|---|---|
| **0:00 - 0:20** | Open `http://localhost:8000` | *"Welcome to Sarvam Narrator. It turns any article, document, or pasted text into natural Indian voice audio."* |
| **0:20 - 0:45** | Click **"Sample: Hindi News"**, pick **"News"** style, click **"Generate Narration"** | *"Watch the live progress indicator. It cleans markdown, chunks sentences around Devanagari dandas, synthesizes with Bulbul v3 voice 'Shubh', and concatenates with ~250ms paragraph silence."* |
| **0:45 - 1:15** | Play the generated Hindi audio & click **"Download WAV"** | *"Notice how natural the flow sounds with no audible chunk boundaries or clipping."* |
| **1:15 - 1:45** | Switch to **"Web Article"** tab, enter a URL (e.g. Wikipedia), toggle **"Narrate in different language"** to Hindi with **"Story"** style | *"Sarvam Narrator extracts the core article with Trafilatura, translates it using Sarvam Mayura, and reads it with Priya's warm storytelling voice."* |
| **1:45 - 2:00** | Play audio and highlight the synchronized transcript preview | *"The final translated transcript is displayed right beside the player with instant copy and download options."* |

---

## 🧪 Testing

Run all unit and integration tests:
```bash
pytest
```

Run automated end-to-end test verifying Hindi, Tamil, and English-to-Hindi URL translation:
```bash
python scripts/test_e2e.py
```
