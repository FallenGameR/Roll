// Логика canvas «Выбор вариантов». Сессия подаёт порцию строк, у каждой
// от одного до нескольких вариантов; Мастер выбирает вариант, пишет свой
// или откладывает строку на обсуждение, и отправляет всё разом. Состояние
// лежит в roll-pick.json в папке сессии: выбор переживает перезагрузку
// страницы и расширения, а клики сохраняются сразу, без кнопки.
import { existsSync } from "node:fs";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";

const fail = (code, message) => Object.assign(new Error(message), { code });

function storePath(session) {
    return session?.workspacePath ? join(session.workspacePath, "roll-pick.json") : null;
}

async function load(session) {
    const path = storePath(session);
    if (!path) return globalThis.__rollPick ?? null;
    try { return JSON.parse(await readFile(path, "utf8")); } catch { return null; }
}

async function save(session, state) {
    const path = storePath(session);
    if (!path) { globalThis.__rollPick = state; return; }
    await writeFile(path, JSON.stringify(state, null, 1), "utf8");
}

// Клики приходят быстрее, чем пишется файл: правки состояния идут по одной,
// иначе две записи подряд затирают друг друга.
let queue = Promise.resolve();
function serial(fn) {
    const run = queue.then(fn, fn);
    queue = run.catch(() => {});
    return run;
}

function parseTsv(text, group) {
    const lines = text.replace(/^\uFEFF/, "").split(/\r?\n/).filter((l) => l.trim());
    if (!lines.length) throw fail("empty", "TSV пуст");
    const head = lines[0].split("\t").map((h) => h.trim().toLowerCase());
    const col = (name) => head.indexOf(name);
    if (col("term") < 0 || col("variants") < 0) throw fail("bad_tsv", "в TSV нет колонок term и variants");
    const rows = [];
    for (const line of lines.slice(1)) {
        const cells = line.split("\t");
        const get = (name) => (col(name) >= 0 ? (cells[col(name)] ?? "").trim() : "");
        if (group && get("group") !== group) continue;
        rows.push({
            id: get("id") || undefined,
            term: get("term"),
            variants: get("variants").split(/\s*;\s*/).filter(Boolean),
            comment: get("comment"),
            recommended: get("recommended") || undefined,
            note: [get("group"), get("category"), get("book")].filter(Boolean).join(" · "),
        });
    }
    return rows;
}

function normalize(rows) {
    const ids = new Set();
    return rows.map((r, n) => {
        let id = String(r.id ?? r.term ?? n + 1);
        while (ids.has(id)) id += "'";
        ids.add(id);
        const variants = (r.variants ?? []).map(String).filter((v) => v.trim());
        let rec = r.recommended;
        if (typeof rec === "string" && /^\d+$/.test(rec)) rec = Number(rec);
        if (typeof rec === "string") rec = variants.indexOf(rec);
        if (!(Number.isInteger(rec) && rec >= 0 && rec < variants.length)) rec = null;
        return { id, term: String(r.term ?? ""), variants, comment: r.comment ?? "", recommended: rec, note: r.note ?? "" };
    });
}

function decided(c) {
    return c && (c.kind === "variant" || c.kind === "skip" || (c.kind === "own" && c.text?.trim()));
}

function view(state) {
    if (!state) return { state: "пусто" };
    const done = state.rows.filter((r) => decided(state.choices[r.id])).length;
    return {
        pid: state.pid, title: state.title, state: state.status, done, total: state.rows.length,
        rows: state.rows.map((r) => ({ ...r, choice: state.choices[r.id] ?? null })),
        sentAt: state.sentAt, out: state.out,
    };
}

function describe(r, c) {
    if (!decided(c)) return { decision: "нет", text: "" };
    if (c.kind === "variant") return { decision: `вариант ${c.index + 1}`, text: r.variants[c.index] };
    if (c.kind === "own") return { decision: "свой", text: c.text.trim() };
    return { decision: "обсудить", text: "" };
}

const tsvCell = (s) => String(s ?? "").replace(/[\t\r\n]+/g, " ");

