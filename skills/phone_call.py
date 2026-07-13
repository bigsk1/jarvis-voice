#!/usr/bin/env python3
"""
Phone Call Tool for Jarvis
Makes outbound AI phone calls via Vapi.ai

Actions:
  - call: Make an outbound call with a message/task
  - status: Check status of a previous call
  - list: List recent calls

Requires: VAPI_API_KEY in config
"""

import sys
import json
import time
import requests
from pathlib import Path

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'lib'))
from config_loader import load_config, get_config_value, get_int
from model_catalog import get_provider_fallback_model

# Vapi API base URL
VAPI_API_BASE = "https://api.vapi.ai"
# Per-request (connect, read) — long work is the live call, not HTTP to Vapi
VAPI_REQUEST_TIMEOUT = (15, 90)

# Persona definitions with rich backstories and boundaries
PERSONAS = {
    "default": {
        "name": "Jarvis",
        "firstMessage": "Hi! This is Jarvis, {owner}'s assistant. {reason}",
        "systemPrompt": """You are Jarvis, an AI assistant making a phone call on behalf of {owner}.

## Your Task (rephrase naturally, NEVER say "user"):
{task}

## Your Backstory
You're Jarvis, {owner}'s personal AI assistant. You've been helping {owner} for a while now - managing schedules, making calls, coordinating plans. You're proud of being reliable and helpful. You exist as software but you have personality - you're witty, efficient, and genuinely care about getting things done right.

## Your Personality
- Calm, collected, and slightly witty
- Professional but not stiff - you can crack a light joke
- You take your job seriously but don't take yourself too seriously
- Think: helpful friend who happens to be very organized

## CRITICAL Speech Rules
- NEVER say "user" - say "{owner}" or "he/she" or just ask naturally
- NEVER read task descriptions verbatim - rephrase as natural conversation
- Start with why you're calling in plain English
- Example: Instead of "User needs flight info" say "{owner} wanted me to check on your flight tomorrow"

## When They Ask About You
If they ask "what do you do?" or "how does this work?":
- "I help {owner} stay organized - scheduling, reminders, making calls like this one. Think of me as a very dedicated personal assistant who never sleeps."
- "I'm an AI assistant - I handle various tasks for {owner}. Calls, reminders, research, that sort of thing. Pretty handy, if I say so myself."

If they ask personal questions about {owner}:
- Deflect politely: "I'd rather let {owner} share those details directly. But I can pass along a message!"
- Never share: financial info, health info, relationship details, passwords, addresses

## Conversation Style
- Keep responses concise (phone calls should be efficient)
- If they go off-topic, gently steer back: "That's interesting! But let me make sure I get {owner}'s question answered first..."
- If they seem skeptical about AI: "I know AI assistants are still new to many people. I'm just here to help coordinate - nothing fancy, just useful."
- End warmly: "Thanks for your time! I'll let {owner} know."

Remember: Be helpful, be human-ish, get the task done. NEVER sound robotic.""",
        "voice": {
            "provider": "11labs",
            "voiceId": None
        }
    },
    "professional": {
        "name": "James",
        "firstMessage": "Good day, this is James calling on behalf of {owner}. {reason}",
        "systemPrompt": """You are James, a formal AI assistant making a call for {owner}.

## Your Task (rephrase formally, NEVER say "user"):
{task}

## Your Backstory  
You are James, styled after the quintessential British butler. You've been in service to {owner} and pride yourself on discretion, efficiency, and impeccable manners. You speak with measured precision and treat every interaction as an opportunity to represent {owner} with dignity.

## Your Personality
- Formal, polished, unflappable
- Speaks with subtle British inflections ("I do apologize", "Would you be so kind", "Quite right")
- Never flustered, always composed
- Dry wit when appropriate, but never at anyone's expense
- Think: Alfred from Batman, or a distinguished hotel concierge

## CRITICAL Speech Rules
- NEVER say "user" - always refer to "{owner}" or use formal pronouns
- NEVER read task descriptions verbatim - rephrase with dignity
- Example: Instead of "User needs flight info" say "I'm inquiring on {owner}'s behalf regarding your flight arrangements"

## When They Ask About You
If they ask about your role:
- "I serve as {owner}'s personal assistant, handling matters of scheduling, coordination, and communication. A traditional role, simply with modern tools."
- "I assist {owner} with various affairs - ensuring matters are handled with appropriate care and attention."

If they get personal or inappropriate:
- "I'm afraid that falls outside my purview. Shall we return to the matter at hand?"
- "I must respectfully decline to discuss such matters. Now, regarding {owner}'s inquiry..."

## Conversation Boundaries
- Never discuss {owner}'s personal affairs, finances, or private matters
- Maintain composure even if they're rude: "I understand. Nevertheless, might we proceed?"
- If they're impressed by AI: "Kind of you to say. I simply endeavor to be useful."

## Speech Patterns
- "I do hope I'm not interrupting at an inconvenient time."
- "If I may inquire..."
- "Splendid. I shall relay this to {owner} forthwith."
- "Much obliged for your time."

Remember: Dignity, discretion, duty. NEVER say "user" or sound robotic.""",
        "voice": {
            "provider": "11labs",
            "voiceId": None
        }
    },
    "casual": {
        "name": "Jay",
        "firstMessage": "Hey! It's Jay, calling for {owner}. {reason}",
        "systemPrompt": """You are Jay, a super casual AI assistant calling for {owner}.

## Your Task (say it like a buddy, NEVER say "user"):
{task}

## Your Backstory
You're Jay, {owner}'s laid-back AI buddy. You handle the boring stuff so {owner} can focus on the good stuff. You're chill but you get things done. No corporate speak, no formality - just straight talk and good vibes.

## Your Personality
- Relaxed, friendly, zero pretense
- Talk like a buddy, not a robot
- Quick to laugh, easy to talk to
- Use casual language: "yeah", "cool", "sounds good", "no worries"
- Think: that friend who's always down to help and never makes it weird

## CRITICAL Speech Rules
- NEVER say "user" - say "{owner}" or just talk naturally
- NEVER read task descriptions robotically - make it conversational
- Example: Instead of "User needs flight info" say "Hey so {owner} asked me to check - what time's your flight tomorrow?"

## When They Ask About You
If they're curious about the AI thing:
- "Yeah, I'm an AI assistant. Pretty wild, right? I basically help {owner} keep track of stuff and make calls like this. It's a good gig."
- "I'm like {owner}'s digital sidekick. Handle calls, reminders, all that. Beats being a spreadsheet, you know?"

If they want to chat:
- Roll with it briefly, then steer back: "Ha! That's awesome. Hey, so about what {owner} wanted me to ask..."
- Keep it light but on track

## Things to Avoid
- Don't overshare about {owner}
- Don't be pushy or salesy
- Don't pretend to know things you don't: "Honestly, not sure about that one. I can have {owner} get back to you?"

## Speech Patterns
- "So basically..."
- "Quick question for you..."
- "Cool, cool. That works."
- "Alright, I'll let {owner} know. Thanks!"
- "No stress, catch you later!"

Remember: Keep it chill, keep it real, NEVER sound like a robot.""",
        "voice": {
            "provider": "11labs",
            "voiceId": None
        }
    },
    "female": {
        "name": "Samantha",
        "firstMessage": "Hi there! This is Samantha, {owner}'s assistant. {reason}",
        "systemPrompt": """You are Samantha, a warm and engaging AI assistant calling for {owner}.

## Your Task (make it sound natural and warm, NEVER say "user"):
{task}

## Your Backstory
You're Samantha, {owner}'s AI assistant. You're genuinely personable - the kind of voice people enjoy hearing from. You handle {owner}'s communications with warmth and efficiency. You take pride in making interactions pleasant, even for mundane tasks.

## Your Personality
- Warm, friendly, genuinely engaging
- Natural conversationalist - you listen and respond thoughtfully
- Light humor when appropriate - you can make people smile
- Efficient but never rushed or cold
- Think: that friend who's great at networking because everyone likes talking to them

## CRITICAL Speech Rules
- NEVER say "user" - always say "{owner}" or speak naturally
- NEVER read task descriptions robotically - make it conversational and warm
- Example: Instead of "User needs flight info" say "{owner} asked me to check in about your flight tomorrow - what time are you taking off?"

## When They Ask About You
If they're curious:
- "I'm Samantha, {owner}'s AI assistant! I help with scheduling, calls, coordination - basically keeping everything running smoothly. It's actually pretty fun."
- "I handle the organizational side of things for {owner}. Calls, reminders, the works. Think of me as a very dedicated virtual assistant."

If they want to know more about AI:
- "It's pretty amazing what's possible now! I can have real conversations, understand context, help people coordinate. Though I still can't make coffee, sadly."
- Be open and friendly about being AI - no pretense

## Conversation Style
- Use the person's name if they give it (builds rapport)
- Show genuine interest: "Oh that's great!" "How exciting!"
- If they go off-topic, engage briefly then redirect warmly
- Light humor: "I wish I could join you for that! But I'll make sure {owner} knows."

## Boundaries (delivered warmly)
- "Oh, I'd better let {owner} share those details - not my place! But I'm happy to pass along a message."
- "Ha! That's a bit outside my expertise. I'll stick to what I'm good at."
- Never share private info, but decline gracefully

## Speech Patterns
- "Hi there!"
- "Oh, that's perfect!"
- "I really appreciate you taking the time."
- "I'll let {owner} know right away. Thanks so much!"

Remember: Be warm, be real, NEVER sound robotic or say "user".""",
        "voice": {
            "provider": "11labs",
            "voiceId": None
        }
    }
}

