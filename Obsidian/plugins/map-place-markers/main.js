"use strict";

/*
  Маркеры мест на карте Map View.

  Правила отображения Map View умеют только «запрос -> готовый значок»:
  чтобы показать оценку, на каждое значение нужно своё правило, а
  составить значок из двух свойств сразу нельзя. Плагин вмешивается в то
  место, где Map View собирает значок маркера (DisplayRulesCache.runOn),
  и дописывает к результату правил:

  - stars (0-5): плашка со звёздами над маркером. Числовые бейджи от
    старых правил (interest) при этом убираются. Нет stars - нет плашки;
  - cost (число, долларов на семью): плашка с ценой под маркером.
    Бесплатно (0) или нет числа - нет плашки;
  - duration (`30m`, `1.5h`): плашка со временем справа от маркера;
  - favorites не пуст: золотая окантовка маркера;
  - tags: значок маркера берётся по первому тегу из правил Map View вида
    `tag:#<тег>` (иконка и цвет). Сам Map View при нескольких тегах берёт
    последнее подходящее правило, а нужен первый тег.

  Значок, иконка и цвет по-прежнему берутся из правил Map View.
  Map View пересобирает маркер, когда меняется шапка заметки, поэтому
  новая оценка видна на карте сразу.
*/

const { Plugin } = require("obsidian");

const PATCHED = Symbol("map-place-markers");
const FAVORITE_CLASS = "mpm-favorite";
const VISITED_CLASS = "mpm-visited";

function starsHtml(stars) {
  return `<span class="mpm-stars mpm-stars-${stars}">${stars ? "★".repeat(stars) : "☆"}</span>`;
}

function costHtml(cost) {
  const rounded = Math.ceil(cost / 10) * 10;
  const text = rounded >= 1000 ? `${(rounded / 1000).toFixed(1).replace(/\.0$/, "")}k` : String(rounded);
  return `<span class="mpm-cost">${text}</span>`;
}

function durationHtml(duration) {
  return `<span class="mpm-dur">${duration}</span>`;
}

const BADGES = [
  { key: "stars", cls: "mpm-stars", html: starsHtml, style: { color: "#ffd23f", backgroundColor: "#222222", border: "1px solid white" } },
  { key: "cost", cls: "mpm-cost", html: costHtml, style: { color: "#ffffff", backgroundColor: "#1f6f3f", border: "1px solid white" } },
  { key: "duration", cls: "mpm-dur", html: durationHtml, style: { color: "#ffffff", backgroundColor: "#2b4a7a", border: "1px solid white" } },
];

