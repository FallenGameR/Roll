// Логика canvas «Правка текста». Перечитывается при каждом изменении файла,
// поэтому состояние держится не в памяти модуля, а в roll-editor.json в
// папке сессии: правка переживает и перезагрузку логики, и перезапуск
// расширения.
import { existsSync } from "node:fs";
import { readFile, writeFile } from "node:fs/promises";
import { basename, dirname, join, relative } from "node:path";

const fail = (code, message) => Object.assign(new Error(message), { code });

function storePath(session) {
    return session?.workspacePath ? join(session.workspacePath, "roll-editor.json") : null;
}

async function load(session) {
    const path = storePath(session);
    if (!path) return globalThis.__rollEditor ?? null;
    try { return JSON.parse(await readFile(path, "utf8")); } catch { return null; }
}

async function save(session, state) {
    const path = storePath(session);
    if (!path) { globalThis.__rollEditor = state; return; }
    await writeFile(path, JSON.stringify(state, null, 2), "utf8");
}

// Корень волта - ближайшая папка с .obsidian: от неё считается путь,
// который страница показывает под именем документа.
function vaultRelative(file) {
    let dir = dirname(file);
    while (dir && dirname(dir) !== dir) {
        if (existsSync(join(dir, ".obsidian"))) return relative(dir, file);
        dir = dirname(dir);
    }
    return file;
}

function count(text, part) {
    let n = 0;
    for (let i = text.indexOf(part); i !== -1; i = text.indexOf(part, i + 1)) n++;
    return n;
}

// Сессия присылает текст с \n, а файл может быть в CRLF: кусок
// приводится к окончаниям строк файла, иначе он в файле не найдётся.
function eolOf(text) { return text.includes("\r\n") ? "\r\n" : "\n"; }
function withEol(text, eol) { return text.replace(/\r\n/g, "\n").replace(/\n/g, eol); }

async function readDoc(file) {
    let text = await readFile(file, "utf8");
    if (text.charCodeAt(0) === 0xfeff) text = text.slice(1);
    return text;
}

function view(state) {
    if (!state) return { state: "пусто" };
    const { file, document, path, original, variants, comment, status, variant, at, decidedAt, reason } = state;
    return { file, document, path, original, variants, comment, state: status, variant, at, decidedAt, reason };
}

function tell(session, prompt) {
    // Сообщение уходит в сессию, открывшую canvas, как реплика Мастера.
    try { session?.send({ prompt }).catch(() => {}); } catch { }
}

async function decide(session, body) {
    const state = await load(session);
    if (!state || state.status !== "ждёт") return view(state);
    if (body.id !== state.id) return view(state);   // страница смотрела на старую правку
    const now = new Date().toISOString();
    if (body.accept === undefined || body.accept === null) {
        state.status = "отклонена";
        state.decidedAt = now;
        await save(session, state);
        tell(session, `[Правка текста] Мастер не принял правку в «${state.document}».`);
        return view(state);
    }
    const n = Number(body.accept);
    const chosen = state.variants[n];
    if (!chosen) throw fail("bad_variant", "нет такого варианта");
    let text;
    try { text = await readDoc(state.file); } catch (e) {
        state.status = "устарела"; state.reason = `файл не читается: ${e.message}`;
    }
    if (text !== undefined) {
        const eol = eolOf(text);
        const original = withEol(state.original, eol);
        const hits = count(text, original);
        if (hits !== 1) {
            state.status = "устарела";
            state.reason = hits ? `кусок встречается в файле ${hits} раза` : "куска в файле больше нет";
        } else {
            const updated = text.replace(original, () => withEol(chosen.text, eol));
            await writeFile(state.file, updated, "utf8");
            state.status = "принята";
            state.variant = n + 1;
        }
    }
    state.decidedAt = now;
    await save(session, state);
    tell(session, state.status === "принята"
        ? `[Правка текста] Мастер принял вариант ${state.variant} в «${state.document}», файл записан.`
        : `[Правка текста] Правка в «${state.document}» устарела и не записана: ${state.reason}.`);
    return view(state);
}

export const actions = {
    async propose({ session, input }) {
        const { file, original, variants, comment } = input;
        let text;
        try { text = await readDoc(file); } catch (e) { throw fail("no_file", `файл не читается: ${e.message}`); }
        const hits = count(text, withEol(original, eolOf(text)));
        if (hits !== 1) {
            throw fail(hits ? "ambiguous" : "not_found",
                hits ? `original встречается в файле ${hits} раза, нужен ровно один` : "original в файле не найден байт в байт");
        }
        const state = {
            id: Date.now().toString(36),
            file,
            document: basename(file).replace(/\.md$/i, ""),
            path: vaultRelative(file),
            original,
            variants: variants.slice(0, 3).map((v) => ({ text: v.text, note: v.note ?? "" })),
            comment: comment ?? "",
            status: "ждёт",
            at: new Date().toISOString(),
        };
        await save(session, state);
        return view(state);
    },
    async status({ session }) {
        return view(await load(session));
    },
};

export const routes = {
    "/state": async ({ session }) => {
        const state = await load(session);
        return { ...view(state), id: state?.id };
    },
    "/decide": async ({ session, body }) => decide(session, body),
    "/clear": async ({ session, body }) => {
        const state = await load(session);
        if (!state || body.id !== state.id) return view(state);   // страница смотрела на старую правку
        await save(session, null);
        if (state.status === "ждёт") {
            tell(session, `[Правка текста] Мастер очистил панель, не решив правку в «${state.document}».`);
        }
        return view(null);
    },
    "/check": async ({ session }) => {
        tell(session, "[Правка текста] Мастер просит посмотреть, что он сейчас пишет: найди свежий абзац и предложи правку.");
        return { ok: true };
    },
};
