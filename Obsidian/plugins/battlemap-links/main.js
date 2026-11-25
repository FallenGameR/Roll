"use strict";

/*
  Батлмапы Excalidraw как пульт боя. Работает в режиме правки, одним
  кликом, без всплывающей ссылки Excalidraw.

  Токен. Клик по картинке-токену открывает статблок в панели Combatant
  трекера инициативы, как клик по бойцу в самом трекере. Кто на токене,
  плагин узнаёт по файлу картинки:
    - у существа бестиария или героя в статблоке есть "image" с путём к
      токену, по нему существо и находится; копия с номером "skeleton 2.webp"
      находит то же существо, что и "skeleton.webp";
    - токен именного NPC называется "<Имя> токен.png", и статблок берётся со
      страницы <Имя>: блок statblock с "monster: Багбир" даёт багбира,
      подписанного именем NPC.

  Значки. Картинка с customData.battlemap = { action, target } работает как
  кнопка:
    - action "encounter" находит в разделе target первый блок encounter (в
      том числе внутри каллаута "Бой") и жмёт его кнопку Start Encounter;
    - action "goto" открывает target, раздел комнаты в заметке локации.

  Ctrl при наведении на токен или значок показывает предпросмотр заметки
  существа или раздела комнаты, как Ctrl-наведение на ссылку.

  Клик отличается от перетаскивания по pointerDownState Excalidraw: если
  элемент сдвинули, это не клик. Shift, Ctrl и Alt оставляют клик
  Excalidraw: ими выделяют несколько элементов.

  Слои. Плагин держит порядок элементов на листе снизу вверх: заблокированная
  подложка, всё прочее (значки комнат, памятка, рисунки), токены бестиария,
  токены NPC, токены героев. Кто есть кто, видно по папке картинки. Герои
  между собой лежат по order из карточки (Adventure/Players/Characters, токен
  с карточкой связывает поле character): первый в отряде сверху. Порядок
  восстанавливается после каждого отпускания мыши и раз в пару секунд, так что
  вставленный или перетащенный токен сам уходит в свой слой.

  Excalidraw не правится: плагин подписывается на onPointerUp из его
  публичного API на каждом открытом листе.
*/

const {
  Plugin,
  Notice,
  Component,
  MarkdownRenderer,
  MarkdownView,
  TFile,
  parseLinktext,
  parseYaml,
  resolveSubpath,
} = require("obsidian");

const EXCALIDRAW_VIEW = "excalidraw";
const TRACKER = "initiative-tracker";
const START_SELECTOR = '[aria-label="Start Encounter"]';
const BUTTON_TIMEOUT = 8000;
const TOKEN_SUFFIX = / токен$/;
const NUMBER_SUFFIX = / \d+(\.[^./]+)$/;
const HOVER_SOURCE = "battlemap-links";
const HOVER_MARGIN = 24;
const HOVER_PENDING = 800;
const DOUBLE_CLICK_MS = 500;
const LAYER_DELAY_MS = 150;
const LAYER_FOLDERS = [
  ["_img/bestiary/", 2],
  ["_img/npc/tokens/", 3],
  ["_img/players/tokens/", 4],
];
const PARTY_FOLDER = "Adventure/Players/Characters/";

