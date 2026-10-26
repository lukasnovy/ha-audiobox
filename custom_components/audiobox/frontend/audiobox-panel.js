// The Audiobox card pairing panel: tap a card on a box, click a book.
// One hand-written custom element, no build step (ADR-43).

const STRINGS = {
  en: {
    title: "Card pairing",
    tapPrompt: "Tap a card on a box",
    card: (uid) => `Card ${uid}`,
    isNew: "new, click a book",
    plays: (book) => `plays ${book}`,
    justNow: "just now",
    minutesAgo: (n) => `${n} min ago`,
    hoursAgo: (n) => `${n} h ago`,
    removeCard: "Remove card",
    reassignHint: "Click another book to give it to this card.",
    paired: (book, uid) => `✓ ${book} ↔ ${uid}. Tap the next card.`,
    removed: (uid) => `Card ${uid} removed.`,
    confirmReassign: (uid, oldBook, newBook) =>
      `Give card ${uid} to “${newBook}” instead of “${oldBook}”?`,
    confirmRemove: (uid, book) => `Remove card ${uid} (${book})?`,
    cancel: "Cancel",
    reassign: "Reassign",
    remove: "Remove",
    search: "Search by title",
    audiobooks: "Audiobooks",
    playlists: "Playlists",
    unpaired: "Only without a card",
    reload: "Reload the library",
    menu: "Menu",
    loading: "Loading the library…",
    nothing: "Nothing matches.",
    cardLabel: (uids) => `card ${uids}`,
    thisCard: "this card",
    retry: "Try again",
    errors: {
      invalid_uid: "The card's UID is not valid.",
      unsupported_media: "Only audiobooks and playlists can be paired.",
      not_library_audiobook: "This audiobook is not in the Music Assistant library.",
      not_found: "This card no longer exists.",
      not_loaded: "The Audiobox integration is not loaded.",
      music_assistant_not_loaded: "Music Assistant is not available.",
      library_failed: "Music Assistant could not list the library.",
      unknown: "Something went wrong.",
    },
  },
  cs: {
    title: "Párování karet",
    tapPrompt: "Přilož kartu ke krabičce",
    card: (uid) => `Karta ${uid}`,
    isNew: "nová, klikni na knihu",
    plays: (book) => `hraje ${book}`,
    justNow: "právě teď",
    minutesAgo: (n) => `před ${n} min`,
    hoursAgo: (n) => `před ${n} h`,
    removeCard: "Odebrat kartu",
    reassignHint: "Klikni na jinou knihu, pokud ji chceš kartě přeřadit.",
    paired: (book, uid) => `✓ ${book} ↔ ${uid}. Přilož další kartu.`,
    removed: (uid) => `Karta ${uid} je odebraná.`,
    confirmReassign: (uid, oldBook, newBook) =>
      `Přeřadit kartu ${uid} z „${oldBook}“ na „${newBook}“?`,
    confirmRemove: (uid, book) => `Odebrat kartu ${uid} (${book})?`,
    cancel: "Zrušit",
    reassign: "Přeřadit",
    remove: "Odebrat",
    search: "Hledat podle názvu",
    audiobooks: "Audioknihy",
    playlists: "Playlisty",
    unpaired: "Jen bez karty",
    reload: "Načíst knihovnu znovu",
    menu: "Menu",
    loading: "Načítám knihovnu…",
    nothing: "Nic neodpovídá.",
    cardLabel: (uids) => `karta ${uids}`,
    thisCard: "tahle karta",
    retry: "Zkusit znovu",
    errors: {
      invalid_uid: "UID karty není platné.",
      unsupported_media: "Spárovat jde jen audioknihu nebo playlist.",
      not_library_audiobook: "Tahle audiokniha není v knihovně Music Assistant.",
      not_found: "Tahle karta už neexistuje.",
      not_loaded: "Integrace Audiobox není načtená.",
      music_assistant_not_loaded: "Music Assistant není dostupný.",
      library_failed: "Music Assistant nevrátil knihovnu.",
      unknown: "Něco se nepovedlo.",
    },
  },
};

