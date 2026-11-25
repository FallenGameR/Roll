"use strict";

/*
  Чипы «кому понравилось» для свойства favorites.

  В тексте заметки пишется строчный код `FAVORITES`, и в режиме чтения,
  во всплывающем предпросмотре и в попапе карты он превращается в ряд
  чипов с именами. Выбранные чипы золотые. Клик добавляет имя в
  favorites или убирает его оттуда.

  Meta Bind тут не годится: его multiSelect бывает только блоком и в
  одну строку со ссылкой и звёздами не встаёт.

  Имена, которых нет в PEOPLE, но которые уже стоят в favorites, тоже
  показываются чипами и тоже снимаются кликом: чужое не теряется молча.

  В Live Preview код заменяется тем же рядом чипов через расширение
  редактора; когда курсор заходит на код, виден исходный текст.

  Второй код, `VISITED`, рисует один чип «✓ Были»: клик ставит в шапку
  visited: true или убирает его.
*/

const { Plugin, editorInfoField, editorLivePreviewField } = require("obsidian");
const { ViewPlugin, Decoration, WidgetType } = require("@codemirror/view");

const MARKER = "FAVORITES";
const VISITED = "VISITED";
const PEOPLE = ["Саша", "Нина", "Матвей", "Лиза"];
const SOURCE = new RegExp("`(" + MARKER + "|" + VISITED + ")`", "g");

class ChipsWidget extends WidgetType {
  constructor(plugin, path, kind) {
    super();
    this.plugin = plugin;
    this.path = path;
    this.kind = kind;
  }

  eq(other) {
    return other.path === this.path && other.kind === this.kind;
  }

  toDOM() {
    return this.plugin.mount(null, this.path, this.kind);
  }

  ignoreEvent() {
    return true;
  }
}

module.exports = class FavoriteChips extends Plugin {
  onload() {
    this.rows = new Set();

    this.registerMarkdownPostProcessor((el, ctx) => {
      for (const code of el.querySelectorAll("code")) {
        const text = code.innerText.trim();
        if ((text !== MARKER && text !== VISITED) || code.closest("pre")) continue;
        this.mount(code, ctx.sourcePath, text);
      }
    });

    this.registerEditorExtension(this.livePreview());

    this.registerEvent(
      this.app.metadataCache.on("changed", (file) => {
        for (const row of this.rows) {
          if (!row.el.isConnected) this.rows.delete(row);
          else if (row.path === file.path) this.paint(row);
        }
      })
    );
  }

  livePreview() {
    const plugin = this;
    const build = (view) => {
      if (!view.state.field(editorLivePreviewField, false)) return Decoration.none;
      const path = view.state.field(editorInfoField, false)?.file?.path;
      if (!path) return Decoration.none;
      const ranges = [];
      const selection = view.state.selection.ranges;
      for (const { from, to } of view.visibleRanges) {
        const text = view.state.doc.sliceString(from, to);
        for (const m of text.matchAll(SOURCE)) {
          const start = from + m.index;
          const end = start + m[0].length;
          if (selection.some((r) => r.from <= end && r.to >= start)) continue;
          ranges.push(Decoration.replace({ widget: new ChipsWidget(plugin, path, m[1]) }).range(start, end));
        }
      }
      return Decoration.set(ranges, true);
    };
    return ViewPlugin.fromClass(
      class {
        constructor(view) {
          this.decorations = build(view);
        }
        update(u) {
          const modeChanged = u.startState.field(editorLivePreviewField, false) !== u.state.field(editorLivePreviewField, false);
          if (u.docChanged || u.viewportChanged || u.selectionSet || modeChanged) this.decorations = build(u.view);
        }
      },
      { decorations: (v) => v.decorations }
    );
  }

  mount(code, path, kind = MARKER) {
    const el = createSpan({ cls: "favorite-chips" });
    const row = { el, path, kind };
    if (code) code.replaceWith(el);
    this.rows.add(row);
    this.paint(row);
    return el;
  }

  current(path) {
    const file = this.app.vault.getAbstractFileByPath(path);
    const value = file && this.app.metadataCache.getFileCache(file)?.frontmatter?.favorites;
    if (Array.isArray(value)) return value.map(String);
    return value ? [String(value)] : [];
  }

  paint(row) {
    if (row.kind === VISITED) return this.paintVisited(row);
    const chosen = this.current(row.path);
    const names = [...PEOPLE, ...chosen.filter((n) => !PEOPLE.includes(n))];
    row.el.empty();
    for (const name of names) {
      const chip = row.el.createSpan({ cls: "favorite-chip", text: name });
      chip.toggleClass("is-chosen", chosen.includes(name));
      chip.setAttr("aria-label", chosen.includes(name) ? `${name}: нравится` : name);
      chip.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        this.toggle(row, name);
      });
    }
  }

  paintVisited(row) {
    const file = this.app.vault.getAbstractFileByPath(row.path);
    const visited = Boolean(file) && this.app.metadataCache.getFileCache(file)?.frontmatter?.visited === true;
    row.el.empty();
    const chip = row.el.createSpan({ cls: "favorite-chip visited-chip", text: "✓ Были" });
    chip.toggleClass("is-chosen", visited);
    chip.addEventListener("click", async (e) => {
      e.preventDefault();
      e.stopPropagation();
      if (!file) return;
      await this.app.fileManager.processFrontMatter(file, (fm) => {
        if (fm.visited === true) delete fm.visited;
        else fm.visited = true;
      });
    });
  }

  async toggle(row, name) {
    const file = this.app.vault.getAbstractFileByPath(row.path);
    if (!file) return;
    await this.app.fileManager.processFrontMatter(file, (fm) => {
      const list = Array.isArray(fm.favorites) ? fm.favorites.map(String) : fm.favorites ? [String(fm.favorites)] : [];
      const next = list.includes(name) ? list.filter((n) => n !== name) : [...list, name];
      const known = PEOPLE.filter((n) => next.includes(n));
      fm.favorites = [...known, ...next.filter((n) => !PEOPLE.includes(n))];
    });
  }
};
