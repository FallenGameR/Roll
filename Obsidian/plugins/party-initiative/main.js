"use strict";

const { Plugin, Modal, Notice, setIcon, parseYaml } = require("obsidian");

const TRACKER_ID = "initiative-tracker";
const TRACKER_VIEW = "initiative-tracker-view";
const BUTTON_CLASS = "party-initiative-button";
const MONSTER_BUTTON_CLASS = "monster-initiative-button";
const PLAYERS_FOLDER = "Adventure/Players";
const MIN_INITIATIVE = -20;
const MAX_INITIATIVE = 99;

/** Читает значение svelte-store, не оставляя подписки. */
function readStore(store) {
    if (!store || typeof store.subscribe !== "function") return undefined;
    let value;
    const result = store.subscribe((v) => {
        value = v;
    });
    if (typeof result === "function") result();
    else if (result && typeof result.unsubscribe === "function") result.unsubscribe();
    return value;
}

/** Достаёт из трекера список существ текущего боя. */
function getCreatures(tracker) {
    const direct = readStore(tracker);
    if (Array.isArray(direct)) return direct;
    if (tracker && Array.isArray(tracker.creatures)) return tracker.creatures;
    const nested = readStore(tracker ? tracker.creatures : null);
    if (Array.isArray(nested)) return nested;
    return null;
}

function firstWord(name) {
    return String(name || "").trim().split(/\s+/)[0] || "";
}

/**
 * Имя существа без порядкового номера: трекер показывает "Гоблин 3", а
 * getName() клеит номер к display или name. Группа - это как раз имя без него.
 */
function baseName(creature) {
    const own = creature.display || creature.name;
    if (own) return String(own).trim();
    const shown = typeof creature.getName === "function" ? creature.getName() : "";
    return String(shown).replace(/\s+\d+$/, "").trim();
}

const NUMERALS = [
    { re: /\b(одну|одна|один|одним|one|once)\b/i, value: 1 },
    { re: /\b(две|два|двумя|дважды|twice|two)\b/i, value: 2 },
    { re: /\b(три|тремя|трижды|three)\b/i, value: 3 },
    { re: /\b(четыре|четырьмя|four)\b/i, value: 4 },
];

/** Первое числительное в тексте: "совершает две атаки" даёт 2. */
function countWord(text) {
    let found = 0;
    let at = Infinity;
    for (const numeral of NUMERALS) {
        const match = text.match(numeral.re);
        if (match && match.index < at) {
            at = match.index;
            found = numeral.value;
        }
    }
    return found;
}

/** Сколько раз мультиатака поминает это действие: "одну укусом и две когтями". */
function mentions(text, name) {
    const stem = firstWord(name).toLowerCase().replace(/[^a-zа-яё]/gi, "").slice(0, 3);
    if (stem.length < 3) return 0;
    const words = text.toLowerCase().split(/[^a-zа-яё0-9]+/i);
    let times = 0;
    for (let i = 0; i < words.length; i++) {
        if (!words[i].startsWith(stem)) continue;
        let count = 1;
        for (let back = Math.max(0, i - 3); back < i; back++) {
            const numeral = countWord(words[back]);
            if (numeral) count = numeral;
        }
        times += count;
    }
    return times;
}

/**
 * Средний урон действия: число перед скобкой с костями, "15 (2d10 + 4)".
 * Добавка считается только через "плюс": варианты вроде "двумя руками 8" и
 * урон по спасброску в счёт не идут. В карточках игроков среднего нет, там
 * голые кости "1d8 + 2": тогда среднее считается по первым костям.
 */
function actionDamage(desc) {
    if (!/attack|атак/i.test(desc)) return 0;
    const dice = /(\d+)\s*\(\s*\d+\s*(?:d|к)\s*\d+[^)]*\)/gi;
    let damage = 0;
    let previous = -1;
    for (const hit of desc.matchAll(dice)) {
        if (previous < 0) {
            damage = Number(hit[1]);
        } else {
            const between = desc.slice(previous, hit.index);
            if (!/\b(?:plus|плюс)\b/i.test(between)) break;
            damage += Number(hit[1]);
        }
        previous = hit.index + hit[0].length;
    }
    if (previous < 0) damage = bareDiceAverage(desc);
    return damage;
}

