// Логика canvas «Сравнение картинок». Сессия подаёт круг: группы вариантов,
// по группе на кадр. Мастер отмечает понравившиеся картинки и пишет
// комментарии, на группу - общий комментарий, и
// отправляет всё разом. Кадры, которые ещё рисуются, стоят заглушками и
// встают на место, когда файл появится. Состояние своё у каждого instanceId (images
// открывает по панели на круг) и лежит в roll-look-<instanceId>.json в
// папке сессии: клики переживают перезагрузку страницы и расширения.
import { closeSync, existsSync, openSync, readSync, statSync } from "node:fs";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { basename, join } from "node:path";

const fail = (code, message) => Object.assign(new Error(message), { code });

function safeId(id) {
    return String(id || "default").replace(/[^A-Za-z0-9._-]/g, "_");
}

function storePath(session, id) {
    return session?.workspacePath ? join(session.workspacePath, `roll-look-${safeId(id)}.json`) : null;
}

const memory = (globalThis.__rollLook ??= {});

async function load(session, id) {
    const path = storePath(session, id);
    let state;
    if (!path) state = memory[safeId(id)] ?? null;
    else { try { state = JSON.parse(await readFile(path, "utf8")); } catch { state = null; } }
    return upgrade(state);
}

// Круги, открытые до прогресса съёмки, хранили картинки строками, оценки
// по номерам «группа.картинка», а комментарии групп по номеру группы.
function upgrade(state) {
    if (!state?.groups) return state;
    const old = state.groups.some((g) => g.images.some((s) => typeof s === "string"));
    if (!old) return state;
    state.groups = state.groups.map((g) => ({ ...g, images: g.images.map((s) => (typeof s === "string" ? { path: s, label: "" } : s)) }));
    const marks = {};
    for (const [k, m] of Object.entries(state.marks ?? {})) {
        const hit = /^(\d+)\.(\d+)$/.exec(k);
        const p = hit && state.groups[+hit[1]]?.images[+hit[2]]?.path;
        marks[p ? p.toLowerCase() : k] = m;
    }
    state.marks = marks;
    const comments = {};
    for (const [k, c] of Object.entries(state.groupComments ?? {})) comments[state.groups[+k]?.name ?? k] = c;
    state.groupComments = comments;
    return state;
}

async function save(session, id, state) {
    const path = storePath(session, id);
    if (!path) { memory[safeId(id)] = state; return; }
    await writeFile(path, JSON.stringify(state, null, 1), "utf8");
}

// Клики приходят быстрее, чем пишется файл: правки идут по одной.
let queue = Promise.resolve();
function serial(fn) {
    const run = queue.then(fn, fn);
    queue = run.catch(() => {});
    return run;
}

const RATING = { like: "нравится" };

// Слот картинки: { path, label }. path может указывать на файл, которого
// ещё нет (кадр рисуется), или быть null (слот без имени, его заполнит add).
// Оценки и комментарии держатся по пути файла, комментарии групп - по имени
// группы: так они переживают и повторный propose, и дорисовку.
function slot(x) {
    if (x && typeof x === "object") return { path: x.path ? String(x.path) : null, label: x.label ? String(x.label) : "" };
    return { path: String(x), label: "" };
}
const markKey = (path) => (path ?? "").toLowerCase();

function stat(path) {
    try { return path ? statSync(path) : null; } catch { return null; }
}

// Есть ли у картинки прозрачность: фон под ней переключается только тогда.
// PNG - по типу цвета в IHDR или чанку tRNS, WebP - по флагу в VP8X или
// VP8L. Ответ кешируется по пути и времени файла.
const alphaCache = new Map();
function hasAlpha(path, st) {
    const key = `${path}|${st.mtimeMs}`;
    if (alphaCache.has(key)) return alphaCache.get(key);
    let alpha = false;
    try {
        const fd = openSync(path, "r");
        const buf = Buffer.alloc(Math.min(st.size, 65536));
        readSync(fd, buf, 0, buf.length, 0);
        closeSync(fd);
        if (buf.toString("latin1", 1, 4) === "PNG") {
            alpha = buf[25] === 4 || buf[25] === 6;
            for (let at = 8; !alpha && at + 8 <= buf.length;) {
                const len = buf.readUInt32BE(at), type = buf.toString("latin1", at + 4, at + 8);
                if (type === "tRNS") alpha = true;
                if (type === "IDAT" || type === "IEND") break;
                at += 12 + len;
            }
        } else if (buf.toString("latin1", 8, 12) === "WEBP") {
            const kind = buf.toString("latin1", 12, 16);
            if (kind === "VP8X") alpha = (buf[20] & 0x10) !== 0;
            else if (kind === "VP8L") alpha = ((buf.readUInt32LE(21) >>> 28) & 1) === 1;
        }
    } catch { }
    alphaCache.set(key, alpha);
    return alpha;
}