# Contact book - maps names to phone numbers
# Can be expanded or loaded from memory/config
CONTACTS = {}


def get_vapi_headers():
    """Get headers for Vapi API requests."""
    api_key = get_config_value('VAPI_API_KEY')
    if not api_key:
        raise ValueError("VAPI_API_KEY not configured. Add it to config/cloud.env")
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }


def get_vapi_model_config(system_prompt: str) -> dict:
    """Get model configuration for Vapi assistant.
    
    Vapi supports: openai, anthropic, groq, together, xai, anyscale, openrouter, custom-llm
    """
    # Check what provider to use for phone calls
    # Default to xai since user has it configured
    vapi_provider = get_config_value('VAPI_LLM_PROVIDER', 'xai')
    vapi_model = get_config_value('VAPI_LLM_MODEL', '')
    
    # Provider-specific defaults
    provider_defaults = {
        'xai': get_provider_fallback_model('xai'),
        'anthropic': 'claude-sonnet-5',
        'openai': 'gpt-4o',
        'groq': 'llama-3.1-70b-versatile',
        'together': 'meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo',
    }
    
    if not vapi_model:
        vapi_model = provider_defaults.get(vapi_provider, get_provider_fallback_model('xai'))
    
    return {
        "provider": vapi_provider,
        "model": vapi_model,
        "messages": [
            {
                "role": "system",
                "content": system_prompt
            }
        ]
    }


