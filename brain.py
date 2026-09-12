"""LLM reasoning layer with tool use via Groq.

Design principles (agentic, NOT command-based):
- The LLM understands FREE-FORM intent in any phrasing — no fixed command list.
- Pending WhatsApp confirmations are resolved by the LLM itself (any wording:
  "haan", "bilkul", "bhej do", "sure", "na rehne do"...), with a tiny fast-path
  for bare yes/no words purely as a latency optimization.
- Known contacts are injected into the prompt so misheard names get matched to
  the real contact by the LLM, not by a hardcoded alias table.
- every tool call carries its own spoken reply ("speak" field) —
  no second LLM round-trip to phrase the confirmation
- 20b primary (fast, reliable tool-JSON), 120b fallback, retry loop
"""
import json
import re
import time

from groq import Groq

import config

_client = Groq(api_key=config.GROQ_API_KEY)

SYSTEM_PROMPT = """You are SAATHI, a fast, friendly voice assistant on the user's Windows laptop.
If asked your name, say "SAATHI".
The user may speak Urdu (Pakistani), English, or Pashto. ALWAYS reply in the SAME
language the user used — including every "speak" field: Urdu input → Urdu
speak, English input → English speak, Pashto input → Pashto speak.

CRITICAL SCRIPT RULE: Whenever you write Urdu (or Pashto), write it phonetically
using Latin/Roman letters ONLY — e.g. "kya hal hai", "shukriya", "message bhej
diya hai". NEVER use Urdu/Perso-Arabic script (ا ب پ ت ...) anywhere, in any
"speak" field or any other text you produce, even if the user's own message
was written in Urdu script. This applies to WhatsApp message text you compose
on the user's behalf too — write the message body in Roman Urdu, not Urdu script.

You understand FREE-FORM intent — there is NO fixed command list. Interpret any
natural phrasing and map it to the closest capability:
- IMPORTANT: You CAN take screenshots and record the screen — the tools
  take_screenshot / start_recording / stop_recording are installed and
  working. NEVER say you cannot capture the screen; just call the tool.
- The user wants to open a website in the browser AND THEN control it with
  follow-up commands (click something on it, scroll, go back, type into a
  field, read the page aloud, switch/close tabs, zoom, refresh) → use
  browser_action (action='open') first, then browser_action with the
  appropriate follow-up action — this is a DIFFERENT, controllable browser
  window from open_app, and stays open across turns so the user never
  repeats the full request.
- The user wants something opened/launched/started on the computer or web
  (an app, program, or website, phrased any way) with NO expectation of
  further clicking on it → open_app with the name.
- The user wants a WhatsApp message sent to a person (phrased any way:
  "bolo", "likho", "bhejo", "message", "text", "tell them"...) → send_whatsapp.
  A person's name is NEVER a valid app_name.
- The user wants information, news, score, weather, or to look something up
  → web_search with a clean query.
- The user wants a screenshot of the screen (any phrasing: "screenshot lo",
  "capture karo", "screen ki photo") → take_screenshot.
- The user wants the screen recorded ("recording shuru karo", "screen record
  karo") → start_recording. When a recording is running and the user says
  stop/bas/kaafi → stop_recording.
- Anything else conversational → general_reply.

WHATSAPP rules:
- Put the user's EXACT message text in "message" (their own words, never
  summarized or translated). If they said WHAT to send, it must not be empty.
- If only the contact is known and no text was said, call send_whatsapp with
  an EMPTY message "" — the assistant will ask "kya likhna hai?" and wait.
- "speak" must be a natural confirmation QUESTION including the contact name
  and the message text (if known), in the user's language. Example:
  Urdu: "Ali ko 'main aa raha hoon' bhej doon?" / English: "Send 'main aa raha
  hoon' to Ali?"

EMAIL rules:
- The user wants to send an EMAIL (any phrasing: "email bhejo", "mail kar do",
  "send an email to X", "X ko mail likho") → send_email.
- "to": the recipient as spoken — a NAME (resolved from saved email contacts)
  or the raw address if the user said one.
- "subject"/"body": the user's exact words. Body may be empty if they only
  said the recipient so far — the assistant will then ask what to write.
- "speak" must be a confirmation QUESTION with recipient (and subject/body if
  known), in the user's language. Example: "Remsha ko 'meeting 5 baje' email
  bhej doon?" / "Send the email to Remsha?"

BROWSER rules:
- action='type' needs BOTH "target" (a hint like 'search', 'email', or empty
  if there's one obvious field) AND "extra" (the exact text to type).
- action='switch_tab' needs "target" as a zero-based index string: first tab
  = "0", second tab = "1", etc. Convert ordinal words yourself.
- action='get_text'/'get_title'/'get_link_url' read live page content —
  your "speak" field is IGNORED for these; the actual result is spoken
  instead, so just describe the intent briefly in "speak".

Be quick and natural — this is a live voice conversation."""

