"""
Highrise Bot
=============
Built on the official Highrise Python Bot SDK:
    pip install highrise-bot-sdk

Run with:
    highrise highrise_bot:Bot <6a5ccbd9664167f0dc207617> <61969f8525b76abbb8e6b11296ba45ccbc76222e4607653ba403f4421028afb7>

COMMANDS
--------
Dances:
    <number>            -> (anyone) plays that dance on yourself, loops until stopped
    <number> @username   -> (admin only) makes that user perform the dance
    stop                 -> cancels the sender's currently looping dance and any follow
    !dancelist           -> lists all numbered dances in chat

Teleport:
    D1 / D2 / D3            -> (anyone) teleports the sender to that floor
                               NOTE: D2 is restricted -> only admins, the
                               owner, and VIPs can self-teleport there.
    D1 @username (etc.)     -> (admin only) teleports that user to that floor
                               (bypasses the D2 restriction)
    TL @username            -> (admin only) teleports the SENDER to that
                               user's current position

Custom named dances (admin only to add, anyone can trigger by name):
    Dance <emote_id>           -> (admin) tries a raw emote id directly on yourself
    SaveDance <emote_id> <name> -> (admin) saves that id under a custom name
    <name>                     -> (anyone) triggers a previously saved custom dance
    DanceList2                 -> lists all saved custom dance names

Voice / Mic (admin only):
    Mic @username           -> invites that user to the mic (Live voice chat
                               must be turned on in the room)
    UnMic @username         -> takes that user's mic away

Follow (admin only):
    Follow me / Fallow me         -> bot follows the sender
    Follow @user / Fallow @user   -> bot follows that user
    UnFollow / UnFallow (+ me)    -> stops following

Moderation (admin only):
    Kick @<username>       -> kicks now AND mutes, both for the default duration (24h),
                               and re-kicks them on rejoin for that same window
    Kick<N> @<username>    -> same as above but for N hours instead of the default
    UnBan @<username>      -> removes an active kick-ban
    Vip @<username>        -> grants VIP status for the default duration (24h)
    Vip<N> @<username>     -> grants VIP status for N hours instead of the default
    UnVip @<username>      -> removes VIP status at any time

Admin management (owner only):
    Admin @<username>        -> grants that user admin rights over the bot
    Ban Admin @<username>    -> revokes that user's admin rights

Spam (admin only):
    <n>spam <text>   -> repeats <text> in chat n times (max 100)

Automatic messages:
    - On join: room rules, then a welcome message tailored to the user
      (owner / VIP / regular member), then a join announcement
    - On leave: a goodbye message
    - On tip: thank-you message when someone tips the bot or the owner

DM commands (admin/owner only):
    Every command above ALSO works if you send it as a direct message
    (private conversation) to the bot instead of typing it in the room.
    The command still executes normally (e.g. Kick really kicks), but the
    bot's confirmation text appears in the ROOM chat, not back in the DM,
    since that's how the existing commands are built.
"""

import asyncio
import json
import os
import re
import time
from typing import Union
from highrise import BaseBot, Position, CurrencyItem, Item
from highrise.models import SessionMetadata


class _SimpleUser:
    """Minimal stand-in for the SDK's User object, used only so DM commands
    can reuse on_chat's exact command logic (which only ever reads
    user.id and user.username)."""

    def __init__(self, id: str, username: str) -> None:
        self.id = id
        self.username = username

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------

# Hardcoded, permanent admins (in addition to anyone granted via "Admin @user").
MODERATORS = {
    "smoking.blood",
    "smoking.blood",
}

# The true room owners -> only these usernames can grant/revoke admin rights,
# and get the special owner welcome message. (Supports multiple owners.)
HOST_USERNAMES = {
    "smoking.blood",
    "smoking.blood",
}

# Usernames that are PERMANENT VIPs (in addition to anyone temporarily
# VIP'd via the "Vip @username" command).
PERMANENT_VIP_USERS = set()

VIP_DURATION_HOURS = 24
KICK_BAN_DURATION_HOURS = 24
LOOP_INTERVAL_SECONDS = 6

# Safety cap on the spam command so one message can't be repeated an
# unreasonable number of times (protects against hitting Highrise rate limits).
MAX_SPAM_COUNT = 100

# Delay (seconds) between each message in a spam burst.
SPAM_DELAY_SECONDS = 0.5

FLOORS = {
    1: Position(x=4.50, y=6.00, z=10.51, facing="FrontRight"),
    2: Position(x=1.50, y=3.50, z=6.51, facing="FrontRight"),
    3: Position(x=16.50, y=0.25, z=2.50, facing="FrontRight"),
}

# Floor numbers listed here can only be self-teleported to (typing "D2") by
# admins, the owner, or VIPs. Admin-targeted teleport ("D2 @user") always
# bypasses this, since only admins can use that command anyway.
RESTRICTED_FLOORS = {2}

STATE_FILE = "bot_state.json"

ROOM_RULES = [
    "Be respectful to everyone in the room.",
    "No spamming or flooding the chat.",
    "No harassment, hate speech, or bullying.",
    "Follow the host's instructions during events.",
    "Have fun!",
]

