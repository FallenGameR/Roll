"use strict";

/*
  Свойства всегда свёрнуты.

  Обсидиан решает, свернуть шапку или нет, по глобальному флагу, который
  переписывается каждый раз, когда шапку руками свернули или развернули. Флаг
  живёт на внутреннем классе и через публичное API не доступен, поэтому плагин
  работает по DOM: появившийся блок свойств сворачивается один раз, добавлением
  класса is-collapsed, ровно того, что вешает сама кнопка.

  Один раз - принципиально: развернул руками, обратно плагин не схлопнет.
  Обработанный блок помечается data-атрибутом и больше не трогается.

  Боковая панель File properties не затрагивается: её блок свойств лежит в
  листе с data-type="file-properties" и из выборки исключён.
*/

const { Plugin, MarkdownView } = require("obsidian");

const DONE = "foldedOnce";
const SKIP = '.workspace-leaf-content[data-type="file-properties"]';

module.exports = class FoldPropertiesAlways extends Plugin {
  onload() {
    this.app.workspace.onLayoutReady(() => {
      this.foldExisting();
      this.watch();
    });

    this.registerEvent(this.app.workspace.on("file-open", () => this.foldExisting()));
    this.registerEvent(this.app.workspace.on("active-leaf-change", () => this.foldExisting()));

    this.addCommand({
      id: "fold-properties-now",
      name: "Свернуть свойства везде",
      callback: () => this.foldExisting(true),
    });
  }

  watch() {
    this.observer = new MutationObserver((records) => {
      for (const record of records) {
        for (const node of record.addedNodes) {
          if (!(node instanceof HTMLElement)) continue;
          if (node.classList.contains("metadata-container")) this.fold(node);
          node.querySelectorAll(".metadata-container").forEach((el) => this.fold(el));
        }
      }
    });
    this.observer.observe(document.body, { childList: true, subtree: true });
    this.register(() => this.observer.disconnect());
  }

  foldExisting(force = false) {
    document.querySelectorAll(".metadata-container").forEach((el) => this.fold(el, force));
    this.app.workspace.iterateAllLeaves((leaf) => {
      const view = leaf && leaf.view;
      const editor = view instanceof MarkdownView ? view.metadataEditor : null;
      if (editor && editor.setCollapse && (force || !editor.collapsed)) {
        editor.setCollapse(true, false);
      }
    });
    this.foldActiveEditor();
  }

  /*
    Когда свойства показываются как исходный YAML (настройка вольта
    "Properties in document" = Source), виджета нет, и сворачивать надо складку
    редактора с первой строки.

    Тоглом это делать нельзя. После file-open Обсидиан сам накатывает на файл
    сохранённое состояние складок, и делает это позже нашего обработчика: шапка,
    свёрнутая сразу по событию, через мгновение разворачивается обратно. Поэтому
    складка ставится не переключением, а заданием нужного состояния, и попытка
    повторяется несколько раз, пока редактор не покажет шапку свёрнутой.

    Окно попыток короткое (полсекунды от открытия файла): развернул руками -
    плагин уже молчит и обратно не схлопывает.
  */
  foldActiveEditor(attempt = 0) {
    const view = this.app.workspace.getActiveViewOfType(MarkdownView);
    const file = view && view.file;
    if (!file) return;
    if (this.foldFrontmatter(view) === "нет шапки") return;
    if (attempt < 5) window.setTimeout(() => this.foldActiveEditor(attempt + 1), 100);
  }

  /*
    Ставит складку на шапку, если её там нет. Возвращает "нет шапки", когда
    следить больше не за чем.
  */
  foldFrontmatter(view) {
    const mode = view.currentMode;
    const editor = view.editor;
    if (!mode || !editor || typeof mode.applyFoldInfo !== "function") return "ждём";

    const lines = editor.lineCount();
    if (lines < 2 || editor.getLine(0).trim() !== "---") return "нет шапки";

    let end = -1;
    for (let i = 1; i < lines; i++) {
      if (editor.getLine(i).trim() === "---") { end = i; break; }
    }
    if (end < 0) return "нет шапки";

    const info = typeof mode.getFoldInfo === "function" ? mode.getFoldInfo() : null;
    const folds = info && Array.isArray(info.folds) ? info.folds.slice() : [];
    if (folds.some((f) => f.from === 0)) return "свёрнуто";

    folds.unshift({ from: 0, to: end });
    const next = { folds, lines };
    mode.applyFoldInfo(next);
    this.app.foldManager.save(view.file, next);
    return "свернули";
  }

  fold(el, force = false) {
    if (!el || el.closest(SKIP)) return;
    if (!force && el.dataset[DONE]) return;
    el.dataset[DONE] = "1";
    el.classList.add("is-collapsed");
  }
};
