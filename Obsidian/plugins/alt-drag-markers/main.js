const { Plugin, Notice } = require('obsidian');

module.exports = class AltDragMarkers extends Plugin {
  onload() {
    this.enabled = false;
    this.dragging = 0;
    this.active = new Set(); // leaflet markers with dragging enabled

    this.registerDomEvent(window, 'keydown', (e) => {
      if (e.key === 'Alt' && !this.enabled) { e.preventDefault(); this.enable(); }
    }, true);
    this.registerDomEvent(window, 'keyup', (e) => {
      if (e.key === 'Alt') { e.preventDefault(); this.enabled = false; if (!this.dragging) this.disableAll(); }
    }, true);
    this.registerDomEvent(window, 'blur', () => { this.enabled = false; if (!this.dragging) this.disableAll(); });
  }

  onunload() { this.disableAll(); }

  // Find all Map View "MapContainer" objects reachable from open leaves (map views, bases views, embedded bases).
  findMapContainers() {
    const found = new Set();
    const seen = new WeakSet();
    const visit = (obj, depth) => {
      if (!obj || typeof obj !== 'object' || seen.has(obj) || depth > 10) return;
      seen.add(obj);
      if (obj.display && obj.display.map && obj.display.layers && obj.mapContainerId !== undefined) { found.add(obj); return; }
      if (obj.mapContainer) visit(obj.mapContainer, depth + 1);
      if (obj.controller) visit(obj.controller, depth + 1);
      if (obj.view && obj.view !== obj) visit(obj.view, depth + 1);
      if (Array.isArray(obj._children)) for (const c of obj._children) visit(c, depth + 1);
    };
    this.app.workspace.iterateAllLeaves((leaf) => visit(leaf.view, 0));
    return [...found];
  }

  enable() {
    this.enabled = true;
    for (const mc of this.findMapContainers()) {
      const layers = mc.display.layers && (mc.display.layers.layers || mc.display.layers);
      if (!layers) continue;
      for (const layer of layers) {
        if (!layer || !layer.file || !layer.geoLayers) continue;
        const marker = layer.geoLayers.get(mc.mapContainerId);
        if (!marker || !marker.dragging || !marker._icon) continue; // only individually visible markers (not inside clusters)
        if (!marker._altDragHooked) {
          marker._altDragHooked = true;
          marker.on('dragstart', () => { this.dragging++; });
          marker.on('dragend', async () => {
            this.dragging = Math.max(0, this.dragging - 1);
            const ll = marker.getLatLng();
            await this.saveLocation(mc, layer, ll);
            if (!this.enabled && !this.dragging) this.disableAll();
          });
        }
        marker.dragging.enable();
        if (marker._icon) marker._icon.classList.add('alt-drag-ready');
        this.active.add(marker);
      }
    }
  }

  disableAll() {
    for (const m of this.active) {
      try { m.dragging && m.dragging.disable(); if (m._icon) m._icon.classList.remove('alt-drag-ready'); } catch (e) { /* ignore */ }
    }
    this.active.clear();
  }

  async saveLocation(mc, layer, ll) {
    const key = (mc.settings && mc.settings.frontMatterKey) || 'location';
    const lat = Math.round(ll.lat * 1e6) / 1e6, lng = Math.round(ll.lng * 1e6) / 1e6;
    const file = layer.file;
    const fm = this.app.metadataCache.getFileCache(file)?.frontmatter;
    if (!fm || fm[key] === undefined) {
      new Notice(`Alt-drag: ${file.basename} has no '${key}' front matter; not moved.`);
      return;
    }
    await this.app.fileManager.processFrontMatter(file, (f) => { f[key] = `${lat},${lng}`; });
    new Notice(`📍 ${file.basename}: ${lat}, ${lng}`);
  }
};