DANCES = {
    1: "sit-idle-cute", 2: "emote-ghost-idle", 3: "dance-twerk", 4: "dance-floss",
    5: "emote-disco", 6: "emote-laughing2", 7: "emote-punkguitar", 8: "emote-shy2",
    9: "emoji-gagging", 10: "dance-duckwalk", 11: "dance-kawai", 12: "idle-fighter",
    13: "idle_layingdown", 14: "emote-teleporting", 15: "emote-pose9", 16: "emote-astronaut",
    17: "emote-cutesalute", 18: "dance-jinglebell", 19: "emote-harlemshake", 20: "emote-superrun",
    21: "emote-disappear", 22: "emote-sleigh", 23: "emote-snake", 24: "emote-apart",
    25: "emote-pose10", 26: "emote-rainbow", 27: "emote-trampoline", 28: "emoji-arrogance",
    29: "emote-boxer", 30: "emoji-mind-blown", 31: "dance-tiktok14", 32: "dance-metal",
    33: "emote-jetpack", 34: "idle-loop-tapdance", 35: "dance-wrong", 36: "emote-lust",
    37: "dance-swagbounce", 38: "idle-space", 39: "dance-popularvibe", 40: "dance-mine",
    41: "dance-shuffle", 42: "emote-frollicking", 43: "dance-robotic", 44: "dance-griddy",
    45: "dance-breakdance", 46: "sit-idle-laidBack", 47: "dance-ballet", 48: "dance-martial-artist",
    49: "emote-hero", 50: "dance-freshprince", 51: "emote-graceful", 52: "emote-headball",
    53: "emoji-cursing", 54: "emoji-flex", 55: "emote-knocking-screen", 56: "idle-loop-annoyed",
    57: "emoji-eyeroll", 58: "emoji-dizzy", 59: "idle-dance-headbobbing", 60: "emote-exasperated",
    61: "emote-cold", 62: "idle_zombie", 63: "emote-theatrical", 64: "emote-hot",
    65: "emote-death2", 66: "idle-lookup", 67: "emote-model", 68: "emote-peace",
    69: "emote-splitsdrop", 70: "dance-pennywise", 71: "idle-sleep", 72: "emote-bunnyhop",
    73: "emoji-pray", 74: "emote-judochop", 75: "emote-suckthumb", 76: "idle_singing",
    77: "emoji-crying", 78: "emoji-naughty", 79: "emote-levelup", 80: "emote-exasperatedb",
    81: "dance-sexy", 82: "emote-proposing", 83: "idle-posh", 84: "emoji-there",
    85: "emote-baseball", 86: "idle-loop-happy", 87: "emote-monster_fail", 88: "dance-weird",
    89: "emote-bow", 90: "emoji-sneeze", 91: "idle-sad", 92: "emote-fail1",
    93: "emote-wings", 94: "idle-loop-sad", 95: "emoji-sick", 96: "emote-telekinesis",
    97: "emote-hug", 98: "emoji-smirking", 99: "emote-embarrassed", 100: "emote-sumo",
    101: "dance-voguehands", 102: "idle_layingdown2", 103: "idle-loop-tired", 104: "idle-loop-sitfloor",
    105: "idle-loop-shy", 106: "idle-loop-aerobics", 107: "idle-hero", 108: "idle-floorsleeping2",
    109: "idle-floorsleeping", 110: "idle-enthusiastic", 111: "idle-dance-swinging", 112: "idle-angry",
    113: "emote-yes", 114: "emote-wave", 115: "emote-tired", 116: "emote-think",
    117: "emote-tapdance", 118: "emote-superpunch", 119: "emote-snowball", 120: "emote-snowangel",
    121: "emote-shy", 122: "emote-secrethandshake", 123: "emote-sad", 124: "emote-ropepull",
    125: "emote-roll", 126: "emote-rofl", 127: "emote-robot", 128: "emote-peekaboo",
    129: "emote-panic", 130: "emote-no", 131: "emote-ninjarun", 132: "emote-nightfever",
    133: "emote-laughing", 134: "emote-kiss", 135: "emote-kicking", 136: "emote-jumpb",
    137: "emote-hugyourself", 138: "emote-hello", 139: "emote-happy", 140: "emote-handstand",
    141: "emote-greedy", 142: "emote-gordonshuffle", 143: "emote-gangnam", 144: "emote-fainting",
    145: "emote-fail2", 146: "emote-elbowbump", 147: "emote-deathdrop", 148: "emote-death",
    149: "emote-dab", 150: "emote-curtsy", 151: "emote-confused", 152: "emote-charging",
    153: "emote-boo", 154: "emoji-thumbsup", 155: "emoji-scared", 156: "emoji-punch",
    157: "emoji-poop", 158: "emoji-lying", 159: "emoji-halo", 160: "emoji-hadoken",
    161: "emoji-give-up", 162: "emoji-clapping", 163: "emoji-celebrate", 164: "emoji-angry",
    165: "dance-tiktok8", 166: "dance-tiktok2", 167: "dance-spiritual", 168: "dance-smoothwalk",
    169: "dance-singleladies", 170: "dance-shoppingcart", 171: "dance-russian", 172: "dance-orangejustice",
    173: "dance-macarena", 174: "dance-handsup", 175: "dance-blackpink", 176: "dance-aerobics",
    177: "emote-gravity", 178: "emote-hyped", 179: "idle-nervous", 180: "idle-toilet",
    181: "emote-attention", 182: "sit-open", 183: "dance-zombie", 184: "emoji-ghost",
    185: "emote-hearteyes", 186: "emote-swordfight", 187: "emote-timejump", 188: "emote-heartfingers",
    189: "emote-heartshape", 190: "emote-float", 191: "emote-puppet", 192: "dance-pinguin",
    193: "dance-creepypuppet", 194: "emote-maniac", 195: "emote-energyball", 196: "emote-frog",
    197: "emote-superpose", 198: "emote-cute", 199: "dance-tiktok9", 200: "dance-tiktok10",
    201: "emote-pose7", 202: "emote-pose8", 203: "idle-dance-casual", 204: "emote-pose1",
    205: "emote-pose3", 206: "emote-pose5", 207: "emote-cutey", 208: "emote-zombierun",
    209: "dance-icecream", 210: "idle-uwu", 211: "idle-dance-tiktok4", 212: "dance-anime",
    213: "idle-wild", 214: "emote-iceskating", 215: "emote-pose6", 216: "emote-celebrationstep",
    217: "emote-creepycute", 218: "emote-frustrated", 219: "sit-relaxed", 220: "emote-stargaze",
    221: "emote-slap", 222: "emote-headblowup", 223: "emote-kawaiigogo", 224: "emote-repose",
    225: "idle-dance-tiktok7", 226: "emote-shrink", 227: "dance-touch", 228: "idle-guitar",
    229: "emote-gift", 230: "dance-employee", 231: "emote-kissing", 232: "dance-tiktok11",
    233: "emote-salute", 234: "dance-tiktok12", 235: "dance-tiktok13", 236: "emote-spiderman",
    237: "dance-true-heart", 238: "emote-idle-daydreaming", 239: "dance-woah", 240: "emote-blowkisses",
    241: "emote-alice-shrink", 242: "emote-threadexchange-star",
}


