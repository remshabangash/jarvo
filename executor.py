"""Executes the actions chosen by the LLM brain.

open_app resolves ANY spoken app name through app_resolver, a
platform-specific package (Windows / macOS / Linux) — see app_resolver/
for the per-OS resolution cascade. This module keeps only the OS-neutral
dispatch logic (WhatsApp, email, screen tools, controlled browser).
"""
import webbrowser

import brain
import screen_tools
import browser_bot
import winfocus
import app_resolver


# ---------------- App opening (per-OS resolution lives in app_resolver/) ----------------

def open_app(app_name: str) -> str:
    return app_resolver.resolve_and_open(app_name)


def web_search(query: str) -> str:
    url = f"https://www.google.com/search?q={query.replace(' ', '+')}"
    webbrowser.open(url)
    winfocus.bring_to_front_async(" ".join(query.split()[:3]), delay=0.8)
    return f"Opened web search for: {query}"


# ---------------- WhatsApp ----------------

def send_whatsapp(contact: str, message: str) -> str:
    from whatsapp_bot import send_message, WaError
    try:
        result = send_message(contact, message)
        winfocus.bring_to_front_async("WhatsApp", delay=0.3)
        return result
    except WaError as e:
        return f"WhatsApp error: {e}"


# ---------------- Email ----------------

def _send_email_tool(args: dict) -> str:
    from email_sender import send_email, EmailError
    try:
        return send_email(args.get("to", ""), args.get("subject", ""), args.get("body", ""))
    except EmailError as e:
        return f"Email error: {e}"
    except Exception as e:
        return f"Email error: {type(e).__name__}: {str(e)[:100]}"


# ---------------- Contacts (voice-saved) ----------------

def _add_contact_tool(args: dict) -> str:
    """Save what the user dictated: phone -> WhatsApp contacts, email ->
    email contacts (either or both). Returns a speakable result string."""
    name = (args.get("name") or "").strip()
    phone = (args.get("phone") or "").strip()
    email = (args.get("email") or "").strip()
    results = []
    try:
        if phone:
            from whatsapp_bot import save_contact
            results.append(save_contact(name, phone))
        if email:
            from email_sender import save_email_contact
            results.append(save_email_contact(name, email))
    except Exception as e:
        return f"Error: contact save nahi hua ({type(e).__name__}: {str(e)[:80]})"
    if not results:
        return "Error: number ya email ke bagair save nahi kar sakta."
    return " ".join(results)


# ---------------- Screen capture ----------------

def _screenshot() -> str:
    try:
        path = screen_tools.take_screenshot()
        print(f"📸 Screenshot: {path}")
        return path
    except Exception as e:
        return f"Error: screenshot nahi le saka ({type(e).__name__})"


def _start_recording() -> str:
    try:
        path = screen_tools.start_recording()
        if path.startswith("Error:"):
            return path
        print(f"🔴 Recording started: {path}")
        return path
    except Exception as e:
        return f"Error: recording shuru nahi ho saki ({type(e).__name__})"


def _stop_recording() -> str:
    try:
        result = screen_tools.stop_recording()
        print(f"⏹  {result}")
        return result
    except Exception as e:
        return f"Error: recording band nahi ho saki ({type(e).__name__})"


# ---------------- Controlled browser (follow-up click/scroll/type/tab commands) ----------------

def _browser_action(action: str, target: str, extra: str = "") -> str:
    try:
        if action == "open":
            return browser_bot.open_page(target)
        if action == "click":
            return browser_bot.click_text(target)
        if action == "scroll_down":
            return browser_bot.scroll("down")
        if action == "scroll_up":
            return browser_bot.scroll("up")
        if action == "back":
            return browser_bot.go_back()
        if action == "refresh":
            return browser_bot.refresh()
        if action == "type":
            return browser_bot.type_into(target, extra)
        if action == "press_enter":
            return browser_bot.press_enter()
        if action == "get_text":
            return browser_bot.get_page_text()
        if action == "get_title":
            return browser_bot.get_page_title()
        if action == "get_link_url":
            return browser_bot.get_link_url(target)
        if action == "new_tab":
            return browser_bot.new_tab(target)
        if action == "switch_tab":
            try:
                index = int(target)
            except (TypeError, ValueError):
                return f"Error: tab number samajh nahi aaya ('{target}')."
            return browser_bot.switch_tab(index)
        if action == "close_tab":
            return browser_bot.close_tab()
        if action == "zoom_in":
            return browser_bot.zoom("in")
        if action == "zoom_out":
            return browser_bot.zoom("out")
        if action == "reset_zoom":
            return browser_bot.reset_zoom()
        return f"Error: unknown browser action '{action}'."
    except browser_bot.BrowserError as e:
        return f"Error: {e}"


# ---------------- Dispatcher ----------------

def execute(name: str, args: dict) -> str:
    if name == "send_whatsapp":
        return send_whatsapp(args.get("contact", ""), args.get("message", ""))
    if name == "send_email":
        return _send_email_tool(args)
    if name == "add_contact":
        return _add_contact_tool(args)
    if name == "open_app":
        return open_app(args.get("app_name", ""))
    if name == "browser_action":
        # Model kabhi-kabhi URL ko "target" ki jagah galat key (jaise
        # "open", "url", "query", "site") mein bhej deta hai — fallback:
        target = args.get("target", "") or ""
        if not target.strip():
            for alt_key in ("open", "url", "site", "query", "page", "link"):
                if args.get(alt_key):
                    target = args[alt_key]
                    break
        return _browser_action(
            args.get("action", ""),
            target,
            args.get("extra", ""),
        )
    if name == "web_search":
        return web_search(args.get("query", ""))
    if name == "take_screenshot":
        return _screenshot()
    if name == "start_recording":
        return _start_recording()
    if name == "stop_recording":
        return _stop_recording()
    if name == "general_reply":
        return args.get("reply", "")
    return f"Unknown tool: {name}"


brain.set_executor(execute)