function view(state) {
    if (!state) return { state: "пусто" };
    let ready = 0, total = 0;
    const groups = state.groups.map((g, gi) => ({
        name: g.name, note: g.note, comment: state.groupComments[g.name] ?? "",
        images: g.images.map((s, ii) => {
            const st = stat(s.path);
            const ok = !!st && st.size > 0;
            total++; if (ok) ready++;
            const m = { ...(s.path ? state.marks[markKey(s.path)] ?? {} : {}) };
            // Недолгое время «скрыта» была оценкой; теперь это отдельный признак.
            if (m.rating === "hide") { m.rating = undefined; m.hidden = true; }
            return {
                gi, ii, path: s.path, label: s.label,
                name: s.path ? basename(s.path) : (s.label || `кадр ${ii + 1}`),
                ready: ok, v: ok ? Math.round(st.mtimeMs) : 0, alpha: ok && hasAlpha(s.path, st),
                ...m, hidden: !!m.hidden,
            };
        }),
    }));
    const p = state.progress ?? null;
    return {
        rid: state.rid, title: state.title, state: state.status, sentAt: state.sentAt, out: state.out,
        groups, ready, total, now: Date.now(),
        progress: p && {
            done: p.done ?? ready, total: p.total ?? total, note: p.note ?? "",
            // До какого момента ждать, по часам сервера; страница сама тикает.
            until: p.eta_seconds != null ? p.at + p.eta_seconds * 1000 : null,
        },
    };
}

const cell = (s) => String(s ?? "").replace(/[\t\r\n]+/g, " ").trim();

async function submit(session, id, body) {
    return serial(async () => {
        const state = await load(session, id);
        if (!state || state.rid !== body.rid || state.status === "отправлен") return view(state);
        const dir = session?.workspacePath
            ? (existsSync(join(session.workspacePath, "files")) ? join(session.workspacePath, "files") : session.workspacePath)
            : null;
        const rows = ["group\tfile\trating\thidden\tcomment\tpath"];
        const msg = [];
        let rated = 0, hidden = 0, total = 0;
        for (const g of view(state).groups) {
            msg.push(`## ${g.name}` + (cell(g.comment) ? `: ${cell(g.comment)}` : ""));
            rows.push([g.name, "", "группа", "", g.comment, ""].map(cell).join("\t"));
            for (const im of g.images) {
                if (!im.ready) continue;  // недорисованные кадры оценить было нельзя
                total++;
                const rating = RATING[im.rating] ?? "—";
                if (im.rating === "like") rated++;
                if (im.hidden) hidden++;
                rows.push([g.name, im.name, rating, im.hidden ? "да" : "", im.comment, im.path].map(cell).join("\t"));
                msg.push(`- ${im.name} → ${rating}` + (im.hidden ? " (скрыта)" : "") + (cell(im.comment) ? `: ${cell(im.comment)}` : ""));
            }
        }
        if (dir) {
            await mkdir(dir, { recursive: true });
            state.out = join(dir, `roll-look-${safeId(id)}-${new Date().toISOString().replace(/[:.]/g, "-")}.tsv`);
            await writeFile(state.out, rows.join("\n") + "\n", "utf8");
        }
        state.status = "отправлен";
        state.sentAt = new Date().toISOString();
        await save(session, id, state);
        const head = `[Сравнение картинок] Мастер отправил «${state.title}»: нравится ${rated} из ${total}` +
            (hidden ? `, скрыто ${hidden}` : "") +
            (state.out ? `, файл ${state.out}` : "") + ".";
        try { session?.send({ prompt: [head, ...msg].join("\n") }).catch(() => {}); } catch { }
        return view(state);
    });
}

function summary(state) {
    const v = view(state);
    return { rid: v.rid, title: v.title, state: v.state, ready: v.ready, total: v.total };
}