async function submit(session, body) {
    return serial(async () => {
        const state = await load(session);
        if (!state || state.pid !== body.pid) return view(state);
        if (state.status === "отправлена") return view(state);
        const dir = session?.workspacePath
            ? (existsSync(join(session.workspacePath, "files")) ? join(session.workspacePath, "files") : session.workspacePath)
            : null;
        const lines = ["id\tterm\tdecision\ttext\tremark"];
        const msg = [];
        let done = 0;
        for (const r of state.rows) {
            const c = state.choices[r.id];
            const d = describe(r, c);
            if (d.decision !== "нет") done++;
            const remark = c?.remark?.trim() ?? "";
            lines.push([r.id, r.term, d.decision, d.text, remark].map(tsvCell).join("\t"));
            const tail = remark ? ` (${remark})` : "";
            if (d.decision === "обсудить") msg.push(`- ${r.term} → обсудить${remark ? ": " + remark : ""}`);
            else if (d.decision === "свой") msg.push(`- ${r.term} → свой: «${d.text}»${tail}`);
            else if (d.decision === "нет") msg.push(`- ${r.term} → без решения${tail}`);
            else msg.push(`- ${r.term} → ${d.text}${tail}`);
        }
        if (dir) {
            await mkdir(dir, { recursive: true });
            state.out = join(dir, `roll-pick-${new Date().toISOString().replace(/[:.]/g, "-")}.tsv`);
            await writeFile(state.out, lines.join("\n") + "\n", "utf8");
        }
        state.status = "отправлена";
        state.sentAt = new Date().toISOString();
        await save(session, state);
        const head = `[Выбор вариантов] Мастер отправил «${state.title}»: решено ${done} из ${state.rows.length}` +
            (state.out ? `, файл ${state.out}` : "") + ".";
        try { session?.send({ prompt: [head, ...msg].join("\n") }).catch(() => {}); } catch { }
        return view(state);
    });
}

export const actions = {
    async propose({ session, input }) {
        let rows = input.rows ?? [];
        if (input.tsv) {
            let text;
            try { text = await readFile(input.tsv, "utf8"); } catch (e) { throw fail("no_file", `TSV не читается: ${e.message}`); }
            rows = rows.concat(parseTsv(text, input.group));
        }
        rows = normalize(rows).filter((r) => r.term);
        if (!rows.length) throw fail("empty", "нет строк: передай rows или tsv (и проверь group)");
        return serial(async () => {
            const state = {
                pid: Date.now().toString(36), title: input.title, rows, choices: {},
                status: "ждёт", at: new Date().toISOString(),
            };
            await save(session, state);
            const v = view(state);
            return { pid: v.pid, title: v.title, state: v.state, total: v.total };
        });
    },
    async status({ session }) {
        const state = await load(session);
        if (!state) return { state: "пусто" };
        const v = view(state);
        const decisions = [];
        for (const r of state.rows) {
            const c = state.choices[r.id];
            const d = describe(r, c);
            if (d.decision !== "нет" || c?.remark?.trim()) decisions.push({ id: r.id, term: r.term, ...d, remark: c?.remark?.trim() ?? "" });
        }
        return { pid: v.pid, title: v.title, state: v.state, done: v.done, total: v.total, sentAt: v.sentAt, out: v.out, decisions };
    },
};

export const routes = {
    "/state": async ({ session }) => view(await load(session)),
    // choice: { kind: "variant", index } | { kind: "own", text } | { kind: "skip" } | null; remark - строка.
    "/choose": async ({ session, body }) => serial(async () => {
        const state = await load(session);
        if (!state || state.pid !== body.pid || state.status !== "ждёт") return { ok: false };
        if (!state.rows.some((r) => r.id === body.id)) return { ok: false };
        const prev = state.choices[body.id] ?? {};
        const next = body.choice === undefined ? { ...prev } : { ...(body.choice ?? {}) };
        next.remark = body.remark !== undefined ? body.remark : prev.remark;
        if (!next.kind && !next.remark) delete state.choices[body.id];
        else state.choices[body.id] = next;
        await save(session, state);
        return { ok: true };
    }),
    "/submit": async ({ session, body }) => submit(session, body),
};