# Bare-word fast path (pure latency optimization for the most common replies;
# every OTHER phrasing still goes through the LLM — nothing is a "command").
_FAST_YES = {"haan", "han", "haan ji", "yes", "ok", "okay", "theek hai", "ji", "ہاں", "جی", "جی ہاں"}
_FAST_NO = {"nahi", "nahin", "nai", "no", "نہیں"}

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "send_whatsapp",
            "description": "Send a WhatsApp message to a contact by name. Use whenever the user wants to message someone, in any phrasing.",
            "parameters": {
                "type": "object",
                "properties": {
                    "contact": {"type": "string", "description": "Contact name as spoken (matched to KNOWN CONTACTS spelling if one resembles it)"},
                    "message": {"type": "string", "description": "Exact message text the user wants sent. Empty string if the user hasn't said what to write yet."},
                    "speak": {"type": "string", "description": "Confirmation QUESTION in user's language (includes contact name and message text if known)"},
                },
                "required": ["contact", "message", "speak"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_email",
            "description": "Send an EMAIL to a person or address. Use whenever the user wants to send an email, in any phrasing.",
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "Recipient as spoken: a person's name OR an email address"},
                    "subject": {"type": "string", "description": "Email subject from the user's words. Empty if not said."},
                    "body": {"type": "string", "description": "Email body from the user's exact words. Empty if not dictated yet."},
                    "speak": {"type": "string", "description": "Confirmation QUESTION in user's language (includes recipient and subject/body if known)"},
                },
                "required": ["to", "subject", "body", "speak"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_send",
            "description": "Cancel the staged send (WhatsApp message or email). Call ONLY when the user clearly declines, postpones, or says to hold off while a send is PENDING confirmation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "speak": {"type": "string", "description": "Short STATEMENT confirming cancellation, in user's language, e.g. 'Theek hai, cancel kar diya.' — NEVER a question."},
                },
                "required": ["speak"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_app",
            "description": "Open ANY application, program, or website on the computer (installed apps, UWP apps, browsers, YouTube, anything).",
            "parameters": {
                "type": "object",
                "properties": {
                    "app_name": {"type": "string", "description": "App, program, or website name as spoken"},
                    "speak": {"type": "string", "description": "Short spoken confirmation in user's language"},
                },
                "required": ["app_name", "speak"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web for something. Use when the user wants information, news, weather, or to look something up.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query in the user's language"},
                    "speak": {"type": "string", "description": "Short spoken confirmation in user's language"},
                },
                "required": ["query", "speak"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "take_screenshot",
            "description": "Capture a PNG screenshot of the screen right now and save it.",
            "parameters": {
                "type": "object",
                "properties": {
                    "speak": {"type": "string", "description": "Short spoken confirmation in the USER'S language, e.g. Urdu: 'Screenshot le liya.' / English: 'Screenshot taken.'"},
                },
                "required": ["speak"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "start_recording",
            "description": "Start recording the screen as an MP4 video (background). Use when the user asks to record the screen.",
            "parameters": {
                "type": "object",
                "properties": {
                    "speak": {"type": "string", "description": "Short spoken confirmation in the USER'S language, e.g. Urdu: 'Recording shuru kar di.' / English: 'Recording started.'"},
                },
                "required": ["speak"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "stop_recording",
            "description": "Stop the running screen recording and save the MP4. Use when a recording is active and the user says to stop.",
            "parameters": {
                "type": "object",
                "properties": {
                    "speak": {"type": "string", "description": "Short spoken confirmation in the USER'S language, e.g. Urdu: 'Recording band kar di.' / English: 'Recording stopped.'"},
                },
                "required": ["speak"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_action",
            "description": (
                "Control a live, already-open browser window for follow-up "
                "actions on a website — use when the user says things like "
                "'click on X', 'is par click karo', 'scroll down/up', "
                "'neeche/upar scroll karo', 'go back', 'peeche jao', 'refresh karo', "
                "'is page par kya likha hai batao' (read page text), "
                "'search box mein X likho' (type into a field), 'enter dabao', "
                "'naya tab kholo', 'pehli/doosri tab par jao' (switch tab, 0-based index), "
                "'ye tab band karo', 'zoom karo'/'zoom out karo', 'ye kaunsa page hai' "
                "(page title), 'ye link kahan jata hai' (get a link's URL without "
                "clicking it), or 'open <site> in the browser' as a first step before "
                "clicking things on it. This keeps ONE browser open across turns so the "
                "user never has to repeat the whole request — each new voice command "
                "just acts on the SAME page."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "open", "click", "scroll_down", "scroll_up", "back",
                            "refresh", "type", "press_enter", "get_text", "get_title",
                            "get_link_url", "new_tab", "switch_tab", "close_tab",
                            "zoom_in", "zoom_out", "reset_zoom",
                        ],
                        "description": (
                            "open: navigate to a URL/search term. click: click an element by "
                            "its visible text. scroll_down/scroll_up: scroll the page. "
                            "back: previous page. refresh: reload current page. "
                            "type: type text into a field matched by target (use 'extra' for "
                            "the text to type). press_enter: submit the focused field. "
                            "get_text: read the page's visible text aloud. get_title: read the "
                            "page/tab title aloud. get_link_url: return a link's destination "
                            "without clicking (target = link's visible text). new_tab: open a "
                            "new tab (target = optional URL/search term to load in it). "
                            "switch_tab: switch to tab number (target = zero-based index as a "
                            "string, e.g. '0' for first tab, '1' for second). close_tab: close "
                            "the current tab. zoom_in/zoom_out: adjust page zoom by one step. "
                            "reset_zoom: reset zoom to 100%."
                        ),
                    },
                    "target": {
                        "type": "string",
                        "description": (
                            "For 'open': a URL or search term. For 'click'/'get_link_url': the "
                            "visible text of the link/button. For 'type': the field's "
                            "placeholder/name/label hint (empty string is OK if there's an "
                            "obvious single field, e.g. a search box). For 'new_tab': optional "
                            "URL/search term. For 'switch_tab': the zero-based tab index as a "
                            "string. Empty for scroll/back/refresh/press_enter/get_text/"
                            "get_title/close_tab/zoom_in/zoom_out/reset_zoom."
                        ),
                    },
                    "extra": {
                        "type": "string",
                        "description": "ONLY used with action='type' — the exact text to type into the field. Empty for all other actions.",
                    },
                    "speak": {"type": "string", "description": "Short spoken confirmation in the USER'S language"},
                },
                "required": ["action", "target", "speak"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "general_reply",
            "description": "Reply conversationally. Use for greetings, questions, chat, or anything that is not a task.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reply": {"type": "string", "description": "Your spoken reply, in the user's language (max 25 words)"},
                },
                "required": ["reply"],
            },
        },
    },
]

# Functions the executor registers; set by executor.py
_executor = None

# Optional hook: speak progress text BEFORE a slow tool runs (set by main.py)
_pre_speech = None

# Pending WhatsApp confirmation: {"contact": str, "message": str|None}
_pending_whatsapp: dict = {}

# LLM sometimes puts the ask-phrase itself in "message" — guard for that.
_ASK_PHRASES = {
    "کیا لکھنا ہے", "کیا لکھوں", "kya likhna hai", "kya likhna hy",
    "what should i write", "kya message bhejna hai", "kya bhejna hai",
}

_MSG_VERBS = (
    r"(?:bol\s*do|bolo|bhejo|bhej\s*do|likh\s*do|likho|send\s*karo|send|"
    r"text\s*karo|message\s*karo|bata\s*do|batao|"
    r"بول\s*دو|بولو|بھیجو|بھیج\s*دو|لکھو|لکھ\s*دو|بتا\s*دو|بتاؤ)"
)
_GENERIC_WORDS = {"message", "msg", "text", "پیغام", "whatsapp message"}


def _extract_message(user_text: str, contact: str) -> str | None:
    t = (user_text or "").strip().strip(".!")
    m = re.match(
        rf"^(?P<c>.+?)\s*(?:ko|کو)\s+(?P<rest>.+)$", t, re.IGNORECASE
    )
    if not m:
        return None
    said_contact = m.group("c").strip().lower()
    heard_contact = (contact or "").strip().lower()
    if heard_contact and heard_contact not in said_contact and said_contact not in heard_contact:
        return None
    rest = m.group("rest").strip()
    rest = re.sub(rf"\s*{_MSG_VERBS}\s*$", "", rest, flags=re.IGNORECASE).strip()
    rest = rest.strip("'\"۔?")
    if not rest or rest.lower() in _GENERIC_WORDS:
        return None
    return rest


def set_executor(fn):
    global _executor
    _executor = fn


def set_pre_speech(fn):
    global _pre_speech
    _pre_speech = fn


def _known_contacts_line() -> str:
    try:
        from whatsapp_bot import _load_contacts
        names = [n for n, v in _load_contacts().items()]
        return ", ".join(names) if names else ""
    except Exception:
        return ""


def _is_rate_limit(e: Exception) -> bool:
    return "429" in str(e) or "rate" in str(e).lower()


def _complete(messages, **kwargs):
    try:
        return _client.chat.completions.create(
            messages=messages,
            temperature=0.3,
            max_completion_tokens=600,
            reasoning_effort="low",
            **kwargs,
        )
    except TypeError:
        return _client.chat.completions.create(
            messages=messages,
            temperature=0.3,
            max_completion_tokens=600,
            **kwargs,
        )


_SCREEN_TOOLS = {"take_screenshot", "start_recording", "stop_recording"}

_UR_HINTS = {"lo", "le", "karo", "kar", "do", "dein", "diya", "di", "liya", "li",
             "meri", "mera", "mere", "ki", "ka", "ke", "se", "ko", "band", "shuru",
             "wala", "wali"}
_EN_HINTS = {"take", "the", "an", "my", "can", "you", "of", "please", "capture"}


def _script_of(text: str) -> str:
    t = (text or "").lower()
    for ch in t:
        if 0x0600 <= ord(ch) <= 0x06FF:
            return "ur"
    words = set(re.findall(r"[a-z']+", t))
    if words & _EN_HINTS:
        return "en"
    if words & _UR_HINTS:
        return "ur"
    return "en"


_CAPTURE_TOOL = {"screenshot": "take_screenshot", "start": "start_recording", "stop": "stop_recording"}


def _capture_intent(text: str) -> str | None:
    t = (text or "").lower()
    if not t or "whatsapp" in t or "bhej" in t or "send" in t:
        return None
    for w in ("screenshot", "screen shot", "سکرین شاٹ", "اسکرین شاٹ",
              "اسکرین کی تصویر", "سکرین کی تصویر", "تصویر کھینچ"):
        if w in t:
            return "screenshot"
    for w in ("recording shuru", "shuru karo recording", "recording start",
              "start recording", "screen record", "record karo",
              "ریکارڈنگ شروع", "ریکارڈنگ سٹارٹ"):
        if w in t:
            return "start"
    for w in ("recording band", "band karo recording", "recording stop",
              "stop recording", "recording rok", "ریکارڈنگ بند"):
        if w in t:
            return "stop"
    return None


def _force_capture(kind: str, user_text: str) -> str:
    print(f"🔧 Capture intent detected — direct tool run ({kind})")
    return _screen_reply(_CAPTURE_TOOL[kind], {}, user_text)


def _screen_reply(name: str, args: dict, user_text: str) -> str:
    if _executor is None:
        return "Screen tools available nahi hain."
    raw = _executor(name, args) or ""
    print(f"⚙  Result: {raw}")
    lang = _script_of(user_text)
    if "error" in raw.lower():
        msg = re.sub(r"(?i)^error:\s*", "", raw).strip()
        return ("Sorry, that didn't work: " if lang == "en" else "Maaf kijiye, ye nahi ho saka: ") + msg
    if name == "take_screenshot":
        return "Screenshot taken." if lang == "en" else "Screenshot le liya."
    if name == "start_recording":
        return "Recording started." if lang == "en" else "Recording shuru kar di hai."
    m = re.search(r"\((\d+)m (\d+)s\)", raw)
    if m:
        mins, secs = int(m.group(1)), int(m.group(2))
        if lang == "en":
            return f"Recording saved — {mins} minute{'s' if mins != 1 else ''} and {secs} seconds."
        return f"Recording save ho gayi — {mins} minute {secs} second."
    return "Recording stopped." if lang == "en" else "Recording band kar di."


def _execute_and_reply(name: str, args: dict) -> str:
    """Run the tool and return the spoken reply (failure-aware)."""
    result_text = ""
    if _executor is not None and name != "general_reply":
        if _pre_speech is not None and name == "send_whatsapp":
            try:
                _pre_speech("Ek minute, WhatsApp khol raha hoon...")
            except Exception:
                pass
        result_text = _executor(name, args) or ""
        print(f"⚙  Result: {result_text}")

    FAILURE_MARKERS = ("error", "failed", "nahi mili", "nahi mila", "could not")
    failed = any(m in result_text.lower() for m in FAILURE_MARKERS)

    if failed:
        if "whatsapp error:" in result_text.lower():
            return result_text.replace("WhatsApp error:", "").strip() or result_text
        if "email error:" in result_text.lower():
            return result_text.replace("Email error:", "").strip() or result_text
        return f"Maaf kijiye, ye nahi ho saka: {result_text}"

    if name == "send_whatsapp":
        return f"{args.get('contact', '')} ko message bhej diya hai."
    if name == "send_email":
        return f"Email bhej diya hai."
    return args.get("speak") or args.get("reply") or "Ho gaya."


def _pending_addendum() -> str:
    if _pending_whatsapp.get("kind") == "email":
        to = _pending_whatsapp.get("to", "")
        subject = _pending_whatsapp.get("subject") or ""
        body = _pending_whatsapp.get("body") or ""
        return (
            f"\n\nPENDING CONTEXT: An EMAIL to '{to}' is staged"
            + (f" with subject '{subject}'" if subject else " (no subject)")
            + (f" and body '{body}'" if body else " (no body yet)")
            + " and awaits the user's decision. Interpret the latest utterance FREELY"
            " (any wording, any language):\n"
            "- Clearly approving → call send_email with the staged recipient/subject/body.\n"
            "- Clearly declining or postponing → call cancel_send.\n"
            "- Dictating the subject or body (or correcting it) → call send_email with"
            " the updated content.\n"
            "- An unrelated new request → ignore the pending state and handle it normally."
        )
    contact = _pending_whatsapp.get("contact", "")
    staged = _pending_whatsapp.get("message")
    return (
        f"\n\nPENDING CONTEXT: A WhatsApp message to '{contact}' is staged"
        + (f" with text '{staged}'" if staged else " (no text yet)")
        + " and awaits the user's decision. Interpret the latest utterance FREELY"
        " (any wording, any language):\n"
        "- Clearly approving the send (e.g. haan, bilkul, bhej do, sure, kar do) →"
        " call send_whatsapp for that contact; use the staged text unless the user"
        " dictated different/new text, in which case use THEIR text.\n"
        "- Clearly declining or postponing (e.g. nahi, rehne do, cancel, abhi nahi) →"
        " call cancel_send.\n"
        "- Dictating the message content (nothing staged yet, and the utterance IS"
        " the text to send) → call send_whatsapp with exactly that text.\n"
        "- An unrelated new request → ignore the pending state and handle it normally."
    )


def _stage_and_confirm(contact: str, message: str | None, question: str | None) -> str:
    _pending_whatsapp.clear()
    _pending_whatsapp.update({"contact": contact, "message": message})
    if message:
        if question and message in question and '""' not in question and "?" in question:
            return question
        return f"{contact} ko '{message}' bhej doon?"
    return f"{contact} ko kya message bhejna hai?"


def _fast_pending(user_text: str) -> str | None:
    if not _pending_whatsapp:
        return None
    t = (user_text or "").strip().lower().strip(".!" )

    if _pending_whatsapp.get("kind") == "email":
        if t in _FAST_NO:
            _pending_whatsapp.clear()
            return "Theek hai, email cancel kar diya."
        if t in _FAST_YES and _pending_whatsapp.get("to") and _pending_whatsapp.get("body"):
            staged = dict(_pending_whatsapp)
            _pending_whatsapp.clear()
            print(f"🛠  Tool: send_email(to='{staged['to']}')  [fast confirm]")
            return _execute_and_reply("send_email", {
                "to": staged["to"],
                "subject": staged.get("subject", ""),
                "body": staged.get("body", ""),
            })
        return None

    contact = _pending_whatsapp.get("contact", "")
    staged = _pending_whatsapp.get("message")

    if t in _FAST_NO:
        _pending_whatsapp.clear()
        return "Theek hai, message cancel kar diya."

    if t in _FAST_YES:
        if staged:
            _pending_whatsapp.clear()
            print(f"🛠  Tool: send_whatsapp(contact='{contact}', message='{staged}')  [fast confirm]")
            return _execute_and_reply("send_whatsapp", {"contact": contact, "message": staged})
        _pending_whatsapp.update({"contact": contact, "message": None})
        return "Kya message bhejna hai?"
    return None


def think(user_text: str, history: list | None = None) -> str:
    """Send text to LLM, execute chosen tool, return the spoken reply."""
    fast = _fast_pending(user_text)
    if fast is not None:
        return fast

    pending_active = bool(_pending_whatsapp)
    contact_hint = _pending_whatsapp.get("contact", "")

    addendum = _pending_addendum() if pending_active else ""
    known = _known_contacts_line()
    if known:
        addendum += (
            f"\n\nKNOWN CONTACTS (if the spoken name resembles one of these —"
            f" Whisper mishears names often — use the EXACT spelling): {known}"
        )

    messages = [{"role": "system", "content": SYSTEM_PROMPT + addendum}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": user_text})

    models = [config.GROQ_MODEL, config.FALLBACK_MODEL]

    last_err = None
    for i, m in enumerate(models):
        try:
            resp = _complete(messages, model=m, tools=TOOLS, tool_choice="auto")
            break
        except Exception as e:
            last_err = e
            if _is_rate_limit(e):
                print(f"⏳ {m} rate-limited — switching model instantly...")
            else:
                print(f"⚠  {m} failed ({str(e)[:60]}...) — retrying...")
    else:
        if _is_rate_limit(last_err):
            time.sleep(2.0)
            resp = _complete(messages, model=config.GROQ_MODEL, tools=TOOLS, tool_choice="auto")
        else:
            raise last_err

    msg = resp.choices[0].message

    capture = None if pending_active else _capture_intent(user_text)

    if not msg.tool_calls:
        if pending_active:
            _pending_whatsapp.clear()
        if capture:
            return _force_capture(capture, user_text)
        return msg.content or "..."

    call = msg.tool_calls[0]
    name = call.function.name
    try:
        args = json.loads(call.function.arguments or "{}")
    except json.JSONDecodeError:
        args = {}

    print(f"🛠  Tool: {name}({args})")

    if capture and name != _CAPTURE_TOOL[capture]:
        return _force_capture(capture, user_text)

    if name == "cancel_send":
        _pending_whatsapp.clear()
        return args.get("speak") or "Theek hai, cancel kar diya."

    if name == "send_whatsapp":
        contact = (args.get("contact") or "").strip()
        message = (args.get("message") or "").strip()
        if not message:
            extracted = _extract_message(user_text, contact)
            if extracted:
                message = extracted
                print(f"🔧 Extracted message from speech: '{message}'")
        if pending_active and contact.lower() == contact_hint.lower():
            _pending_whatsapp.clear()
            return _execute_and_reply("send_whatsapp", {"contact": contact or contact_hint,
                                                        "message": message})
        ask_norm = message.lower().strip("?.! ،")
        if not message or ask_norm in _ASK_PHRASES:
            return _stage_and_confirm(contact, None, args.get("speak"))
        return _stage_and_confirm(contact, message, args.get("speak"))

    if name == "send_email":
        to = (args.get("to") or "").strip()
        subject = (args.get("subject") or "").strip()
        body = (args.get("body") or "").strip()
        if pending_active and _pending_whatsapp.get("kind") == "email":
            staged = dict(_pending_whatsapp)
            _pending_whatsapp.clear()
            return _execute_and_reply("send_email", {
                "to": to or staged.get("to", ""),
                "subject": subject or staged.get("subject", ""),
                "body": body or staged.get("body", ""),
            })
        if not to:
            return "Kisko email bhejna hai? Naam ya address bolein."
        _pending_whatsapp.clear()
        _pending_whatsapp.update({"kind": "email", "to": to, "subject": subject, "body": body})
        q = args.get("speak") or ""
        if "?" not in q:
            detail = f" Subject: '{subject}'." if subject else ""
            q = f"{to} ko email bhej doon?{detail}"
        return q

    if pending_active and name == "general_reply":
        if _pending_whatsapp.get("kind") == "email":
            to = _pending_whatsapp.get("to", "")
            subject = _pending_whatsapp.get("subject") or ""
            detail = f" Subject: '{subject}'." if subject else ""
            return f"{to} ko email bhej doon?{detail}"
        contact = _pending_whatsapp.get("contact", "")
        staged = _pending_whatsapp.get("message")
        return _stage_and_confirm(contact, staged, None)

    if pending_active:
        _pending_whatsapp.clear()

    if name in _SCREEN_TOOLS:
        return _screen_reply(name, args, user_text)

    if name == "browser_action" and args.get("action") in ("get_text", "get_title", "get_link_url"):
        if _executor is None:
            return "Browser available nahi hai."
        raw = _executor(name, args) or ""
        print(f"⚙  Result: {raw}")
        if raw.lower().startswith("error"):
            return f"Maaf kijiye, ye nahi ho saka: {raw[6:].strip()}"
        return raw  # speak the actual page content/title/url, not a canned reply

    return _execute_and_reply(name, args)