"""
Presets and configuration for Sarvam Narrator.
Since SSML is unsupported on Bulbul v3 / v4-flash, content style is achieved
through voice persona selection, pace tuning, and sentence-level pacing.
"""

SUPPORTED_LANGUAGES = [
    {"code": "hi-IN", "name": "Hindi (हिंदी)"},
    {"code": "en-IN", "name": "English (Indian)"},
    {"code": "bn-IN", "name": "Bengali (বাংলা)"},
    {"code": "ta-IN", "name": "Tamil (தமிழ்)"},
    {"code": "te-IN", "name": "Telugu (తెలుగు)"},
    {"code": "gu-IN", "name": "Gujarati (ગુજરાતી)"},
    {"code": "kn-IN", "name": "Kannada (ಕನ್ನಡ)"},
    {"code": "ml-IN", "name": "Malayalam (മലയാളം)"},
    {"code": "mr-IN", "name": "Marathi (मराठी)"},
    {"code": "pa-IN", "name": "Punjabi (ਪੰਜਾਬੀ)"},
    {"code": "od-IN", "name": "Odia (ଓଡ଼ିଆ)"},
]

# Bulbul:v3 curated speakers
SPEAKERS = [
    {"id": "shubh", "name": "Shubh", "gender": "male", "desc": "Steady, clear, articulate (Default)"},
    {"id": "priya", "name": "Priya", "gender": "female", "desc": "Warm, engaging, expressive"},
    {"id": "ritu", "name": "Ritu", "gender": "female", "desc": "Crisp, instructional, clear"},
    {"id": "aditya", "name": "Aditya", "gender": "male", "desc": "Energetic, modern, conversational"},
    {"id": "kavya", "name": "Kavya", "gender": "female", "desc": "Calm, gentle, narrative"},
    {"id": "rahul", "name": "Rahul", "gender": "male", "desc": "Deep, authoritative, grounded"},
    {"id": "simran", "name": "Simran", "gender": "female", "desc": "Friendly, professional"},
    {"id": "roopa", "name": "Roopa", "gender": "female", "desc": "Mature, story-teller tone"},
    {"id": "kabir", "name": "Kabir", "gender": "male", "desc": "Dynamic, broadcast tone"},
    {"id": "neha", "name": "Neha", "gender": "female", "desc": "Approachable, conversational"},
    {"id": "pooja", "name": "Pooja", "gender": "female", "desc": "Polished, welcoming"},
]

STYLE_PRESETS = {
    "news": {
        "label": "News & Editorial",
        "description": "Steady, confident, and professional broadcast pacing.",
        "model": "bulbul:v3",
        "speaker": "shubh",
        "pace": 1.0,
    },
    "story": {
        "label": "Story & Audiobooks",
        "description": "Warmer and slightly slower for immersive narrative flow.",
        "model": "bulbul:v3",
        "speaker": "priya",
        "pace": 0.9,
    },
    "education": {
        "label": "Educational & Explainer",
        "description": "Clear, deliberate, and paced for maximum comprehension.",
        "model": "bulbul:v3",
        "speaker": "ritu",
        "pace": 0.85,
    },
    "casual": {
        "label": "Casual & Conversational",
        "description": "Natural and brisk for blogs, discussions, and updates.",
        "model": "bulbul:v3",
        "speaker": "aditya",
        "pace": 1.05,
    },
}

TRANSLATION_MODES = [
    {"id": "formal", "name": "Formal (Standard)"},
    {"id": "modern-colloquial", "name": "Modern Colloquial"},
    {"id": "classic-colloquial", "name": "Classic Colloquial"},
    {"id": "code-mixed", "name": "Code-Mixed (Hinglish/Tanglish style)"},
]

def get_style_defaults(style_name: str) -> dict:
    return STYLE_PRESETS.get(style_name, STYLE_PRESETS["news"])