/** Среднее по первой записи костей без готового среднего: "1d8 + 2" даёт 6.5. */
function bareDiceAverage(desc) {
    const match = desc.match(/(\d+)\s*(?:d|к)\s*(\d+)(?:\s*([+-])\s*(\d+)\b)?/i);
    if (!match) return 0;
    const count = Number(match[1]);
    const sides = Number(match[2]);
    const bonus = match[3] ? Number(match[4]) * (match[3] === "-" ? -1 : 1) : 0;
    return Math.max(0, count * (sides + 1) / 2 + bonus);
}

/**
 * Средний урон за раунд по списку действий. Без мультиатаки - лучшая атака;
 * с мультиатакой - названные в ней удары, а если разобрать не вышло, лучшая
 * атака по числу ударов.
 */
function damageFromActions(list) {
    const actions = list.map((action) => ({
        name: String(action.name),
        desc: String(action.desc),
        damage: actionDamage(String(action.desc)),
    }));
    if (!actions.length) return 0;

    const best = actions.reduce((max, a) => Math.max(max, a.damage), 0);
    const multi = actions.find((a) => /ультиатак|ultiattack/i.test(a.name));
    if (!multi) return best;

    const plan = multi.desc.split(/\.|\s(?:или|либо|or)\s/)[0];
    const total = countWord(plan) || 1;
    let named = 0;
    let sum = 0;
    for (const action of actions) {
        if (action === multi || !action.damage) continue;
        const times = mentions(plan, action.name);
        if (!times) continue;
        named += times;
        sum += times * action.damage;
    }
    return named === total && sum ? sum : best * total;
}

/** Число из значения вроде "18 (natural armor)". */
function firstNumber(value) {
    const match = String(value === undefined || value === null ? "" : value).match(/-?\d+/);
    return match ? Number(match[0]) : 0;
}

/**
 * Токен существа, как на батлмапах и в погоне: "<Имя> токен.png" для героя
 * (имя из поля character карточки) и именного NPC, иначе картинка image из
 * шапки заметки существа.
 */
function tokenFor(app, creature) {
    if (!creature) return null;
    const note = creature.path ? app.vault.getAbstractFileByPath(creature.path) : null;
    const fm = note ? (app.metadataCache.getFileCache(note) || {}).frontmatter || {} : {};
    const names = [fm.character, note ? note.basename : null, creature.name].filter(Boolean).map(String);
    for (const name of names) {
        const hit = app.metadataCache.getFirstLinkpathDest(name + " токен.png", "");
        if (hit) return app.vault.getResourcePath(hit);
    }
    // У существ бестиария картинка лежит в самом статблоке, её знает Fantasy Statblocks.
    let image = fm.image;
    if (!image) {
        try {
            const fs = window.FantasyStatblocks;
            const c = fs && creature.name && fs.hasCreature(creature.name) ? fs.getCreatureFromBestiary(creature.name) : null;
            image = c && c.image;
        } catch (e) {
            image = null;
        }
    }
    const raw = image ? String(image).replace(/^!?\[\[|\]\]$/g, "").split("|")[0] : null;
    const img = raw ? app.metadataCache.getFirstLinkpathDest(raw, note ? note.path : "") : null;
    return img ? app.vault.getResourcePath(img) : null;
}

/** Блок statblock из текста заметки, разобранный как YAML; null, если блока нет или он не разбирается. */
function readStatblock(text) {
    const block = String(text || "").match(/```statblock[^\n]*\n([\s\S]*?)```/);
    if (!block) return null;
    try {
        const data = parseYaml(block[1]);
        return data && typeof data === "object" ? data : null;
    } catch (e) {
        return null;
    }
}

