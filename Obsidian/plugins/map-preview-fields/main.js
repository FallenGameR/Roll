"use strict";

/*
  Поля Meta Bind в предпросмотре Map View.

  Map View рисует предпросмотр заметки так:
    MarkdownRenderer.render(app, snippet, el, path, new Component())
  Компонент новый и никем не загружен. Meta Bind находит в тексте
  `INPUT[...]` и вешает поле дочерним к этому компоненту, а дочерние
  незагруженного компонента не загружаются никогда. Поэтому в попапе
  вместо звёзд остаётся сырой код.

  Плагин подменяет MarkdownRenderer.render и для вызовов из Map View
  (их видно по кадру plugin:obsidian-map-view в стеке) берёт брошенный
  компонент себе: загружает его до рендера, а когда попап убран из
  документа, выгружает. Остальные вызовы проходят как есть.

  Второе: попап Map View живёт, только пока мышь на маркере. Уводишь мышь
  к попапу, чтобы поставить звёзды, и он гаснет. Плагин подменяет мягкое
  закрытие (closeMarkerPopup(false)) у класса карты: после ухода с маркера
  даёт мыши GRACE_MS долететь до попапа, пока мышь над попапом, не
  закрывает, и закрывает, когда мышь его покинула. Пока раскрыт список
  select, попап тоже не закрывается: список рисуется отдельным окном, и
  уход мыши в него выглядит как уход с попапа.
*/

const { Plugin, MarkdownRenderer } = require("obsidian");

const CALLERS = ["plugin:obsidian-map-view"];
const NEVER_SHOWN_MS = 10000;
const GRACE_MS = 350;
const PATCHED = Symbol("map-preview-fields");

module.exports = class MapPreviewFields extends Plugin {
  onload() {
    this.tracked = new Set();

    const plugin = this;
    const original = MarkdownRenderer.render;
    const patched = function (app, markdown, el, sourcePath, component, ...rest) {
      if (component && !component._loaded && el instanceof HTMLElement && plugin.fromCaller()) {
        plugin.adopt(component, el);
      }
      return original.call(this, app, markdown, el, sourcePath, component, ...rest);
    };
    MarkdownRenderer.render = patched;
    this.register(() => {
      if (MarkdownRenderer.render === patched) MarkdownRenderer.render = original;
    });

    this.observer = new MutationObserver(() => this.sweep());
    this.observer.observe(document.body, { childList: true, subtree: true });
    this.register(() => this.observer.disconnect());

    this.app.workspace.onLayoutReady(() => this.patchMapView());
  }

  patchMapView() {
    const mapView = this.app.plugins.plugins["obsidian-map-view"];
    if (!mapView) return;
    const plugin = this;

    const patchContainer = (container) => {
      const proto = container && Object.getPrototypeOf(container);
      if (!proto || typeof proto.closeMarkerPopup !== "function" || proto[PATCHED]) return;
      const original = proto.closeMarkerPopup;
      proto[PATCHED] = original;
      proto.closeMarkerPopup = function (hardClose) {
        return plugin.closePopup(this, original, hardClose);
      };
      this.register(() => {
        proto.closeMarkerPopup = original;
        delete proto[PATCHED];
      });
    };

    (mapView.allMapContainers || []).forEach(patchContainer);
    const register = mapView.registerMapContainer;
    if (typeof register === "function") {
      mapView.registerMapContainer = function (container) {
        patchContainer(container);
        return register.apply(this, arguments);
      };
      this.register(() => {
        mapView.registerMapContainer = register;
      });
    }
  }

  closePopup(container, original, hardClose) {
    const div = container.display && container.display.popupDiv;
    window.clearTimeout(container._mpfTimer);
    if (hardClose || !div) return original.call(container, hardClose);

    const keep = () => div.matches(":hover") || div._mpfSelectOpen;
    if (keep()) return this.watchPopup(container, original, div, keep);
    container._mpfTimer = window.setTimeout(() => {
      if (keep()) this.watchPopup(container, original, div, keep);
      else original.call(container, false);
    }, GRACE_MS);
  }

  watchPopup(container, original, div, keep) {
    if (div._mpfWatched) return;
    div._mpfWatched = true;
    const closeIfLeft = () => {
      if (div.classList.contains("visible") && !keep()) original.call(container, false);
    };
    const onSelectDone = () => {
      div._mpfSelectOpen = false;
      window.setTimeout(closeIfLeft, 0);
    };
    this.registerDomEvent(div, "mouseleave", closeIfLeft);
    this.registerDomEvent(div, "mousedown", (e) => {
      if (e.target instanceof HTMLSelectElement) div._mpfSelectOpen = true;
    });
    this.registerDomEvent(div, "change", onSelectDone);
    this.registerDomEvent(div, "focusout", onSelectDone);
  }

  fromCaller() {
    const stack = new Error().stack || "";
    return CALLERS.some((c) => stack.includes(c));
  }

  adopt(component, el) {
    const entry = { component, el, shown: false };
    this.tracked.add(entry);
    this.addChild(component);
    // Попап, который так и не попал в документ, тоже надо отпустить.
    window.setTimeout(() => {
      if (!entry.shown) this.release(entry);
    }, NEVER_SHOWN_MS);
  }

  sweep() {
    for (const entry of this.tracked) {
      if (entry.el.isConnected) entry.shown = true;
      else if (entry.shown) this.release(entry);
    }
  }

  release(entry) {
    if (!this.tracked.delete(entry)) return;
    this.removeChild(entry.component);
  }
};
