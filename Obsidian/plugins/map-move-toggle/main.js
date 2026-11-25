"use strict";

/*
  Режим перемещения маркеров на карте Map View.

  Под кнопками справа (+/−, поиск и т.д.) добавляется переключатель.
  Включён - кнопка светится, маркеры подсвечены, и любой отдельный маркер
  можно тащить пальцем или мышью. Отпустил - новые координаты пишутся в
  свойство location заметки. Выключен - карта ведёт себя как обычно.

  Режим свой у каждой карты и не запоминается: открыл карту заново -
  он выключен, чтобы случайно ничего не уехало.

  Map View пересоздаёт маркер, когда меняется его место, и пересоздаёт
  саму карту при обновлении. Поэтому плагин подменяет у карты
  newLeafletMarker (новые маркеры тоже становятся перетаскиваемыми) и
  createMap (кнопка возвращается на новую карту).
*/

const { Plugin, Notice, setIcon } = require("obsidian");
const LIGHT_KEY = "mmt-light-map";

const PATCHED = Symbol("map-move-toggle");
const ON = Symbol("map-move-toggle-on");

// Силуэт маркера карты, вокруг четыре стрелки: «двигать маркер».
// Капля занимает y 6.5..17.5 и x 8..16, то есть её рамка ровно в центре 24x24.
const ICON =
  '<svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
  '<path d="M12 17.5C10.5 16 8 13.6 8 10.5a4 4 0 0 1 8 0c0 3.1-2.5 5.5-4 7z" fill="currentColor" stroke="none"/>' +
  '<circle cx="12" cy="10.5" r="1.5" fill="var(--mmt-hole, #fff)" stroke="none"/>' +
  '<path d="M9.5 4 12 1.5 14.5 4M9.5 20 12 22.5 14.5 20M4 9.5 1.5 12 4 14.5M20 9.5 22.5 12 20 14.5"/>' +
  "</svg>";

