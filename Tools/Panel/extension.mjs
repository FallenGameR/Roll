// Пульт Roll: canvas-расширение Copilot. Здесь только то, что рантайм читает
// один раз при старте сессии: объявление canvas и список действий. Вся
// логика в logic.mjs, а страница в panel.html: оба файла перечитываются на
// лету, и их правки не требуют перезапуска. Как устроено - README.md рядом.
import { createServer } from "node:http";
import { readFile, stat } from "node:fs/promises";
import { realpathSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { createCanvas, CanvasError, joinSession } from "@github/copilot-sdk/extension";

// Упавший обработчик не должен ронять весь пульт: панель тогда молча
// перестаёт отвечать. stderr уходит в лог процесса расширения.
process.on("uncaughtException", (e) => process.stderr.write(`uncaught: ${e?.stack ?? e}\n`));
process.on("unhandledRejection", (e) => process.stderr.write(`unhandled: ${e?.stack ?? e}\n`));

// Расширение подключается заглушкой из ~/.copilot/extensions, поэтому
// соседние файлы ищутся от настоящего пути этого файла.
const HERE = dirname(realpathSync(fileURLToPath(import.meta.url)));
const LOGIC = join(HERE, "logic.mjs");
const PAGE = join(HERE, "panel.html");

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
            res.writeHead(200, { "Content-Type": "application/json; charset=utf-8" });
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
            return await handler({ session, input: ctx.input });
        } catch (e) {
            throw new CanvasError(e.code ?? "failed", e.message);
        }
    },
});

session = await joinSession({
    canvases: [
        createCanvas({
            id: "roll-panel",
            displayName: "Пульт Roll",
            description: "Кнопки голосовой диктовки, страницы плейлиста Winamp и бросков кубиков из модуля Roll.",
            actions: [
                action("status", "Состояние диктовки и страницы Winamp, последняя распознанная фраза."),
                action("dictation_log", "Все распознанные фразы диктовки, новые сверху."),
                action("clear_dictation_log", "Скрыть всю историю диктовки до текущего момента."),
                action("start_dictation", "Запустить диктовку (Start-Dictation)."),
                action("stop_dictation", "Остановить диктовку (Stop-Dictation)."),
                action("start_winamp", "Поднять страницу плейлиста Winamp; её адрес в поле winampUrl."),
                action("stop_winamp", "Остановить сервер страницы плейлиста Winamp."),
                action("open_winamp_tab", "Открыть страницу плейлиста Winamp во вкладке встроенного браузера."),
                action("roll", "Бросить кубики: выражение уходит в `TEXT | roll` модуля Roll, например \"2d6+3\" или \"2xd20 vs 15\".",
                    { type: "object", properties: { text: { type: "string" } }, required: ["text"] }),
            ],
            open: async () => ({ title: "Пульт Roll", url: await ensureServer() }),
        }),
    ],
});
