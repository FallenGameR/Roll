"use strict";

/*
  Макеты статблоков кампании живут здесь, а не в настройках Fantasy Statblocks.

  В папке layouts лежат два макета: monster.json (макет по умолчанию для всего
  бестиария: кубики без числа до броска, в квадратных скобках) и
  player-sheet.json ("Лист игрока", его указывают карточки игроков полем layout).
  Стили к ним - в styles.css этого плагина: прямые кружки ячеек, кубик перед
  числом, курсив результата, прозрачные флажки в PDF листов игроков.

  При запуске плагин сверяет макеты с настройками Fantasy Statblocks. Если их
  там нет или они расходятся (например, плагин обновился и сбросил настройки),
  вписывает свои, ставит "Монстр" макетом по умолчанию и сохраняет. Источник
  правды - файлы в layouts; правят их, а не макеты в окне настроек плагина.

  Файлы чужих плагинов не правятся. Опора на внутренности Fantasy Statblocks
  одна: manager.setLayouts и setDefaultLayout. Если их переименуют, плагин
  просто не встанет и напишет об этом в консоль.
*/

const { Plugin, Notice } = require("obsidian");

const STATBLOCKS = "obsidian-5e-statblocks";
const NOTE_LINK = "statblock-note-link";
const DEFAULT_LAYOUT = "monster-layout";
const RETRY_DELAY = 500;
const RETRY_LIMIT = 20;

/*
  Трекеры в статблоках. Кружки ◯ и цифры ①-⑨ в названиях и описаниях пунктов
  становятся кнопками: щелчок отмечает трату и пишет её прямо в файл, где лежит
  блок statblock, поэтому отметка видна и в заметке, и в трекере инициативы и
  переживает перезапуск. Потраченный кружок пишется ⊗, потраченная цифра ⊘;
  повторный щелчок возвращает исходный знак. Цифру ⊘ восстанавливает по соседям
  в той же строке, а если вся строка потрачена, по номеру строки: в описании
  "Спелл-слоты:\n①①\n②" первая строка со знаками - первый круг.
  Залитые ❶-❾ (цена заклинания) кнопками не становятся.
*/
const TICK = /[\u25EF\u2460-\u2468\u2297\u2298]/g;
const HAS_TICK = /[\u25EF\u2460-\u2468\u2297\u2298]/;
const SLOT_DIGIT = /[\u2460-\u2468]/;
const SPENT_RING = "\u2297";
const SPENT_DIGIT = "\u2298";
const RING = "\u25EF";