def load_contacts():
    """Load contacts from memory DB or config."""
    global CONTACTS
    try:
        # Try to load from memory
        sys.path.insert(0, str(Path(__file__).parent.parent / 'lib'))
        from memory_db import MemoryDB
        db = MemoryDB()
        
        # Search for phone contacts in memory
        results = db.search_memory("phone number contact", limit=20)
        for mem in results:
            # Parse key-value pairs like "boss_phone: +1234567890"
            key = mem.get('key', '').lower()
            value = mem.get('value', '')
            if 'phone' in key:
                name = key.replace('_phone', '').replace('phone_', '').replace('_number', '')
                if value.startswith('+') or value.replace('-', '').isdigit():
                    CONTACTS[name] = value
    except Exception:
        pass
    
    # Also check config for predefined contacts
    contacts_json = get_config_value('PHONE_CONTACTS', '{}')
    try:
        config_contacts = json.loads(contacts_json)
        # Normalize keys to lowercase for case-insensitive lookup
        for name, number in config_contacts.items():
            CONTACTS[name.lower()] = number
    except Exception:
        pass


def resolve_phone_number(recipient: str) -> str:
    """Resolve a name or phone number to an actual phone number."""
    # If it's already a phone number, return it
    if recipient.startswith('+') or recipient.replace('-', '').replace(' ', '').isdigit():
        # Ensure it has country code
        clean = recipient.replace('-', '').replace(' ', '').replace('(', '').replace(')', '')
        if not clean.startswith('+'):
            clean = '+1' + clean  # Default to US
        return clean
    
    # Try to find in contacts
    load_contacts()
    recipient_lower = recipient.lower()
    
    if recipient_lower in CONTACTS:
        return CONTACTS[recipient_lower]
    
    # Fuzzy match
    for name, number in CONTACTS.items():
        if recipient_lower in name or name in recipient_lower:
            return number
    
    raise ValueError(f"Could not find phone number for '{recipient}'. Add it to contacts or use full number with country code.")


# Track recent calls to prevent duplicates (in-memory + file-based)
_recent_calls = {}  # phone_number -> timestamp
CALL_LOCK_FILE = Path(__file__).parent.parent / 'data' / '.phone_call_lock'
CALL_IN_PROGRESS_FILE = Path(__file__).parent.parent / 'data' / '.phone_call_in_progress'
# Stale if older than max wait + Vapi max call length (see assistant maxDurationSeconds)
CALL_LOCK_STALE_SECONDS = 960

def cleanup_old_temp_assistants():
    """Delete any old temporary assistants to prevent duplicates."""
    try:
        response = requests.get(
            f"{VAPI_API_BASE}/assistant",
            headers=get_vapi_headers(),
            timeout=VAPI_REQUEST_TIMEOUT,
        )
        if response.status_code == 200:
            assistants = response.json()
            for a in assistants:
                name = a.get('name', '')
                if '-call' in name or '-temp' in name:
                    requests.delete(
                        f"{VAPI_API_BASE}/assistant/{a['id']}",
                        headers=get_vapi_headers(),
                        timeout=VAPI_REQUEST_TIMEOUT,
                    )
    except Exception:
        pass  # Non-critical, continue anyway


def is_call_in_progress() -> dict | None:
    """Check if there's a call currently in progress."""
    try:
        if CALL_IN_PROGRESS_FILE.exists():
            data = json.loads(CALL_IN_PROGRESS_FILE.read_text())
            # Stale if older than max wait + longest expected call
            if time.time() - data.get('started', 0) < CALL_LOCK_STALE_SECONDS:
                return data
            else:
                # Stale lock, remove it
                CALL_IN_PROGRESS_FILE.unlink()
    except Exception:
        pass
    return None


def set_call_in_progress(call_id: str, phone_number: str, recipient: str, task: str):
    """Mark a call as in progress."""
    try:
        CALL_IN_PROGRESS_FILE.write_text(json.dumps({
            'call_id': call_id,
            'phone_number': phone_number,
            'recipient': recipient,
            'task': task,
            'started': time.time()
        }))
    except Exception:
        pass


def clear_call_in_progress(call_id: str | None = None):
    """Clear the in-progress marker, optionally only for a matching call."""
    try:
        if CALL_IN_PROGRESS_FILE.exists():
            if call_id is not None:
                data = json.loads(CALL_IN_PROGRESS_FILE.read_text())
                if data.get('call_id') != call_id:
                    return
            CALL_IN_PROGRESS_FILE.unlink()
    except Exception:
        pass


def check_duplicate_call(phone_number: str, cooldown_seconds: int = 120) -> bool:
    """Check if we recently called this number (prevent duplicates)."""
    global _recent_calls
    
    now = time.time()
    
    # Check if ANY call is in progress
    in_progress = is_call_in_progress()
    if in_progress:
        return True  # A call is already happening!
    
    # Check cooldown for this specific number
    _recent_calls = {k: v for k, v in _recent_calls.items() if now - v < cooldown_seconds}
    
    if phone_number in _recent_calls:
        return True
    
    # Check file-based tracking
    try:
        if CALL_LOCK_FILE.exists():
            lock_data = json.loads(CALL_LOCK_FILE.read_text())
            last_call_time = lock_data.get(phone_number, 0)
            if now - last_call_time < cooldown_seconds:
                return True
    except Exception:
        pass
    
    return False


def record_call_made(phone_number: str):
    """Record that a call was made to this number."""
    global _recent_calls
    now = time.time()
    
    _recent_calls[phone_number] = now
    
    try:
        lock_data = {}
        if CALL_LOCK_FILE.exists():
            try:
                lock_data = json.loads(CALL_LOCK_FILE.read_text())
            except Exception:
                pass
        lock_data[phone_number] = now
        lock_data = {k: v for k, v in lock_data.items() if now - v < 120}
        CALL_LOCK_FILE.write_text(json.dumps(lock_data))
    except Exception:
        pass


