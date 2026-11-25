"use strict";

/*
 * Погоня по правилам "DnD Lists n Rules/Rules/Погоня/Погоня Правила.md".
 *
 * Открывается тремя способами:
 * - значок бегущего человечка на левой ленте Обсидиана;
 * - команда "Погоня: открыть панель" (Ctrl+P);
 * - кнопка "Начать погоню" в трекере инициативы: противник - тот, чей ход;
 * - код-блок chase в заметке: кнопка, которая кладёт в панель противника,
 *   колоду и стартовую дистанцию и открывает её:
 *
 * ```chase
 * убегающий: Йарно
 * колода: Подземье
 * дистанция: Средняя
 * ```
 *
 * Дистанцию меняют, перетаскивая токен убегающего по дорожке или щёлкая по
 * клетке. Дорожек две: в раунде догоняют двое, и у каждого своя дистанция,
 * иначе группа, где догоняющих больше, получает лишние броски. Первый из пары
 * идёт по первой дорожке, второй - по второй.
 *
 * Карточки показываются печатными картами (image_banner). Ctrl-наведение даёт
 * обычный предпросмотр заметки, щелчок по большой карте - карту на весь экран,
 * двойной щелчок или Ctrl+щелчок - заметку во вкладке. Сцену раунда можно
 * вытянуть наугад или выбрать из колоды местности. Состояние панели хранится
 * в data.json плагина.
 */

const { Plugin, ItemView, MarkdownRenderChild, MarkdownRenderer, Notice, parseYaml, setIcon, TFile } = require("obsidian");

const VIEW = "chase-tracker-view";
const TRACKER_VIEW = "initiative-tracker-view";
const ROOT = "DnD Lists n Rules/Rules/Погоня";
const SCENES = `${ROOT}/Сцены`;
const MOVES = `${ROOT}/Манёвры`;
const PLAYERS = "Adventure/Players/Characters";

const DIST = [
    { name: "Бой", ft: 5 },
    { name: "Близкая", ft: 30 },
    { name: "Средняя", ft: 60 },
    { name: "Дальняя", ft: 120 },
    { name: "Предельная", ft: 240 },
];
const GONE = DIST.length;
const GONE_TIP = "Ушёл";
const RULES = `${ROOT}/Погоня Правила.md`;

const FUGITIVE_MOVES = ["Бег", "Рывок", "Спрятаться", "Помешать", "Выстрел", "Придумать"];
const PURSUER_MOVES = ["Бег", "Рывок", "Срезать", "Окрик", "Выстрел", "Придумать"];