// Cover links are signed for 24 hours. An expired one counts as a failed login,
// so a library is reloaded well before that, and after every Home Assistant start.
const LIBRARY_MAX_AGE = 12 * 60 * 60 * 1000;

const STORAGE = {
  search: "audiobox.search",
  type: "audiobox.type",
  unpaired: "audiobox.unpaired",
};

const MENU_ICON =
  "M3,6H21V8H3V6M3,11H21V13H3V11M3,16H21V18H3V16Z";
const RELOAD_ICON =
  "M17.65,6.35C16.2,4.9 14.21,4 12,4A8,8 0 0,0 4,12A8,8 0 0,0 12,20C15.73,20 18.84,17.45 19.73,14H17.65C16.83,16.33 14.61,18 12,18A6,6 0 0,1 6,12A6,6 0 0,1 12,6C13.66,6 15.14,6.69 16.22,7.78L13,11H20V4L17.65,6.35Z";
const BOOK_ICON =
  "M18,2A2,2 0 0,1 20,4V20A2,2 0 0,1 18,22H6A2,2 0 0,1 4,20V4A2,2 0 0,1 6,2H18M18,4H13V12L10.5,9.75L8,12V4H6V20H18V4Z";

const STYLE = `
  :host {
    display: block;
    min-height: 100vh;
    background: var(--primary-background-color);
    color: var(--primary-text-color);
    font-family: var(--ha-font-family-body, Roboto, sans-serif);
    font-size: 14px;
  }
  .toolbar {
    display: flex;
    align-items: center;
    gap: 8px;
    height: var(--header-height, 56px);
    padding: 0 16px;
    background: var(--app-header-background-color, var(--primary-color));
    color: var(--app-header-text-color, var(--text-primary-color, #fff));
    font-size: 20px;
  }
  .toolbar button { color: inherit; }
  .content { max-width: 760px; margin: 0 auto; padding: 16px; box-sizing: border-box; }
  button {
    font: inherit;
    cursor: pointer;
    border: none;
    background: none;
    color: var(--primary-text-color);
  }
  .icon { width: 24px; height: 24px; fill: currentColor; display: block; }
  .icon-button { padding: 8px; border-radius: 50%; }
  .icon-button:hover { background: rgba(127, 127, 127, 0.15); }
  .tap {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 12px 14px;
    border-radius: 12px;
    background: var(--card-background-color);
    border: 2px solid var(--divider-color);
  }
  .tap.new { border-color: var(--success-color, #4caf50); }
  .tap.known { border-color: var(--primary-color); }
  .tap.pulse { animation: pulse 0.6s ease-in-out 2; }
  @keyframes pulse { 50% { transform: scale(1.02); border-color: var(--warning-color, #ff9800); } }
  .dot { width: 14px; height: 14px; border-radius: 50%; flex: none; background: var(--divider-color); }
  .new .dot { background: var(--success-color, #4caf50); }
  .known .dot { background: var(--primary-color); }
  .tap-text { flex: 1; min-width: 0; }
  .tap-title { font-size: 16px; font-weight: 500; }
  .secondary { color: var(--secondary-text-color); font-size: 13px; }
  .outlined {
    padding: 6px 12px;
    border-radius: 8px;
    border: 1px solid var(--divider-color);
  }
  .danger { color: var(--error-color, #db4437); border-color: var(--error-color, #db4437); }
  .line { margin-top: 10px; padding: 8px 12px; border-radius: 8px; }
  .line.ok { background: rgba(var(--rgb-success-color, 76, 175, 80), 0.15); }
  .line.error { background: rgba(var(--rgb-error-color, 219, 68, 55), 0.15); color: var(--error-color, #db4437); }
  .line.hint { background: rgba(var(--rgb-primary-color, 3, 169, 244), 0.12); }
  .confirm {
    margin-top: 10px;
    padding: 10px 12px;
    border-radius: 8px;
    background: var(--card-background-color);
    border: 1px solid var(--divider-color);
  }
  .confirm .actions { display: flex; gap: 8px; justify-content: flex-end; margin-top: 8px; }
  .primary { background: var(--primary-color); color: var(--text-primary-color, #fff); border-color: var(--primary-color); }
  .tools { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin: 16px 0 10px; }
  input[type="search"] {
    flex: 1 1 180px;
    min-width: 0;
    padding: 9px 12px;
    border-radius: 8px;
    border: 1px solid var(--divider-color);
    background: var(--card-background-color);
    color: var(--primary-text-color);
    font: inherit;
  }
  .segments { display: flex; border: 1px solid var(--primary-color); border-radius: 18px; overflow: hidden; }
  .segments button { padding: 6px 12px; color: var(--primary-color); }
  .segments button[aria-pressed="true"], .chip[aria-pressed="true"] {
    background: var(--primary-color);
    color: var(--text-primary-color, #fff);
  }
  .chip { padding: 6px 12px; border-radius: 18px; border: 1px solid var(--divider-color); }
  .list { display: flex; flex-direction: column; gap: 6px; }
  .row {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 6px;
    border-radius: 10px;
    background: var(--card-background-color);
    border: 1px solid var(--divider-color);
    text-align: left;
    width: 100%;
  }
  .row:hover { border-color: var(--primary-color); }
  .row.paired { opacity: 0.5; }
  .row.current { opacity: 1; border: 2px solid var(--primary-color); }
  .cover {
    width: 48px;
    height: 48px;
    flex: none;
    border-radius: 6px;
    object-fit: cover;
    background: var(--secondary-background-color, rgba(127, 127, 127, 0.15));
    color: var(--secondary-text-color);
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .row-text { flex: 1; min-width: 0; }
  .row-title { overflow-wrap: anywhere; }
  .status { padding: 24px 0; text-align: center; color: var(--secondary-text-color); }
  .status button { margin-top: 8px; }
  [hidden] { display: none !important; }
`;

