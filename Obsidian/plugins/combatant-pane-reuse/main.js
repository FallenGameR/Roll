"use strict";

/*
  Панель Combatant открывается там, где её оставили.

  Клик по бойцу в Initiative Tracker зовёт openCombatant. Плагин ищет свою
  панель так: сначала смотрит запомненную ссылку lastCombatantLeaf, потом
  первую панель нужного типа, и только если ничего не нашёл - создаёт новую
  в правом сайдбаре.

  Ломается это после перезапуска Обсидиана. Начиная с версии 1.7 вкладки,
  восстановленные из вёрстки, но не показанные на экране, висят отложенными:
  сам объект view у них ещё не создан. Проверка "view instanceof CreatureView"
  такую вкладку не узнаёт, трекер считает, что панели нет, и открывает новую -
  в правом сайдбаре, а не там, куда её перетащили.

  Плагин подменяет openCombatant у экземпляра трекера: перед вызовом
  оригинала находит уцелевшую панель, будит её через loadIfDeferred и кладёт
  в lastCombatantLeaf. Дальше оригинал видит живую панель и рисует статблок
  в неё. Ctrl/Cmd-клик (второй аргумент) не трогаем - он и должен открывать
  новую панель.

  Файлы трекера не правятся, так что обновление плагина патч не сносит. Если
  внутренности трекера когда-нибудь переименуют, подмена просто не встанет и
  поведение вернётся к штатному - в консоли будет предупреждение.
*/

const { Plugin } = require("obsidian");

const TRACKER = "initiative-tracker";
const CREATURE_VIEW = "initiative-tracker-creature-view";
const RETRY_DELAY = 500;
const RETRY_LIMIT = 20;

module.exports = class CombatantPaneReuse extends Plugin {
  onload() {
    this.patched = null;
    this.app.workspace.onLayoutReady(() => this.waitForTracker());
  }

  onunload() {
    this.restore();
  }

  waitForTracker() {
    if (this.patch()) return;
    let attempts = 0;
    const timer = window.setInterval(() => {
      attempts++;
      const done = this.patch();
      if (!done && attempts < RETRY_LIMIT) return;
      window.clearInterval(timer);
      if (!done) {
        console.warn("Combatant pane reuse: Initiative Tracker не найден, подмена не встала");
      }
    }, RETRY_DELAY);
    this.registerInterval(timer);
  }

  patch() {
    const tracker = this.app.plugins.plugins[TRACKER];
    if (!tracker || typeof tracker.openCombatant !== "function") return false;
    if (Object.prototype.hasOwnProperty.call(tracker, "openCombatant")) return true;

    const original = tracker.openCombatant;
    const self = this;
    tracker.openCombatant = async function (creature, newLeaf = false) {
      if (!newLeaf) await self.reuseExistingPane(this);
      return original.call(this, creature, newLeaf);
    };
    this.patched = { tracker, original };
    return true;
  }

  restore() {
    if (!this.patched) return;
    const { tracker, original } = this.patched;
    if (tracker.openCombatant !== original) delete tracker.openCombatant;
    this.patched = null;
  }

  async reuseExistingPane(tracker) {
    const leaves = this.app.workspace.getLeavesOfType(CREATURE_VIEW) || [];
    if (!leaves.length) return;
    const remembered = tracker.lastCombatantLeaf;
    const leaf = remembered && leaves.includes(remembered) ? remembered : leaves[0];
    if (leaf.loadIfDeferred) await leaf.loadIfDeferred();
    tracker.lastCombatantLeaf = leaf;
  }
};
