// Правка текста: canvas-расширение Copilot. Сессия кампании кладёт сюда
// предложенную правку куска документа, Мастер принимает вариант или
// отклоняет, и принятый текст сразу пишется в файл. Здесь только то, что
// рантайм читает один раз при старте: объявление canvas и действий. Логика
// в logic.mjs, страница в editor.html, оба перечитываются на лету.
// Как устроено - README.md рядом.
import { createServer } from "node:http";
import { readFile, stat } from "node:fs/promises";
import { realpathSync } from "node:fs";
import { dirname, extname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { createCanvas, CanvasError, joinSession } from "@github/copilot-sdk/extension";

process.on("uncaughtException", (e) => process.stderr.write(`uncaught: ${e?.stack ?? e}\n`));
process.on("unhandledRejection", (e) => process.stderr.write(`unhandled: ${e?.stack ?? e}\n`));

// Расширение подключается заглушкой из ~/.copilot/extensions, поэтому
// соседние файлы ищутся от настоящего пути этого файла.
const HERE = dirname(realpathSync(fileURLToPath(import.meta.url)));

// Три canvas на одном сервере: «Правка текста» (logic.mjs, editor.html) в
// корне, «Выбор вариантов» (pick.mjs, pick.html) под /pick и «Сравнение
// картинок» (look.mjs, look.html) под /look. Модули перечитываются при
// каждом изменении файла.
const PARTS = {
    editor: { logic: join(HERE, "logic.mjs"), page: join(HERE, "editor.html") },
    pick: { logic: join(HERE, "pick.mjs"), page: join(HERE, "pick.html") },
    look: { logic: join(HERE, "look.mjs"), page: join(HERE, "look.html") },
};
const IMAGE_TYPES = { ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp" };

const loaded = {};
async function logic(part = "editor") {
    const file = PARTS[part].logic;
    const { mtimeMs } = await stat(file);
    if (loaded[part]?.mtime !== mtimeMs) {
        loaded[part] = { mtime: mtimeMs, module: await import(`${pathToFileURL(file).href}?v=${mtimeMs}`) };
    }
    return loaded[part].module;
}

function readBody(req) {
    return new Promise((resolve) => {
        let data = "";
        req.setEncoding("utf8");
        req.on("data", (chunk) => { data += chunk; });
        req.on("end", () => {
            try { resolve(data ? JSON.parse(data) : {}); } catch { resolve({}); }
        });
    });
}

let session;
let server;
async function ensureServer() {
    if (server) return server.url;
    const http = createServer(async (req, res) => {
        try {
            const url = new URL(req.url, "http://x");
            const part = ["pick", "look"].find((p) => url.pathname.startsWith("/" + p)) ?? "editor";
            const path = part === "editor" ? url.pathname : url.pathname.slice(part.length + 1) || "/";
            const route = (await logic(part)).routes[path];
            if (!route) {
                res.writeHead(200, { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" });
                res.end(await readFile(PARTS[part].page, "utf8"));
                return;
            }
            const query = Object.fromEntries(url.searchParams);
            const out = await route({ session, body: await readBody(req), query });
            // Маршрут может отдать файл картинки: { file: путь }.
            if (out && out.file) {
                const type = IMAGE_TYPES[extname(out.file).toLowerCase()];
                if (!type) throw new Error("не картинка");
                res.writeHead(200, { "Content-Type": type, "Cache-Control": "no-cache" });
                res.end(await readFile(out.file));
                return;
            }
            res.writeHead(200, { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" });
            res.end(JSON.stringify(out));
        } catch (e) {
            res.writeHead(500, { "Content-Type": "application/json; charset=utf-8" });
            res.end(JSON.stringify({ error: e.message }));
        }
    });
    await new Promise((r) => http.listen(0, "127.0.0.1", r));
    server = { http, url: `http://127.0.0.1:${http.address().port}/` };
    return server.url;
}

const action = (name, description, inputSchema, part = "editor") => ({
    name,
    description,
    inputSchema,
    handler: async (ctx) => {
        const handler = (await logic(part)).actions[name];
        if (!handler) throw CanvasError.noHandler();
        try {
            return await handler({ session, input: ctx.input ?? {}, instanceId: ctx.instanceId });
        } catch (e) {
            throw new CanvasError(e.code ?? "failed", e.message);
        }
    },
});

session = await joinSession({
    canvases: [
        createCanvas({
            id: "roll-editor",
            displayName: "Правка текста",
            description: "Предложенная правка куска документа волта: до трёх вариантов с подсвеченной разницей и кнопки «Принять» / «Не принимать»; принятый вариант пишется в файл.",
            actions: [
                action("propose",
                    "Показать правку. original - кусок файла байт в байт (целые абзацы), variants - до трёх вариантов, первый основной. " +
                    "Заменяет предыдущую правку. О решении Мастера расширение сообщит в сессию сообщением.",
                    {
                        type: "object",
                        properties: {
                            file: { type: "string", description: "Полный путь к файлу." },
                            original: { type: "string", minLength: 1 },
                            variants: {
                                type: "array", minItems: 1, maxItems: 3,
                                items: {
                                    type: "object",
                                    properties: { text: { type: "string" }, note: { type: "string" } },
                                    required: ["text"],
                                },
                            },
                            comment: { type: "string" },
                        },
                        required: ["file", "original", "variants"],
                    }),
                action("status", "Последняя правка и её состояние: ждёт, принята (с номером варианта), отклонена или устарела."),
            ],
            open: async () => ({ title: "Правка текста", url: await ensureServer() }),
        }),
        createCanvas({
            id: "roll-pick",
            displayName: "Выбор вариантов",
            description: "Таблица строк с вариантами (например, глоссарий перевода): Мастер выбирает вариант одним кликом, пишет свой или откладывает на обсуждение, и отправляет решения в сессию.",
            actions: [
                action("propose",
                    "Показать порцию строк. rows - строки, либо tsv - путь к TSV с колонками term, variants (через «; »), " +
                    "comment и необязательными id, recommended, group, category, book; group отбирает строки TSV по колонке group. " +
                    "Заменяет прежнюю порцию. По кнопке «Отправить» решения придут в сессию сообщением [Выбор вариантов] " +
                    "и будут записаны в TSV рядом с состоянием сессии.",
                    {
                        type: "object",
                        properties: {
                            title: { type: "string" },
                            rows: {
                                type: "array",
                                items: {
                                    type: "object",
                                    properties: {
                                        id: { type: "string" },
                                        term: { type: "string" },
                                        variants: { type: "array", items: { type: "string" } },
                                        comment: { type: "string" },
                                        recommended: { type: ["integer", "string"],
                                            description: "Номер варианта с нуля или его текст." },
                                        note: { type: "string" },
                                    },
                                    required: ["term", "variants"],
                                },
                            },
                            tsv: { type: "string", description: "Полный путь к TSV (UTF-8, TAB)." },
                            group: { type: "string" },
                        },
                        required: ["title"],
                    }, "pick"),
                action("status", "Текущая порция: решения по строкам, сколько решено, отправлена ли.", undefined, "pick"),
            ],
            open: async () => ({ title: "Выбор вариантов", url: (await ensureServer()) + "pick" }),
        }),
        createCanvas({
            id: "roll-look",
            displayName: "Сравнение картинок",
            description: "Крупное сравнение вариантов картинок по группам: на каждую «нравится» / «не нравится» и комментарий, общий комментарий на группу; по кнопке «Отправить» оценки уходят в сессию.",
            actions: [
                action("propose",
                    "Показать круг. groups - группы вариантов, по группе на кадр: { name, images: [полные пути PNG/JPG/WebP], note? }. " +
                    "Состояние своё у каждого instanceId: новый круг - новый instanceId или новый propose в тот же. " +
                    "По кнопке «Отправить» оценки придут в сессию сообщением [Сравнение картинок] и запишутся в TSV рядом с состоянием сессии.",
                    {
                        type: "object",
                        properties: {
                            title: { type: "string" },
                            groups: {
                                type: "array", minItems: 1,
                                items: {
                                    type: "object",
                                    properties: {
                                        name: { type: "string" },
                                        images: { type: "array", minItems: 1, items: { type: "string" } },
                                        note: { type: "string" },
                                    },
                                    required: ["name", "images"],
                                },
                            },
                        },
                        required: ["title", "groups"],
                    }, "look"),
                action("status", "Оценки этого круга: по картинке оценка и комментарий, по группе комментарий; отправлен ли.", undefined, "look"),
            ],
            open: async (ctx) => ({
                title: "Сравнение картинок",
                url: (await ensureServer()) + "look?i=" + encodeURIComponent(ctx.instanceId),
            }),
        }),
    ],
});
