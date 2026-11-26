"""Does the screen the guide is about to screenshot look private? Decided locally, from the windows
visible on that monitor (app class + title; neither leaves the machine for this check).

Fails closed: the screenshot only goes out without an approval card when EVERY visible window is
clearly harmless; anything unknown, private-looking or unreadable means "ask Osian". The chat
model's own judgement (`sensitive=true` when his question is about private things) can only add a
card, never remove one, so text on the screen can't talk its way into skipping the card.

Known gaps (nothing here can see them): notification pop-ups with message previews, the tab strip of
a browser (only the active tab's title is known), and the contents of an allowed window that isn't
named like anything private.
"""
import re

# System / settings tools: fine to show, whatever their title says.
SAFE_APPS = {
    "systemsettings", "org.kde.systemsettings", "kcmshell6", "kcmshell5", "org.kde.kinfocenter",
    "org.kde.plasma-systemmonitor", "org.kde.ksysguard", "org.gnome.settings", "gnome-control-center",
    "org.gnome.tweaks", "pavucontrol", "org.pulseaudio.pavucontrol", "com.saivert.pwvucontrol",
    "org.pipewire.helvum", "nm-connection-editor", "blueman-manager", "nwg-look", "qt5ct", "qt6ct",
    "kvantummanager", "org.kde.partitionmanager", "org.kde.kscreen", "arandr", "wdisplays",
    "org.kde.plasma.emojier", "org.kde.kcolorchooser",   # emoji and colour pickers
}

BROWSERS = {
    "vivaldi-stable", "vivaldi", "firefox", "org.mozilla.firefox", "librewolf", "zen", "zen-browser",
    "chromium", "google-chrome", "google-chrome-stable", "brave-browser", "microsoft-edge", "org.kde.falkon",
    "floorp", "waterfox", "opera",
}
FILE_MANAGERS = {
    "org.kde.dolphin", "dolphin", "org.gnome.nautilus", "nautilus", "thunar", "nemo", "pcmanfm", "pcmanfm-qt",
    "org.kde.krusader", "org.kde.index", "doublecmd",
}

# Words in a window title that make a browser/file-manager window private-looking.
SENSITIVE = (
    "bank", "banking", "barclays", "lloyds", "hsbc", "natwest", "santander", "nationwide", "monzo", "revolut",
    "starling", "paypal", "stripe", "wise", "coinbase", "binance", "wallet", "crypto", "payment", "payments",
    "checkout", "billing", "invoice", "invoices", "statement", "statements", "payslip", "payslips", "tax", "hmrc",
    "mortgage", "loan", "credit card", "card details", "password", "passwords", "passkey", "passkeys", "2fa",
    "authenticator", "sign in", "sign-in", "signin", "log in", "log-in", "login", "inbox", "mail", "gmail",
    "outlook", "proton mail", "whatsapp", "telegram", "signal", "messenger", "messages", "message", "chat", "dm",
    "dms", "discord", "slack", "health", "nhs", "medical", "doctor", "prescription", "therapy", "passport",
    "licence", "license", "national insurance", "ssn", "id card", "private", "incognito", "confidential",
    "secret", "secrets", "cv", "resume", "account", "accounts", "profile", "personal", "nsfw",
)
# Extra words that mark a folder as personal (file-manager titles are folder names/paths).
PERSONAL_PATHS = (
    "pictures", "picture", "photos", "photo", "images", "image", "camera", "dcim", "selfie", "selfies",
    "screenshots", "screenshot", "family", "holiday", "holidays", "vacation", "wedding", "kids", "children",
    "baby", "girlfriend", "boyfriend", "partner", "scans", "scan", "documents", "videos", "video", "recordings",
    "receipts", "id", "ids", "journal", "diary", "backup", "backups",
)


def _pattern(words) -> re.Pattern:
    return re.compile(r"(?<![a-z0-9])(" + "|".join(sorted((re.escape(w.lower()) for w in words), key=len, reverse=True))
                      + r")(?![a-z0-9])")


class Policy:
    def __init__(self, safe_apps=(), ask_words=()):
        self.safe = SAFE_APPS | {a.lower() for a in safe_apps}
        self.sensitive = _pattern(SENSITIVE + tuple(ask_words))
        self.personal = _pattern(PERSONAL_PATHS)

    def assess(self, windows, model_flag: bool = False, name_of=lambda cls: cls):
        """(ask, reasons). windows: [{"cls","title"}] visible on the monitor; None means "couldn't
        tell" (-> ask). Reasons name apps, never titles, so they are safe to show on a card."""
        reasons = []
        if model_flag:
            reasons.append("your question looks private")
        if windows is None:
            reasons.append("couldn't check which windows are open")
            return True, reasons
        for w in windows:
            cls = str(w.get("cls", "")).lower()
            title = str(w.get("title", "")).lower()
            app = str(name_of(w.get("cls", "")))[:30] or "an app"
            if cls in self.safe:
                continue
            if cls in BROWSERS:
                if self.sensitive.search(title):
                    reasons.append(f"{app} looks like it's on a private page")
                continue
            if cls in FILE_MANAGERS:
                if self.sensitive.search(title) or self.personal.search(title):
                    reasons.append(f"{app} is showing a folder that may be personal")
                continue
            reasons.append(f"{app} is open")
        seen, out = set(), []
        for r in reasons:    # one line per reason, in order
            if r not in seen:
                seen.add(r)
                out.append(r)
        return bool(out), out