class PartyInitiativeModal extends Modal {
    constructor(app, rows, onApply, stats, title) {
        super(app);
        this.rows = rows;
        this.onApply = onApply;
        this.stats = stats;
        this.title = title || "Инициатива отряда";
        this.inputs = [];
        this.touched = false;
    }

    onOpen() {
        const { contentEl, modalEl } = this;
        modalEl.addClass("party-initiative-modal");
        contentEl.createEl("h3", { text: this.title });

        this.bulk = contentEl.createEl("input", {
            type: "text",
            placeholder: "инициативы через пробел, сверху вниз",
        });
        this.bulk.style.width = "100%";
        this.bulk.style.marginBottom = "0.75em";
        this.bulk.addEventListener("input", () => {
            this.touched = true;
            this.spread();
        });
        this.bulk.addEventListener("keydown", (e) => this.onKey(e));

        const table = contentEl.createEl("table");
        table.style.width = "100%";
        for (const row of this.rows) {
            const tr = table.createEl("tr");
            const name = tr.createEl("td");
            name.style.padding = "2px 8px 2px 0";
            const who = name.createDiv();
            who.style.display = "flex";
            who.style.alignItems = "center";
            who.style.gap = "8px";
            const src = tokenFor(this.app, row.creature || (row.creatures && row.creatures[0]));
            if (src) {
                const img = who.createEl("img", { attr: { src } });
                img.style.cssText = "width:32px;height:32px;border-radius:50%;object-fit:cover;flex:none";
            }
            who.createSpan({ text: row.label });
            const td = tr.createEl("td");
            td.style.width = "5em";
            const input = td.createEl("input", { type: "text" });
            input.style.width = "100%";
            input.value = row.value === null ? "" : String(row.value);
            input.addEventListener("keydown", (e) => this.onKey(e));
            input.addEventListener("input", () => {
                this.touched = true;
                this.collect();
            });
            this.inputs.push(input);
        }

        this.hint = contentEl.createEl("div", {
            text: "Enter - применить, Esc - закрыть. Числа сверху разбегаются по порядку.",
        });
        this.hint.style.marginTop = "0.75em";
        this.hint.style.fontSize = "0.85em";
        this.hint.style.opacity = "0.7";
        this.statsEl = contentEl.createEl("div", { text: "Считаю расклад боя..." });
        this.statsEl.style.marginTop = "0.75em";
        this.statsEl.style.fontSize = "0.85em";
        this.statsEl.style.opacity = "0.7";
        Promise.resolve(this.stats).then((lines) => {
            if (!this.statsEl) return;
            this.statsEl.empty();
            for (const line of lines || []) this.statsEl.createEl("div", { text: line });
        }).catch((error) => {
            console.error("party-initiative:", error);
            if (this.statsEl) this.statsEl.empty();
        });

        this.touched = this.inputs.some((input) => input.value.trim() !== "");
        this.collect();
        window.setTimeout(() => {
            this.bulk.focus();
            this.bulk.select();
        }, 0);
    }

    /** Раскидывает числа из верхней строки по полям таблицы. */
    spread() {
        const numbers = this.bulk.value.trim().split(/[\s,]+/).filter(Boolean);
        numbers.forEach((n, i) => {
            if (i < this.inputs.length) this.inputs[i].value = n;
        });
        this.collect();
    }

    /** Собирает верхнюю строку из полей и подсвечивает негодные значения. */
    collect() {
        const values = [];
        let ok = true;
        this.inputs.forEach((input) => {
            const raw = input.value.trim();
            const num = Number(raw);
            const good = raw !== "" && Number.isInteger(num) && num >= MIN_INITIATIVE && num <= MAX_INITIATIVE;
            input.style.borderColor = good || raw === "" ? "" : "var(--text-error)";
            if (!good) ok = false;
            values.push(good ? num : null);
        });
        this.values = values;
        this.valid = ok;
        if (this.touched && document.activeElement !== this.bulk) {
            this.bulk.value = this.inputs.map((i) => i.value.trim()).filter(Boolean).join(" ");
        }
        return ok;
    }