export const actions = {
    // Повторный propose в тот же неотправленный круг сохраняет оценки (по
    // пути файла) и комментарии групп (по имени группы).
    async propose({ session, input, instanceId }) {
        const groups = input.groups.map((g) => {
            const images = (g.images ?? []).map(slot);
            for (let k = 0; k < (g.pending ?? 0); k++) images.push({ path: null, label: g.labels?.[k] ?? "" });
            return { name: String(g.name), note: g.note ?? "", images };
        });
        return serial(async () => {
            const old = await load(session, instanceId);
            const keep = old && old.status === "ждёт";
            const state = {
                rid: keep ? old.rid : Date.now().toString(36), title: input.title, groups,
                marks: keep ? old.marks : {}, groupComments: keep ? old.groupComments : {},
                progress: keep ? old.progress : null,
                status: "ждёт", at: new Date().toISOString(),
            };
            await save(session, instanceId, state);
            return summary(state);
        });
    },
    // Дописать готовые (или будущие) файлы в группу: сначала занимаются
    // слоты без пути, остальное добавляется в конец; нет группы - создаётся.
    async add({ session, input, instanceId }) {
        return serial(async () => {
            const state = await load(session, instanceId);
            if (!state) throw fail("no_round", "круга нет, сначала propose");
            let g = state.groups.find((x) => x.name === input.group);
            if (!g) { g = { name: String(input.group), note: "", images: [] }; state.groups.push(g); }
            for (const s of (input.images ?? []).map(slot)) {
                if (g.images.some((x) => x.path && markKey(x.path) === markKey(s.path))) continue;
                const free = g.images.find((x) => !x.path);
                if (free) { free.path = s.path; if (s.label) free.label = s.label; }
                else g.images.push(s);
            }
            await save(session, instanceId, state);
            return summary(state);
        });
    },
    // { done?, total?, eta_seconds?, note? }; done и total по умолчанию -
    // сколько файлов круга уже есть на диске. Пустой вызов убирает срок и
    // подпись, счётчик остаётся, пока есть недорисованные кадры.
    async progress({ session, input, instanceId }) {
        return serial(async () => {
            const state = await load(session, instanceId);
            if (!state) throw fail("no_round", "круга нет, сначала propose");
            const empty = !Object.keys(input).length;
            state.progress = empty ? null : { ...input, at: Date.now() };
            await save(session, instanceId, state);
            return summary(state);
        });
    },
    async status({ session, instanceId }) {
        // Через очередь: иначе status, вызванный сразу за propose или add,
        // читает файл раньше, чем они его запишут.
        const state = await serial(() => load(session, instanceId));
        if (!state) return { state: "пусто" };
        const v = view(state);
        return {
            rid: v.rid, title: v.title, state: v.state, sentAt: v.sentAt, out: v.out, ready: v.ready, total: v.total,
            groups: v.groups.map((g) => ({
                name: g.name, comment: g.comment,
                images: g.images.map((im) => ({ file: im.name, path: im.path, ready: im.ready,
                                                rating: RATING[im.rating] ?? "—", hidden: im.hidden, comment: im.comment ?? "" })),
            })),
        };
    },
};

export const routes = {
    "/state": async ({ session, query }) => view(await load(session, query.i)),
    // Отдаётся только картинка из текущего круга, по номеру группы и
    // картинки: произвольный путь с диска через страницу не достать.
    "/img": async ({ session, query }) => {
        const state = await load(session, query.i);
        const path = state?.groups?.[+query.g]?.images?.[+query.n]?.path;
        if (!path || !existsSync(path)) throw fail("no_image", "нет такой картинки");
        return { file: path };
    },
    // { rid, g, n?, rating?: "like"|null, hidden?: bool, comment? }; без n - комментарий группы.
    "/mark": async ({ session, query, body }) => serial(async () => {
        const state = await load(session, query.i);
        if (!state || state.rid !== body.rid || state.status !== "ждёт") return { ok: false };
        const g = state.groups[body.g];
        if (!g) return { ok: false };
        if (body.n === undefined || body.n === null) {
            state.groupComments[g.name] = String(body.comment ?? "");
        } else {
            const path = g.images[body.n]?.path;
            if (!path) return { ok: false };
            const key = markKey(path);
            const m = { ...(state.marks[key] ?? {}) };
            if (m.rating === "hide") { m.rating = undefined; m.hidden = true; }
            if (body.rating !== undefined) m.rating = RATING[body.rating] ? body.rating : undefined;
            if (body.hidden !== undefined) m.hidden = !!body.hidden || undefined;
            if (body.comment !== undefined) m.comment = String(body.comment);
            state.marks[key] = m;
        }
        await save(session, query.i, state);
        return { ok: true };
    }),
    "/submit": async ({ session, query, body }) => submit(session, query.i, body),
};