function svg(path) {
  const ns = "http://www.w3.org/2000/svg";
  const icon = document.createElementNS(ns, "svg");
  icon.setAttribute("viewBox", "0 0 24 24");
  icon.setAttribute("class", "icon");
  const shape = document.createElementNS(ns, "path");
  shape.setAttribute("d", path);
  icon.append(shape);
  return icon;
}

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (key === "class") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else if (key in node) node[key] = value;
    else node.setAttribute(key, value);
  }
  node.append(...children.filter((child) => child !== null && child !== undefined));
  return node;
}

function fold(text) {
  return text.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase();
}

function load(key, fallback) {
  try {
    const value = window.localStorage.getItem(key);
    return value === null ? fallback : value;
  } catch {
    return fallback;
  }
}

function save(key, value) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // Private window or blocked storage: the setting lasts for this visit only.
  }
}

class AudioboxPanel extends HTMLElement {
  constructor() {
    super();
    this._cards = [];
    this._tap = null;
    this._libraries = {};
    this._loadedAt = {};
    this._run = null;
    this._libraryError = {};
    this._loading = {};
    this._search = load(STORAGE.search, "");
    this._type = load(STORAGE.type, "audiobook") === "playlist" ? "playlist" : "audiobook";
    this._unpaired = load(STORAGE.unpaired, "false") === "true";
    this._line = null;
    this._confirm = null;
    this._busy = false;
    this._subscriptionError = null;
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first) {
      this._strings = (hass.language || "en").startsWith("cs") ? STRINGS.cs : STRINGS.en;
      this._collator = new Intl.Collator(hass.language || "en", { sensitivity: "base" });
      this._build();
      if (this.isConnected) this._start();
    }
  }

  set narrow(narrow) {
    this._narrow = narrow;
    if (this._menuButton) this._menuButton.hidden = !narrow;
  }

  set panel(panel) {
    this._panel = panel;
  }

  connectedCallback() {
    if (this._hass) this._start();
  }

  disconnectedCallback() {
    clearInterval(this._ageTimer);
    this._ageTimer = undefined;
    if (this._unsubscribe) {
      this._unsubscribe.then((unsubscribe) => unsubscribe()).catch(() => {});
      this._unsubscribe = undefined;
    }
  }

  _start() {
    if (!this._unsubscribe) {
      this._subscriptionError = null;
      // The websocket library re-subscribes by itself after a reconnect.
      this._unsubscribe = this._hass.connection.subscribeMessage(
        (state) => this._onState(state),
        { type: "audiobox/subscribe" },
      );
      this._unsubscribe.catch((err) => {
        this._unsubscribe = undefined;
        this._subscriptionError = err;
        this._renderTap();
      });
    }
    if (this._ageTimer === undefined) {
      this._ageTimer = setInterval(() => {
        this._renderTap();
        this._dropStaleLibraries(false);
      }, 30000);
    }
    this._dropStaleLibraries(false);
    this._loadLibrary(this._type, false);
  }

  // Forget libraries whose cover links may have expired; reload the one on screen.
  _dropStaleLibraries(all) {
    let dropped = false;
    for (const type of Object.keys(this._libraries)) {
      if (all || Date.now() - this._loadedAt[type] > LIBRARY_MAX_AGE) {
        if (this._rowCache) {
          for (const item of this._libraries[type]) this._rowCache.delete(item);
        }
        delete this._libraries[type];
        dropped = dropped || type === this._type;
      }
    }
    if (dropped && this._hass) this._loadLibrary(this._type, false);
  }

  // --- data ---------------------------------------------------------------

  _onState(state) {
    if (this._run !== null && state.run !== this._run) this._dropStaleLibraries(true);
    this._run = state.run;
    const previous = this._tap;
    this._cards = state.cards;
    this._tap = state.last_tap;
    if (this._tap && (!previous || previous.at !== this._tap.at || previous.uid !== this._tap.uid)) {
      // A new tap: what was on screen was about the previous card.
      if (previous) this._line = null;
      this._confirm = null;
    }
    this._renderTap();
    // The marks follow in place; only the "without a card" filter changes the rows.
    if (this._unpaired) this._renderList();
  }

  async _loadLibrary(type, force) {
    if (this._loading[type] || (this._libraries[type] && !force)) {
      this._renderList();
      return;
    }
    this._loading[type] = true;
    this._libraryError[type] = null;
    this._renderList();
    try {
      const result = await this._hass.callWS({ type: "audiobox/library", media_type: type });
      if (this._rowCache) {
        for (const item of this._libraries[type] || []) this._rowCache.delete(item);
      }
      this._libraries[type] = result.items
        .slice()
        .sort((a, b) => this._collator.compare(a.name, b.name));
      this._loadedAt[type] = Date.now();
    } catch (err) {
      this._libraryError[type] = err;
    } finally {
      this._loading[type] = false;
      this._renderList();
    }
  }

  _cardOf(uid) {
    return this._cards.find((card) => card.uid === uid);
  }

  _errorText(err) {
    const errors = this._strings.errors;
    const text = errors[err && err.code] || errors.unknown;
    return err && err.code === "library_failed" && err.message ? `${text} ${err.message}` : text;
  }

  // --- actions --------------------------------------------------------------

  _clickBook(item) {
    if (this._busy) return;
    const tap = this._tap;
    if (!tap) {
      this._tapBox.classList.remove("pulse");
      void this._tapBox.offsetWidth;
      this._tapBox.classList.add("pulse");
      return;
    }
    const card = this._cardOf(tap.uid);
    if (!card) {
      this._pair(tap.uid, item);
      return;
    }
    if (card.media_id === item.uri) return;
    const s = this._strings;
    this._confirm = {
      text: s.confirmReassign(tap.uid, card.name, item.name),
      action: s.reassign,
      run: () => this._pair(tap.uid, item),
    };
    this._line = null;
    this._renderTap();
  }

  _clickRemove() {
    const card = this._tap && this._cardOf(this._tap.uid);
    if (!card || this._busy) return;
    const s = this._strings;
    this._confirm = {
      text: s.confirmRemove(card.uid, card.name),
      action: s.remove,
      danger: true,
      run: () => this._unpair(card.uid),
    };
    this._line = null;
    this._renderTap();
  }

  async _pair(uid, item) {
    await this._call(
      { type: "audiobox/pair", uid, uri: item.uri, name: item.name },
      () => this._strings.paired(item.name, uid),
    );
  }

  async _unpair(uid) {
    await this._call({ type: "audiobox/unpair", uid }, () => this._strings.removed(uid));
  }

  async _call(message, success) {
    this._busy = true;
    this._confirm = null;
    try {
      await this._hass.callWS(message);
      this._line = { kind: "ok", text: success() };
    } catch (err) {
      this._line = { kind: "error", text: this._errorText(err) };
    } finally {
      this._busy = false;
      this._renderTap();
    }
  }

  // --- rendering --------------------------------------------------------------

  _build() {
    const s = this._strings;
    const root = this.attachShadow({ mode: "open" });

    this._menuButton = el(
      "button",
      {
        class: "icon-button",
        title: s.menu,
        "aria-label": s.menu,
        onclick: () =>
          this.dispatchEvent(new Event("hass-toggle-menu", { bubbles: true, composed: true })),
      },
      svg(MENU_ICON),
    );
    this._menuButton.hidden = !this._narrow;

    this._tapBox = el("div", { class: "tap" });
    this._tapArea = el("div");
    this._listArea = el("div");

    this._searchInput = el("input", {
      type: "search",
      placeholder: s.search,
      "aria-label": s.search,
      value: this._search,
      oninput: (event) => {
        this._search = event.target.value;
        save(STORAGE.search, this._search);
        this._renderList();
      },
    });
    this._typeButtons = {
      audiobook: el("button", { onclick: () => this._setType("audiobook") }, s.audiobooks),
      playlist: el("button", { onclick: () => this._setType("playlist") }, s.playlists),
    };
    this._unpairedButton = el(
      "button",
      {
        class: "chip",
        onclick: () => {
          this._unpaired = !this._unpaired;
          save(STORAGE.unpaired, String(this._unpaired));
          this._renderTools();
          this._renderList();
        },
      },
      s.unpaired,
    );
    const reload = el(
      "button",
      {
        class: "icon-button",
        title: s.reload,
        "aria-label": s.reload,
        onclick: () => this._loadLibrary(this._type, true),
      },
      svg(RELOAD_ICON),
    );

    root.append(
      el("style", {}, STYLE),
      el("div", { class: "toolbar" }, this._menuButton, el("div", {}, `Audiobox · ${s.title}`)),
      el(
        "div",
        { class: "content" },
        this._tapArea,
        el(
          "div",
          { class: "tools" },
          this._searchInput,
          el("div", { class: "segments" }, this._typeButtons.audiobook, this._typeButtons.playlist),
          this._unpairedButton,
          reload,
        ),
        this._listArea,
      ),
    );
    this._renderTools();
    this._renderTap();
    this._renderList();
  }

  _setType(type) {
    if (type === this._type) return;
    this._type = type;
    save(STORAGE.type, type);
    this._renderTools();
    this._loadLibrary(type, false);
  }

  _renderTools() {
    for (const [type, button] of Object.entries(this._typeButtons)) {
      button.setAttribute("aria-pressed", String(type === this._type));
    }
    this._unpairedButton.setAttribute("aria-pressed", String(this._unpaired));
  }

  _age(at) {
    const s = this._strings;
    const minutes = Math.floor((Date.now() - new Date(at).getTime()) / 60000);
    if (minutes < 1) return s.justNow;
    if (minutes < 60) return s.minutesAgo(minutes);
    return s.hoursAgo(Math.floor(minutes / 60));
  }

  _renderTap() {
    if (!this._tapArea) return;
    const s = this._strings;
    const tap = this._tap;
    const card = tap && this._cardOf(tap.uid);
    const box = this._tapBox;
    box.className = `tap${tap ? (card ? " known" : " new") : ""}`;
    box.replaceChildren();
    const text = el("div", { class: "tap-text" });
    if (this._subscriptionError) {
      text.append(el("div", { class: "tap-title" }, this._errorText(this._subscriptionError)));
    } else if (!tap) {
      text.append(el("div", { class: "tap-title" }, s.tapPrompt));
    } else {
      text.append(
        el("div", { class: "tap-title" }, s.card(tap.uid)),
        el("div", { class: "secondary" }, card ? s.plays(card.name) : s.isNew),
        el("div", { class: "secondary" }, `${tap.box} · ${this._age(tap.at)}`),
      );
    }
    box.append(el("div", { class: "dot" }), text);
    if (card) {
      box.append(
        el("button", { class: "outlined danger", onclick: () => this._clickRemove() }, s.removeCard),
      );
    }

    const parts = [box];
    if (this._confirm) {
      const confirm = this._confirm;
      parts.push(
        el(
          "div",
          { class: "confirm" },
          el("div", {}, confirm.text),
          el(
            "div",
            { class: "actions" },
            el(
              "button",
              {
                class: "outlined",
                onclick: () => {
                  this._confirm = null;
                  this._renderTap();
                },
              },
              s.cancel,
            ),
            el(
              "button",
              { class: `outlined ${confirm.danger ? "danger" : "primary"}`, onclick: () => confirm.run() },
              confirm.action,
            ),
          ),
        ),
      );
    }
    if (this._line) {
      parts.push(el("div", { class: `line ${this._line.kind}` }, this._line.text));
    } else if (card) {
      parts.push(el("div", { class: "line hint" }, s.reassignHint));
    }
    this._tapArea.replaceChildren(...parts);
    this._renderListMarks();
  }

  _visibleItems() {
    const items = this._libraries[this._type] || [];
    const query = fold(this._search.trim());
    const paired = this._pairedUids();
    return items.filter(
      (item) =>
        (!query || fold(item.name).includes(query)) &&
        (!this._unpaired || !paired.has(item.uri)),
    );
  }

  _pairedUids() {
    const paired = new Map();
    for (const card of this._cards) {
      if (!paired.has(card.media_id)) paired.set(card.media_id, []);
      paired.get(card.media_id).push(card.uid);
    }
    return paired;
  }

  _renderList() {
    if (!this._listArea) return;
    const s = this._strings;
    const type = this._type;
    if (this._loading[type]) {
      this._listArea.replaceChildren(el("div", { class: "status" }, s.loading));
      return;
    }
    if (this._libraryError[type]) {
      this._listArea.replaceChildren(
        el(
          "div",
          { class: "status" },
          el("div", {}, this._errorText(this._libraryError[type])),
          el("button", { class: "outlined", onclick: () => this._loadLibrary(type, true) }, s.retry),
        ),
      );
      return;
    }
    const items = this._visibleItems();
    if (!items.length) {
      this._listArea.replaceChildren(el("div", { class: "status" }, s.nothing));
      return;
    }
    this._rows = new Map();
    const list = el("div", { class: "list" });
    for (const item of items) {
      const entry = this._rowFor(item);
      this._rows.set(item.uri, entry);
      list.append(entry.row);
    }
    this._listArea.replaceChildren(list);
    this._renderListMarks();
  }

  // One row per library item, built once: typing in the search must not reload covers.
  _rowFor(item) {
    if (!this._rowCache) this._rowCache = new Map();
    const cached = this._rowCache.get(item);
    if (cached) return cached;
    const cover = item.image
      ? el("img", { class: "cover", src: item.image, alt: "", loading: "lazy", decoding: "async" })
      : el("div", { class: "cover" }, svg(BOOK_ICON));
    if (item.image) {
      cover.addEventListener("error", () => cover.replaceWith(el("div", { class: "cover" }, svg(BOOK_ICON))), {
        once: true,
      });
    }
    const label = el("div", { class: "secondary" });
    const row = el(
      "button",
      { class: "row", onclick: () => this._clickBook(item) },
      cover,
      el("div", { class: "row-text" }, el("div", { class: "row-title" }, item.name), label),
    );
    const entry = { row, label };
    this._rowCache.set(item, entry);
    return entry;
  }

  // Greys paired books and frames the tapped card's book without rebuilding the list.
  _renderListMarks() {
    if (!this._rows) return;
    const s = this._strings;
    const paired = this._pairedUids();
    const tapCard = this._tap && this._cardOf(this._tap.uid);
    for (const [uri, { row, label }] of this._rows) {
      const uids = paired.get(uri) || [];
      const current = Boolean(tapCard && tapCard.media_id === uri);
      row.classList.toggle("paired", uids.length > 0);
      row.classList.toggle("current", current);
      label.textContent = current ? s.thisCard : uids.length ? s.cardLabel(uids.join(", ")) : "";
    }
  }
}

customElements.define("audiobox-panel", AudioboxPanel);
