// Правка текста: canvas-расширение Copilot. Сессия кампании кладёт сюда
// предложенную правку куска документа, Мастер принимает вариант или
// отклоняет, и принятый текст сразу пишется в файл. Здесь только то, что
// рантайм читает один раз при старте: объявление canvas и действий. Логика
// в logic.mjs, страница в editor.html, оба перечитываются на лету.
// Как устроено - README.md рядом.
import { createServer } from "node:http";
import { readFile, stat } from "node:fs/promises";
import { realpathSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { createCanvas, CanvasError, joinSession } from "@github/copilot-sdk/extension";

process.on("uncaughtException", (e) => process.stderr.write(`uncaught: ${e?.stack ?? e}\n`));
process.on("unhandledRejection", (e) => process.stderr.write(`unhandled: ${e?.stack ?? e}\n`));

// Расширение подключается заглушкой из ~/.copilot/extensions, поэтому
// соседние файлы ищутся от настоящего пути этого файла.
const HERE = dirname(realpathSync(fileURLToPath(import.meta.url)));
const LOGIC = join(HERE, "logic.mjs");
const PAGE = join(HERE, "editor.html");

let loaded = { mtime: 0, module: null };
async function logic() {
    const { mtimeMs } = await stat(LOGIC);
    if (mtimeMs !== loaded.mtime) {
        loaded = { mtime: mtimeMs, module: await import(`${pathToFileURL(LOGIC).href}?v=${mtimeMs}`) };
    }
    return loaded.module;
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
            const route = (await logic()).routes[req.url];
            if (!route) {
                res.writeHead(200, { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" });
                res.end(await readFile(PAGE, "utf8"));
                return;
            }
            const body = JSON.stringify(await route({ session, body: await readBody(req) }));
            res.writeHead(200, { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" });
            res.end(body);
        } catch (e) {
            res.writeHead(500, { "Content-Type": "application/json; charset=utf-8" });
            res.end(JSON.stringify({ error: e.message }));
        }
    });
    await new Promise((r) => http.listen(0, "127.0.0.1", r));
    server = { http, url: `http://127.0.0.1:${http.address().port}/` };
    return server.url;
}

const action = (name, description, inputSchema) => ({
    name,
    description,
    inputSchema,
    handler: async (ctx) => {
        const handler = (await logic()).actions[name];
        if (!handler) throw CanvasError.noHandler();
        try {
            return await handler({ session, input: ctx.input ?? {} });
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
            description: "Предложенная правка куска документа волта: исходник, до трёх вариантов с подсвеченной разницей и кнопки «Принять» / «Не принимать»; принятый вариант пишется в файл.",
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
    ],
});
