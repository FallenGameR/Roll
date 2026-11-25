"use strict";

/*
  Ссылка на заметку монстра внутри статблока.

  Панель Initiative Tracker рисует статблок тем же движком Fantasy Statblocks,
  что и страница, поэтому отдельного места для ссылки там нет: всё, что видно
  в карточке, приходит из макета. Плагин дописывает в макеты один блок типа
  property - он зовёт callback и отдаёт вики-ссылку. Ссылки внутри статблока
  Обсидиан рисует сам, если включена настройка "Try to render links".

  Куда ведёт ссылка: монстры, разобранные из заметок, носят поле path - полный
  путь к файлу. Если его нет (монстр из встроенного бестиария), берётся имя:
  файлы в DnD Rules/Bestiary названы именем монстра.

  Макеты правятся в памяти, data.json плагина не трогается. Блок помечен
  постоянным id, поэтому при повторной загрузке не задваивается, а при
  выгрузке убирается.
*/

const { Plugin } = require("obsidian");

const STATBLOCKS = "obsidian-5e-statblocks";
const BLOCK_ID = "note-link-block";

const BLOCK = {
  type: "property",
  id: BLOCK_ID,
  properties: ["name"],
  fallback: "",
  display: "",
  conditioned: true,
  hasRule: false,
  markdown: true,
  cls: "note-link",
  callback: [
    "const target = monster.path || monster.name;",
    'if (!target) return "";',
    "return `Карточка [[${target}|${monster.name}]]`;",
  ].join("\n"),
};

module.exports = class StatblockNoteLink extends Plugin {
  onload() {
    this.app.workspace.onLayoutReady(() => this.inject());
  }

  onunload() {
    for (const layout of this.layouts()) {
      const at = layout.blocks.findIndex((b) => b.id === BLOCK_ID);
      if (at !== -1) layout.blocks.splice(at, 1);
    }
  }

  layouts() {
    const statblocks = this.app.plugins.plugins[STATBLOCKS];
    const manager = statblocks && statblocks.manager;
    if (!manager || !manager.getAllLayouts) return [];
    const all = manager.getAllLayouts() || [];
    const fallback = manager.getDefaultLayout ? [manager.getDefaultLayout()] : [];
    const seen = new Set();
    return [...all, ...fallback].filter((layout) => {
      if (!layout || !Array.isArray(layout.blocks) || seen.has(layout.id)) return false;
      seen.add(layout.id);
      return true;
    });
  }

  inject() {
    let count = 0;
    for (const layout of this.layouts()) {
      if (layout.blocks.some((b) => b.id === BLOCK_ID)) continue;
      layout.blocks.push(Object.assign({}, BLOCK));
      count++;
    }
    if (!count) console.debug("Statblock note link: макеты не найдены или блок уже стоит");
  }
};