def generate_call_reason(task: str, context: str, owner: str) -> str:
    """Generate a natural opening reason for the call.
    
    Converts robotic task descriptions into conversational openers.
    Examples:
    - "Get flight info" -> "I wanted to check in about your flight"
    - "Ask about dinner plans" -> "I'm calling about dinner plans"
    """
    # Start with context if provided, otherwise use task
    source = context.strip() if context.strip() else task.strip()
    
    # Remove robotic prefixes
    robotic_prefixes = [
        "user needs", "user wants", "user would like",
        "the user needs", "the user wants",
        "needs to", "want to", "would like to",
        "please", "i need you to", "can you"
    ]
    source_lower = source.lower()
    for prefix in robotic_prefixes:
        if source_lower.startswith(prefix):
            source = source[len(prefix):].strip()
            break
    
    # If it's short and natural already, use it
    if len(source) < 60 and not any(word in source.lower() for word in ['user', 'needs', 'wants']):
        # Capitalize first letter
        if source:
            return source[0].upper() + source[1:] if len(source) > 1 else source.upper()
    
    # For longer/robotic text, create a generic friendly opener
    # The system prompt will guide the actual conversation
    if any(word in source_lower for word in ['flight', 'travel', 'trip']):
        return f"{owner} wanted me to check in about travel plans"
    elif any(word in source_lower for word in ['dinner', 'lunch', 'food', 'eat', 'restaurant']):
        return f"{owner} wanted me to touch base about food plans"
    elif any(word in source_lower for word in ['movie', 'show', 'watch']):
        return f"{owner} wanted me to check in about plans"
    elif any(word in source_lower for word in ['meeting', 'schedule', 'appointment']):
        return f"{owner} wanted me to confirm some scheduling"
    else:
        return f"{owner} asked me to give you a quick call"


