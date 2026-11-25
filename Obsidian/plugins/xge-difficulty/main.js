"use strict";

/*
 * Сложность боя в Initiative Tracker по странице кампании
 * "DnD Lists n Rules/Rules/Extensions DnD/Сложность боя.md" (Xanathar's Guide).
 *
 * Код трекера не правится: плагин подменяет в памяти его стор difficulty
 * (plugin.tracker.difficulty) и пишет слово сложности в шапку боя вместо XP.
 * Обновление трекера эту доработку не сносит; если трекер поменяет устройство,
 * плагин молча ничего не делает.
 */

const { Plugin } = require("obsidian");

const TRACKER_ID = "initiative-tracker";
const TRACKER_VIEW = "initiative-tracker-view";

/** Сколько персонажей стоит один монстр: "a/b" из таблиц страницы, по уровню. */
const MULTI = (() => {
    const blocks = [
        {
            crs: ["1/8", "1/4", "1/2", "1", "2", "3", "4", "5", "6"],
            rows: {
                1: "1/2 1/1 3/1 5/1 - - - - -",
                2: "1/3 1/2 1/1 3/1 6/1 - - - -",
                3: "1/5 1/2 1/1 2/1 4/1 6/1 - - -",
                4: "1/8 1/4 1/2 1/1 2/1 4/1 6/1 - -",
                5: "1/12 1/8 1/4 1/2 1/1 2/1 3/1 5/1 6/1",
            },
        },
        {
            crs: ["1/8", "1/4", "1/2", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10"],
            rows: {
                6: "1/12 1/9 1/5 1/2 1/1 2/1 2/1 4/1 5/1 6/1 - - -",
                7: "1/12 1/12 1/6 1/3 1/1 1/1 2/1 3/1 4/1 5/1 - - -",
                8: "1/12 1/12 1/7 1/4 1/2 1/1 2/1 3/1 3/1 4/1 6/1 - -",
                9: "1/12 1/12 1/8 1/4 1/2 1/1 1/1 2/1 3/1 4/1 5/1 6/1 -",
                10: "1/12 1/12 1/10 1/5 1/2 1/1 1/1 2/1 2/1 3/1 4/1 5/1 6/1",
            },
        },
        {
            crs: ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12", "13", "14", "15"],
            rows: {
                11: "1/6 1/3 1/2 1/1 2/1 2/1 2/1 3/1 4/1 5/1 6/1 - - - -",
                12: "1/8 1/3 1/2 1/1 1/1 2/1 2/1 3/1 3/1 4/1 5/1 6/1 - - -",
                13: "1/9 1/4 1/2 1/2 1/1 1/1 2/1 2/1 3/1 3/1 4/1 5/1 6/1 - -",
                14: "1/10 1/4 1/3 1/2 1/1 1/1 2/1 2/1 3/1 3/1 4/1 4/1 5/1 6/1 -",
                15: "1/12 1/5 1/3 1/2 1/1 1/1 1/1 2/1 2/1 3/1 3/1 4/1 5/1 5/1 6/1",
            },
        },
        {
            crs: ["2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12", "13", "14", "15", "16", "17", "18", "19", "20"],
            rows: {
                16: "1/5 1/3 1/2 1/1 1/1 1/1 2/1 2/1 2/1 3/1 4/1 4/1 5/1 5/1 6/1 - - - -",
                17: "1/7 1/4 1/3 1/2 1/1 1/1 1/1 2/1 2/1 2/1 3/1 3/1 4/1 4/1 5/1 6/1 - - -",
                18: "1/7 1/5 1/3 1/2 1/1 1/1 1/1 2/1 2/1 2/1 3/1 3/1 4/1 4/1 5/1 6/1 6/1 - -",
                19: "1/8 1/5 1/3 1/2 1/2 1/1 1/1 1/1 2/1 2/1 2/1 3/1 3/1 4/1 4/1 5/1 6/1 6/1 -",
                20: "1/9 1/6 1/4 1/2 1/2 1/1 1/1 1/1 1/1 2/1 2/1 2/1 3/1 3/1 4/1 4/1 5/1 5/1 6/1",
            },
        },
    ];
    const table = {};
    for (const block of blocks) {
        for (const [level, row] of Object.entries(block.rows)) {
            const cells = row.split(" ");
            table[level] = block.crs.map((cr, i) => ({ cr: parseCr(cr), cell: cells[i] }));
        }
    }
    return table;
})();

/** Одиночный монстр: CR для отряда из 4, 5 и 6 персонажей. */
const SOLO = {
    1: [1, 2, 2], 2: [2, 3, 4], 3: [3, 4, 5], 4: [4, 5, 6], 5: [7, 8, 9],
    6: [8, 9, 10], 7: [9, 10, 11], 8: [10, 11, 12], 9: [11, 12, 13], 10: [12, 13, 14],
    11: [13, 14, 15], 12: [15, 16, 17], 13: [16, 17, 18], 14: [17, 18, 19], 15: [18, 19, 20],
    16: [19, 20, 21], 17: [20, 21, 22], 18: [20, 21, 22], 19: [21, 22, 23], 20: [22, 23, 24],
};

/** Границы по доле отряда: полегче считают как две трети, смертельный как полтора. */
const GRADES = [
    { name: "Лёгкий", from: 0, cls: "easy" },
    { name: "Честный", from: 0.83, cls: "medium" },
    { name: "Смертельный", from: 1.25, cls: "deadly" },
    { name: "Сверх смертельного", from: 1.55, cls: "deadly" },
];
// Шкала полоски: с ней жёлтая зона трекера (0.33-0.66) ложится на честный бой,
// а красная начинается со смертельного.
const BAR_MAX = 1.9;

function parseCr(value) {
    if (typeof value === "number") return value;
    const text = String(value === undefined || value === null ? "" : value).trim();
    if (!text) return null;
    const parts = text.split("/");
    const n = parts.length === 2 ? Number(parts[0]) / Number(parts[1]) : Number(text);
    return isNaN(n) ? null : n;
}

/** Сколько персонажей отряда стоит один монстр этого CR. */
function covers(level, cr) {
    const row = MULTI[level];
    if (!row) return 0;
    const exact = row.find((c) => Math.abs(c.cr - cr) < 1e-6);
    if (exact && exact.cell !== "-") {
        const [pcs, monsters] = exact.cell.split("/").map(Number);
        return pcs / monsters;
    }
    if (cr < row[0].cr) return 1 / 12;
    // Сильнее таблицы: монстр-одиночка. По странице CR из таблицы на шестерых - честный бой,
    // на 1-2 выше - опасный, на 3 ниже - лёгкий.
    const fair = SOLO[level][2];
    return Math.max(6, cr >= fair ? 6 * (1 + 0.25 * (cr - fair)) : 6 * (1 - (fair - cr) / 9));
}

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

function plural(n, one, few, many) {
    const k = Math.abs(Math.round(n)) % 100;
    const d = k % 10;
    if (k > 10 && k < 20) return many;
    if (d === 1) return one;
    if (d >= 2 && d <= 4) return few;
    return many;
}

function fmt(n) {
    return Number.isInteger(n) ? String(n) : n.toFixed(1).replace(".", ",");
}

module.exports = class XgeDifficultyPlugin extends Plugin {
    onload() {
        this.current = null;
        this.app.workspace.onLayoutReady(() => this.install());
        this.registerEvent(this.app.workspace.on("layout-change", () => this.paintHeaders()));
    }

    onunload() {
        if (this.store && this.original) this.store.difficulty = this.original;
        if (this.observer) this.observer.disconnect();
        this.rebuildTrackerViews();
    }

    install() {
        const tracker = this.app.plugins.plugins[TRACKER_ID];
        const store = tracker && tracker.tracker;
        if (!store || typeof store.difficulty !== "function" || store.difficulty.xgeWrapped) return;
        this.trackerPlugin = tracker;
        this.store = store;
        this.original = store.difficulty;
        const wrapped = (plugin) => this.wrapStore(this.original.call(store, plugin));
        wrapped.xgeWrapped = true;
        store.difficulty = wrapped;

        this.observer = new MutationObserver(() => this.paintHeaders());
        this.observer.observe(document.body, { childList: true, subtree: true });
        // Шапка и полоска берут стор один раз при создании: пересобираем панели.
        this.rebuildTrackerViews();
    }

    rebuildTrackerViews() {
        for (const leaf of this.app.workspace.getLeavesOfType(TRACKER_VIEW)) {
            if (typeof leaf.rebuildView === "function") leaf.rebuildView();
        }
    }

    /** Стор того же вида, что у трекера, но со своим расчётом поверх его обновлений. */
    wrapStore(inner) {
        return {
            subscribe: (run) => inner.subscribe(() => {
                const result = this.compute();
                this.current = result;
                run(result);
                window.setTimeout(() => this.paintHeaders(), 0);
            }),
        };
    }

    compute() {
        const creatures = readStore(this.store) || [];
        const levels = [];
        const monsters = [];
        for (const c of creatures) {
            if (!c || c.enabled === false || c.friendly) continue;
            if (c.player) {
                if (c.level) levels.push(Number(c.level));
                continue;
            }
            monsters.push(c);
        }
        const party = levels.length;
        const level = party ? Math.max(1, Math.min(20, Math.round(levels.reduce((s, l) => s + l, 0) / party))) : 0;

        let worth = 0;
        for (const m of monsters) {
            let cr = parseCr(m.cr);
            if (cr === null && typeof this.trackerPlugin.getCreatureFromBestiary === "function") {
                const base = this.trackerPlugin.getCreatureFromBestiary(m.name);
                cr = parseCr(base && base.cr);
            }
            if (cr === null) cr = 0;
            worth += level ? covers(level, cr) : 0;
        }

        const ratio = party ? worth / party : 0;
        const grade = [...GRADES].reverse().find((g) => ratio >= g.from) || GRADES[0];
        const w = Math.round(worth * 10) / 10;
        const summary = party && monsters.length
            ? `${grade.name} бой.\n` +
              `Монстры стоят ${fmt(w)} ${plural(w, "персонажа", "персонажей", "персонажей")}, в отряде ${party}.\n` +
              `Лёгкий - как на ${fmt(Math.round(party * 2 / 3 * 10) / 10)}, честный - как на ${party}, ` +
              `смертельный - как на ${fmt(Math.round(party * 1.5 * 10) / 10)}.`
            : "Нет отряда или монстров.";
        return {
            difficulty: {
                displayName: grade.name,
                summary,
                cssClass: grade.cls,
                value: party && monsters.length ? Math.max(ratio, 0.001) : 0,
                title: "Сложность",
                intermediateValues: [],
            },
            thresholds: [
                ...GRADES.map((g) => ({ displayName: g.name, minValue: g.from })),
                { displayName: "Шкала", minValue: BAR_MAX },
            ],
            labels: ["Лёгкий", "Смертельный"],
        };
    }

    /** Слово сложности вместо XP в шапке боя. */
    paintHeaders() {
        if (!this.current) return;
        const text = this.current.difficulty.displayName;
        for (const el of document.querySelectorAll(".initiative-tracker-xp.encounter-xp")) {
            if (el.textContent !== text) el.textContent = text;
            el.setAttribute("aria-label", this.current.difficulty.summary);
        }
    }
};