const CSS = `
.chase { padding: 6px 4px; }
.chase-bar { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; margin-bottom: 8px; }
.chase-bar input { width: 9em; }
.chase-bar .chase-sp { flex: 1; }
.chase-status { color: var(--text-muted); }
.chase-lane { display: grid; grid-template-columns: 22px 84px 1fr; gap: 8px; align-items: center; margin: 8px 0; }
/* Первая колонка "Дорожка N" одинаковая в инициативе и на дорожках: узкая полоска с вертикальной подписью. */
.chase-lane-no, .chase-track-label { align-self: stretch; display: flex; align-items: center; justify-content: center; font-size: 0.85em; color: var(--text-muted); border-radius: 6px; background: var(--background-secondary); }
.chase-lane.is-idle { opacity: 0.45; }
.chase-lane-name { font-size: 0.8em; color: var(--text-normal); margin-top: 4px; text-align: center; line-height: 1.1; }
/* Дорожка в том же стиле, что клетки инициативы: отдельные скруглённые плитки, текущая подсвечена акцентом. */
.chase-road { display: grid; grid-template-columns: repeat(6, 1fr); gap: 6px; }
.chase-cell { min-height: 92px; display: flex; flex-direction: column; align-items: center; justify-content: flex-start; gap: 6px;
  padding: 6px 2px 8px; font-size: 0.8em; cursor: pointer; border-radius: 6px; background: var(--background-secondary); }
.chase-cell:hover { background: var(--background-modifier-hover); }
.chase-cell-label { text-align: center; color: var(--text-muted); line-height: 1.15; }
.chase-cell-label small { display: block; color: var(--text-faint); font-size: 0.85em; }
/* Разрыв между догоняющим и убегающим: чем дальше клетка, тем гуще заливка. */
.chase-cell.is-on { background: color-mix(in srgb, var(--interactive-accent) 22%, var(--background-secondary)); }
.chase-cell.is-on .chase-cell-label { color: var(--text-normal); }
.chase-cell.is-drop { box-shadow: inset 0 0 0 2px var(--interactive-accent); }
/* Противник оформлен как токен NPC: тёмная тонкая кайма, цветное кольцо, внутренняя тонкая кайма; внутри только буква. */
.chase-foe { --ring: #b5473a; background: radial-gradient(circle at 50% 40%, #3a3330, #1f1b19); color: #efe6da; border: none;
  box-shadow: inset 0 0 0 1.5px #1e1e1e, inset 0 0 0 5px var(--ring), inset 0 0 0 6.5px #1e1e1e, 0 0 0 1px #1e1e1e, 0 3px 8px rgba(0,0,0,.5); }
.chase-foe.is-mini { box-shadow: inset 0 0 0 1px #1e1e1e, inset 0 0 0 3px var(--ring), inset 0 0 0 4px #1e1e1e, 0 0 0 1px #1e1e1e; }
.chase-foe svg { width: 55%; height: 55%; }
.chase-tok.chase-foe { font-size: 26px; font-weight: 600; line-height: 1; }
.chase-tok.chase-foe.is-big { font-size: 30px; }
.chase-tok.chase-foe.is-mini { font-size: 15px; }
.chase-start { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 2px; }
.chase-tok { width: 56px; height: 56px; border-radius: 50%; object-fit: cover; display: inline-flex; align-items: center; justify-content: center;
  background: var(--background-modifier-border); color: var(--text-normal); font-weight: 700; font-size: 1.3em; margin-top: 4px;
  filter: drop-shadow(0 2px 3px rgba(0,0,0,.5)); }
.chase-tok.is-fug { cursor: grab; }
.chase-tok.is-link { cursor: pointer; }
.chase-tok.is-big { width: 64px; height: 64px; margin: 0; }
.chase-tok.is-mini { width: 32px; height: 32px; margin: 0; font-size: 0.9em; filter: none; }
.chase-banner { margin: 18px 0 6px 0; color: var(--text-normal); }
.chase-banner-title { font-weight: 600; margin-bottom: 2px; }
.chase-h { font-weight: 600; margin: 10px 0 4px; }
.chase-crop { aspect-ratio: 726 / 1026; overflow: hidden; border-radius: 6px; }
.chase-crop img { width: 113.2231% !important; max-width: none !important; height: auto; margin: -6.6116% 0 0 -6.6116%; display: block; }
.chase-scene { display: grid; grid-template-columns: minmax(120px, 200px) 1fr; gap: 22px; align-items: start; }
.chase-scene .chase-crop { cursor: zoom-in; }
.chase-scene p { margin: 0 0 6px; }
.chase-launch { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin: 6px 0; }
.chase-launch button { display: inline-flex; align-items: center; gap: 6px; }
.chase-launch button svg { width: 16px; height: 16px; }
.chase-launch-info { color: var(--text-muted); }
.chase-text { margin: 0; padding: 4px 14px !important; }
.chase-text .markdown-preview-view { padding: 0 !important; }
.chase-dc { position: absolute; top: 14px; right: 14px; font-weight: 600; font-size: 0.95em; padding: 2px 10px; border-radius: 999px;
  border: 1px solid var(--cg); color: var(--text-normal); cursor: pointer; z-index: 2; }
.chase-dc:hover { background: var(--background-modifier-hover); }
.chase-dc.is-edit input { width: 3.5em; padding: 0 4px; height: 1.6em; }
.chase-group { position: relative; --cg: var(--interactive-accent); margin: 12px 0; padding: 4px 12px 10px 12px; border-radius: 8px; border: 1px solid color-mix(in srgb, var(--cg) 45%, transparent); border-left: 5px solid var(--cg); }
.chase-group.is-soft { border-color: var(--background-modifier-border); border-left-color: color-mix(in srgb, var(--cg) 40%, var(--background-modifier-border)); }
.chase-group > .chase-h:first-child, .chase-group > .chase-deck:first-child { margin-top: 6px; }
.chase-group .chase-card.is-current .chase-crop { --hl: var(--cg); }
.chase-deck-head { margin: 10px 0 4px; }
.chase-who { display: flex; align-items: center; gap: 8px; }
.chase-deck > summary.chase-h { margin: 0 0 4px; }
.chase-deck[open] > summary { margin-bottom: 12px; }
.chase-deck[open] { margin-bottom: 16px; }
.chase-deck-head .chase-cards { column-gap: 14px; }
.chase-cards { display: grid; grid-template-columns: repeat(6, 1fr); gap: 6px; }
.chase-card { text-align: center; font-size: 0.8em; cursor: zoom-in; }
.chase-deck .chase-card { cursor: pointer; }
.chase-card.no-img { border: 1px solid var(--background-modifier-border); border-radius: 5px; padding: 18px 2px; }
/* Рамка текущей карты рисуется внутри карты, чтобы не наезжать на соседей. */
.chase-crop { position: relative; }
.chase-card.is-current .chase-crop::after { content: ""; position: absolute; inset: 0; border-radius: inherit; box-shadow: inset 0 0 0 3px var(--hl, var(--interactive-accent)); pointer-events: none; }
.chase-deck { margin: 8px 0; }
.chase-empty { aspect-ratio: 726 / 1026; border: 1px dashed var(--background-modifier-border); border-radius: 6px; display: flex; align-items: center; justify-content: center; text-align: center; color: var(--text-muted); padding: 8px; }
.chase-deck .chase-cards { grid-template-columns: repeat(6, 1fr); }
.chase-deck summary { cursor: pointer; font-weight: 600; margin-bottom: 4px; }
.chase-full { position: fixed; inset: 0; z-index: 1000; background: rgba(0,0,0,.85); display: flex; align-items: center; justify-content: center; cursor: zoom-out; }
.chase-full .chase-crop { height: 94vh; border-radius: 12px; }
.chase-party { display: grid; grid-template-rows: repeat(3, auto); grid-auto-flow: column; gap: 4px 6px; align-items: stretch; margin: 4px 0 10px; }

.chase-pair-head { text-align: center; font-size: 0.85em; color: var(--text-muted); padding: 3px; border-radius: 6px 6px 0 0; cursor: pointer; }
.chase-pair-head.is-current { color: var(--text-on-accent); background: var(--interactive-accent); font-weight: 600; }
.chase-seat { display: flex; align-items: center; gap: 6px; padding: 4px 6px; border-radius: 6px; background: var(--background-secondary); }
.chase-seat.is-current { background: color-mix(in srgb, var(--interactive-accent) 22%, var(--background-secondary)); }
.chase-seat-name { flex: 1; }
.chase-seat input { width: 3.5em; }
.chase-sort { font-weight: normal; }
.chase-icon { display: inline-flex; align-items: center; justify-content: center; width: 36px; height: 36px; padding: 0; border-radius: 8px; background: var(--interactive-normal); box-shadow: var(--input-shadow); color: var(--text-normal); }
.chase-icon:hover { background: var(--interactive-hover); }
.chase-icon svg { width: 20px; height: 20px; }
.chase-gap { width: 24px; }
.chase-seg { display: inline-flex; }
.chase-verb { margin-left: -6px; margin-right: 2px; white-space: pre; }
.chase-bar input[type=text] { padding-left: 6px; }
.chase-bar .chase-seg { margin-left: 6px; }
.chase-seg button { display: inline-flex; align-items: center; gap: 6px; margin: 0; padding: 0; height: auto; background: none !important; box-shadow: none !important; border: none; color: var(--text-normal); font-size: inherit; cursor: pointer; }
.chase-seg button:hover { color: var(--interactive-accent); }
.chase-seg button > span:first-child { display: inline-flex; align-items: center; }
.chase-seg button svg { width: 15px; height: 15px; color: var(--text-muted); display: block; transform: translateY(1px); }
.chase-reset { color: var(--text-muted); }
.chase-reset:hover { color: var(--text-error); }
.chase-step { margin-left: 6px; font-weight: normal; }
.chase-peek { position: fixed; z-index: 1000; width: 150px; padding: 10px; border-radius: 8px; background: var(--background-primary);
  border: 1px solid var(--background-modifier-border); box-shadow: 0 6px 18px rgba(0,0,0,.45); pointer-events: none; }
.chase-peek-name { font-weight: 600; margin-bottom: 6px; }
.chase-peek.is-empty .chase-peek-name { font-weight: normal; text-align: center; color: var(--text-muted); margin: 0; }
.chase-peek .chase-scene { grid-template-columns: 200px 1fr; gap: 14px; align-items: stretch; }
.chase-peek .chase-scene > div:last-child { display: flex; }
.chase-peek .chase-text { flex: 1; display: flex; align-items: center; }
.chase-round { margin-left: auto; margin-right: 10px; padding: 3px 14px; border-radius: 999px; font-size: 1em; font-weight: normal; background: var(--interactive-accent); color: var(--text-on-accent); }`;

function asList(v) {
    if (v == null) return [];
    if (Array.isArray(v)) return v.map((x) => String(x).trim()).filter(Boolean);
    return String(v).split(",").map((x) => x.trim()).filter(Boolean);
}

