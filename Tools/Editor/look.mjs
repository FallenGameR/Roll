// Логика canvas «Сравнение картинок». Сессия подаёт круг: группы вариантов,
// по группе на кадр. Мастер на каждую картинку ставит «нравится» или «не
// нравится» и пишет комментарий, на группу - общий комментарий, и
// отправляет всё разом. Состояние своё у каждого instanceId (images
// открывает по панели на круг) и лежит в roll-look-<instanceId>.json в
// папке сессии: клики переживают перезагрузку страницы и расширения.
import { existsSync } from "node:fs";
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
    if (!path) return memory[safeId(id)] ?? null;
    try { return JSON.parse(await readFile(path, "utf8")); } catch { return null; }
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

const RATING = { like: "нравится", dislike: "не нравится" };

function view(state) {
    if (!state) return { state: "пусто" };
    return {
        rid: state.rid, title: state.title, state: state.status, sentAt: state.sentAt, out: state.out,
        groups: state.groups.map((g, gi) => ({
            name: g.name, note: g.note, comment: state.groupComments[gi] ?? "",
            images: g.images.map((path, ii) => ({
                gi, ii, name: basename(path),
                ...(state.marks[`${gi}.${ii}`] ?? {}),
            })),
        })),
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
        const rows = ["group\tfile\trating\tcomment\tpath"];
        const msg = [];
        let rated = 0, total = 0;
        state.groups.forEach((g, gi) => {
            msg.push(`## ${g.name}` + (cell(state.groupComments[gi]) ? `: ${cell(state.groupComments[gi])}` : ""));
            rows.push([g.name, "", "группа", state.groupComments[gi], ""].map(cell).join("\t"));
            g.images.forEach((path, ii) => {
                total++;
                const m = state.marks[`${gi}.${ii}`] ?? {};
                const rating = RATING[m.rating] ?? "без оценки";
                if (m.rating) rated++;
                rows.push([g.name, basename(path), rating, m.comment, path].map(cell).join("\t"));
                msg.push(`- ${basename(path)} → ${rating}` + (cell(m.comment) ? `: ${cell(m.comment)}` : ""));
            });
        });
        if (dir) {
            await mkdir(dir, { recursive: true });
            state.out = join(dir, `roll-look-${safeId(id)}-${new Date().toISOString().replace(/[:.]/g, "-")}.tsv`);
            await writeFile(state.out, rows.join("\n") + "\n", "utf8");
        }
        state.status = "отправлен";
        state.sentAt = new Date().toISOString();
        await save(session, id, state);
        const head = `[Сравнение картинок] Мастер отправил «${state.title}»: оценено ${rated} из ${total}` +
            (state.out ? `, файл ${state.out}` : "") + ".";
        try { session?.send({ prompt: [head, ...msg].join("\n") }).catch(() => {}); } catch { }
        return view(state);
    });
}

export const actions = {
    async propose({ session, input, instanceId }) {
        const groups = [];
        for (const g of input.groups) {
            const images = (g.images ?? []).map(String);
            const missing = images.filter((p) => !existsSync(p));
            if (missing.length) throw fail("no_file", `нет файлов: ${missing.join(", ")}`);
            groups.push({ name: String(g.name), note: g.note ?? "", images });
        }
        return serial(async () => {
            const state = {
                rid: Date.now().toString(36), title: input.title, groups,
                marks: {}, groupComments: {}, status: "ждёт", at: new Date().toISOString(),
            };
            await save(session, instanceId, state);
            return { rid: state.rid, title: state.title, state: state.status,
                     images: groups.reduce((n, g) => n + g.images.length, 0) };
        });
    },
    async status({ session, instanceId }) {
        const state = await load(session, instanceId);
        if (!state) return { state: "пусто" };
        const v = view(state);
        return {
            rid: v.rid, title: v.title, state: v.state, sentAt: v.sentAt, out: v.out,
            groups: v.groups.map((g) => ({
                name: g.name, comment: g.comment,
                images: g.images.map((im) => ({ file: im.name, path: state.groups[im.gi].images[im.ii],
                                                rating: RATING[im.rating] ?? "без оценки", comment: im.comment ?? "" })),
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
        const path = state?.groups?.[+query.g]?.images?.[+query.n];
        if (!path) throw fail("no_image", "нет такой картинки");
        return { file: path };
    },
    // { rid, g, n?, rating?: "like"|"dislike"|null, comment? }; без n - комментарий группы.
    "/mark": async ({ session, query, body }) => serial(async () => {
        const state = await load(session, query.i);
        if (!state || state.rid !== body.rid || state.status !== "ждёт") return { ok: false };
        if (body.n === undefined || body.n === null) {
            state.groupComments[body.g] = String(body.comment ?? "");
        } else {
            const key = `${body.g}.${body.n}`;
            const m = { ...(state.marks[key] ?? {}) };
            if (body.rating !== undefined) m.rating = body.rating || undefined;
            if (body.comment !== undefined) m.comment = String(body.comment);
            state.marks[key] = m;
        }
        await save(session, query.i, state);
        return { ok: true };
    }),
    "/submit": async ({ session, query, body }) => submit(session, query.i, body),
};
