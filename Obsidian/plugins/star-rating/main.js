"use strict";

/*
  Пять звёзд вместо выпадающего списка оценки.

  Оценку в шапку пишет Meta Bind: шаблон поля stars - это inlineSelect с
  классом stars. В системном выпадающем списке нельзя раскрасить часть
  строки, и ★★★☆☆ читается плохо. Плагин прячет этот список и ставит
  рядом пять звёзд. Клик по звезде выбирает значение в спрятанном списке,
  дальше всё делает Meta Bind. Клик по уже выбранной звезде ставит 0.

  Текущее значение Meta Bind держит в data-internal-value обёртки поля;
  за этим атрибутом плагин и следит, так что правка шапки руками или из
  другого окна сразу видна на звёздах.
*/

const { Plugin } = require("obsidian");

const WRAPPER = ".mb-input-wrapper.stars";
const MAX = 5;

module.exports = class StarRating extends Plugin {
  onload() {
    this.observer = new MutationObserver((records) => {
      for (const record of records) {
        if (record.type === "attributes") {
          const wrapper = record.target;
          if (wrapper._starRating) this.paint(wrapper);
          continue;
        }
        for (const node of record.addedNodes) {
          if (!(node instanceof HTMLElement)) continue;
          if (node.matches(WRAPPER)) this.enhance(node);
          node.querySelectorAll(WRAPPER).forEach((el) => this.enhance(el));
        }
      }
    });
    this.observer.observe(document.body, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ["data-internal-value"],
    });
    this.register(() => this.observer.disconnect());

    document.querySelectorAll(WRAPPER).forEach((el) => this.enhance(el));
    this.register(() => document.querySelectorAll(WRAPPER).forEach((el) => this.restore(el)));
  }

  enhance(wrapper) {
    const select = wrapper.querySelector("select");
    if (!select || wrapper._starRating) return;

    const row = createDiv({ cls: "star-rating" });
    const stars = [];
    for (let n = 1; n <= MAX; n++) {
      const star = row.createSpan({ cls: "star-rating-star", text: "★" });
      star.setAttr("aria-label", `${n}`);
      star.addEventListener("mouseenter", () => this.paint(wrapper, n));
      star.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        this.choose(wrapper, this.value(wrapper) === n ? 0 : n);
      });
      stars.push(star);
    }
    row.addEventListener("mouseleave", () => this.paint(wrapper));

    wrapper._starRating = { row, stars, select };
    wrapper.classList.add("star-rating-active");
    wrapper.appendChild(row);
    this.paint(wrapper);
  }

  restore(wrapper) {
    const state = wrapper._starRating;
    if (!state) return;
    state.row.remove();
    wrapper.classList.remove("star-rating-active");
    delete wrapper._starRating;
  }

  value(wrapper) {
    let v = null;
    try {
      v = JSON.parse(wrapper.dataset.internalValue ?? "null");
    } catch (e) {
      v = null;
    }
    return typeof v === "number" ? v : null;
  }

  choose(wrapper, n) {
    const { select } = wrapper._starRating;
    select.value = String(n);
    select.dispatchEvent(new Event("change", { bubbles: true }));
  }

  paint(wrapper, preview) {
    const { row, stars } = wrapper._starRating;
    const value = this.value(wrapper);
    const shown = preview ?? value ?? 0;
    stars.forEach((star, i) => star.toggleClass("is-filled", i < shown));
    row.toggleClass("is-preview", preview !== undefined);
    row.toggleClass("is-unrated", value === null);
    row.setAttr("title", value === null ? "Не оценено" : `${value} из ${MAX}`);
  }
};