function section(text, title) {
    const lines = text.split("\n");
    const start = lines.findIndex((l) => l.trim() === `# ${title}`);
    if (start < 0) return "";
    const out = [];
    for (let i = start + 1; i < lines.length; i++) {
        if (/^# /.test(lines[i])) break;
        out.push(lines[i]);
    }
    return out.join("\n").trim();
}

function distIndex(name, fallback) {
    const i = DIST.findIndex((d) => d.name.toLowerCase() === String(name || "").trim().toLowerCase());
    return i >= 0 ? i : fallback;
}

function freshState(conf) {
    return { round: 1, dists: [conf.start, conf.start], scene: null, drawn: [] };
}

/* Раньше дорожка была одна: state.dist. Теперь у каждого из пары своя. */
function migrate(state, conf) {
    if (!Array.isArray(state.dists)) {
        const d = typeof state.dist === "number" ? state.dist : conf.start;
        state.dists = [d, d];
        delete state.dist;
    }
    if (!state.inits || typeof state.inits !== "object") state.inits = {};
    if (!state.moves || typeof state.moves !== "object") state.moves = {};
    if (typeof state.pair !== "number") state.pair = Math.max(0, (state.round || 1) - 1);
    return state;
}

/* Одна погоня: настройки conf, состояние state, отрисовка в el. */
class Chase {
    constructor(plugin, el, conf, state, persist, owner, sourcePath, editable) {
        this.plugin = plugin;
        this.app = plugin.app;
        this.el = el;
        this.conf = conf;
        this.state = migrate(state, conf);
        this.persist = persist;
        this.owner = owner;
        this.sourcePath = sourcePath || "";
        this.editable = editable;
    }

    files(prefix) {
        return this.app.vault.getMarkdownFiles().filter((f) => f.path.startsWith(prefix));
    }

    decks() {
        const set = new Set(this.files(`${SCENES}/`).map((f) => f.parent.name));
        return [...set].sort((a, b) => a.localeCompare(b, "ru"));
    }

    /* Картинка карточки: печатная карта (image_banner), без неё - иллюстрация. */
    image(file) {
        const fm = this.app.metadataCache.getFileCache(file)?.frontmatter || {};
        for (const key of ["image_banner", "image_raw"]) {
            if (!fm[key]) continue;
            const name = String(fm[key]).replace(/^\[\[|\]\]$/g, "").split("|")[0];
            const img = this.app.metadataCache.getFirstLinkpathDest(name, file.path);
            if (img) return this.app.vault.getResourcePath(img);
        }
        return null;
    }

    token(name) {
        if (!name) return null;
        const first = name.split(/[ ,]/)[0];
        const pngs = this.app.vault.getFiles().filter((f) => / токен$/.test(f.basename));
        const hit = pngs.find((f) => f.basename === `${name} токен`) || pngs.find((f) => f.basename.startsWith(first + " ") || f.basename === `${first} токен`);
        return hit ? this.app.vault.getResourcePath(hit) : null;
    }

    pursuers() {
        if (this.conf.pursuers.length) return this.conf.pursuers;
        return this.files(`${PLAYERS}/`)
            .filter((f) => f.parent.path === PLAYERS)
            .map((f) => ({ f, order: Number(this.app.metadataCache.getFileCache(f)?.frontmatter?.order) || 99 }))
            .sort((a, b) => a.order - b.order || a.f.basename.localeCompare(b.f.basename, "ru"))
            .map((x) => x.f.basename);
    }

    findScene(name) {
        const all = this.files(`${SCENES}/`);
        return all.find((f) => f.basename === name && f.parent.name === this.conf.deck) || all.find((f) => f.basename === name) || null;
    }

    deckScenes() {
        return this.files(`${SCENES}/${this.conf.deck}/`).sort((a, b) => a.basename.localeCompare(b.basename, "ru"));
    }

    drawScene() {
        const st = this.state;
        const deck = this.deckScenes();
        let pool = deck.filter((f) => !st.drawn.includes(f.path));
        if (!pool.length) {
            st.drawn = [];
            pool = deck;
        }
        if (!pool.length) {
            st.scene = null;
            return;
        }
        const f = pool[Math.floor(Math.random() * pool.length)];
        st.scene = f.path;
        st.drawn.push(f.path);
    }

    /* Мастер выбрал сцену из колоды сам. */
    pickScene(file) {
        const st = this.state;
        st.scene = file.path;
        if (!st.drawn.includes(file.path)) st.drawn.push(file.path);
        this.commit();
    }

    commit() {
        this.persist(this.conf, this.state);
        this.render();
    }

    setDist(track, i) {
        this.state.dists[track] = Math.min(GONE, Math.max(0, i));
        this.commit();
    }

    /* Заметка карточки во вкладке рядом: на месте панели погоню не теряем. */
    card(file) {
        this.app.workspace.openLinkText(file.path, this.sourcePath, "tab");
    }

    /* Печатная карта на весь экран; закрывается щелчком или Esc. */
    fullscreen(file) {
        const over = document.body.createDiv({ cls: "chase-full" });
        this.picture(over, file);
        const close = () => {
            over.remove();
            document.removeEventListener("keydown", onKey, true);
        };
        const onKey = (e) => {
            if (e.key === "Escape") {
                e.stopPropagation();
                close();
            }
        };
        over.onclick = close;
        document.addEventListener("keydown", onKey, true);
    }

    /* Ctrl-наведение показывает заметку карточки обычным предпросмотром Обсидиана. */
    hover(el, file) {
        el.addEventListener("mouseover", (event) => {
            this.app.workspace.trigger("hover-link", {
                event,
                source: "chase-tracker",
                hoverParent: this.owner,
                targetEl: el,
                linktext: file.path,
                sourcePath: this.sourcePath,
            });
        });
    }

    /* Печатная карта без чёрной рамки под обрез: рамка 48 px из 822 по ширине. */
    picture(parent, file, title) {
        const src = this.image(file);
        if (!src) return null;
        const banner = !!this.app.metadataCache.getFileCache(file)?.frontmatter?.image_banner;
        const box = parent.createDiv({ cls: banner ? "chase-crop" : "" });
        box.createEl("img", { attr: { src, title: title || file.basename } });
        return box;
    }

    /* Противник у каждой погони свой, поэтому вместо портрета у него значок роли. */
    /* Рисованные значки погони из _img/chase/icons. */
    icon(name) {
        const f = this.app.vault.getAbstractFileByPath(`_img/chase/icons/${name}.png`);
        return f instanceof TFile ? this.app.vault.getResourcePath(f) : null;
    }

    /* Противник у каждой погони свой, поэтому вместо портрета у него общий значок. */
    foeTok(parent, cls) {
        const tf = this.conf.foeToken ? this.app.vault.getAbstractFileByPath(this.conf.foeToken) : null;
        if (tf instanceof TFile) {
            return parent.createEl("img", { cls: `chase-tok ${cls}`, attr: { src: this.app.vault.getResourcePath(tf), title: this.foeLabel() } });
        }
        const t = parent.createDiv({ cls: `chase-tok chase-foe ${cls}`, attr: { title: this.foeLabel() } });
        // Противник любой: человек, зверь, повозка. Поэтому без картинки, только первая буква имени.
        t.setText((this.foeName() || (this.conf.flee ? "Д" : "У")).slice(0, 1).toUpperCase());
        return t;
    }

    tok(parent, name, cls) {
        const src = this.token(name);
        const t = src
            ? parent.createEl("img", { cls: `chase-tok ${cls}`, attr: { src, title: name } })
            : parent.createDiv({ cls: `chase-tok ${cls}`, text: (name || "?").slice(0, 1), attr: { title: name } });
        return t;
    }

    async md(parent, text) {
        await MarkdownRenderer.render(this.app, text, parent, this.sourcePath, this.owner);
    }

    renderBar(box) {
        const conf = this.conf;
        const bar = box.createDiv({ cls: "chase-bar" });
        // Кнопки как в Initiative Tracker: значки без подписи, подсказка при наведении.
        const icon = (name, label, fn) => {
            const b = bar.createDiv({ cls: "clickable-icon chase-icon", attr: { "aria-label": label } });
            setIcon(b, name);
            b.onclick = fn;
            return b;
        };
        const reset = () => {
            // Сброс возвращает и инициативу: отряд снова сидит по order из карточек.
            this.state = migrate(freshState(conf), conf);
            this.drawScene();
            this.commit();
        };
        if (this.editable) {
            // Сброс в другом конце ряда от кнопок раундов и только двойным щелчком,
            // чтобы случайный щелчок не стёр идущую погоню.
            const r = icon("rotate-ccw", "Сначала: двойной щелчок", () => new Notice("Погоня сбрасывается двойным щелчком"));
            r.addClass("chase-reset");
            r.ondblclick = reset;
            bar.createDiv({ cls: "chase-gap" });

            // Что делает отряд: догоняет противника или убегает от него.
            // Одна кнопка-щелкунок: показывает текущее, щелчок переключает на другое.
            const seg = bar.createDiv({ cls: "chase-seg" });
            const b = seg.createEl("button", {
                text: conf.flee ? "Отряд убегает" : "Отряд догоняет",
                attr: { "aria-label": conf.flee ? "Щелчок: отряд догоняет" : "Щелчок: отряд убегает" },
            });
            b.empty();
            setIcon(b.createSpan(), "arrow-left-right");
            b.createSpan({ text: conf.flee ? "Отряд убегает" : "Отряд догоняет" });
            b.onclick = () => {
                conf.flee = !conf.flee;
                this.state.moves = {};
                this.commit();
            };
            bar.createSpan({ cls: "chase-verb", text: conf.flee ? ", догоняет" : ", убегает" });
            const who = bar.createEl("input", { type: "text", value: this.foeName(), attr: { placeholder: "имя противника" } });
            who.onchange = () => {
                conf.fugitive = who.value.trim();
                conf.foeToken = null;
                this.commit();
            };
        } else {
            bar.createSpan({ text: `${conf.flee ? "Отряд убегает от" : "Отряд догоняет"}: ${this.foeLabel()}, ${conf.deck}` });
        }
        bar.createDiv({ cls: "chase-sp" });
        icon("skip-back", "Предыдущий раунд", () => this.step(-1));
        icon("skip-forward", "Следующий раунд", () => this.step(1));
    }

    /* Шаг раунда вперёд или назад; кнопки стоят справа в верхней строке. */
    step(d) {
        {
            if (d < 0 && this.state.round <= 1) return;
            if (d > 0 && this.outcome()) {
                new Notice("Погоня окончена: поправьте дистанцию или начните сначала");
                return;
            }
            this.state.round += d;
            const n = this.pairs().length;
            this.state.pair = n ? (((this.state.pair + d) % n) + n) % n : 0;
            this.state.moves = {};
            // Новый раунд: колоды снова раскрываются до первого выбора и сворачиваются после.
            for (const k of ["open:scene", "open:fug", "open:p0", "open:p1"]) delete this.plugin.ui[k];
            if (d > 0) this.drawScene();
            this.commit();
        }
    }

    /* Роли: отряд догоняет (противник убегает) или отряд убегает (противник догоняет). */
    foeRole() {
        return this.conf.flee ? "Догоняющий" : "Убегающий";
    }

    partyRole() {
        return this.conf.flee ? "Убегающий" : "Догоняющий";
    }

    /* Имя противника; ролевые заглушки прежних версий за имя не считаются. */
    foeName() {
        const n = String(this.conf.fugitive || "").trim();
        return n === "Убегающий" || n === "Догоняющий" ? "" : n;
    }

    foeLabel() {
        return this.foeName() || this.foeRole();
    }

    /* Отряд по инициативе: больше - раньше; без инициативы - по order карточки. */
    ordered() {
        const team = this.pursuers();
        const inits = this.state.inits;
        const val = (n) => (typeof inits[n] === "number" ? inits[n] : -Infinity);
        return team.map((n, i) => ({ n, i })).sort((a, b) => val(b.n) - val(a.n) || a.i - b.i).map((x) => x.n);
    }

    /*
     * Таблица заполняется строками: первая дорожка - первая половина отряда по
     * инициативе, вторая - вторая половина. Пара - это столбец: i-й с первой
     * дорожки и i-й со второй.
     */
    pairs() {
        const order = this.ordered();
        const n = Math.ceil(order.length / 2);
        const out = [];
        for (let i = 0; i < n; i++) out.push([order[i], order[n + i] || null]);
        return out;
    }

    /* Пара этого раунда: первый идёт по первой дорожке, второй - по второй. */
    pair() {
        const all = this.pairs();
        return all.length ? all[this.state.pair % all.length] : [null, null];
    }

/*
     * Отряд одной таблицей: столбцы - пары по инициативе (кто ходит в каком
     * раунде), строки - дорожки. Первый из каждой пары всегда идёт по
     * дорожке 1, второй - по дорожке 2, это и видно по строкам. Инициатива
     * вводится прямо в клетках; пока фокус ходит по полям, ничего не
     * перерисовывается, а когда фокус ушёл из таблицы (Tab с последнего поля,
     * Enter, щелчок мимо или кнопка), отряд пересаживается по парам.
     */
    renderParty(box) {
        const pairs = this.pairs();
        const cur = this.state.pair % Math.max(1, pairs.length);
        const head = box.createDiv({ cls: "chase-h chase-who" });
        head.appendText("Инициатива");
        head.createSpan({ cls: "chase-round", text: `Раунд ${this.state.round}` });
        const sort = head.createDiv({ cls: "clickable-icon chase-icon chase-sort", attr: { "aria-label": "Рассадить по парам" } });
        setIcon(sort, "arrow-down-wide-narrow");

        const grid = box.createDiv({ cls: "chase-party" });
        grid.style.gridTemplateColumns = `22px repeat(${Math.max(1, pairs.length)}, 1fr)`;
        let dirty = false;
        const apply = () => {
            if (!dirty) return;
            dirty = false;
            this.commit();
        };
        sort.onclick = apply;
        grid.addEventListener("focusout", (e) => {
            if (!(e.relatedTarget instanceof Node && grid.contains(e.relatedTarget))) apply();
        });

        // Tab идёт по таблице слева направо по первой дорожке, потом по второй.
        const order = [0, 1].flatMap((track) => pairs.map((p) => p[track]).filter(Boolean));
        const inputs = new Map();
        // Сетка заполняется по столбцам: так Tab идёт по паре сверху вниз, потом к следующей.
        grid.createDiv();
        [0, 1].forEach((track) => grid.createDiv({ cls: "chase-track-label", text: String(track + 1), attr: { "aria-label": `Дорожка ${track + 1}` } }));
        pairs.forEach((p, i) => {
            const h = grid.createDiv({ cls: "chase-pair-head" + (i === cur ? " is-current" : ""), text: `Пара ${i + 1}` });
            h.title = "Эта пара догоняет в текущем раунде";
            h.onclick = () => {
                this.state.pair = i;
                delete this.state.moves.p0;
                delete this.state.moves.p1;
                this.commit();
            };
            [0, 1].forEach((track) => {
                const cell = grid.createDiv({ cls: "chase-seat" + (i === cur ? " is-current" : "") });
                const name = p[track];
                if (!name) return;
                this.tok(cell, name, "is-mini");
                cell.createSpan({ text: name, cls: "chase-seat-name" });
                const v = this.state.inits[name];
                const inp = cell.createEl("input", { type: "number", value: typeof v === "number" ? String(v) : "" });
                inp.oninput = () => {
                    const x = parseInt(inp.value, 10);
                    if (Number.isFinite(x)) this.state.inits[name] = x;
                    else delete this.state.inits[name];
                    this.state.pair = 0;
                    delete this.state.moves.p0;
                    delete this.state.moves.p1;
                    dirty = true;
                    this.persist(this.conf, this.state);
                };
                inputs.set(name, inp);
                inp.onkeydown = (e) => {
                    if (e.key === "Enter") {
                        e.preventDefault();
                        apply();
                        return;
                    }
                    if (e.key === "Tab") {
                        const i = order.indexOf(name) + (e.shiftKey ? -1 : 1);
                        const next = i >= 0 && i < order.length ? inputs.get(order[i]) : null;
                        if (next) {
                            e.preventDefault();
                            next.focus();
                            next.select();
                        }
                    }
                };
            });
        });
    }

    /* Чем кончилась погоня: первая дорожка, где догнали или оторвались. */
    outcome() {
        const pair = this.pair();
        for (const track of [0, 1]) {
            const dist = this.state.dists[track];
            if (!pair[track] || (dist > 0 && dist < GONE)) continue;
            const flee = !!this.conf.flee;
            const runner = flee ? pair[track] : this.foeLabel();
            const chaser = flee ? this.foeLabel() : pair[track];
            return { track, caught: dist <= 0, runner, chaser };
        }
        return null;
    }

    renderRoad(box) {
        const pair = this.pair();
        const st = this.state;
        // Одна дорожка решает за всех: догнали или оторвались - погоня окончена.
        const end = this.outcome();
        [0, 1].forEach((track) => this.renderTrack(box, track, pair[track], end));
        if (end) {
            const b = box.createDiv({ cls: "chase-banner " + (end.caught ? "is-caught" : "is-gone") });
            b.createDiv({ cls: "chase-banner-title", text: "Погоня окончена" });
            b.createDiv({
                text: end.caught
                    ? `${end.chaser} и ${end.runner} сходятся в бою. Бросайте инициативу.`
                    : `${end.runner} уходит дальше предельной, ${end.chaser} теряет след.`,
            });
        }
    }

    renderTrack(box, track, who, end) {
        const dist = this.state.dists[track];
        // Слева стоит догоняющий, по дорожке от него уходит убегающий.
        const flee = !!this.conf.flee;
        const chaser = flee ? this.foeLabel() : who;
        const runner = flee ? who : this.foeLabel();
        const lane = box.createDiv({ cls: "chase-lane" });
        lane.createDiv({ cls: "chase-lane-no", text: String(track + 1), attr: { "aria-label": `Дорожка ${track + 1}` } });
        const start = lane.createDiv({ cls: "chase-start" });
        if (chaser) {
            // Щелчок по портрету ведёт к выбору его манёвра.
            const t = flee ? this.foeTok(start, "is-big") : this.tok(start, chaser, "is-big");
            t.addClass("is-link");
            t.onclick = () => this.gotoMove(flee ? "fug" : `p${track}`);
            this.peek(t, flee ? "fug" : `p${track}`);
        }
        start.createDiv({ cls: "chase-lane-name", text: chaser || "" });

        const road = lane.createDiv({ cls: "chase-road" });
        const cells = [...DIST, { name: "Ушёл", ft: null }];
        cells.forEach((d, i) => {
            const cell = road.createDiv({ cls: "chase-cell" });
            if (i > 0 && i < dist) cell.addClass("is-gap");
            if (i === dist) cell.addClass("is-on");
            if (i === 0) cell.addClass("is-fight");
            if (i === GONE) cell.addClass("is-gone");
            const label = cell.createDiv({ cls: "chase-cell-label" });
            label.createSpan({ text: d.name });
            label.createEl("small", { text: d.ft ? `${d.ft} фт.` : "дальше 240 фт." });
            const tip = this.plugin.distTips[d.name] || (i === GONE ? this.plugin.distTips[GONE_TIP] : "");
            if (tip) cell.setAttr("aria-label", tip);
            cell.onclick = () => this.setDist(track, i);
            cell.ondragover = (e) => {
                e.preventDefault();
                cell.addClass("is-drop");
            };
            cell.ondragleave = () => cell.removeClass("is-drop");
            cell.ondrop = (e) => {
                e.preventDefault();
                if (e.dataTransfer.getData("text/plain") === `chase-${track}`) this.setDist(track, i);
                else cell.removeClass("is-drop");
            };
            // Чем дальше ушёл убегающий, тем гуще и ярче след: уровень 1..5 по клетке.
            cell.style.setProperty("--lvl", String(i));
            // calc() внутри color-mix Обсидиан не понимает, поэтому процент считается здесь.
            if (i > 0 && i < dist) cell.style.background = `color-mix(in srgb, var(--interactive-accent) ${6 + i * 5}%, var(--background-secondary))`;
            if (i === dist && i > 0 && i < GONE) cell.style.background = `color-mix(in srgb, var(--interactive-accent) ${14 + i * 6}%, var(--background-secondary))`;
            if (i === dist) {
                const t = flee ? this.tok(cell, runner, "is-fug") : this.foeTok(cell, "is-fug");
                t.draggable = true;
                t.ondragstart = (e) => {
                    this.unpeek();
                    e.dataTransfer.setData("text/plain", `chase-${track}`);
                };
                this.peek(t, flee ? `p${track}` : "fug");
                t.addClass("is-link");
                t.onclick = (e) => {
                    e.stopPropagation();
                    this.unpeek();
                    this.gotoMove(flee ? `p${track}` : "fug");
                };
            }
        });
    }

    /*
     * Колода одним видом: слева печатная карта, справа её описание и механика
     * из заметки. Над ними раскрывающаяся строка "Сцена: Топь" с выбором другой
     * карты из той же колоды.
     * opts: title, label, files, current (путь), pick(file), drawn (пути), head(box).
     */
    async renderPanel(box, opts) {
        if (opts.head) opts.head(box);
        else {
            const h = box.createDiv({ cls: "chase-h chase-who" });
            if (opts.who) {
                // Щелчок по токену в заголовке возвращает к началу панели, к дорожкам.
                const t = opts.foe ? this.foeTok(h, "is-mini") : this.tok(h, opts.who, "is-mini");
                t.addClass("is-link");
                t.onclick = () => this.gotoTop();
            }
            h.appendText(opts.title);
        }
        const file = opts.current ? this.app.vault.getAbstractFileByPath(opts.current) : null;
        const key = `open:${opts.id}`;
        const details = box.createEl("details", { cls: "chase-deck" });
        // Пока карта не выбрана, колода раскрыта; первый выбор её сворачивает.
        // Раскрыл руками - остаётся раскрытой и при перевыборе. Запоминается только
        // щелчок по строке, а не программное раскрытие.
        details.open = !(file instanceof TFile) || !!this.plugin.ui[key];
        const summary = details.createEl("summary", { cls: "chase-h", text: `${opts.label}: ${file instanceof TFile ? file.basename : "не выбрана"}` });
        summary.addEventListener("click", () => (this.plugin.ui[key] = !details.open));
        const cards = details.createDiv({ cls: "chase-cards" });
        for (const f of opts.files) {
            const c = cards.createDiv({ cls: "chase-card" });
            if (opts.current === f.path) c.addClass("is-current");
            else if (opts.drawn && opts.drawn.includes(f.path)) c.addClass("is-drawn");
            if (!this.picture(c, f)) {
                c.addClass("no-img");
                c.createDiv({ text: f.basename });
            }
            c.onclick = () => opts.pick(f);
            this.hover(c, f);
        }

        const grid = box.createDiv({ cls: "chase-scene" });
        const left = grid.createDiv();
        const right = grid.createDiv();
        if (file instanceof TFile) {
            const pic = this.picture(left, file);
            if (pic) {
                // Щелчок - карта на весь экран; двойной щелчок или Ctrl - заметка во вкладке.
                let timer = null;
                pic.onclick = (e) => {
                    if (e.ctrlKey || e.metaKey) return this.card(file);
                    clearTimeout(timer);
                    timer = setTimeout(() => this.fullscreen(file), 250);
                };
                pic.ondblclick = () => {
                    clearTimeout(timer);
                    this.card(file);
                };
                this.hover(pic, file);
            }
            await this.cardText(right, file);
        } else {
            left.createDiv({ cls: "chase-empty", text: opts.empty || "Карта не выбрана" });
        }
    }

    /*
     * Текст карточки берётся из заметки при каждой отрисовке и рисуется одним блоком
     * с теми же классами, что у встроенной заметки, чтобы тема оформила его так же.
     */
    async cardText(right, file) {
        {
            const text = await this.app.vault.cachedRead(file);
            const body = ["Описание", "Механика"]
                .map((h) => [h, section(text, h)])
                .filter(([, s]) => s)
                .map(([h, s], _, all) => (all.length > 1 ? `# ${h}\n${s}` : s))
                .join("\n\n");
            const embed = right.createDiv({ cls: "internal-embed markdown-embed inline-embed is-loaded chase-text" });
            const view = embed.createDiv({ cls: "markdown-embed-content" }).createDiv({ cls: "markdown-preview-view markdown-rendered" });
            await MarkdownRenderer.render(this.app, body, view, file.path, this.owner);
        }
    }

    async renderScene(box) {
        const st = this.state;
        if (!st.scene && !st.drawn.length) {
            this.drawScene();
            this.persist(this.conf, st);
        }
        let empty = null;
        if (!st.scene) empty = `В колоде "${this.conf.deck}" нет сцен.`;
        else if (st.scene.startsWith("?")) empty = `Сцена "${st.scene.slice(1)}" не найдена.`;
        await this.renderPanel(box, {
            id: "scene",
            title: `Сцена: ${this.conf.deck}`,
            files: this.deckScenes(),
            current: empty ? null : st.scene,
            drawn: st.drawn,
            empty,
            label: "Сцена",
            pick: (f) => this.pickScene(f),
            head: (b) => this.renderDeckPick(b),
        });
    }

    /* Цвет рубашки колоды: поле color в заметке Деки/<колода>.md. */
    deckColor(deck) {
        const f = this.app.vault.getAbstractFileByPath(`${ROOT}/Деки/${deck}.md`);
        const c = f instanceof TFile ? this.app.metadataCache.getFileCache(f)?.frontmatter?.color : null;
        return c ? String(c) : null;
    }

    group(box, deck) {
        const g = box.createDiv({ cls: "chase-group" });
        const c = this.deckColor(deck);
        if (c) g.style.setProperty("--cg", c);
        return g;
    }

    /* Рубашки колод местности: заметки в Деки с тем же именем, что папка сцен. */    deckFiles() {
        return this.decks()
            .map((d) => this.app.vault.getAbstractFileByPath(`${ROOT}/Деки/${d}.md`))
            .filter((f) => f instanceof TFile);
    }

    /* Заголовок "Колода: Лес" раскрывается в рубашки колод местности. */
    renderDeckPick(box) {
        const st = this.state;
        const title = `Колода: ${this.conf.deck}`;
        if (!this.editable) {
            box.createDiv({ cls: "chase-h", text: title });
            return;
        }
        const details = box.createEl("details", { cls: "chase-deck chase-deck-head" });
        details.open = !!this.plugin.ui["open:decks"];
        details.ontoggle = () => (this.plugin.ui["open:decks"] = details.open);
        details.createEl("summary", { cls: "chase-h", text: title });
        const row = details.createDiv({ cls: "chase-cards" });
        row.style.gridTemplateColumns = `repeat(${Math.max(1, this.deckFiles().length)}, 1fr)`;
        for (const f of this.deckFiles()) {
            const c = row.createDiv({ cls: "chase-card" });
            if (f.basename === this.conf.deck) c.addClass("is-current");
            if (!this.picture(c, f)) {
                c.addClass("no-img");
                c.createDiv({ text: f.basename });
            }
            c.onclick = () => {
                if (f.basename === this.conf.deck) return;
                this.conf.deck = f.basename;
                st.drawn = [];
                this.drawScene();
                this.commit();
            };
            this.hover(c, f);
        }
    }

    moveFiles(side, names) {
        return names
            .map((m) => this.app.vault.getAbstractFileByPath(`${MOVES}/${side}/${m}.md`))
            .filter((f) => f instanceof TFile);
    }

    /* Манёвр стороны: slot - "fug", "p0" или "p1". Выбор живёт до конца раунда. */
    /* Наведение на токен дорожки показывает выбранную карту манёвра этого участника. */
    peek(el, slot) {
        el.addEventListener("mouseenter", () => {
            this.unpeek();
            const path = this.state.moves[slot];
            const file = path ? this.app.vault.getAbstractFileByPath(path) : null;
            const pop = document.body.createDiv({ cls: "chase-peek" });
            this.peekEl = pop;
            this.plugin.peek = { pop, anchor: el };
            if (file instanceof TFile) {
                // Тот же вид, что в блоке манёвра: карта слева, текст карточки справа.
                const grid = pop.createDiv({ cls: "chase-scene" });
                this.picture(grid.createDiv(), file);
                const right = grid.createDiv();
                this.cardText(right, file);
            } else {
                pop.addClass("is-empty");
                pop.createDiv({ cls: "chase-peek-name", text: "манёвр не выбран" });
            }
            const r = el.getBoundingClientRect();
            const w = file instanceof TFile ? 600 : 150;
            pop.style.width = `${w}px`;
            pop.style.left = `${Math.max(8, Math.min(window.innerWidth - w - 8, r.left + r.width / 2 - w / 2))}px`;
            pop.style.top = `${r.bottom + 8}px`;
            const h = pop.getBoundingClientRect().height;
            if (r.bottom + 8 + h > window.innerHeight) pop.style.top = `${Math.max(8, r.top - h - 8)}px`;
        });
        el.addEventListener("mouseleave", () => this.unpeek());
    }

    unpeek() {
        if (this.peekEl) this.peekEl.remove();
        this.peekEl = null;
        this.plugin.peek = null;
    }

    gotoTop() {
        let s = this.el;
        while (s && s.scrollHeight <= s.clientHeight) s = s.parentElement;
        if (s) s.scrollTo({ top: 0, behavior: "smooth" });
    }

    gotoMove(slot) {
        const g = this.el.querySelector(`.chase-group[data-slot="${slot}"]`);
        if (!g) return;
        // Колода раскрывается, если карта не выбрана, а у противника всегда:
        // его карту тянет плагин, и Мастер приходит её посмотреть и переложить.
        const d = g.querySelector("details.chase-deck");
        if (d && (slot === "fug" || !this.state.moves[slot])) d.open = true;
        g.scrollIntoView({ behavior: "smooth", block: "start" });
    }

    async renderMove(box, slot, title, side, names, who) {
        box.dataset.slot = slot;
        const st = this.state;
        await this.renderPanel(box, {
            id: slot,
            title,
            files: this.moveFiles(side, names),
            current: st.moves[slot] || null,
            label: "Манёвр",
            who,
            foe: slot === "fug",
            pick: (f) => {
                st.moves[slot] = f.path;
                this.commit();
            },
        });
    }

    /*
     * Новая отрисовка собирается рядом со старой, скрытой, и подменяет её
     * целиком, когда готова: иначе высота на миг схлопывается и прокрутка
     * прыгает. Позиция прокрутки сохраняется и восстанавливается.
     */
    /*
     * Подсказки к дистанциям берутся из таблицы "Дистанция" в правилах погони
     * (столбец "Что значит"), чтобы текст жил в одном месте.
     */
    async loadTips() {
        const f = this.app.vault.getAbstractFileByPath(RULES);
        const tips = {};
        if (f instanceof TFile) {
            const text = await this.app.vault.cachedRead(f);
            for (const line of text.split("\n")) {
                const cols = line.split("|").map((s) => s.trim());
                if (cols.length < 5) continue;
                const name = cols[1];
                if (DIST.some((d) => d.name === name)) tips[name] = cols[3];
            }
            if (tips["Предельная"]) tips[GONE_TIP] = "дистанция увеличилась после предельной, ушёл";
        }
        this.plugin.distTips = tips;
    }

    /* DC в углу блока сцены; щелчок превращает его в поле, Enter или уход - сохранить, Esc - отмена. */
    renderDc(box) {
        const dc = box.createDiv({ cls: "chase-dc", text: `DC ${this.conf.dc}`, attr: { "aria-label": "Сложность простых проверок погони. Щелчок - поменять" } });
        dc.onclick = () => {
            dc.empty();
            dc.addClass("is-edit");
            dc.appendText("DC ");
            const inp = dc.createEl("input", { type: "number", value: String(this.conf.dc) });
            inp.focus();
            inp.select();
            let done = false;
            const finish = (save) => {
                if (done) return;
                done = true;
                const x = parseInt(inp.value, 10);
                if (save && Number.isFinite(x) && x > 0) this.conf.dc = x;
                this.commit();
            };
            inp.onkeydown = (e) => {
                if (e.key === "Enter") finish(true);
                if (e.key === "Escape") finish(false);
            };
            inp.onblur = () => finish(true);
        };
    }

    async render() {
        this.unpeek();
        const token = (this.renderToken = (this.renderToken || 0) + 1);
        let scroller = this.el;
        while (scroller && scroller.scrollHeight <= scroller.clientHeight) scroller = scroller.parentElement;
        const top = scroller ? scroller.scrollTop : 0;

        if (!this.plugin.distTips) await this.loadTips();
        const box = this.el.createDiv({ cls: "chase" });
        box.style.display = "none";
        this.renderBar(box);
        // Инициатива и дорожки - такие же плашки, как колоды; кромка инициативы - цвет колоды отряда.
        const party = this.group(box, this.partyRole());
        party.addClass("is-soft");
        this.renderParty(party);
        this.renderRoad(this.group(box, null));
        // Группы рисуются плашками с цветной кромкой: сцена, убегающий, догоняющие.
        // Кромка группы - основной цвет рубашки её колоды (поле color в заметке колоды).
        const scene = this.group(box, this.conf.deck);
        this.renderDc(scene);
        await this.renderScene(scene);
        const [a, b] = this.pair();
        const foe = this.foeRole();
        const mine = this.partyRole();
        const moves = (role) => (role === "Убегающий" ? FUGITIVE_MOVES : PURSUER_MOVES);
        // За противника карту манёвра тянет плагин, наугад, как сцену: каждый новый
        // раунд, после сброса и при смене ролей. Мастер может переложить её руками.
        if (!this.state.moves.fug) {
            const pool = this.moveFiles(foe, moves(foe));
            if (pool.length) {
                this.state.moves.fug = pool[Math.floor(Math.random() * pool.length)].path;
                this.persist(this.conf, this.state);
            }
        }
        const foeTitle = this.foeName() ? `${foe}: ${this.foeName()}` : foe;
        await this.renderMove(this.group(box, foe), "fug", foeTitle, foe, moves(foe), this.foeLabel());
        if (a) await this.renderMove(this.group(box, mine), "p0", `${mine}: ${a} (дорожка 1)`, mine, moves(mine), a);
        if (b) await this.renderMove(this.group(box, mine), "p1", `${mine}: ${b} (дорожка 2)`, mine, moves(mine), b);

        if (token !== this.renderToken) {
            box.remove();
            return;
        }
        for (const old of [...this.el.children]) if (old !== box) old.remove();
        box.style.display = "";
        if (scroller) scroller.scrollTop = top;
    }
}

function parseConf(source) {
    let raw = {};
    try {
        raw = parseYaml(source) || {};
    } catch (e) {
        raw = {};
    }
    const pick = (...keys) => keys.map((k) => raw[k]).find((v) => v != null);
    return {
        fugitive: String(pick("противник", "убегающий", "догоняющий", "fugitive") || ""),
        flee: /убега/i.test(String(pick("отряд", "party") || "")) || raw["догоняющий"] != null,
        deck: String(pick("колода", "местность", "deck") || "Подземье"),
        start: distIndex(pick("дистанция", "start"), 1),
        pursuers: asList(pick("догоняющие", "pursuers")),
        dc: Number(pick("сложность", "dc")) || 12,
    };
}

/*
 * Блок chase в заметке - кнопка запуска. Погоня всегда идёт в панели: блок кладёт в
 * неё противника, колоду и стартовую дистанцию, сбрасывает погоню и открывает панель.
 */
class ChaseBlock extends MarkdownRenderChild {
    constructor(plugin, el, source, ctx) {
        super(el);
        this.plugin = plugin;
        this.conf = parseConf(source);
        this.raw = source;
    }

    onload() {
        const c = this.conf;
        const row = this.containerEl.createDiv({ cls: "chase-launch" });
        const b = row.createEl("button", { cls: "mod-cta" });
        setIcon(b.createSpan(), "footprints");
        b.createSpan({ text: "Начать погоню" });
        const who = c.fugitive || (c.flee ? "Догоняющий" : "Убегающий");
        row.createSpan({
            cls: "chase-launch-info",
            text: `${c.flee ? "отряд убегает, догоняет" : "отряд догоняет, убегает"} ${who}; колода ${c.deck}; старт ${DIST[c.start].name.toLowerCase()}`,
        });
        b.onclick = () => this.plugin.startFrom(this.conf);
    }
}

class ChaseView extends ItemView {
    constructor(leaf, plugin) {
        super(leaf);
        this.plugin = plugin;
        this.hoverPopover = null;
    }

    getViewType() {
        return VIEW;
    }

    getDisplayText() {
        return "Погоня";
    }

    getIcon() {
        return "footprints";
    }

    async onOpen() {
        const data = this.plugin.data;
        const persist = (c, s) => {
            data.conf = c;
            data.state = s;
            this.plugin.saveData(data);
        };
        this.chase = new Chase(this.plugin, this.contentEl, data.conf, data.state, persist, this, "", true);
        await this.chase.render();
    }

    async onClose() {
        this.contentEl.empty();
    }
}

module.exports = class ChaseTrackerPlugin extends Plugin {
    async onload() {
        const conf = parseConf("");
        this.data = Object.assign({ conf, state: freshState(conf) }, await this.loadData());
        this.data.conf = Object.assign(parseConf(""), this.data.conf);
        // Погоня в панели всегда начинается с близкой дистанции.
        this.data.conf.start = 1;

        this.style = document.head.createEl("style", { attr: { id: "chase-tracker-css" } });
        this.style.textContent = CSS;

        this.registerView(VIEW, (leaf) => new ChaseView(leaf, this));
        this.ui = {};
        this.registerHoverLinkSource("chase-tracker", { display: "Погоня", defaultMod: true });
        this.addRibbonIcon("footprints", "Погоня", () => this.open());
        this.addCommand({ id: "start-from-tracker", name: "Начать погоню с противником из трекера", callback: () => this.startFromTracker() });
        this.observers = [];
        const drop = () => {
            if (this.peek) this.peek.pop.remove();
            this.peek = null;
        };
        this.registerDomEvent(document, "mousemove", (e) => {
            const p = this.peek;
            if (p && (!p.anchor.isConnected || !(e.target instanceof Node) || !p.anchor.contains(e.target))) drop();
        }, true);
        this.registerDomEvent(document, "scroll", drop, true);
        this.registerDomEvent(document, "wheel", drop, true);
        this.registerDomEvent(document, "pointerdown", drop, true);
        this.register(drop);
        this.app.workspace.onLayoutReady(() => this.decorateTracker());
        this.registerEvent(this.app.workspace.on("layout-change", () => this.decorateTracker()));
        this.registerEvent(this.app.workspace.on("active-leaf-change", () => this.decorateTracker()));
        this.addCommand({ id: "open", name: "Открыть панель", callback: () => this.open() });
        this.registerMarkdownCodeBlockProcessor("chase", (source, el, ctx) => {
            ctx.addChild(new ChaseBlock(this, el, source, ctx));
        });
    }

    async open() {
        const leaves = this.app.workspace.getLeavesOfType(VIEW);
        const leaf = leaves[0] || this.app.workspace.getLeaf("tab");
        if (!leaves.length) await leaf.setViewState({ type: VIEW, active: true });
        this.app.workspace.revealLeaf(leaf);
    }

    /*
     * Кнопка "Начать погоню" в ряду значков Initiative Tracker. Противником
     * становится существо, чей сейчас ход; если ход у героя или бой не начат -
     * первый не-герой в бою. Погоня начинается заново: раунд 1, инициатива по
     * order, новая сцена.
     */
    decorateTracker() {
        for (const leaf of this.app.workspace.getLeavesOfType(TRACKER_VIEW)) {
            const view = leaf.view;
            if (!view || !view.contentEl) continue;
            this.injectButton(view.contentEl);
            if (view.chaseTrackerObserved) continue;
            const observer = new MutationObserver(() => this.injectButton(view.contentEl));
            observer.observe(view.contentEl, { childList: true, subtree: true });
            view.chaseTrackerObserved = true;
            this.observers.push(observer);
        }
    }

    injectButton(container) {
        const row = container.querySelector(".buttons .clean") || container.querySelector(".buttons");
        if (!row) return;
        if (row.querySelector(".chase-start-button")) return this.placeButton(row);
        const b = createDiv({ cls: "clickable-icon chase-start-button", attr: { "aria-label": "Начать погоню" } });
        setIcon(b, "footprints");
        b.addEventListener("click", () => this.startFromTracker());
        row.appendChild(b);
        this.placeButton(row);
    }

    /* Кнопка погони стоит сразу за "Инициативой монстров"; та вставляется позже, поэтому место правится каждый раз. */
    placeButton(row) {
        const b = row.querySelector(".chase-start-button");
        const monsters = row.querySelector(".monster-initiative-button");
        if (b && monsters && monsters.nextSibling !== b) row.insertBefore(b, monsters.nextSibling);
    }

    trackerCreatures() {
        const tracker = this.app.plugins.plugins["initiative-tracker"]?.tracker;
        if (!tracker) return [];
        let value;
        const off = typeof tracker.subscribe === "function" ? tracker.subscribe((v) => (value = v)) : null;
        if (typeof off === "function") off();
        if (Array.isArray(value)) return value;
        if (value && Array.isArray(value.creatures)) return value.creatures;
        return Array.isArray(tracker.creatures) ? tracker.creatures : [];
    }

    /*
     * Путь к токену существа из боя: "<Имя> токен.png" по заметке (NPC, герой),
     * иначе image из статблока бестиария. Нумерованная копия ("skeleton 2.webp")
     * берётся, если она есть.
     */
    creatureToken(c) {
        const mc = this.app.metadataCache;
        const note = c.path ? this.app.vault.getAbstractFileByPath(c.path) : null;
        const fm = note instanceof TFile ? (mc.getFileCache(note) || {}).frontmatter || {} : {};
        for (const n of [fm.character, note instanceof TFile ? note.basename : null, c.name].filter(Boolean)) {
            const hit = mc.getFirstLinkpathDest(`${n} токен.png`, "");
            if (hit) return hit.path;
        }
        let image = fm.image;
        if (!image) {
            try {
                const fs = window.FantasyStatblocks;
                const cr = fs && c.name && fs.hasCreature(c.name) ? fs.getCreatureFromBestiary(c.name) : null;
                image = cr && cr.image;
            } catch (e) {
                image = null;
            }
        }
        const raw = image ? String(image).replace(/^!?\[\[|\]\]$/g, "").split("|")[0] : null;
        if (!raw) return null;
        const shown = typeof c.getName === "function" ? String(c.getName()) : "";
        const num = shown.match(/ (\d+)$/);
        if (num) {
            const numbered = mc.getFirstLinkpathDest(raw.replace(/(\.[^./]+)$/, ` ${num[1]}$1`), "");
            if (numbered) return numbered.path;
        }
        const img = mc.getFirstLinkpathDest(raw, note instanceof TFile ? note.path : "");
        return img ? img.path : null;
    }

    /* Запуск из блока в заметке: противник по имени, токен - по его заметке, если она есть. */
    async startFrom(blockConf) {
        const conf = this.data.conf;
        Object.assign(conf, { fugitive: blockConf.fugitive, deck: blockConf.deck, start: blockConf.start,
            dc: blockConf.dc, flee: blockConf.flee });
        const note = conf.fugitive ? this.app.metadataCache.getFirstLinkpathDest(conf.fugitive, "") : null;
        conf.foeToken = note instanceof TFile ? this.creatureToken({ name: conf.fugitive, path: note.path }) : null;
        this.data.state = migrate(freshState(conf), conf);
        await this.saveData(this.data);
        await this.open();
        for (const leaf of this.app.workspace.getLeavesOfType(VIEW)) await leaf.view.onOpen();
    }

    async startFromTracker() {
        const creatures = this.trackerCreatures().filter((c) => c && c.enabled !== false);
        const foes = creatures.filter((c) => !c.player);
        const foe = foes.find((c) => c.active) || foes[0];
        const name = foe ? (typeof foe.getName === "function" ? foe.getName() : foe.display || foe.name) : "";
        const conf = this.data.conf;
        conf.fugitive = String(name || "").trim();
        conf.foeToken = foe ? this.creatureToken(foe) : null;
        this.data.state = migrate(freshState(conf), conf);
        await this.saveData(this.data);
        await this.open();
        for (const leaf of this.app.workspace.getLeavesOfType(VIEW)) await leaf.view.onOpen();
        new Notice(name ? `Погоня: противник ${name}` : "Погоня: в бою нет противника, имя впишите сами");
    }

    onunload() {
        for (const o of this.observers || []) o.disconnect();
        document.querySelectorAll(".chase-start-button").forEach((el) => el.remove());
        if (this.style) this.style.remove();
    }
};