    onKey(event) {
        if (event.key === "Enter") {
            event.preventDefault();
            this.apply();
        } else if (event.key === "Escape") {
            event.preventDefault();
            this.close();
        }
    }

    apply() {
        if (!this.collect()) {
            const empty = this.inputs.filter((i) => i.value.trim() === "").length;
            this.hint.setText(
                empty
                    ? "Не у всех есть число: заполните пустые поля."
                    : "Где-то не число или значение вне диапазона: поправьте подсвеченное."
            );
            this.hint.style.color = "var(--text-error)";
            const bad = this.inputs.find(
                (i) => i.value.trim() === "" || !Number.isInteger(Number(i.value.trim()))
            );
            if (bad) bad.focus();
            return;
        }
        this.onApply(this.rows.map((row, i) => ({ row, value: this.values[i] })));
        this.close();
    }

    onClose() {
        this.contentEl.empty();
    }
}

module.exports = class PartyInitiativePlugin extends Plugin {
    async onload() {
        this.observers = [];
        this.addCommand({
            id: "set-party-initiative",
            name: "Инициатива отряда",
            callback: () => this.open(),
        });

        this.addRibbonIcon("list-ordered", "Инициатива отряда", () => this.open());

        this.addCommand({
            id: "set-monster-initiative",
            name: "Инициатива монстров",
            callback: () => this.openMonsters(),
        });

        this.addRibbonIcon("swords", "Инициатива монстров", () => this.openMonsters());

        this.app.workspace.onLayoutReady(() => this.decorateTracker());
        this.registerEvent(
            this.app.workspace.on("layout-change", () => this.decorateTracker())
        );
        this.registerEvent(
            this.app.workspace.on("active-leaf-change", () => this.decorateTracker())
        );
    }

    onunload() {
        for (const observer of this.observers || []) observer.disconnect();
        this.observers = [];
        document.querySelectorAll("." + BUTTON_CLASS).forEach((el) => el.remove());
        document.querySelectorAll("." + MONSTER_BUTTON_CLASS).forEach((el) => el.remove());
    }

    /**
     * Вешает кнопку в ряд иконок самой панели трекера: своей шапки у боковой
     * панели нет, поэтому addAction там не виден.
     */
    decorateTracker() {
        const leaves = this.app.workspace.getLeavesOfType(TRACKER_VIEW);
        for (const leaf of leaves) {
            const view = leaf.view;
            if (!view || !view.contentEl) continue;
            this.injectButton(view.contentEl);
            if (view.partyInitiativeObserved) continue;
            const observer = new MutationObserver(() => this.injectButton(view.contentEl));
            observer.observe(view.contentEl, { childList: true, subtree: true });
            view.partyInitiativeObserved = true;
            this.observers.push(observer);
        }
    }

    /** Ставит иконки рядом с остальными кнопками панели, если их там ещё нет. */
    injectButton(container) {
        const row = container.querySelector(".buttons .clean") || container.querySelector(".buttons");
        if (!row) return;
        if (!row.querySelector("." + MONSTER_BUTTON_CLASS)) {
            const monsters = createDiv({ cls: "clickable-icon " + MONSTER_BUTTON_CLASS });
            monsters.setAttribute("aria-label", "Инициатива монстров");
            setIcon(monsters, "swords");
            monsters.addEventListener("click", () => this.openMonsters());
            row.insertBefore(monsters, row.firstChild);
        }
        if (row.querySelector("." + BUTTON_CLASS)) return;
        const button = createDiv({ cls: "clickable-icon " + BUTTON_CLASS });
        button.setAttribute("aria-label", "Инициатива отряда");
        setIcon(button, "list-ordered");
        button.addEventListener("click", () => this.open());
        row.insertBefore(button, row.firstChild);
    }

    getTracker() {
        const plugin = this.app.plugins.plugins[TRACKER_ID];
        if (!plugin) {
            new Notice("Initiative Tracker не найден или выключен.");
            return null;
        }
        if (!plugin.tracker || typeof plugin.tracker.updateCreatures !== "function") {
            new Notice("Не вижу у трекера метод updateCreatures: плагин обновился?");
            return null;
        }
        return plugin.tracker;
    }

    /** Порядок и подписи берём из карточек игроков, участников - из боя. */
    collectRows(creatures) {
        const cards = this.app.vault
            .getMarkdownFiles()
            .filter((f) => f.path.startsWith(PLAYERS_FOLDER + "/"))
            .map((f) => {
                const cache = this.app.metadataCache.getFileCache(f);
                const fm = (cache && cache.frontmatter) ? cache.frontmatter : {};
                return {
                    file: f,
                    order: typeof fm.order === "number" ? fm.order : 999,
                    short: firstWord(f.basename),
                };
            });

        const rows = [];
        const seen = new Set();
        for (const creature of creatures) {
            if (!creature.player) continue;
            if (creature.id) {
                if (seen.has(creature.id)) continue;
                seen.add(creature.id);
            }
            const rawName = creature.name ? creature.name : (typeof creature.getName === "function" ? creature.getName() : "");
            const name = firstWord(rawName);
            const card = cards.find((c) => c.short === name);
            rows.push({
                creature,
                order: card ? card.order : 999,
                label: (card ? card.order + ". " : "") + (creature.name ? creature.name : name),
                value: creature.initiative ? creature.initiative : null,
            });
        }
        rows.sort((a, b) => a.order - b.order || String(a.label).localeCompare(String(b.label)));
        return rows;
    }

    /**
     * Группы противников: все "Гоблин 1..4" идут одной строкой и получают одну
     * инициативу. Порядок - как существа стоят в трекере.
     */
    collectGroups(creatures) {
        const groups = new Map();
        for (const creature of creatures) {
            if (creature.player || creature.enabled === false) continue;
            const key = baseName(creature);
            if (!key) continue;
            if (!groups.has(key)) groups.set(key, []);
            groups.get(key).push(creature);
        }

        const rows = [];
        for (const [key, list] of groups) {
            const first = list[0].initiative ? list[0].initiative : null;
            const same = list.every((c) => (c.initiative ? c.initiative : null) === first);
            rows.push({
                creatures: list,
                label: list.length > 1 ? key + " x" + list.length : key,
                value: same ? first : null,
            });
        }
        return rows;
    }

    /**
     * Средний урон существа за раунд по статблоку. Статблок берётся из карточки
     * вольта, а если её нет - из бестиария 5e-statblocks.
     */
    async damagePerRound(creature) {
        const key = creature.path || creature.name;
        if (!key) return 0;
        if (!this.damageCache) this.damageCache = new Map();
        if (this.damageCache.has(key)) return this.damageCache.get(key);

        let damage = 0;
        const file = creature.path ? this.app.vault.getAbstractFileByPath(creature.path) : null;
        if (file && "extension" in file) {
            const data = readStatblock(await this.app.vault.cachedRead(file));
            if (data && Array.isArray(data.actions)) damage = this.damageFromList(data.actions);
            // Заметка ссылается на статблок бестиария ("monster: Багбир") - урон оттуда.
            if (!damage && data) damage = this.damageFromBestiary(data.monster || data.creature || creature.name);
        } else {
            damage = this.damageFromBestiary(creature.name);
        }
        this.damageCache.set(key, damage);
        return damage;
    }

    /** Достаёт действия из бестиария 5e-statblocks: там живут существа без карточки. */
    damageFromBestiary(name) {
        const bestiary = window.FantasyStatblocks;
        if (!name || !bestiary || typeof bestiary.getCreatureFromBestiary !== "function") return 0;
        const monster = bestiary.getCreatureFromBestiary(name);
        if (!monster || !Array.isArray(monster.actions)) return 0;
        return this.damageFromList(monster.actions);
    }

    damageFromList(list) {
        return damageFromActions(list.filter((a) => a && typeof a === "object").map((action) => ({
            name: String(action.name || "").replace(/\[\[[^\]|]*\|?([^\]]*)\]\]/g, "$1"),
            desc: String(action.desc || ""),
        })));
    }

    /** Две строки расклада: итог по отряду и по противнику. */
    async collectStats(creatures) {
        const sides = [
            { label: "Отряд", list: creatures.filter((c) => c.player && c.enabled !== false) },
            { label: "Противник", list: creatures.filter((c) => !c.player && c.enabled !== false) },
        ];
        const lines = [];
        for (const side of sides) {
            if (!side.list.length) {
                lines.push(side.label + ": никого");
                continue;
            }
            let hp = 0;
            let ac = 0;
            let damage = 0;
            for (const creature of side.list) {
                hp += firstNumber(creature.hp);
                ac += firstNumber(creature.current_ac || creature.ac);
                damage += await this.damagePerRound(creature);
            }
            lines.push(
                side.label + ": хитов " + hp + ", средний AC " + Math.round(ac / side.list.length) +
                ", урон за раунд " + Math.round(damage)
            );
        }
        return lines;
    }

    open() {
        const tracker = this.getTracker();
        if (!tracker) return;

        const creatures = getCreatures(tracker);
        if (!creatures) {
            new Notice("Не могу прочитать состав боя из трекера.");
            return;
        }

        const rows = this.collectRows(creatures);
        if (!rows.length) {
            new Notice("В текущем бою нет игроков.");
            return;
        }

        new PartyInitiativeModal(this.app, rows, (result) => {
            const current = getCreatures(tracker) || [];
            const changes = [];
            const lost = [];
            for (const { row, value } of result) {
                const creature = current.includes(row.creature)
                    ? row.creature
                    : current.find((c) => c.player && row.creature.id && c.id === row.creature.id);
                if (!creature) {
                    lost.push(row.label);
                    continue;
                }
                changes.push({ creature, change: { initiative: value } });
            }
            if (!changes.length) {
                new Notice("Состав боя сменился: применять уже не к кому.");
                return;
            }
            try {
                tracker.updateCreatures(...changes);
                const tail = lost.length ? ", пропущено (нет в бою): " + lost.join(", ") : "";
                new Notice("Инициатива проставлена: " + changes.length + " игроков" + tail + ".");
            } catch (error) {
                console.error("party-initiative:", error);
                new Notice("Не вышло применить инициативу, смотри консоль.");
            }
        }, this.collectStats(creatures)).open();
    }

    openMonsters() {
        const tracker = this.getTracker();
        if (!tracker) return;

        const creatures = getCreatures(tracker);
        if (!creatures) {
            new Notice("Не могу прочитать состав боя из трекера.");
            return;
        }

        const rows = this.collectGroups(creatures);
        if (!rows.length) {
            new Notice("В текущем бою нет монстров.");
            return;
        }

        new PartyInitiativeModal(this.app, rows, (result) => {
            const current = getCreatures(tracker) || [];
            const changes = [];
            const lost = [];
            for (const { row, value } of result) {
                let found = 0;
                for (const member of row.creatures) {
                    const creature = current.includes(member)
                        ? member
                        : current.find((c) => !c.player && member.id && c.id === member.id);
                    if (!creature) continue;
                    found += 1;
                    changes.push({ creature, change: { initiative: value } });
                }
                if (!found) lost.push(row.label);
            }
            if (!changes.length) {
                new Notice("Состав боя сменился: применять уже не к кому.");
                return;
            }
            try {
                tracker.updateCreatures(...changes);
                const tail = lost.length ? ", пропущено (нет в бою): " + lost.join(", ") : "";
                new Notice("Инициатива проставлена: " + changes.length + " монстров" + tail + ".");
            } catch (error) {
                console.error("party-initiative:", error);
                new Notice("Не вышло применить инициативу, смотри консоль.");
            }
        }, this.collectStats(creatures), "Инициатива монстров").open();
    }
};
