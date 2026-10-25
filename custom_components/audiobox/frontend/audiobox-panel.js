// The Audiobox card pairing panel. Replaced by the full panel in the next step.
class AudioboxPanel extends HTMLElement {
  set hass(hass) {
    this._hass = hass;
    if (!this.shadowRoot) {
      this.attachShadow({ mode: "open" }).innerHTML = "<h1>Audiobox</h1>";
    }
  }
}

customElements.define("audiobox-panel", AudioboxPanel);
