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
    последнее подходящее правило, а нужен первый тег;
  - тег lodging (наше жильё): маркер не уходит в кластер, его видно всегда.

  Значок, иконка и цвет по-прежнему берутся из правил Map View.
  Map View пересобирает маркер, когда меняется шапка заметки, поэтому
  новая оценка видна на карте сразу.
*/

const { Plugin } = require("obsidian");

const PATCHED = Symbol("map-place-markers");
const FAVORITE_CLASS = "mpm-favorite";
const VISITED_CLASS = "mpm-visited";
const NO_CLUSTER_CLASS = "mpm-nocluster";
const NO_CLUSTER_TAGS = ["lodging"];

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
    const retry = () => window.setTimeout(() => this.patchClusterGroup(), 1500);
    this.registerEvent(this.app.workspace.on("layout-change", () => this.clusterPatched || retry()));
    retry();
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
    if (this.isNoCluster(fm.tags)) {
      iconDetails = { ...iconDetails, className: `${iconDetails.className || ""} ${NO_CLUSTER_CLASS}`.trim() };
      if (!this.clusterPatched) this.patchClusterGroup();
    }
    layer.mpmState = state;
    layer.mpmSignature = `${state.stars}|${state.cost}|${state.favorite}|${state.duration}|${state.visited}`;
    return [iconDetails, pathOptions, badgeOptions];
  }

  isNoCluster(tags) {
    const list = (Array.isArray(tags) ? tags : [tags]).map((t) => String(t || "").replace(/^#/, ""));
    return list.some((t) => NO_CLUSTER_TAGS.includes(t));
  }

  /*
    Кластер Map View собирает все маркеры подряд, и отель, стоящий в одном
    доме с рестораном, прячется в кружок «2». Исключений кластер не знает,
    поэтому его addLayers/removeLayers перехватываются: маркеры с классом
    mpm-nocluster кладутся прямо на карту. Класс кластера сидит внутри
    сборки Map View, и прототип достаётся с первой найденной карты.
  */
  findMapContainers() {
    const found = [];
    const seen = new Set();
    let level = [];
    this.app.workspace.iterateAllLeaves((leaf) => level.push(leaf.view));
    for (let depth = 0; depth <= 8 && level.length; depth++) {
      const next = [];
      for (const o of level) {
        if (!o || typeof o !== "object" || seen.has(o) || o instanceof Node) continue;
        seen.add(o);
        try {
          if (o.display && o.display.clusterGroup && o.display.map) {
            found.push(o);
            continue;
          }
          for (const k of Object.keys(o)) if (k !== "app") next.push(o[k]);
        } catch (e) {}
      }
      level = next;
    }
    return found;
  }

  patchClusterGroup() {
    if (this.clusterPatched) return;
    const containers = this.findMapContainers();
    if (!containers.length) return;
    const proto = Object.getPrototypeOf(containers[0].display.clusterGroup);
    if (!proto[PATCHED]) {
      const loose = (m) => String(m?.options?.icon?.options?.className || "").includes(NO_CLUSTER_CLASS);
      const orig = { addLayers: proto.addLayers, removeLayers: proto.removeLayers, addLayer: proto.addLayer, removeLayer: proto.removeLayer, hasLayer: proto.hasLayer };
      proto[PATCHED] = orig;
      const putOnMap = (group, m) => {
        (group.mpmLoose ||= new Set()).add(m);
        if (group._map) m.addTo(group._map);
      };
      const takeOff = (group, m) => {
        if (!group.mpmLoose?.has(m)) return false;
        group.mpmLoose.delete(m);
        m.remove();
        return true;
      };
      proto.addLayers = function (layers, skip) {
        const rest = [];
        for (const m of layers) loose(m) ? putOnMap(this, m) : rest.push(m);
        return orig.addLayers.call(this, rest, skip);
      };
      proto.removeLayers = function (layers) {
        return orig.removeLayers.call(this, layers.filter((m) => !takeOff(this, m)));
      };
      proto.addLayer = function (m) {
        if (loose(m)) {
          putOnMap(this, m);
          return this;
        }
        return orig.addLayer.call(this, m);
      };
      proto.removeLayer = function (m) {
        return takeOff(this, m) ? this : orig.removeLayer.call(this, m);
      };
      proto.hasLayer = function (m) {
        return Boolean(this.mpmLoose?.has(m)) || orig.hasLayer.call(this, m);
      };
      this.register(() => {
        Object.assign(proto, orig);
        delete proto[PATCHED];
        for (const c of this.findMapContainers()) {
          const group = c.display.clusterGroup;
          const back = [...(group.mpmLoose || [])];
          delete group.mpmLoose;
          back.forEach((m) => m.remove());
          if (back.length) orig.addLayers.call(group, back);
        }
      });
    }
    this.clusterPatched = true;
    for (const c of containers) {
      const group = c.display.clusterGroup;
      const stuck = group.getLayers().filter((m) => String(m?.options?.icon?.options?.className || "").includes(NO_CLUSTER_CLASS));
      if (stuck.length) {
        proto[PATCHED].removeLayers.call(group, stuck);
        for (const m of stuck) {
          (group.mpmLoose ||= new Set()).add(m);
          m.addTo(c.display.map);
        }
      }
    }
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
