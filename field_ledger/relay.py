"""The Telegram relay (Design Doc §2; README "In the field"): when phones can't reach the hub,
their writes travel as messages to the team's bot, and the hub fetches them over outbound
HTTPS. The bot carries writes; it is never the record.

Three kinds of message, all from people linked to the People list (`fl people link <name>`
gives a one-time code; `/start <code>` to the bot links that account). The bot answers nobody
else, so a stranger who finds it learns nothing.

- **A phone's waiting writes**, one `#fl {...}` line each, made by the board when the hub is
  away. Each is the same JSON the phone would POST, with its own id, time and seq, so it goes
  through `hub.write` exactly like a resend: logged once, held on Needs a look if refused.
- **A typed move** (`MOVE BAT-12 > van`). It has no time, so the bot asks for one; a clock
  time is marked `prompted` (approximate, so it gets the wider ⚠ window). `now` is the moment
  the message was sent, as exact as a phone's stamp, so it isn't (Teyr, 2026-11-01). `@14:30` at the end gives
  the time at once; so does a bare `now` or `14:30` (with its `:`), which would otherwise end up
  in the place's name. Its event id comes from the chat and message, so a refetch adds nothing.
- **A question**: `WHERE BAT-12`, `AT van`. Read only.

Only one hub may poll a bot at a time (Telegram refuses a second). The token lives outside
both repos: `FL_TELEGRAM_TOKEN`, or the file `~/.config/field-ledger/telegram-token`.
"""

import json
import os
import re
import threading
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import hub as hub_module
from .ledger import store
from .ledger.model import At, Move, Where
from .ledger.parse import ParseError, parse
from .ledger.ids import canonical_item, canonical_location, suggest
from .ledger.state import State, ancestors, fold, items_at, resolve, where_text
from .ledger.validate import canonical_destination, node_id, not_found

API = "https://api.telegram.org"
TOKEN_FILE = Path.home() / ".config" / "field-ledger" / "telegram-token"
PAYLOAD = "#fl "
AT_TIME = re.compile(r"\s+@\s*(\S+)\s*$")
# A move's time without the @: only what no place name ends with. `MOVE BAT-01 > truck now`
# logged a place "truck now" (Teyr, 2026-11-01). A bare `1430` stays a place: Gate 1430.
BARE_TIME = re.compile(r"\s+(now|\d{1,2}[:.h]\d{2})\s*$", re.IGNORECASE)
CLOCK = re.compile(r"^(\d{1,2})[:.h]?(\d{2})$")
TYPED_IDS = uuid.UUID("6f1c2a7e-5d3b-4c8e-9a1f-0b7e4d2c9a63")   # namespace: chat + message -> id
ASK_TIME = "When did that happen? Reply with a time (14:30) or 'now'. A rough time beats none."
# Telegram's command menu: typing / lists these (setMyCommands). A bot sees nothing until a
# message is sent, so this is the only as-you-type help it can give (Teyr, 2026-11-02).
COMMANDS = [{"command": "move", "description": "MOVE BAT-12 > van now: log a move"},
            {"command": "where", "description": "WHERE BAT-12: where it is, and who put it there"},
            {"command": "at", "description": "AT van: what's there"}]
EXAMPLES = {"MOVE": "MOVE BAT-12 > van now", "WHERE": "WHERE BAT-12", "AT": "AT van"}
SLASH = re.compile(r"^/(move|where|at)(?:@\w+)?(?=\s|$)", re.IGNORECASE)
SUGGESTED = "did-you-mean"          # a pending "Did you mean …?", waiting for a yes
YES = {"yes", "y", "ok"}


class RelayError(RuntimeError):
    pass


def read_token() -> str | None:
    token = os.environ.get("FL_TELEGRAM_TOKEN", "").strip()
    if not token and TOKEN_FILE.is_file():
        token = TOKEN_FILE.read_text(encoding="utf-8").strip()
    return token or None


