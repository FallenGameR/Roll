// Логика пульта Roll. extension.mjs перечитывает этот файл при каждом его
// изменении, поэтому правки здесь подхватываются без перезапуска сессии.
// Каждый обработчик получает ({ session, body }).
import { connect } from "node:net";
import { execFile, spawn } from "node:child_process";
import { readFile, writeFile } from "node:fs/promises";
import { realpathSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

// Модуль лежит двумя уровнями выше: Roll\Tools\Panel\logic.mjs.
const ROLL = join(dirname(realpathSync(fileURLToPath(import.meta.url))), "..", "..", "Roll.psd1");
const DICTATION_DIR = join(process.env.LOCALAPPDATA ?? "", "Roll", "dictation");
const DICTATION_LOG = join(DICTATION_DIR, "dictation.log");
// Очистка истории не трогает лог: он нужен для отладки. В файл пишется
// момент очистки, и всё, что раньше, пульт больше не показывает.
const CLEARED = join(DICTATION_DIR, "history-cleared.txt");
const WINAMP_PORT = 8731;
const WINAMP_URL = `http://127.0.0.1:${WINAMP_PORT}/`;
const WINAMP_LOG = join(process.env.LOCALAPPDATA ?? "", "Roll", "winamp-start.log");

export class PanelError extends Error {
    constructor(code, message) { super(message); this.code = code; }
}

function pwsh(command, timeout = 240_000) {
    return new Promise((resolve, reject) => {
        execFile("pwsh.exe", ["-NoProfile", "-NonInteractive", "-Command",
            `[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false); ${command}`],
            { windowsHide: true, timeout, encoding: "utf8" },
            (error, stdout, stderr) => {
                if (error) reject(new Error((stderr || error.message).trim()));
                else resolve(stdout.trim());
            });
    });
}

const roll = (command, timeout) => pwsh(`Import-Module '${ROLL}'; ${command}`, timeout);

async function processes() {
    const json = await pwsh(
        "Get-CimInstance Win32_Process -Filter \"Name like 'python%'\" | " +
        "Where-Object { $_.CommandLine -match 'ptt\\.py|tagger\\.py' } | " +
        "Select-Object ProcessId, CommandLine | ConvertTo-Json -Compress", 30_000);
    if (!json) return [];
    const list = JSON.parse(json);
    return Array.isArray(list) ? list : [list];
}

// Голый TCP вместо fetch: undici падал с assert на ответах этого сервера
// и ронял процесс расширения целиком.
function winampUp() {
    return new Promise((resolve) => {
        const socket = connect({ host: "127.0.0.1", port: WINAMP_PORT });
        const done = (ok) => { socket.destroy(); resolve(ok); };
        socket.setTimeout(1500, () => done(false));
        socket.once("connect", () => done(true));
        socket.once("error", () => done(false));
    });
}

async function clearedAt() {
    try { return (await readFile(CLEARED, "utf8")).trim(); } catch { return ""; }
}

// Распознанные фразы из лога диктовки, новые сверху.
export async function phrases(limit = 300) {
    const found = [];
    const since = await clearedAt();
    try {
        const lines = (await readFile(DICTATION_LOG, "utf8")).trimEnd().split(/\r?\n/);
        for (let i = lines.length - 1; i >= 0 && found.length < limit; i--) {
            const m = lines[i].match(/^(\S+) (\d\d:\d\d:\d\d),\d+ ([\d.]+)s audio -> ([\d.]+)s: (.*)$/);
            if (!m || !m[5].trim()) continue;
            if (`${m[1]} ${m[2]}` <= since) break;
            found.push({ date: m[1], time: m[2].slice(0, 5), audio: +m[3], took: +m[4], text: m[5] });
        }
    } catch { /* лога ещё нет */ }
    return found;
}

export async function clearPhrases() {
    const now = new Date();
    const pad = (n) => String(n).padStart(2, "0");
    const stamp = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())} ` +
        `${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`;
    await writeFile(CLEARED, stamp, "utf8");
    return { cleared: stamp };
}

export async function status() {
    const [list, winamp, last] = await Promise.all([processes(), winampUp(), phrases(1)]);
    return {
        dictation: list.some((p) => /ptt\.py/.test(p.CommandLine)),
        winamp,
        winampUrl: WINAMP_URL,
        // По метке последней фразы страница понимает, что пора обновить журнал.
        lastPhrase: last[0] ? `${last[0].date} ${last[0].time} ${last[0].text}` : "",
    };
}

export async function startDictation() {
    await roll("Start-Dictation | Out-Null");
    return status();
}

export async function stopDictation() {
    await roll("Stop-Dictation | Out-Null", 60_000);
    return status();
}

export async function startWinamp() {
    if (!(await winampUp())) {
        // Start-WinampPlaylist держит сервер на переднем плане, поэтому он
        // живёт в отдельном скрытом pwsh, отвязанном от расширения: так
        // страница переживает перезапуск расширения. Запуск идёт через
        // `cmd /c start`: pwsh из Microsoft Store, порождённый напрямую с
        // detached, выходит с кодом 0, не выполнив команду. Перенаправление
        // `*>>` в такой строке тоже ломало запуск, поэтому лог пишет
        // Start-Transcript; хвост лога показывается при ошибке.
        await writeFile(WINAMP_LOG, "", "utf8");
        const command = `Start-Transcript -Path '${WINAMP_LOG}' | Out-Null; Import-Module '${ROLL}'; ` +
            `Start-WinampPlaylist -Port ${WINAMP_PORT} -NoBrowser`;
        const child = spawn("cmd.exe",
            [`/d /s /c "start "" /min pwsh.exe -NoProfile -WindowStyle Hidden -Command "${command}""`],
            { detached: true, stdio: "ignore", windowsHide: true, windowsVerbatimArguments: true });
        child.on("error", (e) => writeFile(WINAMP_LOG, `spawn: ${e.message}\n`, { flag: "a" }));
        child.unref();
        for (let i = 0; i < 40 && !(await winampUp()); i++) {
            await new Promise((r) => setTimeout(r, 500));
        }
        if (!(await winampUp())) {
            let tail = "";
            try { tail = (await readFile(WINAMP_LOG, "utf8")).trim().split(/\r?\n/).slice(-5).join("\n"); } catch { }
            throw new PanelError("winamp_start_failed",
                "Страница Winamp не поднялась за 20 секунд." + (tail ? `\n${tail}` : ` Лог: ${WINAMP_LOG}`));
        }
    }
    return status();
}

export async function stopWinamp() {
    for (const p of await processes()) {
        if (/tagger\.py/.test(p.CommandLine)) {
            await pwsh(`Stop-Process -Id ${p.ProcessId} -Force -ErrorAction SilentlyContinue`, 30_000);
        }
    }
    return status();
}

export function openWinampBrowser() {
    spawn("cmd.exe", ["/c", "start", "", WINAMP_URL], { detached: true, stdio: "ignore", windowsHide: true }).unref();
    return status();
}

// Вкладка встроенного браузера приложения. По `#app` страница снимает с себя
// зум приложения и показывается в масштабе 100%, как в обычном браузере.
export async function openWinampTab({ session }) {
    await session.rpc.canvas.open({
        canvasId: "browser",
        instanceId: "roll-winamp",
        input: { url: `${WINAMP_URL}#app`, title: "Плейлист Winamp", placement: { focus: true } },
    });
    return status();
}

// TEXT | roll. Текст уходит в pwsh строкой в одинарных кавычках, поэтому
// подставить в него команду нельзя: кавычки внутри удваиваются.
export async function rollDice(text) {
    const expression = String(text ?? "").trim();
    if (!expression) throw new PanelError("empty", "Пустое выражение.");
    try {
        return { text: expression, output: await roll(
            `try { '${expression.replace(/'/g, "''")}' | roll 6>&1 } ` +
            "catch { [Console]::Error.WriteLine($_.Exception.Message); exit 1 }", 30_000) };
    } catch (e) {
        return { text: expression, error: e.message.replace(/\x1b\[[0-9;]*m/g, "").trim() };
    }
}

// HTTP-маршруты страницы пульта.
export const routes = {
    "/api/status": () => status(),
    "/api/dictation/start": () => startDictation(),
    "/api/dictation/stop": () => stopDictation(),
    "/api/dictation/log": () => phrases(),
    "/api/dictation/clear": () => clearPhrases(),
    "/api/winamp/start": () => startWinamp(),
    "/api/winamp/stop": () => stopWinamp(),
    "/api/winamp/open": () => openWinampBrowser(),
    "/api/winamp/tab": (ctx) => openWinampTab(ctx),
    "/api/roll": ({ body }) => rollDice(body.text),
};

// Обработчики действий агента. Сам список действий объявлен в
// extension.mjs: он уходит в рантайм при старте и без перезапуска не меняется.
export const actions = {
    status: () => status(),
    dictation_log: () => phrases(),
    clear_dictation_log: () => clearPhrases(),
    start_dictation: () => startDictation(),
    stop_dictation: () => stopDictation(),
    start_winamp: () => startWinamp(),
    stop_winamp: () => stopWinamp(),
    open_winamp_tab: (ctx) => openWinampTab(ctx),
    roll: ({ input }) => rollDice(input?.text),
};