function sleep(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

/** Строки без префиксов цитаты и каллаута. */
function unquote(text) {
  return text
    .split("\n")
    .map((line) => line.replace(/^(\s*>\s?)+/, ""))
    .join("\n");
}

function findBlock(text, lang) {
  const blocks = findBlocks(text, lang);
  return blocks.length ? blocks[0] : null;
}

function findBlocks(text, lang) {
  const re = new RegExp("^```" + lang + "[ \\t]*\\n([\\s\\S]*?)^```", "gm");
  return [...unquote(text).matchAll(re)].map((m) => m[1]);
}

/** Путь картинки из статблока: "[[a.png]]", "![[a.png]]" или просто путь. */
function imagePath(value) {
  if (!value || typeof value !== "string") return "";
  const wiki = value.match(/\[\[([^\]|]+)/);
  return (wiki ? wiki[1] : value).trim();
}

module.exports = class BattlemapLinks extends Plugin {
  onload() {
    this.hookedApis = new WeakSet();
    this.hookedViews = new WeakSet();
    this.hoverKey = null;
    this.hoverAt = 0;
    this.lastMouse = null;
    this.registerDomEvent(window, "keydown", (e) => this.onKeyDown(e), true);
    this.registerHoverLinkSource(HOVER_SOURCE, { display: "Battlemap", defaultMod: true });
    this.disposers = [];
    this.busy = false;
    this.app.workspace.onLayoutReady(() => {
      this.hookAll();
      this.registerEvent(this.app.workspace.on("layout-change", () => this.hookAll()));
      this.registerEvent(this.app.workspace.on("active-leaf-change", () => this.hookAll()));
      this.registerEvent(this.app.workspace.on("file-open", () => this.hookAll()));
      // Лист подгружает сцену не сразу после открытия вкладки.
      this.registerInterval(
        window.setInterval(() => {
          this.hookAll();
          this.layerAll();
        }, 2000)
      );
    });
  }

  onunload() {
    for (const dispose of this.disposers) {
      try {
        dispose();
      } catch (e) {
        console.warn("Battlemap links: не удалось снять подписку", e);
      }
    }
    this.disposers = [];
  }

  hookAll() {
    for (const leaf of this.app.workspace.getLeavesOfType(EXCALIDRAW_VIEW)) {
      const view = leaf.view;
      const api = view ? view.excalidrawAPI : null;
      if (!api || typeof api.onPointerUp !== "function" || this.hookedApis.has(api)) continue;
      const dispose = api.onPointerUp((tool, state, event) => this.onPointerUp(view, tool, state, event));
      this.hookedApis.add(api);
      if (typeof dispose === "function") this.disposers.push(dispose);
      if (!this.hookedViews.has(view)) {
        this.hookedViews.add(view);
        this.registerDomEvent(view.contentEl, "mousemove", (e) => this.onHover(view, e));
        this.registerDomEvent(view.contentEl, "mouseleave", () => {
          this.hoverKey = null;
          this.lastMouse = null;
        });
      }
    }
  }

  // ---------- слои токенов ----------

  layerAll() {
    for (const leaf of this.app.workspace.getLeavesOfType(EXCALIDRAW_VIEW)) {
      try {
        this.layer(leaf.view);
      } catch (e) {
        console.warn("Battlemap links: не удалось разложить слои", e);
      }
    }
  }

  /**
   * Слой элемента: 0 подложка, 1 прочее, 2 бестиарий, 3 NPC, 4 и выше герои.
   * Герои между собой лежат по order из карточки: первый в отряде сверху.
   */
  layerOf(view, element, party) {
    if (element.locked) return 0;
    if (element.type !== "image") return 1;
    const file = this.imageFile(view, element);
    if (!file) return 1;
    for (const [folder, layer] of LAYER_FOLDERS) {
      if (!file.path.startsWith(folder)) continue;
      if (layer !== 4) return layer;
      const order = party.get(file.basename.replace(TOKEN_SUFFIX, ""));
      return 4 + (1000 - (order === undefined ? 999 : order)) / 1000;
    }
    return 1;
  }

  /** Имя героя (поле character карточки) -> его order в отряде. */
  partyOrder() {
    const party = new Map();
    for (const file of this.app.vault.getMarkdownFiles()) {
      if (!file.path.startsWith(PARTY_FOLDER)) continue;
      const fm = (this.app.metadataCache.getFileCache(file) || {}).frontmatter;
      if (!fm || fm.order === undefined) continue;
      const order = Number(fm.order);
      if (!Number.isFinite(order)) continue;
      party.set(String(fm.character || file.basename), order);
    }
    return party;
  }

  /** Переставляет элементы по слоям, сохраняя порядок внутри слоя. */
  layer(view) {
    const api = view ? view.excalidrawAPI : null;
    if (!api || typeof api.updateScene !== "function") return;
    const st = api.getAppState();
    // Пока мышь зажата или что-то редактируется, сцену не трогаем.
    if (!st || st.cursorButton === "down" || st.selectedElementsAreBeingDragged) return;
    if (st.editingTextElement || st.editingElement || st.resizingElement) return;
    if (st.newElement || st.multiElement || st.isCropping || st.croppingElementId) return;
    const all =
      typeof api.getSceneElementsIncludingDeleted === "function"
        ? api.getSceneElementsIncludingDeleted()
        : api.getSceneElements();
    if (!all || all.length < 2) return;
    const party = this.partyOrder();
    const ranked = all.map((element, i) => ({ element, i, layer: this.layerOf(view, element, party) }));
    let sorted = true;
    for (let k = 1; k < ranked.length; k++) {
      if (ranked[k].layer < ranked[k - 1].layer) {
        sorted = false;
        break;
      }
    }
    if (sorted) return;
    ranked.sort((a, b) => a.layer - b.layer || a.i - b.i);
    // Перестановка слоёв - не правка Мастера, в историю отмены её не пишем.
    api.updateScene({
      elements: ranked.map((r) => r.element),
      captureUpdate: "NEVER",
      storeAction: "update",
    });
  }

  // ---------- предпросмотр по Ctrl ----------

  /** Верхний элемент-картинка под курсором, кроме заблокированной подложки. */
  elementAt(view, event) {
    const api = view.excalidrawAPI;
    if (!api) return null;
    const st = api.getAppState();
    const zoom = st.zoom && st.zoom.value ? st.zoom.value : 1;
    const x = (event.clientX - st.offsetLeft) / zoom - st.scrollX;
    const y = (event.clientY - st.offsetTop) / zoom - st.scrollY;
    const elements = api.getSceneElements();
    for (let i = elements.length - 1; i >= 0; i--) {
      const e = elements[i];
      if (e.type !== "image" || e.locked || e.isDeleted) continue;
      if (x >= e.x && x <= e.x + e.width && y >= e.y && y <= e.y + e.height) return e;
    }
    return null;
  }

  /** Что показать в предпросмотре: раздел комнаты или заметку существа. */
  async previewTarget(view, element, sourcePath) {
    const data = element.customData && element.customData.battlemap;
    if (data && data.target) return String(data.target).replace(/^\[\[|\]\]$/g, "");
    const file = this.imageFile(view, element);
    if (!file) return null;
    const combatant = await this.combatantForImage(file, sourcePath);
    return combatant && combatant.path ? combatant.path : null;
  }

  /** Прямоугольник элемента на экране. */
  screenRect(view, element) {
    const st = view.excalidrawAPI.getAppState();
    const zoom = st.zoom && st.zoom.value ? st.zoom.value : 1;
    const left = (element.x + st.scrollX) * zoom + st.offsetLeft;
    const top = (element.y + st.scrollY) * zoom + st.offsetTop;
    return { left, top, right: left + element.width * zoom, bottom: top + element.height * zoom };
  }

  /**
   * targetEl предпросмотра - сам лист: он под курсором всё время, поэтому
   * Обсидиан окно не закрывает, а ставит его у курсора, раз лист высокий.
   * Закрывает окно плагин, когда курсор отошёл от элемента дальше чем на
   * HOVER_MARGIN; на само окно курсор уходит свободно, оно вне листа.
   */
  onHover(view, event) {
    this.lastMouse = { view, x: event.clientX, y: event.clientY };
    this.trackPopover(view, event);
    if (!(event.ctrlKey || event.metaKey)) {
      this.hoverKey = null;
      return;
    }
    const element = this.elementAt(view, event);
    if (!element) {
      this.hoverKey = null;
      return;
    }
    // Тот же элемент не открываем повторно, пока окно открыто или вот-вот
    // откроется; закрылось само - откроем снова.
    const shown = view.hoverPopover && view.hoverPopover.state !== 3;
    const fresh = Date.now() - this.hoverAt < HOVER_PENDING;
    if (this.hoverKey === element.id && (shown || fresh)) return;
    this.hoverKey = element.id;
    this.hoverAt = Date.now();
    const sourcePath = view.file ? view.file.path : "";
    this.previewTarget(view, element, sourcePath)
      .then((linktext) => {
        if (!linktext || this.hoverKey !== element.id) return;
        this.popover = { view, rect: this.screenRect(view, element) };
        this.app.workspace.trigger("hover-link", {
          event,
          source: HOVER_SOURCE,
          hoverParent: view,
          targetEl: view.contentEl,
          linktext,
          sourcePath,
        });
      })
      .catch((e) => console.error("Battlemap links", e));
  }

  /** Ctrl нажали, когда курсор уже стоит на токене: мышь не двигалась. */
  onKeyDown(event) {
    if (event.key !== "Control" && event.key !== "Meta") return;
    if (event.repeat) return;
    const last = this.lastMouse;
    if (!last || !last.view.contentEl.isConnected) return;
    const r = last.view.contentEl.getBoundingClientRect();
    if (last.x < r.left || last.x > r.right || last.y < r.top || last.y > r.bottom) return;
    const synthetic = new MouseEvent("mousemove", {
      clientX: last.x,
      clientY: last.y,
      ctrlKey: event.key === "Control",
      metaKey: event.key === "Meta",
    });
    this.onHover(last.view, synthetic);
  }

  trackPopover(view, event) {
    const active = this.popover;
    if (!active || active.view !== view) return;
    const r = active.rect;
    const m = HOVER_MARGIN;
    const inside =
      event.clientX >= r.left - m &&
      event.clientX <= r.right + m &&
      event.clientY >= r.top - m &&
      event.clientY <= r.bottom + m;
    if (inside) return;
    this.popover = null;
    this.hoverKey = null;
    const popover = view.hoverPopover;
    if (!popover) return;
    try {
      popover.hide();
    } catch (e) {
      console.warn("Battlemap links: окно предпросмотра не закрылось", e);
    }
  }

  onPointerUp(view, tool, state, event) {
    window.setTimeout(() => {
      try {
        this.layer(view);
      } catch (e) {
        console.warn("Battlemap links: не удалось разложить слои", e);
      }
    }, LAYER_DELAY_MS);
    try {
      if (!state || !event) return;
      if (event.button !== undefined && event.button !== 0) return;
      if (event.shiftKey || event.ctrlKey || event.metaKey || event.altKey) return;
      if (tool && tool.type && tool.type !== "selection") return;
      if (state.drag && state.drag.hasOccurred) return;
      if (state.resize && state.resize.handleType) return;
      const hit = state.hit || {};
      const element = hit.element;
      if (!element || element.isDeleted || element.type !== "image") return;
      // Мечи начинают бой только двойным щелчком: случайный щелчок посреди
      // сессии не должен сбрасывать идущий бой.
      const data = element.customData && element.customData.battlemap;
      if (data && data.action === "encounter") {
        const last = this.lastEncounterClick;
        const now = Date.now();
        if (!last || last.id !== element.id || now - last.at > DOUBLE_CLICK_MS) {
          this.lastEncounterClick = { id: element.id, at: now };
          return;
        }
        this.lastEncounterClick = null;
        // Двойной щелчок по картинке Excalidraw открывает обрезку; закрываем её.
        window.setTimeout(() => {
          try {
            const api = view.excalidrawAPI;
            const st = api && api.getAppState();
            if (st && (st.isCropping || st.croppingElementId)) {
              api.updateScene({ appState: { isCropping: false, croppingElementId: null } });
            }
          } catch (e) {
            console.warn("Battlemap links: не удалось закрыть обрезку", e);
          }
        }, 50);
      }
      this.act(view, element).catch((e) => {
        console.error("Battlemap links", e);
        new Notice("Battlemap: не получилось, подробности в консоли");
      });
    } catch (e) {
      console.error("Battlemap links", e);
    }
  }

  async act(view, element) {
    if (this.busy) return;
    this.busy = true;
    try {
      const sourcePath = view.file ? view.file.path : "";
      const data = element.customData && element.customData.battlemap;
      if (data && data.target) {
        if (data.action === "encounter") await this.startEncounterAt(data.target, sourcePath, data.encounter);
        else await this.goto(data.target, sourcePath);
        return;
      }
      const file = this.imageFile(view, element);
      if (!file) return;
      const combatant = await this.combatantForImage(file, sourcePath);
      if (combatant) await this.openCombatant(combatant);
    } finally {
      window.setTimeout(() => (this.busy = false), 300);
    }
  }

  imageFile(view, element) {
    const data = view.excalidrawData;
    const files = data && data.files;
    const embedded = files && typeof files.get === "function" ? files.get(element.fileId) : null;
    const file = embedded ? embedded.file : null;
    return file instanceof TFile ? file : null;
  }

  // ---------- токены ----------

  async combatantForImage(file, sourcePath) {
    const fs = window.FantasyStatblocks;
    if (!fs || typeof fs.getBestiaryCreatures !== "function") return null;

    // Нумерованная копия токена "skeleton 2.webp" ведёт к тому же существу,
    // что и "skeleton.webp": номер нужен только глазам, как в трекере.
    const unnumbered = file.path.replace(NUMBER_SUFFIX, "$1");
    const creatures = fs.getBestiaryCreatures();
    const byImage =
      creatures.find((c) => c && imagePath(c.image) === file.path) ||
      (unnumbered !== file.path ? creatures.find((c) => c && imagePath(c.image) === unnumbered) : null);
    if (byImage) return this.combatant(byImage, byImage.name, byImage.path || file.path);

    const name = file.basename.replace(TOKEN_SUFFIX, "");
    if (name === file.basename) return null;
    const note = this.app.metadataCache.getFirstLinkpathDest(name, sourcePath);
    if (!(note instanceof TFile) || note.extension !== "md") return null;
    return this.combatantForNote(note);
  }

  async combatantForNote(note) {
    const fs = window.FantasyStatblocks;
    const own = fs.getBestiaryCreatures().find((c) => c && c.path === note.path);
    if (own) return this.combatant(own, own.name, note.path);

    const block = findBlock(await this.app.vault.cachedRead(note), "statblock");
    if (!block) return null;
    let params;
    try {
      params = parseYaml(block);
    } catch (e) {
      return null;
    }
    if (!params || typeof params !== "object") return null;
    const base = params.monster || params.creature || params.name;
    let fromBestiary = null;
    try {
      fromBestiary = base && fs.hasCreature(base) ? fs.getCreatureFromBestiary(base) : null;
    } catch (e) {
      new Notice("Battlemap: бестиарий ещё загружается, попробуйте через секунду");
      return null;
    }
    if (!fromBestiary && !params.name) return null;
    const creature = Object.assign({}, fromBestiary || {}, params);
    delete creature.monster;
    delete creature.creature;
    if (fromBestiary) creature.name = fromBestiary.name;
    return this.combatant(creature, params.name || note.basename, note.path);
  }

  combatant(creature, display, path) {
    return {
      id: "battlemap:" + path,
      path: path,
      name: display,
      display: display,
      creature: creature,
      getName() {
        return display;
      },
    };
  }

  async openCombatant(combatant) {
    const tracker = this.app.plugins.plugins[TRACKER];
    if (!tracker || typeof tracker.openCombatant !== "function") {
      new Notice("Battlemap: Initiative Tracker не найден");
      return;
    }
    await tracker.openCombatant(combatant, false);
  }

  // ---------- значки ----------

  resolve(target, sourcePath) {
    const { path, subpath } = parseLinktext(String(target).replace(/^\[\[|\]\]$/g, ""));
    const file = this.app.metadataCache.getFirstLinkpathDest(path, sourcePath);
    if (!(file instanceof TFile)) {
      new Notice("Battlemap: не найдена заметка " + path);
      return null;
    }
    return { file, subpath };
  }

  async startEncounterAt(target, sourcePath, wanted) {
    const found = this.resolve(target, sourcePath);
    if (!found) return;
    const { file, subpath } = found;
    const text = await this.app.vault.cachedRead(file);
    const cache = this.app.metadataCache.getFileCache(file);
    const range = subpath && cache ? resolveSubpath(cache, subpath) : null;
    const section = range
      ? text.slice(range.start.offset, range.end ? range.end.offset : undefined)
      : text;
    const blocks = findBlocks(section, "encounter");
    // Бой комнаты стоит в конце её раздела; блоки выше - побочные сцены
    // вроде паука у сундука. Имя боя в customData значка перебивает это.
    const byName = wanted
      ? blocks.find((b) => {
          const m = b.match(/^name:\s*(.+)$/m);
          return m && m[1].trim() === wanted;
        })
      : null;
    const source = byName || blocks[blocks.length - 1];
    if (!source) {
      new Notice("Battlemap: в " + target + " нет блока encounter");
      return;
    }
    await this.startEncounter(source, file.path);
  }

  /**
   * Рисует блок encounter вне экрана силами самого трекера и жмёт его
   * кнопку Start Encounter: бой собирается тем же кодом, что и из заметки.
   */
  async startEncounter(source, sourcePath) {
    const host = document.createElement("div");
    const component = new Component();
    component.load();
    try {
      await MarkdownRenderer.render(this.app, "```encounter\n" + source + "```\n", host, sourcePath, component);
      const deadline = Date.now() + BUTTON_TIMEOUT;
      let button = host.querySelector(START_SELECTOR);
      while (!button && Date.now() < deadline) {
        await sleep(100);
        button = host.querySelector(START_SELECTOR);
      }
      if (!button) {
        new Notice("Battlemap: блок encounter не отрисовался, бой не начат");
        return;
      }
      button.click();
      await sleep(1500);
    } finally {
      component.unload();
    }
  }

  /**
   * Открывает раздел комнаты: в уже открытой вкладке заметки или в новой.
   * openLinkText со ссылкой на заголовок выделяет весь раздел, поэтому файл
   * открывается без подпути, а к строке заголовка плагин прокручивает сам.
   */
  async goto(target, sourcePath) {
    const found = this.resolve(target, sourcePath);
    if (!found) return;
    const { file, subpath } = found;
    const cache = this.app.metadataCache.getFileCache(file);
    const range = subpath && cache ? resolveSubpath(cache, subpath) : null;
    const line = range && range.start ? range.start.line : 0;

    let leaf = null;
    this.app.workspace.iterateAllLeaves((l) => {
      if (!leaf && l.view instanceof MarkdownView && l.view.file && l.view.file.path === file.path) leaf = l;
    });
    if (!leaf) {
      leaf = this.app.workspace.getLeaf("tab");
      await leaf.openFile(file);
    }
    this.app.workspace.setActiveLeaf(leaf, { focus: true });
    await sleep(50);
    const view = leaf.view;
    if (!(view instanceof MarkdownView)) return;
    if (view.getMode() === "source") {
      const editor = view.editor;
      const pos = { line, ch: 0 };
      editor.setCursor(pos);
      editor.scrollIntoView({ from: pos, to: pos }, true);
      editor.focus();
    } else {
      view.setEphemeralState({ line });
    }
  }
};