def call(token: str, method: str, params: dict, api: str = API, timeout: float = 35) -> object:
    """One Bot API call. Raises RelayError when it can't be reached or says no."""
    request = urllib.request.Request(f"{api}/bot{token}/{method}", json.dumps(params).encode(),
                                     {"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            answer = json.loads(response.read())
    except urllib.error.HTTPError as error:              # e.g. 409: another hub is polling
        answer = json.loads(error.read() or b"{}")
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise RelayError(f"can't reach Telegram ({error})") from None
    if not answer.get("ok"):
        raise RelayError(answer.get("description", "Telegram said no"))
    return answer["result"]


# --- pure parts --------------------------------------------------------------------------

def payload_writes(text: str) -> list[tuple[str, dict]]:
    """The board's waiting writes in a message: (command, body) per `#fl` line. Lines that
    aren't well-formed are skipped; the hub checks everything else, as for any request."""
    writes = []
    for line in text.splitlines():
        if not line.startswith(PAYLOAD):
            continue
        try:
            data = json.loads(line[len(PAYLOAD):])
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and isinstance(data.get("command"), str) \
                and isinstance(data.get("body"), dict):
            writes.append((data["command"], data["body"]))
    return writes


def asked_time(text: str, sent: datetime) -> datetime | None:
    """A reply to "when?": 'now' (when the move was sent), or a clock time on the day it was
    sent; a time later than that is taken as the day before. None if it isn't a time."""
    text = text.strip().lower()
    if text == "now":
        return sent
    match = CLOCK.match(text)
    if not match or int(match[1]) > 23 or int(match[2]) > 59:
        return None
    local = sent.astimezone()
    when = local.replace(hour=int(match[1]), minute=int(match[2]), second=0, microsecond=0)
    return when - timedelta(days=1) if when > local + timedelta(minutes=5) else when


def unslash(text: str) -> str:
    """`/move BAT-12 > van`, the command menu's form (with `@bot` in a group), reads as
    `MOVE BAT-12 > van`."""
    return SLASH.sub(lambda m: m[1].upper(), text, count=1)


def did_you_mean(line: str, state: State) -> str | None:
    """The line it was probably meant to be, or None: a near-miss command word, item or place
    put right, by the same closest-match `fl` uses for items. A place nobody has used that is
    close to one in use is how a typo quietly became a new place ("vn" for van; "truck now"
    on 2026-10-31). An ID-shaped place is left to the hub, which already asks about those."""
    word, _, rest = line.strip().partition(" ")
    if word.upper() not in (*EXAMPLES, "MOV"):
        word = suggest(word.upper(), set(EXAMPLES), cutoff=0.6)
    if word is None or not rest.strip():
        return None
    places = state.locations | state.fixed

    def item(raw: str) -> str:
        return raw if node_id(raw, state) else suggest(canonical_item(raw) or raw, set(state.items)) or raw

    def place(raw: str) -> str:
        known = node_id(raw, state) or canonical_item(raw) or canonical_location(raw) in places
        return raw if known else suggest(canonical_location(raw), places) or raw

    if word.upper() in ("MOVE", "MOV") and ">" in rest:
        left, dst = (part.strip() for part in rest.split(">", 1))
        thing, _, src = left.partition(" ")
        fixed = f"{word} {item(thing)}{' ' + src if src else ''} > {place(dst)}"
    elif word.upper() == "WHERE":
        fixed = f"{word} {item(rest.strip())}"
    elif word.upper() == "AT":
        fixed = f"{word} {place(rest.strip())}"
    else:
        return None
    return fixed if fixed.split() != line.split() else None


# --- handling one message ----------------------------------------------------------------

def short_time(when: datetime, now: datetime) -> str:
    """14:02 today, else 31 Oct 14:02: a reply is read on the day, so the date is noise."""
    local = when.astimezone()
    return f"{local:%H:%M}" if local.date() == now.astimezone().date() else f"{local:%d %b %H:%M}"


def answer_question(ledger_dir: Path, cmd, now: datetime) -> str:
    """WHERE names the chain, innermost first, and who put each link there: "I know it's in
    Case A, but who shifted Case A?" (Teyr, 2026-11-02)."""
    state = fold(store.read_events(ledger_dir))
    if isinstance(cmd, Where):
        item = node_id(cmd.item, state)
        if item is None:
            return not_found(cmd.item, state)
        if item not in state.where:
            return f"{item}: nowhere yet"
        links = [item, *ancestors(state, item)[:-1]]
        put = " · ".join(f"{n} by {state.placed[n].actor}, {short_time(state.placed[n].ts, now)}"
                         for n in links if n in state.placed)
        return f"{item}: {where_text(state, item)}" + (f"\nPut there: {put}" if put else "")
    target = resolve(canonical_destination(cmd.location, state), state.aliases)
    items = items_at(state, target)
    return f"At {target}: {', '.join(items)}" if items else f"Nothing logged at '{target}'."


def relay_writes(the_hub, name: str, writes: list[tuple[str, dict]]) -> str:
    """A phone's waiting writes, logged as the linked person, each exactly as a resend."""
    lines = []
    for command, body in writes:
        if command not in hub_module.CAN_RELAY:
            lines.append(f"Not logged: '{command}' needs the hub itself.")
            continue
        try:
            answer = hub_module.write(the_hub, command, {**body, "actor": name, "queued": True})
        except hub_module.BadRequest as error:
            answer = {"verdict": "REJECT", "messages": [str(error)], "readback": ""}
        if answer.get("held"):
            lines.append(f"Needs a look on the board: {' '.join(answer['messages'])}")
        elif answer.get("readback"):
            lines.append(answer["readback"])
        else:
            lines.append(" ".join(answer["messages"]) or answer["verdict"])
    return "\n".join(lines)


def typed_move(the_hub, name: str, chat: int, message: dict, cmd: Move, when: datetime,
               exact: bool, kept: bool = False) -> str:
    """`kept`: the sender was offered a "Did you mean" and sent theirs again, which answers
    the hub's own question about a new place too, so it isn't held on Needs a look."""
    body = {"id": str(uuid.uuid5(TYPED_IDS, f"{chat}:{message['message_id']}")),
            "item": cmd.item, "to": cmd.dst, "actor": name, "device": f"telegram-{message['from']['id']}",
            "occurred_at": when.isoformat(), "queued": True, **({"confirmed": True} if kept else {})}
    answer = hub_module.write(the_hub, "move", body, time_source="" if exact else "prompted")
    if answer.get("held"):
        return f"Needs a look on the board: {' '.join(answer['messages'])}"
    return answer.get("readback") or " ".join(answer["messages"])


def handle(the_hub, message: dict, pending: dict) -> str | None:
    """One incoming message -> the bot's reply (None: say nothing)."""
    text = (message.get("text") or "").strip()
    user, chat = str(message["from"]["id"]), message["chat"]["id"]
    sent = datetime.fromtimestamp(message["date"], timezone.utc)
    if text.startswith("/start"):
        code = text.split()[1] if len(text.split()) > 1 else ""
        name = store.use_link_code(the_hub.ledger_dir, code, user) if code else None
        return (f"Hello, {name}. Moves you send here go into the ledger." if name else
                "I don't know you yet. Ask the field-ops owner for a link code.")
    name = store.telegram_people(the_hub.ledger_dir).get(user)
    if name is None:
        return "I don't know you yet. Ask the field-ops owner for a link code."
    writes = payload_writes(text)
    if writes:
        return relay_writes(the_hub, name, writes)
    text, kept = unslash(text), False
    waiting = pending.get(chat)
    if waiting and waiting[0] == SUGGESTED:     # yes takes the suggestion; resent keeps yours
        pending.pop(chat)
        if text.lower() in YES:
            return handle(the_hub, waiting[1], pending)
        kept = text == waiting[2]
    elif waiting:
        when = asked_time(text, waiting[1])
        if when is not None:
            original, _, cmd, was_kept = pending.pop(chat)
            return typed_move(the_hub, name, chat, original, cmd, when, text.lower() == "now", was_kept)
    if text.upper() in EXAMPLES:                # a bare /move from the menu
        return f"Send it like this: {EXAMPLES[text.upper()]}"
    timed = AT_TIME.search(text) or (text[:4].upper() == "MOVE" and BARE_TIME.search(text))
    line = text[:timed.start()] if timed else text
    fixed = None if kept else did_you_mean(line, fold(store.read_events(the_hub.ledger_dir)))
    if fixed:
        meant = fixed + text[len(line):]
        pending[chat] = (SUGGESTED, {**message, "text": meant}, text)
        return f"Did you mean: {meant}\nReply yes to send that. Send yours again to keep it as typed."
    try:
        cmd = parse(line)
    except ParseError as error:
        return f"{error}\nI read MOVE <ITEM> > <PLACE>, WHERE <ITEM> and AT <PLACE>."
    if isinstance(cmd, (Where, At)):
        return answer_question(the_hub.ledger_dir, cmd, sent)
    if not isinstance(cmd, Move):
        return "Only moves come through here; use the board or `fl` for the rest."
    when = asked_time(timed[1], sent) if timed else None
    if when is None:
        pending[chat] = (message, sent, cmd, kept)
        return ASK_TIME
    return typed_move(the_hub, name, chat, message, cmd, when, timed[1].lower() == "now", kept)


# --- polling -----------------------------------------------------------------------------

def poll_once(the_hub, token: str, pending: dict, api: str = API, wait: int = 25) -> int:
    """Fetch what's new, handle it, answer it. The last update handled is kept in the cache,
    so a restarted hub doesn't handle a message twice. Returns how many were handled."""
    conn = store.connect(the_hub.db)
    try:
        offset = int(store.get_meta(conn, "telegram_offset") or 0)
        updates = call(token, "getUpdates", {"offset": offset, "timeout": wait,
                                             "allowed_updates": ["message"]}, api, timeout=wait + 10)
        for update in updates:
            message = update.get("message")
            if message and message.get("text") and message.get("from"):
                with the_hub.lock:
                    reply = handle(the_hub, message, pending)
                if reply:
                    call(token, "sendMessage", {"chat_id": message["chat"]["id"], "text": reply[:4000],
                                                "reply_to_message_id": message["message_id"]}, api)
            store.set_meta(conn, "telegram_offset", str(update["update_id"] + 1))
            conn.commit()
        return len(updates)
    finally:
        conn.close()


def start(the_hub, token: str, api: str = API) -> threading.Event:
    """Poll in the background until the returned event is set. With no internet it waits and
    tries again; the field needs nothing from Telegram to keep working."""
    stop, pending = threading.Event(), {}

    def loop() -> None:
        quiet = False
        while not stop.is_set():
            try:
                if not the_hub.relay_bot:          # the board's "send through Telegram" needs it
                    the_hub.relay_bot = call(token, "getMe", {}, api)["username"]
                    print(f"  Relay: on, as @{the_hub.relay_bot}.", flush=True)
                    try:
                        call(token, "setMyCommands", {"commands": COMMANDS}, api)
                    except RelayError:          # the menu is a nicety; moves work without it
                        pass
                poll_once(the_hub, token, pending, api)
                quiet = False
            except RelayError as error:
                if not quiet:
                    print(f"  Relay: {error}. Trying again every 30 s.", flush=True)
                quiet = True
                stop.wait(30)

    threading.Thread(target=loop, daemon=True, name="relay").start()
    return stop