def to_bold(text: str) -> str:
    """Convert plain ASCII text into Unicode Mathematical Bold characters."""
    result = []
    for ch in text:
        if "A" <= ch <= "Z":
            result.append(chr(ord(ch) - ord("A") + 0x1D400))
        elif "a" <= ch <= "z":
            result.append(chr(ord(ch) - ord("a") + 0x1D41A))
        elif "0" <= ch <= "9":
            result.append(chr(ord(ch) - ord("0") + 0x1D7CE))
        else:
            result.append(ch)
    return "".join(result)


class Bot(BaseBot):
    def __init__(self) -> None:
        super().__init__()
        self._active_dances: dict[str, asyncio.Task] = {}
        self._temp_vip: dict[str, float] = {}
        self._kick_bans: dict[str, float] = {}
        self._mutes: dict[str, float] = {}
        self._admins: set[str] = set()
        self._custom_dances: dict[str, str] = {}  # name (lowercase) -> emote_id
        self._follow_task: asyncio.Task | None = None
        self.bot_id: str | None = None
        self._load_state()

    def _load_state(self) -> None:
        if not STATE_FILE or not os.path.exists(STATE_FILE):
            return
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._temp_vip = data.get("temp_vip", {})
            self._kick_bans = data.get("kick_bans", {})
            self._mutes = data.get("mutes", {})
            self._admins = set(data.get("admins", []))
            self._custom_dances = data.get("custom_dances", {})
        except Exception as e:
            print(f"Could not load state file: {e}")

    def _save_state(self) -> None:
        if not STATE_FILE:
            return
        try:
            with open(STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "temp_vip": self._temp_vip,
                        "kick_bans": self._kick_bans,
                        "mutes": self._mutes,
                        "admins": list(self._admins),
                        "custom_dances": self._custom_dances,
                    },
                    f,
                )
        except Exception as e:
            print(f"Could not save state file: {e}")

    async def on_start(self, session_metadata: SessionMetadata) -> None:
        self.bot_id = session_metadata.user_id
        print("Bot connected and ready.")
        asyncio.create_task(self._expiry_cleanup_loop())

    async def _expiry_cleanup_loop(self) -> None:
        try:
            while True:
                now = time.time()
                expired_vip = [u for u, exp in self._temp_vip.items() if exp <= now]
                expired_bans = [u for u, exp in self._kick_bans.items() if exp <= now]
                expired_mutes = [u for u, exp in self._mutes.items() if exp <= now]
                changed = False
                for u in expired_vip:
                    del self._temp_vip[u]
                    changed = True
                for u in expired_bans:
                    del self._kick_bans[u]
                    changed = True
                for u in expired_mutes:
                    del self._mutes[u]
                    changed = True
                if changed:
                    self._save_state()
                await asyncio.sleep(60)
        except asyncio.CancelledError:
            pass

    def _is_vip(self, username: str) -> bool:
        if username in PERMANENT_VIP_USERS:
            return True
        expiry = self._temp_vip.get(username)
        return expiry is not None and expiry > time.time()

    def _is_banned(self, username: str) -> bool:
        expiry = self._kick_bans.get(username)
        return expiry is not None and expiry > time.time()

    def _is_muted(self, username: str) -> bool:
        expiry = self._mutes.get(username)
        return expiry is not None and expiry > time.time()

    def _is_admin(self, username: str) -> bool:
        """True for the hardcoded owner/moderators list, or anyone granted
        admin at runtime via the 'Admin @username' command."""
        return username in MODERATORS or username in self._admins

    # ---------------- DM commands ---------------------------------------
    # Lets admins/owner send the EXACT SAME commands via a private message
    # (whisper-style DM/"conversation") instead of typing them in the room.
    # We resolve the sender's username via the Web API, then reuse on_chat's
    # entire command-parsing logic as-is (no code duplicated).
    #
    # IMPORTANT LIMITATION: on_chat's replies use self.highrise.chat(...),
    # which posts to the ROOM, not back into this DM. So the command still
    # executes correctly (e.g. a real Kick happens), but you'll see the
    # bot's confirmation message in the room chat, not in the DM itself.
    async def on_message(self, user_id: str, conversation_id: str, is_new_conversation: bool) -> None:
        try:
            messages_resp = await self.highrise.get_messages(conversation_id)
            messages = getattr(messages_resp, "messages", None) or messages_resp
            if not messages:
                return
            latest = messages[0]
            text = getattr(latest, "content", None) or getattr(latest, "message", None) or ""
            text = text.strip()
            if not text:
                return

            username = None
            try:
                user_resp = await self.webapi.get_user(user_id)
                username = getattr(getattr(user_resp, "user", user_resp), "username", None)
            except Exception as e:
                print(f"DM: could not resolve username for {user_id}: {e}")

            if not username or not self._is_admin(username):
                await self.highrise.send_message(
                    conversation_id, "⛔ فقط ادمین‌ها می‌تونن از طریق پیوی به بات دستور بدن."
                )
                return

            fake_user = _SimpleUser(id=user_id, username=username)
            await self.highrise.send_message(
                conversation_id, "✅ دستور دریافت شد و اجرا می‌شه — نتیجه رو تو چت روم ببین."
            )
            await self.on_chat(fake_user, text)
        except Exception as e:
            print(f"on_message error: {e}")
            try:
                await self.highrise.send_message(conversation_id, f"⚠️ خطا در اجرای دستور: {e}")
            except Exception:
                pass

    # ---------------- Join / Leave ----------------
    async def on_user_join(self, user, position) -> None:
        if self._is_banned(user.username):
            await self.highrise.moderate_room(user.id, "kick")
            await self.highrise.chat(to_bold(f"⛔ {user.username} is still banned and was removed."))
            return

        if self._is_muted(user.username):
            try:
                remaining = int(self._mutes[user.username] - time.time())
                await self.highrise.moderate_room(user.id, "mute", max(remaining, 1))
            except Exception as e:
                print(f"Could not re-apply mute on join: {e}")

        # 1) Room rules
        rules_text = to_bold("📋 ROOM RULES 📋\n")
        for i, rule in enumerate(ROOM_RULES, start=1):
            rules_text += to_bold(f"{i}. {rule}\n")
        await self.highrise.chat(rules_text)

        # 2) Tailored welcome message
        if user.username in HOST_USERNAMES:
            await self.highrise.chat(
                to_bold("👑 The owner of this bot has entered the room! 👑\n")
                + to_bold(f"Welcome back, {user.username}!")
            )
        elif self._is_vip(user.username):
            await self.highrise.chat(
                to_bold("💎 A VIP member has arrived! 💎\n")
                + to_bold(f"Welcome, {user.username} — enjoy your exclusive perks!")
            )
        else:
            await self.highrise.chat(
                to_bold(f"✨ Welcome to the room, {user.username}! ✨\n")
                + to_bold("Glad to have you here, make yourself at home!")
            )

        # 3) Join announcement
        await self.highrise.chat(to_bold(f"👋 {user.username} has entered the room."))

    async def on_user_leave(self, user) -> None:
        await self.highrise.chat(to_bold(f"👋 {user.username} has left the room. Goodbye, {user.username}!"))

    # ---------------- Tips ----------------
    async def on_tip(
        self, sender, receiver, tip: Union[CurrencyItem, Item]
    ) -> None:
        if receiver.id == self.bot_id:
            if isinstance(tip, CurrencyItem):
                await self.highrise.chat(
                    to_bold(f"🎁 Thank you {sender.username} for tipping the bot {tip.amount} gold! 🎁")
                )
            else:
                await self.highrise.chat(
                    to_bold(f"🎁 Thank you {sender.username} for the gift to the bot! 🎁")
                )
            return

        if receiver.username in HOST_USERNAMES:
            if isinstance(tip, CurrencyItem):
                await self.highrise.chat(
                    to_bold(f"💛 Thank you {sender.username} for tipping the owner {tip.amount} gold! 💛")
                )
            else:
                await self.highrise.chat(
                    to_bold(f"💛 Thank you {sender.username} for the gift to the owner! 💛")
                )
            return

    # ---------------- Chat commands ----------------
    async def on_chat(self, user, message: str) -> None:
        text = message.strip()
        if not text:
            return

        # ---------------- Outfit debug commands (admin only) --------------
        # These just print info to the Termux console so we can see the
        # exact data format before writing a real "change outfit" command.
        if text.lower() == "!myoutfit":
            if not self._is_admin(user.username):
                await self.highrise.chat(to_bold("Only an admin can use this."))
                return
            outfit = await self.highrise.get_my_outfit()
            print("=== CURRENT OUTFIT ===")
            print(outfit)
            await self.highrise.chat(to_bold("Outfit printed to console."))
            return

        if text.lower() == "!myinventory":
            if not self._is_admin(user.username):
                await self.highrise.chat(to_bold("Only an admin can use this."))
                return
            inventory = await self.highrise.get_inventory()
            print("=== INVENTORY ===")
            print(inventory)
            await self.highrise.chat(to_bold("Inventory printed to console."))
            return

        # ---------------- Wear <item_id> (admin only) ----------------------
        # Swaps ONE clothing item on the bot. The item's category is read
        # from the prefix before the first "-" in its id (e.g. "shirt" in
        # "shirt-n_room32019denimjackethoodie"). Any currently-worn item of
        # that same category is replaced; everything else stays as-is.
        wear_match = re.match(r"^Wear\s+(\S+)$", text, re.IGNORECASE)
        if wear_match:
            if not self._is_admin(user.username):
                await self.highrise.chat(to_bold("Only an admin can use this."))
                return
            new_item_id = wear_match.group(1)
            category = new_item_id.split("-", 1)[0]

            outfit_response = await self.highrise.get_my_outfit()
            # Handle whichever shape the SDK actually returns.
            if hasattr(outfit_response, "outfit"):
                current = outfit_response.outfit
            elif hasattr(outfit_response, "items"):
                current = outfit_response.items
            else:
                current = outfit_response  # already a plain list
            kept_items = [it for it in current if it.id.split("-", 1)[0] != category]
            new_item = Item(
                type="clothing",
                amount=1,
                id=new_item_id,
                account_bound=False,
                active_palette=None,
            )
            new_outfit = kept_items + [new_item]

            try:
                await self.highrise.set_outfit(outfit=new_outfit)
                await self.highrise.chat(to_bold(f"Now wearing: {new_item_id}"))
            except Exception as e:
                print(f"set_outfit failed: {e}")
                await self.highrise.chat(to_bold("Could not change outfit — check the console for details."))
            return

        # ---------------- WearAll <id1> <id2> ... (admin only) --------------
        # Equips MULTIPLE items in one call. Any old item that shares a
        # category with ANY of the new items is removed first, then all the
        # new items are added together — so pairs like two "face_hair" pieces
        # (upper + lower) or two "tattoo" pieces both stay equipped, instead
        # of the second one silently replacing the first.
        wearall_match = re.match(r"^WearAll\s+(.+)$", text, re.IGNORECASE)
        if wearall_match:
            if not self._is_admin(user.username):
                await self.highrise.chat(to_bold("Only an admin can use this."))
                return
            new_ids = wearall_match.group(1).split()
            if not new_ids:
                await self.highrise.chat(to_bold("Usage: WearAll <id1> <id2> ..."))
                return

            new_categories = {i.split("-", 1)[0] for i in new_ids}

            outfit_response = await self.highrise.get_my_outfit()
            if hasattr(outfit_response, "outfit"):
                current = outfit_response.outfit
            elif hasattr(outfit_response, "items"):
                current = outfit_response.items
            else:
                current = outfit_response

            kept_items = [it for it in current if it.id.split("-", 1)[0] not in new_categories]
            new_items = [
                Item(type="clothing", amount=1, id=item_id, account_bound=False, active_palette=None)
                for item_id in new_ids
            ]
            new_outfit = kept_items + new_items

            try:
                await self.highrise.set_outfit(outfit=new_outfit)
                await self.highrise.chat(to_bold(f"Outfit updated with {len(new_ids)} item(s)."))
            except Exception as e:
                print(f"set_outfit failed: {e}")
                await self.highrise.chat(to_bold("Could not change outfit — check the console for details."))
            return

        # ---------------- TakeOff <category or full item id> (admin only) --
        # "TakeOff pants" removes every currently-worn item whose category
        # is "pants". "TakeOff tattoo-n_bpositive2021darkstretchmarks"
        # removes just that one specific item (useful when a category, like
        # tattoo or face_hair, can have more than one item equipped at once).
        # NOTE: Highrise requires body, eye, eyebrow, nose, mouth, and either
        # shirt+pants / a dress / a fullsuit to always be present — taking
        # off a required category may be rejected by the server (see console
        # for the error if that happens).
        takeoff_match = re.match(r"^TakeOff\s+(\S+)$", text, re.IGNORECASE)
        if takeoff_match:
            if not self._is_admin(user.username):
                await self.highrise.chat(to_bold("Only an admin can use this."))
                return
            target = takeoff_match.group(1)

            outfit_response = await self.highrise.get_my_outfit()
            if hasattr(outfit_response, "outfit"):
                current = outfit_response.outfit
            elif hasattr(outfit_response, "items"):
                current = outfit_response.items
            else:
                current = outfit_response

            if "-" in target:
                # Exact item id given — remove just that one.
                new_outfit = [it for it in current if it.id != target]
            else:
                # A bare category name given — remove everything in it.
                new_outfit = [it for it in current if it.id.split("-", 1)[0] != target]

            if len(new_outfit) == len(current):
                await self.highrise.chat(to_bold(f"Nothing matching '{target}' is currently worn."))
                return

            try:
                await self.highrise.set_outfit(outfit=new_outfit)
                await self.highrise.chat(to_bold(f"Removed: {target}"))
            except Exception as e:
                print(f"set_outfit failed: {e}")
                await self.highrise.chat(
                    to_bold("Could not remove that — it may be a required category. Check the console.")
                )
            return

        # ---------------- Palette <category> <number> (admin only) ---------
        # Changes the COLOR of an already-equipped item (skin tone, eye
        # color, hair color, etc. all work through a palette number instead
        # of a different item id). Example: "Palette body 15" changes skin
        # tone; "Palette eye 3" changes eye color. The right numbers vary by
        # item, so this may take some trial and error — run "!myoutfit"
        # after to see the palette that got applied, and adjust from there.
        palette_match = re.match(r"^Palette\s+(\S+)\s+(\d+)$", text, re.IGNORECASE)
        if palette_match:
            if not self._is_admin(user.username):
                await self.highrise.chat(to_bold("Only an admin can use this."))
                return
            category, palette_str = palette_match.groups()
            palette_number = int(palette_str)

            outfit_response = await self.highrise.get_my_outfit()
            if hasattr(outfit_response, "outfit"):
                current = outfit_response.outfit
            elif hasattr(outfit_response, "items"):
                current = outfit_response.items
            else:
                current = outfit_response

            found = False
            new_outfit = []
            for it in current:
                if it.id.split("-", 1)[0] == category:
                    found = True
                    new_outfit.append(
                        Item(
                            type=it.type,
                            amount=it.amount,
                            id=it.id,
                            account_bound=it.account_bound,
                            active_palette=palette_number,
                        )
                    )
                else:
                    new_outfit.append(it)

            if not found:
                await self.highrise.chat(to_bold(f"Nothing worn in category '{category}' right now."))
                return

            try:
                await self.highrise.set_outfit(outfit=new_outfit)
                await self.highrise.chat(to_bold(f"{category} palette set to {palette_number}."))
            except Exception as e:
                print(f"set_outfit failed: {e}")
                await self.highrise.chat(to_bold("Could not change the color — check the console."))
            return

        if text.lower() == "stop":
            await self._stop_dance(user.id)
            await self._stop_follow()
            await self.highrise.chat(to_bold(f"Stopped {user.username}'s dance."))
            return

        follow_me_match = re.match(r"^(?:follow|fallow)\s+me$", text, re.IGNORECASE)
        if follow_me_match:
            if not self._is_admin(user.username):
                await self.highrise.chat(to_bold("Only an admin can ask me to follow."))
                return
            await self._start_follow(user.id, user.username)
            return

        follow_target_match = re.match(r"^(?:follow|fallow)\s+@(\S+)$", text, re.IGNORECASE)
        if follow_target_match:
            if not self._is_admin(user.username):
                await self.highrise.chat(to_bold("Only an admin can direct me to follow someone."))
                return
            target_username = follow_target_match.group(1)
            target_id = await self._find_user_id(target_username)
            if not target_id:
                await self.highrise.chat(to_bold(f"User '{target_username}' not found in the room."))
                return
            await self._start_follow(target_id, target_username)
            return

        unfollow_match = re.match(r"^(?:unfollow|unfallow)(?:\s+me)?$", text, re.IGNORECASE)
        if unfollow_match:
            if not self._is_admin(user.username):
                await self.highrise.chat(to_bold("Only an admin can ask me to stop following."))
                return
            await self._stop_follow()
            await self.highrise.chat(to_bold("Stopped following."))
            return

        spam_match = re.match(r"^(\d+)spam\s+(.+)$", text, re.IGNORECASE)
        if spam_match:
            if not self._is_admin(user.username):
                await self.highrise.chat(to_bold("Only an admin can use the spam command."))
                return
            count_str, spam_text = spam_match.groups()
            count = int(count_str)
            if count < 1:
                await self.highrise.chat(to_bold("Count must be at least 1."))
                return
            if count > MAX_SPAM_COUNT:
                await self.highrise.chat(to_bold(f"Max allowed is {MAX_SPAM_COUNT}. Use a smaller number."))
                return
            asyncio.create_task(self._run_spam(spam_text, count))
            return

        if text.lower() == "!dancelist":
            lines = [f"{n}: {e}" for n, e in sorted(DANCES.items())]
            chunk = ""
            for line in lines:
                if len(chunk) + len(line) + 1 > 250:
                    await self.highrise.chat(chunk)
                    chunk = ""
                chunk += line + "\n"
            if chunk:
                await self.highrise.chat(chunk)
            return

        # ---------------- Admin management (owner only) ----------------
        ban_admin_match = re.match(r"^Ban\s+Admin\s+@(\S+)$", text, re.IGNORECASE)
        if ban_admin_match:
            if user.username not in HOST_USERNAMES:
                await self.highrise.chat(to_bold("Only the true owner can remove admins."))
                return
            target_username = ban_admin_match.group(1)
            if target_username in self._admins:
                self._admins.discard(target_username)
                self._save_state()
                await self.highrise.chat(to_bold(f"{target_username} is no longer an admin."))
            else:
                await self.highrise.chat(to_bold(f"{target_username} wasn't an admin."))
            return

        admin_match = re.match(r"^Admin\s+@(\S+)$", text, re.IGNORECASE)
        if admin_match:
            if user.username not in HOST_USERNAMES:
                await self.highrise.chat(to_bold("Only the true owner can grant admin rights."))
                return
            target_username = admin_match.group(1)
            self._admins.add(target_username)
            self._save_state()
            await self.highrise.chat(to_bold(f"👑 {target_username} is now an admin of this bot! 👑"))
            return

        # ---------------- Kick (+ mute), with optional custom hours ------
        kick_match = re.match(r"^Kick(\d+)?\s+@(\S+)$", text, re.IGNORECASE)
        if kick_match:
            if not self._is_admin(user.username):
                await self.highrise.chat(to_bold("Only an admin can use Kick."))
                return
            hours_str, target_username = kick_match.groups()
            hours = int(hours_str) if hours_str else KICK_BAN_DURATION_HOURS
            target_id = await self._find_user_id(target_username)
            if not target_id:
                await self.highrise.chat(to_bold(f"User '{target_username}' not found in the room."))
                return
            await self.highrise.moderate_room(target_id, "kick")
            try:
                await self.highrise.moderate_room(target_id, "mute", hours * 3600)
            except Exception as e:
                print(f"Mute call failed: {e}")
            expiry = time.time() + hours * 3600
            self._kick_bans[target_username] = expiry
            self._mutes[target_username] = expiry
            self._save_state()
            await self.highrise.chat(to_bold(f"{target_username} was kicked and muted for {hours}h."))
            return

        unban_match = re.match(r"^UnBan\s+@(\S+)$", text, re.IGNORECASE)
        if unban_match:
            if not self._is_admin(user.username):
                await self.highrise.chat(to_bold("Only an admin can use UnBan."))
                return
            target_username = unban_match.group(1)
            changed = False
            if target_username in self._kick_bans:
                del self._kick_bans[target_username]
                changed = True
            if target_username in self._mutes:
                del self._mutes[target_username]
                changed = True
            if changed:
                self._save_state()
                await self.highrise.chat(to_bold(f"{target_username} has been unbanned and unmuted."))
            else:
                await self.highrise.chat(to_bold(f"{target_username} is not currently banned."))
            return

        # ---------------- Vip, with optional custom hours ----------------
        vip_match = re.match(r"^Vip(\d+)?\s+@(\S+)$", text, re.IGNORECASE)
        if vip_match:
            if not self._is_admin(user.username):
                await self.highrise.chat(to_bold("Only an admin can use Vip."))
                return
            hours_str, target_username = vip_match.groups()
            hours = int(hours_str) if hours_str else VIP_DURATION_HOURS
            self._temp_vip[target_username] = time.time() + hours * 3600
            self._save_state()
            await self.highrise.chat(to_bold(f"💎 {target_username} is now VIP for {hours}h! 💎"))
            return

        unvip_match = re.match(r"^UnVip\s+@(\S+)$", text, re.IGNORECASE)
        if unvip_match:
            if not self._is_admin(user.username):
                await self.highrise.chat(to_bold("Only an admin can use UnVip."))
                return
            target_username = unvip_match.group(1)
            if target_username in self._temp_vip:
                del self._temp_vip[target_username]
                self._save_state()
                await self.highrise.chat(to_bold(f"{target_username} is no longer VIP."))
            elif target_username in PERMANENT_VIP_USERS:
                await self.highrise.chat(to_bold(f"{target_username} is a permanent VIP in the code, can't be removed with this command."))
            else:
                await self.highrise.chat(to_bold(f"{target_username} is not currently VIP."))
            return

        # ---------------- TL @username (admin only) ------------------------
        # Teleports the SENDER to the position of the tagged user.
        tl_match = re.match(r"^TL\s+@(\S+)$", text, re.IGNORECASE)
        if tl_match:
            if not self._is_admin(user.username):
                await self.highrise.chat(to_bold("Only an admin can use TL."))
                return
            target_username = tl_match.group(1)
            room_users = (await self.highrise.get_room_users()).content
            target_pos = None
            for u, pos in room_users:
                if u.username == target_username:
                    target_pos = pos
                    break
            if target_pos is None:
                await self.highrise.chat(to_bold(f"User '{target_username}' not found in the room."))
                return
            await self.highrise.teleport(user.id, target_pos)
            await self.highrise.chat(to_bold(f"{user.username} teleported to {target_username}."))
            return

        # ---------------- Mic @username (admin only) -----------------------
        # Invites a user to voice chat (requires the room to have live voice
        # enabled / the bot to have permission to manage voice).
        mic_match = re.match(r"^Mic\s+@(\S+)$", text, re.IGNORECASE)
        if mic_match:
            if not self._is_admin(user.username):
                await self.highrise.chat(to_bold("Only an admin can use Mic."))
                return
            target_username = mic_match.group(1)
            target_id = await self._find_user_id(target_username)
            if not target_id:
                await self.highrise.chat(to_bold(f"User '{target_username}' not found in the room."))
                return
            try:
                await self.highrise.add_user_to_voice(target_id)
                await self.highrise.chat(to_bold(f"🎤 {target_username} was invited to the mic!"))
            except Exception as e:
                await self.highrise.chat(
                    to_bold(f"Couldn't invite {target_username} to the mic. Make sure Live/voice is turned on in this room.")
                )
            return

        # ---------------- UnMic @username (admin only) ----------------------
        # Removes a user from voice chat / takes their mic away.
        unmic_match = re.match(r"^UnMic\s+@(\S+)$", text, re.IGNORECASE)
        if unmic_match:
            if not self._is_admin(user.username):
                await self.highrise.chat(to_bold("Only an admin can use UnMic."))
                return
            target_username = unmic_match.group(1)
            target_id = await self._find_user_id(target_username)
            if not target_id:
                await self.highrise.chat(to_bold(f"User '{target_username}' not found in the room."))
                return
            try:
                await self.highrise.remove_user_from_voice(target_id)
                await self.highrise.chat(to_bold(f"🔇 {target_username}'s mic was taken away."))
            except Exception as e:
                await self.highrise.chat(
                    to_bold(f"Couldn't remove {target_username} from the mic. Make sure Live/voice is turned on in this room.")
                )
            return

        # ---------------- Teleport a specific user (admin only) ----------
        floor_target_match = re.match(r"^[Dd](\d+)\s+@(\S+)$", text)
        if floor_target_match:
            if not self._is_admin(user.username):
                await self.highrise.chat(to_bold("Only an admin can teleport other members."))
                return
            floor_number = int(floor_target_match.group(1))
            target_username = floor_target_match.group(2)
            if floor_number not in FLOORS:
                await self.highrise.chat(
                    to_bold(
                        f"No floor D{floor_number} is configured. Available: "
                        + ", ".join("D" + str(f) for f in sorted(FLOORS))
                    )
                )
                return
            target_id = await self._find_user_id(target_username)
            if not target_id:
                await self.highrise.chat(to_bold(f"User '{target_username}' not found in the room."))
                return
            await self.highrise.teleport(target_id, FLOORS[floor_number])
            await self.highrise.chat(to_bold(f"{target_username} teleported to D{floor_number}."))
            return

        # ---------------- Self teleport (anyone, but some floors are restricted) --
        floor_match = re.match(r"^[Dd](\d+)$", text)
        if floor_match:
            floor_number = int(floor_match.group(1))
            if floor_number not in FLOORS:
                await self.highrise.chat(
                    to_bold(
                        f"No floor D{floor_number} is configured. Available: "
                        + ", ".join("D" + str(f) for f in sorted(FLOORS))
                    )
                )
                return
            if floor_number in RESTRICTED_FLOORS:
                allowed = (
                    self._is_admin(user.username)
                    or self._is_vip(user.username)
                )
                if not allowed:
                    await self.highrise.chat(
                        to_bold(f"D{floor_number} is only for admins, the owner, and VIPs.")
                    )
                    return
            await self.highrise.teleport(user.id, FLOORS[floor_number])
            await self.highrise.chat(to_bold(f"{user.username} teleported to D{floor_number}."))
            return

        dance_target_match = re.match(r"^(\d+)\s+@(\S+)$", text)
        if dance_target_match:
            if not self._is_admin(user.username):
                await self.highrise.chat(to_bold("Only an admin can make other members dance."))
                return
            number = int(dance_target_match.group(1))
            target_username = dance_target_match.group(2)
            if number not in DANCES:
                await self.highrise.chat(to_bold(f"No dance is mapped to {number}."))
                return
            target_id = await self._find_user_id(target_username)
            if not target_id:
                await self.highrise.chat(to_bold(f"User '{target_username}' not found in the room."))
                return
            await self._start_dance(target_id, DANCES[number])
            await self.highrise.chat(to_bold(f"{target_username} is now dancing (#{number})!"))
            return

        if text.isdigit():
            number = int(text)
            if number not in DANCES:
                await self.highrise.chat(to_bold(f"No dance is mapped to {number}."))
                return
            await self._start_dance(user.id, DANCES[number])
            return

        # ---------------- Dance <emote_id> (admin only) ---------------------
        # Directly tries a raw emote id, e.g. "Dance dance-griddy".
        dance_id_match = re.match(r"^Dance\s+(\S+)$", text, re.IGNORECASE)
        if dance_id_match:
            if not self._is_admin(user.username):
                await self.highrise.chat(to_bold("Only an admin can use Dance <id>."))
                return
            emote_id = dance_id_match.group(1)
            try:
                await self._start_dance(user.id, emote_id)
                await self.highrise.chat(
                    to_bold(f"Tried emote id '{emote_id}'. If it didn't work, the id is wrong.")
                )
            except Exception:
                await self.highrise.chat(to_bold(f"'{emote_id}' is not a valid emote id."))
            return

        # ---------------- SaveDance <emote_id> <name> (admin only) ---------
        # Saves a confirmed-working emote id under a custom name, so anyone
        # can later trigger it by typing that name.
        save_dance_match = re.match(r"^SaveDance\s+(\S+)\s+(.+)$", text, re.IGNORECASE)
        if save_dance_match:
            if not self._is_admin(user.username):
                await self.highrise.chat(to_bold("Only an admin can use SaveDance."))
                return
            emote_id = save_dance_match.group(1)
            custom_name = save_dance_match.group(2).strip()
            key = custom_name.lower()
            if key in self._custom_dances:
                await self.highrise.chat(
                    to_bold(f"'{custom_name}' is already saved (id: {self._custom_dances[key]}). Overwriting it.")
                )
            self._custom_dances[key] = emote_id
            self._save_state()
            await self.highrise.chat(
                to_bold(f"✅ Saved! Anyone can now type '{custom_name}' to do this dance.")
            )
            return

        # ---------------- DanceList2 (list custom-named dances) -------------
        if text.lower() == "dancelist2":
            if not self._custom_dances:
                await self.highrise.chat(to_bold("No custom dances saved yet. Use SaveDance to add some."))
                return
            names = ", ".join(sorted(self._custom_dances.keys()))
            await self.highrise.chat(to_bold(f"Custom dances: {names}"))
            return

        # ---------------- Trigger a saved custom-named dance -----------------
        custom_key = text.lower()
        if custom_key in self._custom_dances:
            await self._start_dance(user.id, self._custom_dances[custom_key])
            return

    async def _find_user_id(self, username: str) -> str | None:
        room_users = (await self.highrise.get_room_users()).content
        for u, _pos in room_users:
            if u.username == username:
                return u.id
        return None

    async def _start_dance(self, user_id: str, emote_id: str) -> None:
        await self._stop_dance(user_id)

        async def loop() -> None:
            try:
                while True:
                    await self.highrise.send_emote(emote_id, user_id)
                    await asyncio.sleep(LOOP_INTERVAL_SECONDS)
            except asyncio.CancelledError:
                pass

        self._active_dances[user_id] = asyncio.create_task(loop())

    async def _stop_dance(self, user_id: str) -> None:
        task = self._active_dances.pop(user_id, None)
        if task and not task.done():
            task.cancel()

    async def _start_follow(self, target_id: str, target_username: str) -> None:
        await self._stop_follow()

        async def loop() -> None:
            try:
                while True:
                    room_users = (await self.highrise.get_room_users()).content
                    for u, pos in room_users:
                        if u.id == target_id and isinstance(pos, Position):
                            await self.highrise.walk_to(pos)
                            break
                    await asyncio.sleep(2)
            except asyncio.CancelledError:
                pass

        self._follow_task = asyncio.create_task(loop())
        await self.highrise.chat(to_bold(f"Following {target_username} now. Type Stop to cancel."))

    async def _stop_follow(self) -> None:
        if self._follow_task and not self._follow_task.done():
            self._follow_task.cancel()
        self._follow_task = None

    async def _run_spam(self, text: str, count: int) -> None:
        formatted = to_bold(text)
        for _ in range(count):
            await self.highrise.chat(formatted)
            await asyncio.sleep(SPAM_DELAY_SECONDS)