function plainName(s) {
  return String(s || "")
    .replace(/\[\[([^\]|]+)\|([^\]]+)\]\]/g, "$2")
    .replace(/\[\[([^\]]+)\]\]/g, (m, a) => a.split("#").pop())
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/[*`_]/g, "")
    .replace(TICK, "")
    .replace(/[\u2776-\u277E]/g, "")
    .replace(/\s+/g, " ")
    .replace(/[\s.:]+$/, "")
    .trim();
}

function squash(s) {
  return plainName(s).toLowerCase().replace(/[^0-9a-zа-яё]+/g, "");
}

function isSpent(ch) {
  return ch === SPENT_RING || ch === SPENT_DIGIT;
}

/* Потраченный знак рисуется пустым кружком с перечёркиванием: у ⊘ и ⊗ в шрифте
   свой размер, и строка слотов прыгала бы. Настоящий знак лежит в data-g. */
function paint(span, ch) {
  span.dataset.g = ch;
  span.textContent = ch === SPENT_RING ? RING : ch === SPENT_DIGIT ? span.dataset.digit || ch : ch;
  span.classList.toggle("is-spent", isSpent(ch));
  span.classList.toggle("is-ring", ch === SPENT_RING || ch === RING);
}

/* Черта через потраченный знак ставится по центру его рисунка, а не рамки:
   увеличенные size-adjust глифы из рамки вылезают, и насколько - зависит от
   шрифта. Центр и ширину рисунка меряет canvas.measureText тем же шрифтом. */
let measureCtx = null;
function fitSlash(span) {
  if (!span.classList.contains("is-spent") || !span.isConnected) return;
  const cs = window.getComputedStyle(span);
  const fs = parseFloat(cs.fontSize) || 16;
  measureCtx = measureCtx || document.createElement("canvas").getContext("2d");
  measureCtx.font = `${cs.fontStyle} ${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`;
  const m = measureCtx.measureText(span.textContent);
  const fa = m.fontBoundingBoxAscent || fs * 0.8;
  const fd = m.fontBoundingBoxDescent || fs * 0.2;
  const baseline = (fs - (fa + fd)) / 2 + fa;
  const cx = (m.actualBoundingBoxRight - m.actualBoundingBoxLeft) / 2 - m.width / 2;
  const cy = baseline + (m.actualBoundingBoxDescent - m.actualBoundingBoxAscent) / 2 - fs / 2;
  const ink = Math.min(m.actualBoundingBoxRight + m.actualBoundingBoxLeft, m.actualBoundingBoxAscent + m.actualBoundingBoxDescent);
  span.style.setProperty("--cs-x", `${cx.toFixed(2)}px`);
  span.style.setProperty("--cs-y", `${cy.toFixed(2)}px`);
  span.style.setProperty("--cs-w", `${(ink * 0.92).toFixed(2)}px`);
}

/* Цифра, которой рисуется потраченный слот ⊘: та же, что у соседей в строке,
   а если вся строка потрачена - по номеру строки со слотами. Строка - это
   подряд идущие кружки без текста между ними. */
function assignDigits(spans) {
  const runs = [];
  let run = null;
  for (const s of spans) {
    const prev = s.previousSibling;
    const glued = run && prev === run[run.length - 1];
    if (!glued) {
      run = [];
      runs.push(run);
    }
    run.push(s);
  }
  let level = 0;
  for (const r of runs) {
    const glyphs = r.map((s) => s.dataset.g);
    if (!glyphs.some((g) => SLOT_DIGIT.test(g) || g === SPENT_DIGIT)) continue;
    level++;
    const known = glyphs.find((g) => SLOT_DIGIT.test(g));
    const digit = known || String.fromCharCode(0x245f + Math.min(9, level));
    for (const s of r) {
      s.dataset.digit = digit;
      if (s.dataset.g === SPENT_DIGIT) paint(s, SPENT_DIGIT);
    }
  }
}

function toggleGlyph(value, at) {
  const rows = value.split("\\n");
  let offset = 0;
  for (let r = 0; r < rows.length; r++) {
    const row = rows[r];
    if (at < offset + row.length) {
      const i = at - offset;
      const ch = row[i];
      let next;
      if (ch === RING) next = SPENT_RING;
      else if (ch === SPENT_RING) next = RING;
      else if (SLOT_DIGIT.test(ch)) next = SPENT_DIGIT;
      else if (ch === SPENT_DIGIT) {
        const sib = row.match(SLOT_DIGIT);
        if (sib) next = sib[0];
        else {
          const level = rows.slice(0, r + 1).filter((x) => /[\u2460-\u2468\u2298]/.test(x)).length;
          next = String.fromCharCode(0x245f + Math.min(9, Math.max(1, level)));
        }
      } else return null;
      rows[r] = row.slice(0, i) + next + row.slice(i + 1);
      return { value: rows.join("\\n"), glyph: next };
    }
    offset += row.length + 2;
  }
  return null;
}

/* После записи Fantasy Statblocks перечитывает существо, и трекер рисует
   статблок заново с прокруткой в начало. Прокрутка контейнеров вокруг пункта
   запоминается до записи и держится полторы секунды, пока идёт перерисовка;
   колесо или клавиши самого Мастера удержание снимают. */
function holdScroll(from) {
  const saved = [];
  for (let el = from.parentElement; el && el !== document.body; el = el.parentElement) {
    if (el.scrollHeight > el.clientHeight && el.scrollTop > 0) saved.push([el, el.scrollTop]);
  }
  if (!saved.length) return;
  let stop = false;
  const cancel = () => (stop = true);
  window.addEventListener("wheel", cancel, { once: true, passive: true });
  window.addEventListener("keydown", cancel, { once: true });
  const until = Date.now() + 1500;
  const tick = () => {
    if (stop || Date.now() > until) {
      window.removeEventListener("wheel", cancel);
      window.removeEventListener("keydown", cancel);
      return;
    }
    for (const [el, top] of saved) if (el.isConnected && el.scrollTop !== top) el.scrollTop = top;
    window.requestAnimationFrame(tick);
  };
  window.requestAnimationFrame(tick);
}

module.exports = class CampaignStatblocks extends Plugin {
  onload() {
    this.app.workspace.onLayoutReady(() => this.waitForStatblocks());
    this.app.workspace.onLayoutReady(() => this.watchTrackers());
  }

  watchTrackers() {
    let pending = false;
    const run = () => {
      pending = false;
      document.querySelectorAll(".obsidian-statblock-plugin .trait").forEach((el) => this.wrapTicks(el));
    };
    const obs = new MutationObserver(() => {
      if (pending) return;
      pending = true;
      window.requestAnimationFrame(run);
    });
    obs.observe(document.body, { childList: true, subtree: true });
    this.register(() => obs.disconnect());
    run();
  }

  wrapTicks(trait) {
    const nameEl = trait.querySelector(".trait-name");
    const walker = document.createTreeWalker(trait, NodeFilter.SHOW_TEXT);
    const nodes = [];
    while (walker.nextNode()) {
      const node = walker.currentNode;
      if (node.parentElement && node.parentElement.closest(".cs-tick")) continue;
      if (HAS_TICK.test(node.nodeValue)) nodes.push(node);
    }
    for (const node of nodes) {
      const frag = document.createDocumentFragment();
      let last = 0;
      const text = node.nodeValue;
      text.replace(TICK, (ch, pos) => {
        if (pos > last) frag.appendChild(document.createTextNode(text.slice(last, pos)));
        const span = document.createElement("span");
        span.className = "cs-tick";
        paint(span, ch);
        span.title = "Щелчок отмечает трату и пишет её в файл";
        span.addEventListener("click", (e) => {
          e.preventDefault();
          e.stopPropagation();
          this.toggleTick(trait, span);
        });
        frag.appendChild(span);
        last = pos + 1;
        return ch;
      });
      if (last < text.length) frag.appendChild(document.createTextNode(text.slice(last)));
      node.parentNode.replaceChild(frag, node);
    }
    // Номера считаются заново на каждом проходе: описание дорисовывается позже имени.
    const counters = { name: 0, desc: 0 };
    trait.querySelectorAll(".cs-tick").forEach((span) => {
      const part = nameEl && nameEl.contains(span) ? "name" : "desc";
      span.dataset.part = part;
      span.dataset.i = String(counters[part]++);
    });
    const all = [...trait.querySelectorAll(".cs-tick")];
    assignDigits(all.filter((s) => s.dataset.part === "name"));
    assignDigits(all.filter((s) => s.dataset.part === "desc"));
    all.forEach(fitSlash);
  }
  async toggleTick(trait, span) {
    const nameEl = trait.querySelector(".trait-name");
    const traitName = squash(nameEl ? nameEl.textContent : "");
    if (!traitName) return;
    const root = trait.closest(".obsidian-statblock-plugin");
    const heading = root && root.querySelector("h1, .name, .statblock-name");
    const creature = heading ? squash(heading.textContent) : "";
    const part = span.dataset.part;
    const index = Number(span.dataset.i);

    const hits = [];
    for (const file of this.app.vault.getMarkdownFiles()) {
      const text = await this.app.vault.cachedRead(file);
      if (!text.includes("```statblock")) continue;
      const lines = text.split("\n");
      let inBlock = false;
      let blockName = "";
      for (let n = 0; n < lines.length; n++) {
        const line = lines[n];
        if (/^```statblock/.test(line)) {
          inBlock = true;
          blockName = "";
          continue;
        }
        if (inBlock && /^```/.test(line)) {
          inBlock = false;
          continue;
        }
        if (!inBlock) continue;
        const top = line.match(/^"name":\s*"(.*)"\s*$/);
        if (top) {
          blockName = squash(top[1]);
          continue;
        }
        const m = line.match(/^\s*-?\s*"name":\s*"(.*)"\s*$/);
        if (!m) continue;
        const key = squash(m[1]);
        // На экране к названию могут прилипнуть кнопка броска и её результат.
        if (!key || !traitName.startsWith(key)) continue;
        let target = n;
        if (part === "desc") {
          const prev = lines[n - 1] || "";
          const next = lines[n + 1] || "";
          if (/^\s+"desc":/.test(next)) target = n + 1;
          else if (/^\s*-\s*"desc":/.test(prev)) target = n - 1;
          else continue;
        }
        hits.push({ file, line: target, raw: lines[target], blockName, exact: key === traitName, len: key.length });
      }
    }
    hits.sort((a, b) => Number(b.exact) - Number(a.exact) || b.len - a.len);
    const best = hits.length ? hits[0].len : 0;
    const top = hits.filter((h) => h.len === best);
    const hit = top.find((h) => creature && h.blockName === creature) || top[0];
    if (!hit) {
      new Notice(`Не нашла в волте пункт "${traitName}" для отметки`);
      return;
    }

    const key = hit.raw.match(/^(\s*-?\s*"(?:name|desc)":\s*")(.*)("\s*)$/);
    if (!key) return;
    const value = key[2];
    const positions = [];
    value.replace(TICK, (ch, pos) => {
      positions.push(pos);
      return ch;
    });
    TICK.lastIndex = 0;
    if (index >= positions.length) {
      new Notice("Отметка не совпала с файлом, обновите статблок");
      return;
    }
    const res = toggleGlyph(value, positions[index]);
    if (!res) return;
    const newLine = key[1] + res.value + key[3];
    holdScroll(trait);
    let ok = false;
    await this.app.vault.process(hit.file, (text) => {
      const lines = text.split("\n");
      if (lines[hit.line] !== hit.raw) return text;
      lines[hit.line] = newLine;
      ok = true;
      return lines.join("\n");
    });
    if (!ok) {
      new Notice("Файл изменился, щёлкните ещё раз");
      return;
    }
    paint(span, res.glyph);
    fitSlash(span);
  }

  waitForStatblocks() {
    let attempts = 0;
    const tick = async () => {
      const fs = this.app.plugins.plugins[STATBLOCKS];
      if (fs && fs.manager && fs.settings) {
        try {
          await this.sync(fs);
        } catch (e) {
          console.error("Campaign statblocks:", e);
        }
        return;
      }
      if (++attempts < RETRY_LIMIT) window.setTimeout(tick, RETRY_DELAY);
      else console.warn("Campaign statblocks: Fantasy Statblocks не найден");
    };
    tick();
  }

  async readLayouts() {
    const dir = `${this.manifest.dir}/layouts`;
    const adapter = this.app.vault.adapter;
    if (!(await adapter.exists(dir))) return [];
    const { files } = await adapter.list(dir);
    const layouts = [];
    for (const file of files.filter((f) => f.endsWith(".json")).sort()) {
      layouts.push(JSON.parse(await adapter.read(file)));
    }
    return layouts;
  }

  async sync(fs) {
    const layouts = await this.readLayouts();
    if (!layouts.length) return;
    if (typeof fs.manager.setLayouts !== "function") {
      console.warn("Campaign statblocks: у Fantasy Statblocks нет manager.setLayouts, макеты не встали");
      return;
    }

    const saved = Array.isArray(fs.settings.layouts) ? fs.settings.layouts : [];
    const changed = [];
    for (const layout of layouts) {
      const at = saved.findIndex((l) => l.id === layout.id);
      if (at === -1) {
        saved.push(layout);
        changed.push(layout);
      } else if (JSON.stringify(stripInjected(saved[at])) !== JSON.stringify(layout)) {
        saved[at] = layout;
        changed.push(layout);
      }
    }
    fs.settings.layouts = saved;

    let defaultChanged = false;
    if (layouts.some((l) => l.id === DEFAULT_LAYOUT) && fs.settings.default !== DEFAULT_LAYOUT) {
      fs.settings.default = DEFAULT_LAYOUT;
      defaultChanged = true;
    }

    if (!changed.length && !defaultChanged) return;

    fs.manager.setLayouts(changed);
    if (defaultChanged && typeof fs.manager.setDefaultLayout === "function") {
      fs.manager.setDefaultLayout(DEFAULT_LAYOUT);
    }
    await fs.saveSettings();

    const noteLink = this.app.plugins.plugins[NOTE_LINK];
    if (noteLink && typeof noteLink.inject === "function") noteLink.inject();

    new Notice("Макеты статблоков кампании восстановлены. Открытые карточки обновятся после переоткрытия.");
  }
};

/** Макет без блоков, которые дописывают другие наши плагины в памяти. */
function stripInjected(layout) {
  if (!layout || !Array.isArray(layout.blocks)) return layout;
  return Object.assign({}, layout, { blocks: layout.blocks.filter((b) => b.id !== "note-link-block") });
}