module.exports = class MapMoveToggle extends Plugin {
  onload() {
    this.app.workspace.onLayoutReady(() => this.patch());

    // Alt-плагин на отпускание Alt выключает перетаскивание у всех маркеров.
    this.registerDomEvent(window, "keyup", (e) => {
      if (e.key === "Alt") window.setTimeout(() => this.reapplyAll(), 0);
    });
  }

  patch() {
    const mapView = this.app.plugins.plugins["obsidian-map-view"];
    if (!mapView) return;
    const plugin = this;

    const patchProto = (container) => {
      const proto = container && Object.getPrototypeOf(container);
      if (!proto || proto[PATCHED] || typeof proto.createMap !== "function") return;
      const { createMap, newLeafletMarker, showMarkerPopups } = proto;
      proto[PATCHED] = true;
      proto.createMap = async function (...args) {
        const result = await createMap.apply(this, args);
        plugin.addButton(this);
        return result;
      };
      proto.newLeafletMarker = function (marker) {
        const leafletMarker = newLeafletMarker.call(this, marker);
        plugin.hookMarker(this, marker, leafletMarker);
        return leafletMarker;
      };
      // Пока включён режим перемещения или маркер тащат (в том числе с Alt), попап не нужен: он закрывает карту.
      proto.showMarkerPopups = function (...args) {
        if (this[ON] || this._mmtDragging) return;
        return showMarkerPopups.apply(this, args);
      };
      this.register(() => {
        proto.createMap = createMap;
        proto.newLeafletMarker = newLeafletMarker;
        proto.showMarkerPopups = showMarkerPopups;
        delete proto[PATCHED];
      });
    };

    const register = mapView.registerMapContainer;
    mapView.registerMapContainer = function (container) {
      patchProto(container);
      return register.apply(this, arguments);
    };
    this.register(() => {
      mapView.registerMapContainer = register;
    });

    for (const container of mapView.allMapContainers || []) {
      patchProto(container);
      this.addButton(container);
      for (const layer of container.display?.layers?.layers || []) {
        const leafletMarker = layer.geoLayers?.get(container.mapContainerId);
        if (leafletMarker && layer.layerType === "fileMarker") this.hookMarker(container, layer, leafletMarker);
      }
    }
  }

  addButton(container) {
    const map = container.display?.map;
    const corner = map && map.getContainer().querySelector(".leaflet-top.leaflet-right");
    if (!corner || corner.querySelector(".mmt-control")) return;

    const bar = corner.createDiv({ cls: "leaflet-bar leaflet-control mmt-control" });
    const button = bar.createEl("a", { cls: "mmt-button", href: "#" });
    button.innerHTML = ICON;
    for (const type of ["mousedown", "touchstart", "pointerdown", "dblclick", "contextmenu", "wheel"]) {
      button.addEventListener(type, (e) => e.stopPropagation());
    }
    button.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      this.setMode(container, !container[ON]);
    });
    container._mmtButton = button;
    this.paintButton(container);
    this.register(() => bar.remove());
    this.addLightButton(container, corner);
  }

  /*
    Светлая карта при тёмной теме. Map View в тёмной теме не берёт другие
    тайлы, а перекрашивает светлые CSS-фильтром на слое с классом dark-mode.
    Кнопка снимает этот фильтр классом на контейнере карты, без пересборки
    карты. Выбор общий для всех карт и запоминается в localStorage.
  */
  addLightButton(container, corner) {
    const bar = corner.createDiv({ cls: "leaflet-bar leaflet-control mmt-light-control" });
    const button = bar.createEl("a", { cls: "mmt-button mmt-light-button", href: "#" });
    for (const type of ["mousedown", "touchstart", "pointerdown", "dblclick", "contextmenu", "wheel"]) {
      button.addEventListener(type, (e) => e.stopPropagation());
    }
    button.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      window.localStorage.setItem(LIGHT_KEY, this.isLight() ? "0" : "1");
      this.paintLightAll();
    });
    container._mmtLightButton = button;
    this.paintLight(container);
    this.register(() => bar.remove());
  }

  isLight() {
    return window.localStorage.getItem(LIGHT_KEY) === "1";
  }

  paintLight(container) {
    const light = this.isLight();
    container.display?.map?.getContainer().toggleClass("mmt-light", light);
    const button = container._mmtLightButton;
    if (!button) return;
    setIcon(button, light ? "moon" : "sun");
    const label = light ? "Карта как в тёмной теме" : "Светлая карта";
    button.setAttr("aria-label", label);
    button.setAttr("title", label);
  }

  paintLightAll() {
    const mapView = this.app.plugins.plugins["obsidian-map-view"];
    for (const container of mapView?.allMapContainers || []) this.paintLight(container);
  }

  paintButton(container) {
    const button = container._mmtButton;
    if (!button) return;
    button.toggleClass("is-on", Boolean(container[ON]));
    button.setAttr("aria-label", container[ON] ? "Перемещение маркеров включено" : "Перемещать маркеры");
    button.setAttr("title", container[ON] ? "Перемещение маркеров включено" : "Перемещать маркеры");
    container.display?.map?.getContainer().toggleClass("mmt-on", Boolean(container[ON]));
  }

  setMode(container, on) {
    container[ON] = on;
    if (on) container.closeMarkerPopup?.(true);
    this.paintButton(container);
    this.applyTo(container);
  }

  applyTo(container) {
    for (const layer of container.display?.layers?.layers || []) {
      const leafletMarker = layer.geoLayers?.get(container.mapContainerId);
      if (leafletMarker) this.syncDragging(container, leafletMarker);
    }
  }

  reapplyAll() {
    const mapView = this.app.plugins.plugins["obsidian-map-view"];
    for (const container of mapView?.allMapContainers || []) if (container[ON]) this.applyTo(container);
  }

  hookMarker(container, layer, leafletMarker) {
    if (leafletMarker._mmtHooked || !layer.file) return;
    leafletMarker._mmtHooked = true;
    leafletMarker.on("add", () => this.syncDragging(container, leafletMarker));
    leafletMarker.on("dragstart", () => {
      container._mmtDragging = true;
      container.closeMarkerPopup?.(true);
    });
    leafletMarker.on("dragend", () => {
      container._mmtDragging = false;
      if (container[ON]) this.save(layer, leafletMarker.getLatLng());
    });
  }

  syncDragging(container, leafletMarker) {
    const drag = leafletMarker.dragging;
    if (!drag || !leafletMarker._icon) return;
    if (container[ON]) drag.enable();
    else drag.disable();
  }

  async save(layer, latLng) {
    const mapView = this.app.plugins.plugins["obsidian-map-view"];
    const key = mapView?.settings?.frontMatterKey || "location";
    const file = layer.file;
    const fm = this.app.metadataCache.getFileCache(file)?.frontmatter;
    if (!fm || fm[key] === undefined) {
      new Notice(`${file.basename}: в шапке нет ${key}, маркер не сдвинут.`);
      return;
    }
    const lat = Math.round(latLng.lat * 1e6) / 1e6;
    const lng = Math.round(latLng.lng * 1e6) / 1e6;
    await this.app.fileManager.processFrontMatter(file, (f) => {
      f[key] = `${lat},${lng}`;
    });
    new Notice(`📍 ${file.basename}: ${lat}, ${lng}`);
  }

  onunload() {
    const mapView = this.app.plugins.plugins["obsidian-map-view"];
    for (const container of mapView?.allMapContainers || []) {
      if (!container[ON]) continue;
      container[ON] = false;
      this.applyTo(container);
      container.display?.map?.getContainer().removeClass("mmt-on");
    }
  }
};