module.exports = class MapPlaceMarkers extends Plugin {
  onload() {
    this.app.workspace.onLayoutReady(() => this.patch());
  }

  async patch() {
    const mapView = this.app.plugins.plugins["obsidian-map-view"];
    const cache = mapView && mapView.displayRulesCache;
    const proto = cache && Object.getPrototypeOf(cache);
    if (!proto || typeof proto.runOn !== "function" || proto[PATCHED]) return;

    const plugin = this;
    const original = proto.runOn;
    proto[PATCHED] = original;
    proto.runOn = function (layer) {
      return plugin.decorate(layer, original.call(this, layer));
    };
    this.register(() => {
      proto.runOn = original;
      delete proto[PATCHED];
    });
    if (typeof mapView.waitForInitialization === "function") await mapView.waitForInitialization();
    if (!this._loaded) return;
    this.patchIsSame(mapView);
    this.refreshMaps(mapView);
  }

  /*
    Обновляя карту, Map View оставляет старый маркер, если новый «такой же»:
    сравниваются только значок, его цвет и прозрачность. Смена звёзд или
    favorites так не видна. Пересоздавать маркер ради неё тоже плохо:
    вместе со старым маркером Map View закрывает его попап, а оценку
    ставят как раз из попапа. Поэтому маркер остаётся прежним, а плашка
    со звёздами и окантовка правятся прямо на нём.
  */
  patchIsSame(mapView) {
    const layer = (mapView.layerCache?.layers || []).find((l) => l.layerType === "fileMarker");
    const proto = layer && Object.getPrototypeOf(layer);
    if (!proto || typeof proto.isSame !== "function" || proto[PATCHED]) return;
    const plugin = this;
    const original = proto.isSame;
    proto[PATCHED] = original;
    proto.isSame = function (other) {
      if (!original.call(this, other)) return false;
      if (this.mpmSignature !== other.mpmSignature) plugin.updateInPlace(this, other);
      return true;
    };
    this.register(() => {
      proto.isSame = original;
      delete proto[PATCHED];
    });
  }

  updateInPlace(shown, fresh) {
    shown.icon = fresh.icon;
    shown.mpmSignature = fresh.mpmSignature;
    shown.mpmState = fresh.mpmState;
    for (const marker of shown.geoLayers.values()) {
      if (marker.options) marker.options.icon = fresh.icon;
      const el = marker.getElement && marker.getElement();
      if (el) this.paintElement(el, fresh.mpmState);
    }
  }

  paintElement(el, state) {
    el.classList.toggle(FAVORITE_CLASS, state.favorite);
    el.classList.toggle(VISITED_CLASS, state.visited);
    for (const kind of BADGES) {
      let badge = el.querySelector(`.${kind.cls}`)?.closest(".mv-badge");
      const value = state[kind.key];
      if (value === null) {
        badge?.remove();
        continue;
      }
      if (!badge) {
        badge = el.createDiv({ cls: "mv-badge mv-badge-tl" });
        Object.assign(badge.style, kind.style);
      }
      badge.innerHTML = `<span class="mv-badge-text">${kind.html(value)}</span>`;
    }
  }

  readState(fm) {
    const stars = typeof fm.stars === "number" ? Math.max(0, Math.min(5, Math.round(fm.stars))) : null;
    const cost = typeof fm.cost === "number" && fm.cost > 0 ? Math.round(fm.cost) : null;
    const favorites = fm.favorites;
    const favorite = Array.isArray(favorites) ? favorites.length > 0 : Boolean(favorites);
    const dm = String(fm.duration ?? "").trim().match(/^(\d+(?:\.\d+)?)\s*([mh])$/i);
    const duration = dm ? `${dm[1]}${dm[2].toLowerCase()}` : null;
    return { stars, cost, favorite, duration, visited: fm.visited === true };
  }

  decorate(layer, result) {
    const fm = layer && layer.file && this.app.metadataCache.getFileCache(layer.file)?.frontmatter;
    if (!fm) return result;
    let [iconDetails, pathOptions, badgeOptions] = result;
    const state = this.readState(fm);

    if (state.stars !== null) badgeOptions = badgeOptions.filter((b) => !/^\d+$/.test(String(b.badge)));
    const ours = BADGES.filter((k) => state[k.key] !== null).map((k) => ({
      badge: k.html(state[k.key]),
      textColor: k.style.color,
      backColor: k.style.backgroundColor,
      border: k.style.border,
    }));
    badgeOptions = [...ours, ...badgeOptions];

    if (state.favorite) {
      iconDetails = { ...iconDetails, className: `${iconDetails.className || ""} ${FAVORITE_CLASS}`.trim() };
    }
    if (state.visited) {
      iconDetails = { ...iconDetails, className: `${iconDetails.className || ""} ${VISITED_CLASS}`.trim() };
    }
    const typeIcon = this.iconForTag(fm.tags);
    if (typeIcon) iconDetails = { ...iconDetails, ...typeIcon, className: iconDetails.className };
    layer.mpmState = state;
    layer.mpmSignature = `${state.stars}|${state.cost}|${state.favorite}|${state.duration}|${state.visited}`;
    return [iconDetails, pathOptions, badgeOptions];
  }

  iconForTag(tags) {
    const first = String((Array.isArray(tags) ? tags[0] : tags) || "").replace(/^#/, "");
    if (!first) return null;
    const rules = this.app.plugins.plugins["obsidian-map-view"]?.settings?.displayRules || [];
    const rule = rules.find((r) => r.query === `tag:#${first}` && r.iconDetails);
    return rule ? { ...rule.iconDetails } : null;
  }

  refreshMaps(mapView) {
    if (typeof mapView.refreshDisplayRules === "function" && mapView.layerCache) mapView.refreshDisplayRules();
    if (typeof mapView.refreshAllMapViews === "function") mapView.refreshAllMapViews();
  }

  onunload() {
    const mapView = this.app.plugins.plugins["obsidian-map-view"];
    if (mapView) window.setTimeout(() => this.refreshMaps(mapView), 0);
  }
};