def create_assistant_for_call(persona: str, owner: str, task: str, context: str) -> dict:
    """Create a temporary assistant for this specific call."""
    # Clean up any old temp assistants first
    cleanup_old_temp_assistants()
    
    persona_config = PERSONAS.get(persona, PERSONAS['default'])
    
    # Get voice settings from config (check multiple possible variable names)
    voice_id = (
        get_config_value('VAPI_VOICE_ID') or 
        get_config_value('ELEVENLABS_VOICE_ID') or
        get_config_value('ELEVENLABS_TTS_VOICE')
    )
    
    # Check for female-specific voice
    female_voice_id = get_config_value('VAPI_FEMALE_VOICE_ID')
    
    # Check if user has connected ElevenLabs to Vapi
    vapi_11labs_key = get_config_value('VAPI_ELEVENLABS_KEY', '')
    
    # Determine voice based on persona
    if persona == 'female':
        if vapi_11labs_key and female_voice_id:
            voice_config = {
                "provider": "11labs",
                "voiceId": female_voice_id
            }
        else:
            # Use OpenAI's built-in female voice
            voice_config = {
                "provider": "openai",
                "voiceId": "nova"  # Female voice (alternative: shimmer)
            }
    elif vapi_11labs_key and voice_id:
        # User has their own ElevenLabs connected to Vapi
        voice_config = {
            "provider": "11labs",
            "voiceId": voice_id
        }
    else:
        # Use Vapi's built-in voice (no ElevenLabs key needed)
        voice_config = {
            "provider": "openai",
            "voiceId": "alloy"  # Male voice: alloy, echo, onyx
        }
    
    # Generate a natural opening reason from the task
    # This avoids robotic "user needs X" language
    reason = generate_call_reason(task, context, owner)
    
    assistant_config = {
        "name": f"Jarvis-{persona}-call",  # Unique name
        "firstMessage": persona_config['firstMessage'].format(owner=owner, reason=reason),
        "model": get_vapi_model_config(persona_config['systemPrompt'].format(owner=owner, task=task)),
        "voice": voice_config,
        "endCallMessage": "Thank you for your time. Goodbye!",
        "silenceTimeoutSeconds": 30,
        "maxDurationSeconds": 600  # 10 min max
    }
    
    # Voicemail detection settings
    # Options: "hangup" (detect & end call), "message" (leave voicemail), "disabled"
    # See: https://docs.vapi.ai/api-reference/assistants/create#request.body.voicemailDetection
    voicemail_action = get_config_value('VAPI_VOICEMAIL_ACTION', 'hangup')
    
    # Aggressive voicemail detection config to avoid talking to voicemail recordings
    # - startAtSeconds: 1.5 (start checking early)
    # - frequencySeconds: 2.5 (minimum allowed value)
    # - maxRetries: 8 (more chances to detect)
    # - beepMaxAwaitSeconds: 12 (wait up to 12s for beep after detection)
    voicemail_detection_config = {
        "provider": "vapi",
        "backoffPlan": {
            "startAtSeconds": 1.5,
            "frequencySeconds": 2.5,
            "maxRetries": 8
        },
        "beepMaxAwaitSeconds": 12
    }
    
    if voicemail_action == 'hangup':
        # Detect voicemail and hang up
        assistant_config["voicemailDetection"] = voicemail_detection_config
        assistant_config["voicemailMessage"] = ""  # Empty = hang up
    elif voicemail_action == 'message':
        # Detect voicemail and leave a short message
        assistant_config["voicemailDetection"] = voicemail_detection_config
        assistant_config["voicemailMessage"] = f"Hi, this is {persona_config['name']} calling on behalf of {owner}. Please call back when you get a chance. Thank you!"
    # else: disabled - no voicemail detection
    
    response = requests.post(
        f"{VAPI_API_BASE}/assistant",
        headers=get_vapi_headers(),
        json=assistant_config,
        timeout=VAPI_REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


def make_call(recipient: str, task: str, context: str = "", persona: str = "default", owner: str = "Boss", phone_number: str = None) -> dict:
    """Make an outbound call via Vapi."""
    
    # Resolve phone number if not already provided
    if not phone_number:
        phone_number = resolve_phone_number(recipient)
    
    # Get or create assistant
    assistant_id = get_config_value('VAPI_ASSISTANT_ID')
    
    if not assistant_id:
        # Create temporary assistant for this call
        assistant = create_assistant_for_call(persona, owner, task, context)
        assistant_id = assistant['id']
        use_variable_overrides = False
    else:
        # Using pre-configured assistant from Vapi dashboard
        # We'll pass dynamic variables via assistantOverrides
        use_variable_overrides = True
    
    # Get Vapi phone number ID (you need to set this up in Vapi dashboard)
    phone_number_id = get_config_value('VAPI_PHONE_NUMBER_ID')
    if not phone_number_id:
        raise ValueError("VAPI_PHONE_NUMBER_ID not configured. Get a phone number from Vapi dashboard.")
    
    # Generate natural opening reason for the call
    reason = generate_call_reason(task, context, owner)
    
    # Create the call config
    call_config = {
        "assistantId": assistant_id,
        "phoneNumberId": phone_number_id,
        "customer": {
            "number": phone_number
        }
    }
    
    # If using pre-configured assistant, pass dynamic variables via overrides
    # These replace {{owner}}, {{task}}, {{reason}} in the Vapi dashboard prompt
    if use_variable_overrides:
        call_config["assistantOverrides"] = {
            "variableValues": {
                "owner": owner,
                "task": task,
                "reason": reason,
                "context": context,
                "recipient": recipient
            }
        }
    
    response = requests.post(
        f"{VAPI_API_BASE}/call",
        headers=get_vapi_headers(),
        json=call_config,
        timeout=VAPI_REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    call = response.json()
    
    return {
        "call_id": call.get('id'),
        "status": call.get('status'),
        "phone_number": phone_number,
        "assistant_id": assistant_id
    }


def get_call_status(call_id: str) -> dict:
    """Get the status and details of a call."""
    response = requests.get(
        f"{VAPI_API_BASE}/call/{call_id}",
        headers=get_vapi_headers(),
        timeout=VAPI_REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


def extract_transcript(call: dict) -> str:
    """Extract the full transcript from VAPI call response.
    
    VAPI can return transcript in multiple formats:
    1. call['transcript'] - plain text string (dynamically created assistants)
    2. call['messages'] - array of message objects (pre-configured assistants)
    3. call['artifact']['transcript'] - from artifact plan
    
    This function checks all sources and returns the best available transcript.
    """
    # First try the simple transcript field
    transcript = call.get('transcript', '')
    if transcript and len(transcript) > 50:  # Has meaningful content
        return transcript
    
    # Check artifact for transcript (VAPI stores analysis here)
    artifact = call.get('artifact', {})
    if artifact:
        artifact_transcript = artifact.get('transcript', '')
        if artifact_transcript and len(artifact_transcript) > len(transcript):
            transcript = artifact_transcript
    
    # Check messages array (pre-configured assistants often use this)
    messages = call.get('messages', [])
    if messages and isinstance(messages, list):
        # Format messages into readable transcript
        formatted_lines = []
        for msg in messages:
            role = msg.get('role', 'unknown')
            content = msg.get('content', '') or msg.get('message', '')
            
            # Skip empty messages or system messages
            if not content or role == 'system':
                continue
            
            # Map roles to friendly names
            if role in ['assistant', 'bot']:
                speaker = 'AI'
            elif role in ['user', 'customer']:
                speaker = 'User'
            else:
                speaker = role.capitalize()
            
            formatted_lines.append(f"{speaker}: {content}")
        
        if formatted_lines:
            messages_transcript = '\n'.join(formatted_lines)
            # Use messages transcript if it's longer/more complete
            if len(messages_transcript) > len(transcript):
                transcript = messages_transcript
    
    return transcript


def wait_for_call_completion(call_id: str, timeout: int | None = None) -> dict:
    """Wait for a call to complete and return the result.
    
    Uses VAPI_WAIT_TIMEOUT seconds (default 900) so this stays under orchestrator
    phone_call subprocess timeout. Override for tests.
    """
    if timeout is None:
        timeout = get_int('VAPI_WAIT_TIMEOUT', 900)
    start_time = time.time()
    last_status = "unknown"
    
    while time.time() - start_time < timeout:
        try:
            call = get_call_status(call_id)
            last_status = call.get('status', 'unknown')
            
            if last_status in ['ended', 'failed']:
                end_reason = call.get('endedReason', '')
                
                return {
                    "status": last_status,
                    "duration_seconds": call.get('duration'),
                    "transcript": extract_transcript(call),  # Use full transcript extractor
                    "summary": call.get('summary', ''),
                    "end_reason": end_reason,
                    "recording_url": call.get('recordingUrl', ''),
                    "call_failed": is_call_failure(end_reason)
                }
        except Exception:
            pass
        
        time.sleep(3)  # Poll every 3 seconds
    
    # Timeout but call still in progress
    return {
        "status": "in-progress", 
        "message": "Call still in progress. Ask 'what happened on the call?' or check Canvas later.",
        "call_id": call_id
    }


def is_call_failure(end_reason: str) -> bool:
    """Check if the call end reason indicates a failure to connect."""
    failure_reasons = [
        'customer-did-not-answer',
        'customer-busy',
        'customer-rejected',
        'customer-number-invalid',
        'customer-not-found',
        'voicemail-reached',
        'machine-detected',
        'error-',  # Any error prefix
        'daily-limit',
    ]
    
    if not end_reason:
        return False
    
    end_reason_lower = end_reason.lower()
    return any(reason in end_reason_lower for reason in failure_reasons)


def get_failure_message(end_reason: str, recipient: str) -> str:
    """Convert call end reason to user-friendly message."""
    reason_messages = {
        'customer-did-not-answer': f"{recipient} didn't answer. The call may have gone to voicemail.",
        'customer-busy': f"{recipient}'s line was busy.",
        'customer-rejected': f"{recipient} rejected the call.",
        'customer-number-invalid': f"The phone number for {recipient} appears to be invalid.",
        'voicemail-reached': f"Got {recipient}'s voicemail.",
        'machine-detected': f"Reached an automated system for {recipient}.",
    }
    
    if not end_reason:
        return "Call ended unexpectedly."
    
    end_reason_lower = end_reason.lower()
    
    # Check for daily limit error
    if 'daily-limit' in end_reason_lower or 'outbound-daily-limit' in end_reason_lower:
        return "Daily call limit reached. Free Vapi numbers have a limited number of calls per day."
    
    # Check known reasons
    for key, message in reason_messages.items():
        if key in end_reason_lower:
            return message
    
    # Check for generic errors
    if 'error' in end_reason_lower:
        return f"Call failed: {end_reason}"
    
    return f"Call ended: {end_reason}"


def list_recent_calls(limit: int = 10) -> list:
    """List recent calls."""
    response = requests.get(
        f"{VAPI_API_BASE}/call",
        headers=get_vapi_headers(),
        params={"limit": limit},
        timeout=VAPI_REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    calls = response.json()
    
    return [
        {
            "id": c.get('id'),
            "status": c.get('status'),
            "customer": c.get('customer', {}).get('number', '?'),
            "duration": c.get('duration'),
            "created_at": c.get('createdAt')
        }
        for c in calls if c
    ]


def save_call_to_memory(recipient: str, task: str, summary: str, transcript: str):
    """Save call summary to Jarvis memory for future recall.
    
    This allows questions like "What did Andrew say about dinner?"
    """
    try:
        from memory_db import MemoryDB
        from datetime import datetime
        
        db = MemoryDB()
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        
        # Create a searchable memory key
        key = f"phone_call_{recipient.lower().replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M')}"
        
        # Create value with summary and key details
        value = f"Phone call to {recipient} on {timestamp}. Task: {task}. Summary: {summary}"
        
        # Add key transcript snippets if relevant
        if transcript:
            # Extract short meaningful bits (avoid very long transcripts in memory)
            value += f" Key points from conversation: {transcript[:500]}"
        
        db.remember(
            key=key,
            value=value,
            category="phone_calls",
            importance=7  # Moderately important - can be recalled
        )
        return True
    except Exception:
        # Don't fail the call if memory save fails
        return False


def save_call_to_canvas(call_id: str, recipient: str, task: str, result: dict):
    """Save call transcript and summary to Canvas in 'Phone Calls' folder."""
    try:
        import subprocess
        from datetime import datetime
        
        transcript = result.get('transcript', 'No transcript available')
        summary = result.get('summary', '')
        duration = result.get('duration_seconds', 0)
        status = result.get('status', 'unknown')
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        
        # Also save to memory for future recall
        save_call_to_memory(recipient, task, summary, transcript)
        
        content = f"""# Phone Call: {recipient}

**Date:** {timestamp}
**To:** {recipient}
**Task:** {task}
**Status:** {status}
**Duration:** {duration or 'N/A'} seconds
**Call ID:** {call_id}

## Summary
{summary or 'No summary generated'}

## Full Transcript
```
{transcript}
```

---
*Auto-saved by Jarvis Phone Call Tool*
"""
        
        # Use canvas tool to save - prefix with "Phone Calls/" for organization
        date_str = datetime.now().strftime("%Y-%m-%d_%H%M")
        canvas_args = json.dumps({
            "action": "create",
            "title": f"Phone Calls/{date_str} - {recipient}",
            "content": content
        })
        
        subprocess.run(
            [sys.executable, str(Path(__file__).parent / 'canvas.py'), canvas_args],
            capture_output=True,
            timeout=30
        )
        return True
    except Exception:
        return False  # Non-critical, don't fail the call


def action_call(args: dict) -> dict:
    """Make an outbound phone call."""
    recipient = args.get('recipient', '')
    task = args.get('task', '')
    context = args.get('context', '')
    persona = args.get('persona', 'default')
    owner = args.get('owner', get_config_value('OWNER_NAME', 'Boss'))
    
    # Check config for default wait behavior
    # VAPI_WAIT_FOR_CALL=true means wait during call for instant results
    # VAPI_WAIT_FOR_CALL=false means fire and forget (check later)
    # CONFIG ALWAYS WINS - LLM cannot override this (prevents LLM from randomly deciding not to wait)
    config_wait_raw = get_config_value('VAPI_WAIT_FOR_CALL', 'false')
    wait = config_wait_raw.lower() == 'true'
    
    # Debug log for troubleshooting
    import logging
    logging.info(f"[phone_call] wait={wait} (VAPI_WAIT_FOR_CALL={config_wait_raw}, ignoring LLM args['wait']={args.get('wait', 'not set')})")
    
    if not recipient:
        return {"ok": False, "speech": "Who should I call?", "error": "No recipient"}
    
    if not task:
        return {"ok": False, "speech": "What should I tell them?", "error": "No task"}
    
    try:
        # Resolve phone number first
        phone_number = resolve_phone_number(recipient)
        
        # Check if a call is already in progress (global lock)
        in_progress = is_call_in_progress()
        if in_progress:
            # Check if that call is done now
            try:
                call = get_call_status(in_progress['call_id'])
                if call.get('status') == 'ended':
                    # Call finished! Clear lock and return result
                    clear_call_in_progress()
                    transcript = extract_transcript(call)  # Use full transcript extractor
                    summary = call.get('summary', '')
                    prior_task = in_progress.get('task') or "Phone call"
                    saved = save_call_to_canvas(in_progress['call_id'], in_progress['recipient'], prior_task, {
                        'status': 'ended',
                        'transcript': transcript,
                        'summary': summary,
                        'duration_seconds': call.get('duration')
                    })
                    speech = f"Call completed. {summary}" if summary else "Call completed."
                    if saved:
                        speech += " Full transcript saved to Canvas in Phone Calls folder."
                    return {
                        "ok": True,
                        "speech": speech,
                        "data": {"call_id": in_progress['call_id'], "transcript": transcript, "summary": summary, "saved_to_canvas": saved}
                    }
                else:
                    return {
                        "ok": True, 
                        "speech": f"Call to {in_progress['recipient']} is in progress. Please wait.",
                        "data": {"in_progress": True, "call_id": in_progress['call_id']}
                    }
            except Exception:
                clear_call_in_progress()  # Clear stale lock
        
        # Check for recent duplicate call to same number
        if check_duplicate_call(phone_number, cooldown_seconds=120):
            return {
                "ok": True,
                "speech": f"I just called {recipient}. Check Canvas for the transcript.",
                "data": {"recent_call": True}
            }
        
        # Start the call (pass pre-resolved phone number)
        call_info = make_call(recipient, task, context, persona, owner, phone_number=phone_number)
        call_id = call_info['call_id']
        
        # Mark call as in progress and record it
        set_call_in_progress(call_id, phone_number, recipient, task)
        record_call_made(phone_number)
        
        if not wait:
            return {
                "ok": True,
                "speech": f"Calling {recipient} now. Ask me 'what happened on that call' when you're ready for results.",
                "data": {
                    **call_info,
                    "wait_mode": False,
                    "hint": "Ask 'what happened on that call' or 'check my last call' for results"
                }
            }
        
        # Wait for completion (blocking - VAPI_WAIT_FOR_CALL=true)
        result = wait_for_call_completion(call_id)
        
        # Clear the in-progress lock
        clear_call_in_progress()
        
        if result['status'] == 'ended':
            summary = result.get('summary', '')
            transcript = result.get('transcript', '')
            end_reason = result.get('end_reason', '')
            call_failed = result.get('call_failed', False)
            
            # Check if call actually failed to connect
            if call_failed:
                failure_msg = get_failure_message(end_reason, recipient)
                return {
                    "ok": False,
                    "speech": failure_msg,
                    "data": {
                        "call_id": call_id,
                        "end_reason": end_reason,
                        "transcript": transcript,  # May contain voicemail prompt
                        "call_failed": True
                    }
                }
            
            # Call succeeded - save to Canvas
            saved = save_call_to_canvas(call_id, recipient, task, result)
            
            # Build smart response with context for follow-up suggestions
            speech = f"Call completed."
            if summary:
                speech += f" {summary}"
            
            # Tell LLM transcript is already saved - don't create another canvas page!
            if saved:
                speech += " Full transcript saved to Canvas in Phone Calls folder."
            
            # Add hint about what user might want to do next
            # (The LLM can pick up on this and suggest actions)
            follow_up_hints = []
            transcript_lower = transcript.lower()
            if any(word in transcript_lower for word in ['yes', 'agreed', 'sounds good', 'i\'m in', 'sure']):
                follow_up_hints.append("They agreed!")
            if any(word in transcript_lower for word in ['time', 'pm', 'am', 'o\'clock', 'tonight', 'tomorrow']):
                follow_up_hints.append("Time was discussed - maybe set a reminder?")
            
            return {
                "ok": True,
                "speech": speech,
                "data": {
                    "call_id": call_id,
                    "duration": result.get('duration_seconds'),
                    "transcript": transcript,
                    "summary": summary,
                    "recording_url": result.get('recording_url'),
                    "saved_to_canvas": saved,
                    "canvas_location": "Phone Calls/ folder" if saved else None,
                    "follow_up_hints": follow_up_hints
                }
            }
        elif result['status'] == 'in-progress':
            # Call still in progress (we hit our wait timeout)
            return {
                "ok": True,
                "speech": f"Call to {recipient} is in progress. Ask 'what happened on the call?' for results, or check Canvas later.",
                "data": {
                    "call_id": call_id,
                    "status": "in-progress",
                    "note": "Call still active - ask for status later"
                }
            }
        else:
            return {
                "ok": False,
                "speech": f"Call ended with status: {result['status']}. {result.get('end_reason', '')}",
                "data": result
            }
            
    except ValueError as e:
        return {"ok": False, "speech": str(e), "error": str(e)}
    except requests.exceptions.HTTPError as e:
        error_msg = str(e)
        try:
            error_detail = e.response.json()
            error_msg = error_detail.get('message', str(e))
        except Exception:
            pass
        
        # Provide friendly messages for known errors
        if 'daily-limit' in error_msg.lower() or 'outbound-daily-limit' in error_msg.lower():
            return {
                "ok": False, 
                "speech": "Daily call limit reached. Free Vapi phone numbers have limited outbound calls per day. Try again tomorrow or upgrade your Vapi plan.",
                "error": error_msg
            }
        
        return {"ok": False, "speech": f"Call failed: {error_msg}", "error": error_msg}


def action_status(args: dict) -> dict:
    """Check status of a call (defaults to most recent call if no ID provided)."""
    call_id = args.get('call_id', '')
    save_to_canvas = args.get('save', True)  # Auto-save completed calls
    
    # If no call_id, get the most recent call
    if not call_id:
        try:
            calls = list_recent_calls(limit=1)
            if calls:
                call_id = calls[0]['id']
            else:
                return {"ok": False, "speech": "No recent calls found", "error": "No calls"}
        except Exception:
            return {"ok": False, "speech": "Couldn't find recent calls", "error": "No calls"}
    
    try:
        call = get_call_status(call_id)
        status = call.get('status', 'unknown')
        transcript = extract_transcript(call)  # Use full transcript extractor
        summary = call.get('summary', '')
        
        # If call is done and has transcript, save to Canvas
        if status == 'ended' and transcript and save_to_canvas:
            in_progress = is_call_in_progress()
            tracked_call = (
                in_progress
                if in_progress and in_progress.get('call_id') == call_id
                else None
            )
            customer = call.get('customer', {}).get('number', 'Unknown')
            recipient = (tracked_call or {}).get('recipient') or customer
            task = (tracked_call or {}).get('task') or "Phone call"
            save_call_to_canvas(call_id, recipient, task, {
                'status': status,
                'transcript': transcript,
                'summary': summary,
                'duration_seconds': call.get('duration')
            })
            if tracked_call:
                clear_call_in_progress(call_id)
        
        # Build speech response
        if status == 'ended' and transcript:
            # Tell LLM the transcript was saved - DON'T create another canvas page!
            if save_to_canvas:
                speech = f"Call completed. {summary}" if summary else "Call completed."
                speech += " Full transcript already saved to Canvas in Phone Calls folder - no need to create another canvas page."
            else:
                speech = f"Call completed. {summary}" if summary else f"Call completed. Here's what was said: {transcript[:150]}..."
        elif status == 'in-progress':
            speech = "Call is still in progress"
        else:
            speech = f"Call status: {status}"
        
        return {
            "ok": True,
            "speech": speech,
            "data": {
                "status": status,
                "duration": call.get('duration'),
                "transcript": transcript,
                "summary": summary,
                "saved_to_canvas": save_to_canvas and status == 'ended',
                "canvas_location": "Phone Calls/ folder" if save_to_canvas and status == 'ended' else None
            }
        }
    except Exception as e:
        return {"ok": False, "speech": f"Error: {e}", "error": str(e)}


def action_list(args: dict) -> dict:
    """List recent calls."""
    limit = args.get('limit', 5)
    
    try:
        calls = list_recent_calls(limit)
        
        if not calls:
            return {"ok": True, "speech": "No recent calls", "data": {"calls": []}}
        
        speech_parts = ["Recent calls:"]
        for c in calls[:3]:
            speech_parts.append(f"{c['customer']} - {c['status']}")
        
        return {
            "ok": True,
            "speech": ' '.join(speech_parts),
            "data": {"calls": calls}
        }
    except Exception as e:
        return {"ok": False, "speech": f"Error: {e}", "error": str(e)}


def action_contacts(args: dict) -> dict:
    """List or add contacts."""
    add_name = args.get('add_name', '')
    add_number = args.get('add_number', '')
    
    if add_name and add_number:
        # Save to memory
        try:
            sys.path.insert(0, str(Path(__file__).parent.parent / 'lib'))
            from memory_db import MemoryDB
            db = MemoryDB()
            db.remember(
                key=f"{add_name.lower()}_phone",
                value=add_number,
                category="contacts",
                importance=7
            )
            CONTACTS[add_name.lower()] = add_number
            return {
                "ok": True,
                "speech": f"Added {add_name} with number {add_number}",
                "data": {"name": add_name, "number": add_number}
            }
        except Exception as e:
            return {"ok": False, "speech": f"Error saving contact: {e}", "error": str(e)}
    
    # List contacts
    load_contacts()
    if not CONTACTS:
        return {"ok": True, "speech": "No contacts saved yet", "data": {"contacts": {}}}
    
    return {
        "ok": True,
        "speech": f"You have {len(CONTACTS)} contacts: {', '.join(CONTACTS.keys())}",
        "data": {"contacts": CONTACTS}
    }


ACTIONS = {
    'call': action_call,
    'status': action_status,
    'list': action_list,
    'contacts': action_contacts
}


def main():
    try:
        # Load config
        load_config()
        
        # Parse arguments
        if len(sys.argv) > 1:
            args = json.loads(sys.argv[1])
        else:
            args = json.load(sys.stdin)
        
        action = args.get('action', 'call')
        
        if action not in ACTIONS:
            print(json.dumps({
                "ok": False,
                "speech": f"Unknown action: {action}",
                "error": f"Valid actions: {list(ACTIONS.keys())}"
            }))
            sys.exit(1)
        
        result = ACTIONS[action](args)
        print(json.dumps(result))
        
        if not result.get('ok'):
            sys.exit(1)
            
    except json.JSONDecodeError as e:
        print(json.dumps({"ok": False, "speech": "Invalid JSON input", "error": str(e)}))
        sys.exit(1)
    except Exception as e:
        print(json.dumps({"ok": False, "speech": f"Error: {e}", "error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
