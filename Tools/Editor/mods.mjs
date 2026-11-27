// Логика canvas «Моды Remarkable». Статус собирается одним заходом по SSH:
// база установленного Vellum, индекс каталога, файлы модов на планшете,
// версия прошивки и загружен ли XOVI. Мастер выбирает действие по каждому
// моду, «Применить» выполняет всё разом и заводит страховку: если за
// три минуты не нажать «Всё в порядке», планшет сам выключает моды.
// Как устроено - README.md рядом, про сами моды - скилл remarkable-mods.
import { spawn } from "node:child_process";
import { existsSync, readdirSync } from "node:fs";
import { readFile, writeFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { basename, dirname, join } from "node:path";
import { realpathSync } from "node:fs";
import { fileURLToPath } from "node:url";

const HERE = dirname(realpathSync(fileURLToPath(import.meta.url)));
const ROLL = join(HERE, "..", "..");
const ASKPASS = join(ROLL, "Tools", "Remarkable", "askpass.cmd");
const LOCAL_MODS = join(ROLL, "Remarkable", "mods");

const X = "/home/root/xovi";
const Q = `${X}/exthome/qt-resource-rebuilder`;
const E = `${X}/extensions.d`;
const D = `${X}/disabled-mods`;
const ASSETS = `${X}/exthome/own-assets`;
const VELLUM = "/home/root/.vellum/bin/vellum";
const TRIAL_SECONDS = 900;

const SYSTEM = new Set(["xovi", "xovi-extensions", "qt-resource-rebuilder", "qt-command-executor",
    "xovi-message-broker", "vellum", "vellum-bash-completion", "remarkable-os", "rmpp"]);
const DEVICES = new Set(["rm1", "rm2", "rmpp", "rmppm"]);

// Описания по-русски для того, что у нас стоит или стояло; остальным
// достаётся английское из каталога.
const RU = {
    "disable-infinite-scroll": "Не даёт листу уезжать за края страницы при прокрутке и масштабе.",
    "faster-page-labels": "Номер страницы прячется через ~1,25 с после перелистывания.",
    "faster-scroll-bar": "Полоса прокрутки прячется через ~0,35 с после остановки.",
    "filter-annotated-pages": "Кнопка в обзоре страниц: показать только страницы с пометками.",
    "fix-battery-indicator": "Значок батареи обновляется после зарядки во сне.",
    "ghostbuster": "Тап пятью пальцами - полная перерисовка экрана.",
    "librarian": "Расширение для управления библиотекой документов.",
    "mount-utils": "Команды: система только для чтения или для записи.",
    "nav-history": "Назад и вперёд по истории просмотренных страниц.",
    "scroll-screen-up-or-down": "Прокрутка экрана со сменой страницы на границе; нужна для навигации тапом.",
    "sort-templates-recent": "Шаблоны в выборе отсортированы по недавнему использованию.",
    "tap-to-change-view-or-page": "Тап по краю экрана листает, когда панель скрыта.",
    "three-finger-swipe-to-reset-view": "Свайп тремя пальцами вниз сбрасывает масштаб на 100%.",
    "touch-lock": "Кнопка на панели: заблокировать касания, перо работает.",
    "tripletap": "Тройное нажатие кнопки питания запускает моды (XOVI).",
    "ghostbuster-page.qmd": "Полная перерисовка при перелистывании и переходе по папкам.",
    "ghostbuster-eraser.qmd": "Полная перерисовка после ластика.",
    "ghostbuster-settings.qmd": "Полная перерисовка при выходе из настроек.",
    "ghostbuster-global.qmd": "Тап пятью пальцами где угодно - перерисовка (EPFramebuffer.clearGhosting).",
    "ghostbuster-everywhere.qmd": "Тап пятью пальцами перерисовывает экран где угодно: в документе, в библиотеке, в настройках.",
    "ghostbuster-automated.qmd": "Сам перерисовывает экран там, где остаются следы: после ввода PIN и первой отрисовки библиотеки, при входе в настройки, после значка ожидания. В PDF ещё после медленного перелистывания, закрытия панельки на панели инструментов и скрытия самой панели; в заметках и EPUB этого не делает.",
    "sleep-rotate.qmd": "Своя картинка сна на весь экран, без рамки, и они сменяются от сна к сну: sleep-1.png, sleep-2.png... из /home/root/sleepscreen. Номер берёт у встроенной карусели прошивки.",
    "tap-page-turn.qmd": "Тап по левой или правой четверти экрана ниже верхней трети листает назад или вперёд; длинную страницу сначала прокручивает. Когда панель скрыта, работает всегда; когда показана, только если включена кнопка-книга на панели (или пункт Tap Turn в меню, если панели тесно). Один файл вместо пары модов Vellum.",
    "touch-lock.qmd": "Кнопка на панели: заблокировать касания, перо работает. Копия touch-lock из Vellum со своими иконками: тонкий открытый замок с откинутой дужкой и жирный закрытый. Иконки ставятся в xovi/exthome/own-assets/touch-lock.",
};

const ACTION_NAMES = {
    enable: "включить", disable: "выключить", upgrade: "обновить",
    remove: "удалить", install: "поставить",
};

const fail = (code, message) => Object.assign(new Error(message), { code });

// ---------- SSH ----------

function preset() {
    const ini = join(process.env.APPDATA ?? "", "davisr", "rcu.ini");
    if (!existsSync(ini)) throw fail("no_preset", "Нет пресета RCU: Set-RemarkableConnection.");
    return readFile(ini, "utf8").then((text) => {
        const line = text.split(/\r?\n/).find((l) => l.startsWith("presets="));
        if (!line) throw fail("no_preset", "Нет пресета RCU: Set-RemarkableConnection.");
        let v = line.slice("presets=".length);
        if (v.startsWith('"') && v.endsWith('"')) v = v.slice(1, -1);
        const data = JSON.parse(v.replaceAll('\\"', '"').replaceAll("\\\\", "\\"));
        const p = data.presets?.[Number(data.active) || 0];
        if (!p?.host) throw fail("no_preset", "Нет пресета RCU: Set-RemarkableConnection.");
        return p;
    });
}

function run(cmd, args, input, timeoutMs) {
    return new Promise((resolve) => {
        const child = spawn(cmd, args, {
            env: { ...process.env, SSH_ASKPASS: ASKPASS, SSH_ASKPASS_REQUIRE: "force" },
            windowsHide: true,
        });
        let out = "", err = "";
        child.stdout.setEncoding("utf8").on("data", (c) => { out += c; });
        child.stderr.setEncoding("utf8").on("data", (c) => { err += c; });
        const timer = setTimeout(() => { err += "\nпревышено время ожидания"; child.kill(); }, timeoutMs);
        child.on("error", (e) => { err += e.message; });
        child.on("close", (code) => { clearTimeout(timer); resolve({ code, out, err }); });
        if (input != null) child.stdin.end(input.replace(/\r/g, ""));
        else child.stdin.end();
    });
}

const SSH_OPTS = ["-o", "ConnectTimeout=5", "-o", "StrictHostKeyChecking=accept-new"];

async function ssh(script, timeoutMs = 180000) {
    const p = await preset();
    const r = await run("ssh", ["-T", ...SSH_OPTS, `${p.username}@${p.host}`, "sh -s"], script, timeoutMs);
    if (r.code === 255) {
        throw fail("offline", `Планшет не отвечает по ${p.host}: разбуди его и проверь Wi-Fi.` +
            (r.err.trim() ? `\n${r.err.trim()}` : ""));
    }
    return r;
}

async function scp(local, remote, recursive = false) {
    const p = await preset();
    const r = await run("scp", ["-O", "-q", ...(recursive ? ["-r"] : []), ...SSH_OPTS, local, `${p.username}@${p.host}:${remote}`], null, 60000);
    if (r.code !== 0) throw fail("scp", `scp не прошёл: ${r.err.trim()}`);
}

// ---------- разбор ----------

function records(text) {
    const out = [];
    let cur = null;
    for (const line of text.split("\n")) {
        if (!line.trim()) { if (cur) out.push(cur); cur = null; continue; }
        const m = /^(.):(.*)$/.exec(line);
        if (!m) continue;
        cur ??= { files: [] };
        const [, k, v] = m;
        if (k === "F") cur.dir = v;
        else if (k === "R") cur.files.push("/" + (cur.dir ? cur.dir + "/" : "") + v);
        else if (!(k in cur)) cur[k] = v;
    }
    if (cur) out.push(cur);
    return out.filter((r) => r.P);
}

function vparts(v) {
    const [main, rev] = String(v).split(/-r(?=\d+$)/);
    const tok = (main.match(/\d+|[a-z]+/gi) ?? []).map((t) => (/^\d+$/.test(t) ? Number(t) : t));
    return { tok, rev: Number(rev ?? 0) };
}

export function vcmp(a, b) {
    const x = vparts(a), y = vparts(b);
    for (let i = 0; i < Math.max(x.tok.length, y.tok.length); i++) {
        const p = x.tok[i], q = y.tok[i];
        if (p === undefined) return -1;
        if (q === undefined) return 1;
        if (p === q) continue;
        if (typeof p === "number" && typeof q === "number") return p < q ? -1 : 1;
        return String(p) < String(q) ? -1 : 1;
    }
    return x.rev - y.rev;
}

function parseDeps(d) {
    return (d ?? "").split(/\s+/).filter(Boolean).map((t) => {
        const m = /^(!?)([^<>=~]+)(>=|<=|>|<|=|~)?(.*)$/.exec(t);
        return { neg: !!m[1], name: m[2], op: m[3] ?? "", ver: m[4] ?? "" };
    });
}

function osOk(deps, os) {
    for (const d of deps) {
        if (d.name !== "remarkable-os" || !d.op) continue;
        const c = vcmp(os, d.ver);
        const ok = { ">=": c >= 0, "<=": c <= 0, ">": c > 0, "<": c < 0, "=": c === 0, "~": c >= 0 }[d.op];
        if (!ok) return false;
    }
    return true;
}

const realDep = (d) => !d.neg && d.name !== "remarkable-os" && !DEVICES.has(d.name) && !/^[/]|:/.test(d.name);

function osRange(deps) {
    return deps.filter((d) => d.name === "remarkable-os" && d.op).map((d) => d.op + d.ver).join(" ");
}

function sections(text) {
    const out = {};
    let key = null;
    for (const line of text.split("\n")) {
        const m = /^@@([A-Z]+)$/.exec(line.trim());
        if (m) { key = m[1]; out[key] = []; continue; }
        if (key) out[key].push(line);
    }
    return Object.fromEntries(Object.entries(out).map(([k, v]) => [k, v.join("\n")]));
}

// Сторонний мод - подпапка Remarkable\mods со своим LICENSE, как у
// ghostbuster-reloaded; свой - такая же подпапка в Remarkable\mods\own.
// Остальное там - копии модов Vellum и расшифровки. Папка assets рядом с
// .qmd (иконки и прочее) ставится в ASSETS/<папка мода>.
function localThirdParty() {
    const out = [];
    const scan = (root, own) => {
        if (!existsSync(root)) return;
        for (const dir of readdirSync(root, { withFileTypes: true })) {
            if (!dir.isDirectory() || !existsSync(join(root, dir.name, "LICENSE"))) continue;
            const assets = join(root, dir.name, "assets");
            for (const f of readdirSync(join(root, dir.name))) {
                if (f.endsWith(".qmd")) out.push({ name: f, source: dir.name, own, local: join(root, dir.name, f), assets: existsSync(assets) ? assets : null });
            }
        }
    };
    scan(LOCAL_MODS, false);
    scan(join(LOCAL_MODS, "own"), true);
    return out;
}

const STATUS_SCRIPT = `
V=${VELLUM}
[ "\${FETCH:-0}" = 1 ] && $V update >/dev/null 2>&1
echo @@OS; . /etc/os-release; echo "$IMG_VERSION"
echo @@XOVI; P=$(pidof xochitl)
if [ -z "$P" ]; then echo down; elif tr '\\0' '\\n' < /proc/$P/environ | grep -q '^LD_PRELOAD=${X}/xovi.so'; then echo on; else echo off; fi
echo @@TRIAL; cat /tmp/mod-trial 2>/dev/null
echo @@TRIALSTATE; cat ${X}/trial.state 2>/dev/null
echo @@NOW; date +%s
echo @@HASHTAB; cat ${X}/hashtab.os 2>/dev/null; [ -f /tmp/hashtab.running ] && echo running
echo @@INSTALLED; cat /home/root/.vellum/lib/apk/db/installed
echo @@INDEX; for f in /home/root/.vellum/etc/apk/cache/APKINDEX.*.tar.gz /home/root/.vellum/local-repo/*/APKINDEX.tar.gz; do [ -f "$f" ] && tar -xzOf "$f" APKINDEX; echo; done
echo @@FILES; find ${Q} ${E} ${D} -type f 2>/dev/null
echo @@SUMS; find ${Q} ${D} -name "*.qmd" -type f -exec md5sum {} + 2>/dev/null
echo @@LOADERS; for f in ${Q}/_*.qmd; do [ -f "$f" ] && cat "$f"; echo; done
echo @@END
`;

async function fetchStatus(fetchIndex = false) {
    const r = await ssh(`FETCH=${fetchIndex ? 1 : 0}\n` + STATUS_SCRIPT, 120000);
    const s = sections(r.out);
    if (!("END" in s)) throw fail("status", `Статус не собрался: ${r.err.trim() || r.out.slice(-400)}`);
    return build(s);
}

function build(s) {
    const os = s.OS.trim();
    const files = new Set(s.FILES.split("\n").map((l) => l.trim()).filter(Boolean));
    const sums = new Map((s.SUMS ?? "").split("\n").map((l) => l.trim().split(/\s+/)).filter((p) => p.length === 2).map(([h, f]) => [f, h]));
    const loaded = new Set((s.LOADERS ?? "").split("\n").map((l) => /^LOAD\s+(\S+)/.exec(l.trim())?.[1]).filter(Boolean));
    const live = (f) => files.has(f) && (!loaderOf(f) || loaded.has(loaderOf(f).rel));
    const installed = records(s.INSTALLED);
    const index = records(s.INDEX);
    const now = Number(s.NOW.trim());
    const trialEnd = Number(s.TRIAL.trim()) || 0;
    const [tKind, tAt] = (s.TRIALSTATE ?? "").trim().split(/\s+/);
    // armed без /tmp/mod-trial - таймер пропал вместе с перезагрузкой.
    const trialLast = !tKind ? null
        : tKind === "armed" ? (trialEnd ? null : { kind: "reboot", at: Number(tAt) * 1000 })
            : { kind: tKind, at: Number(tAt) * 1000, ago: now - Number(tAt) };
    const hashLines = s.HASHTAB.split("\n").map((l) => l.trim()).filter(Boolean);

    const byName = new Map();
    for (const r of index) {
        if (!byName.has(r.P)) byName.set(r.P, []);
        byName.get(r.P).push(r);
    }
    const provided = new Set(index.flatMap((r) => (r.p ?? "").split(/\s+/).map((x) => x.split("=")[0]).filter(Boolean)));
    const instNames = new Set(installed.map((r) => r.P));
    const devOk = (deps) => deps.every((d) => d.neg || !DEVICES.has(d.name) || instNames.has(d.name));
    const best = (name) => {
        const vs = (byName.get(name) ?? []).filter((r) => {
            const deps = parseDeps(r.D);
            return osOk(deps, os) && devOk(deps);
        });
        vs.sort((a, b) => vcmp(b.V, a.V));
        return vs[0] ?? null;
    };

    const requiredBy = {};
    for (const r of installed) {
        for (const d of parseDeps(r.D)) {
            if (!realDep(d)) continue;
            const list = (requiredBy[d.name] ??= []);
            if (!list.includes(r.P)) list.push(r.P);
        }
    }

    const owned = new Set();
    const items = [];
    for (const r of installed) {
        const deps = parseDeps(r.D);
        const modFiles = r.files.filter((f) => f.startsWith(Q + "/") || f.startsWith(E + "/"));
        modFiles.forEach((f) => owned.add(f));
        const kind = SYSTEM.has(r.P) ? "system" : modFiles.length ? "mod" : "utility";
        const on = modFiles.filter(live).length;
        const off = modFiles.filter((f) => files.has(D + f)).length;
        const stuck = modFiles.filter((f) => files.has(f) && !live(f)).length;
        const state = kind !== "mod" ? "стоит"
            : on === modFiles.length ? "включён"
                : off === modFiles.length ? "выключен"
                    : stuck ? "не загружается"
                        : on + off === 0 ? "файлов нет" : "частично";
        const fresh = best(r.P);
        items.push({
            key: "pkg:" + r.P, name: r.P, kind, source: "vellum", state,
            version: r.V, fresh: fresh && vcmp(fresh.V, r.V) > 0 ? fresh.V : null,
            compatible: osOk(deps, os), osRange: osRange(deps),
            freshRange: fresh ? osRange(parseDeps(fresh.D)) : "",
            noFresh: !fresh,
            needs: deps.filter(realDep).map((d) => d.name).filter((n, i, a) => a.indexOf(n) === i),
            requiredBy: requiredBy[r.P] ?? [],
            desc: RU[r.P] ?? r.T ?? "", url: r.U ?? "",
            files: modFiles,
        });
    }

    // Сторонние: файлы модов без хозяина-пакета на планшете и .qmd из
    // подпапок Remarkable\mods.
    const third = new Map();
    for (const f of files) {
        const orig = f.startsWith(D + "/") ? f.slice(D.length) : f;
        if (owned.has(orig) || orig === Q + "/hashtab" || /^_.*\.qmd$/.test(basename(orig)) && dirname(orig) === Q) continue;
        if (!(orig.startsWith(Q + "/") || orig.startsWith(E + "/"))) continue;
        const name = basename(orig);
        const it = third.get(name) ?? { files: new Set(), on: 0, off: 0 };
        it.files.add(orig);
        if (f === orig) it.on++; else it.off++;
        third.set(name, it);
    }
    const local = localThirdParty();
    for (const l of local) if (!third.has(l.name)) third.set(l.name, { files: new Set([`${Q}/${l.name}`]), on: 0, off: 0 });
    for (const [name, it] of third) {
        const l = local.find((x) => x.name === name);
        items.push({
            key: "3p:" + name, name: name.replace(/\.qmd$/, ""), file: name, kind: l?.own ? "own" : "third", source: l ? l.source : "на планшете",
            state: it.on && !it.off ? "включён" : it.off && !it.on ? "выключен" : it.on ? "частично" : "не стоит",
            version: "", fresh: null, compatible: true, needs: [], requiredBy: [],
            desc: RU[name] ?? "", files: [...it.files], local: l?.local ?? null, assets: l?.assets ?? null, assetsDir: l ? `${ASSETS}/${l.source}` : null,
            // Обновлять есть что, только если файл на планшете не совпадает с нашим.
            differs: !!l && [...it.files].some((f) => { const h = sums.get(f) ?? sums.get(D + f); return h && h !== md5(l.local); }),
        });
    }

    const catalog = [];
    for (const [name] of byName) {
        if (instNames.has(name) || SYSTEM.has(name) || DEVICES.has(name)) continue;
        const b = best(name);
        if (!b) continue;
        catalog.push({
            key: "pkg:" + name, name, kind: "catalog", source: "vellum", state: "не стоит",
            version: "", fresh: b.V, compatible: true, osRange: osRange(parseDeps(b.D)),
            needs: parseDeps(b.D).filter(realDep).map((d) => d.name).filter((n, i, a) => a.indexOf(n) === i),
            requiredBy: [], desc: RU[name] ?? b.T ?? "", url: b.U ?? "", files: [],
        });
    }
    catalog.sort((a, b) => a.name.localeCompare(b.name));

    return {
        at: new Date().toISOString(), os, xovi: s.XOVI.trim(),
        trial: trialEnd && trialEnd > now ? { left: trialEnd - now } : null,
        trialLast,
        hashtab: { os: hashLines.find((l) => l !== "running") ?? "", running: hashLines.includes("running") },
        items, catalog,
        provided: [...provided].length,
    };
}

function actionsFor(it) {
    if (it.kind === "catalog") return ["install"];
    if (it.kind === "third" || it.kind === "own") {
        if (it.state === "не стоит") return it.local ? ["install"] : [];
        const a = it.state === "включён" ? ["disable"] : it.state === "выключен" ? ["enable"] : ["enable", "disable"];
        if (it.local && it.differs) a.push("upgrade");
        return [...a, "remove"];
    }
    const a = [];
    if (it.kind === "mod") {
        if (it.state !== "включён") a.push("enable");
        if (it.state !== "выключен") a.push("disable");
    }
    if (it.fresh) a.push("upgrade");
    if (it.kind !== "system") a.push("remove");
    return a;
}

// ---------- состояние ----------

const mem = { status: null, choices: {}, busy: null, log: [], error: null, last: null };

function storePath(session) {
    return session?.workspacePath ? join(session.workspacePath, "roll-mods.json") : null;
}

async function loadChoices(session) {
    const p = storePath(session);
    if (!p || mem.loaded) return;
    mem.loaded = true;
    try {
        const s = JSON.parse(await readFile(p, "utf8"));
        mem.choices = s.choices ?? {};
        mem.last = s.last ?? null;
    } catch { }
}

async function saveChoices(session) {
    const p = storePath(session);
    if (p) await writeFile(p, JSON.stringify({ choices: mem.choices, last: mem.last }, null, 1), "utf8");
}

function view() {
    const st = mem.status;
    const decorate = (it) => ({ ...it, actions: actionsFor(it), choice: mem.choices[it.key] ?? "" });
    return {
        busy: mem.busy, log: mem.log, error: mem.error, last: mem.last, checked: mem.checked ?? null,
        status: st && {
            ...st,
            items: st.items.map(decorate),
            catalog: st.catalog.map(decorate),
            trial: st.trial && { end: Date.parse(st.at) + st.trial.left * 1000 },
        },
    };
}

async function busy(label, fn) {
    if (mem.busy) throw fail("busy", `Занята: ${mem.busy}`);
    mem.busy = label;
    mem.error = null;
    try { return await fn(); }
    catch (e) { mem.error = e.message; throw e; }
    finally { mem.busy = null; }
}

async function refresh(fetchIndex) {
    mem.status = await fetchStatus(fetchIndex);
    // Выбор, который больше не применим (мод уже включён и т. п.), снимается.
    const all = [...mem.status.items, ...mem.status.catalog];
    for (const [k, a] of Object.entries(mem.choices)) {
        const it = all.find((x) => x.key === k);
        if (!it || !actionsFor(it).includes(a)) delete mem.choices[k];
    }
}

const q = (s) => "'" + String(s).replace(/'/g, "'\\''") + "'";

const TS = `${X}/trial.state`;
const ARM = `END=$(( $(date +%s) + ${TRIAL_SECONDS} )); echo $END > /tmp/mod-trial; echo "armed $END" > ${TS}
setsid sh -c 'while [ -f /tmp/mod-trial ] && [ $(date +%s) -lt $(cat /tmp/mod-trial 2>/dev/null || echo 0) ]; do sleep 5; done
if [ -f /tmp/mod-trial ]; then rm -f /tmp/mod-trial; echo "fired $(date +%s)" > ${TS}; umount -q /etc/systemd/system/xochitl.service.d; systemctl daemon-reload; systemctl restart xochitl; fi' </dev/null >/dev/null 2>&1 &
`;
const DISARM = (how) => `[ -f /tmp/mod-trial ] && echo "${how} $(date +%s)" > ${TS}; rm -f /tmp/mod-trial\n`;
// У xochitl в юните StartLimitBurst=4 за 10 минут: это защита от петли
// падений, после неё планшет перезагружается чистым, без модов. Наши
// перезапуски намеренные, их счётчик обнуляется, но только если интерфейс
// за эти 10 минут сам не падал: тогда защита остаётся в силе.
const RESET = `journalctl -u xochitl --since "-10min" --no-pager 2>/dev/null | grep -q "Main process exited\\|code=dumped\\|code=killed" && echo "@@LOG интерфейс недавно падал: защиту от перезапусков не трогаю" || systemctl reset-failed xochitl; `;
const XOVI_ON = RESET + `(setsid ${X}/start </dev/null >/dev/null 2>&1 &); echo "@@LOG XOVI запущен с модами"\n`;
const XOVI_OFF = RESET + `umount -q /etc/systemd/system/xochitl.service.d; systemctl daemon-reload; systemctl restart xochitl; echo "@@LOG XOVI остановлен, интерфейс без модов"\n`;

// Мод из подпапки qt-resource-rebuilder (ingatellent/x.qmd) qmldiff сам не
// видит: его подключает строка «LOAD ingatellent/x.qmd» в загрузчике
// _ingatellent.qmd в корне. Загрузчик ведёт установщик пакета, и при
// ручном включении и выключении строку надо дописывать и убирать самой.
const md5 = (p) => createHash("md5").update(readFileSync(p)).digest("hex");

function loaderOf(f) {
    const rel = f.startsWith(Q + "/") ? f.slice(Q.length + 1) : "";
    if (!rel.includes("/")) return null;
    return { rel, file: `${Q}/_${rel.split("/")[0]}.qmd` };
}

export function moveScript(fileList, enable) {
    return fileList.map((f) => {
        const l = loaderOf(f);
        if (enable) {
            const load = l ? `; then touch ${q(l.file)}; grep -qx ${q("LOAD " + l.rel)} ${q(l.file)} || echo ${q("LOAD " + l.rel)} >> ${q(l.file)}; echo "@@LOG подключён ${l.rel}"` : "";
            return `if [ -f ${q(D + f)} ]; then mkdir -p ${q(dirname(f))}; if [ -f ${q(f)} ]; then rm -f ${q(D + f)}; else mv ${q(D + f)} ${q(f)}; fi; echo "@@LOG включён ${basename(f)}"; fi` +
                (l ? `\nif [ -f ${q(f)} ]${load}; fi` : "");
        }
        const unload = l ? `\nif [ -f ${q(l.file)} ]; then sed -i ${q("\\|^LOAD " + l.rel + "$|d")} ${q(l.file)}; [ -s ${q(l.file)} ] || rm -f ${q(l.file)}; fi` : "";
        return `if [ -f ${q(f)} ]; then mkdir -p ${q(dirname(D + f))}; mv -f ${q(f)} ${q(D + f)}; echo "@@LOG выключен ${basename(f)}"; fi` + unload;
    }).join("\n") + "\n";
}

// Ошибки оболочки на планшете (sh: ... syntax error и т. п.) не роняют
// сценарий, а просто пропускают строку; их надо показать.
function shErrors(err) {
    return err.split("\n").map((l) => l.trim()).filter((l) => /^(sh|-sh|ash|bash):|syntax error|not found|No such file/i.test(l))
        .map((l) => "ОШИБКА: " + l);
}

function logLines(text) {
    return text.split("\n").map((l) => l.replace(/^@@LOG /, "").trimEnd())
        .filter((l) => l && !/reenable/.test(l));
}

async function apply(session, opts) {
    return busy("применяю", async () => {
        mem.log = [];
        if (!mem.status) await refresh(false);
        const all = [...mem.status.items, ...mem.status.catalog];
        const chosen = { ...mem.choices };
        const plan = Object.entries(chosen)
            .map(([k, a]) => ({ it: all.find((x) => x.key === k), a }))
            .filter((p) => p.it && actionsFor(p.it).includes(p.a));
        if (!plan.length) throw fail("empty", "Ничего не отмечено.");

        const pkgs = (a) => plan.filter((p) => p.a === a && p.it.source === "vellum").map((p) => p.it.name);
        const del = pkgs("remove"), add = pkgs("install"), upg = pkgs("upgrade");
        const wasOff = new Set(mem.status.items.filter((i) => i.kind === "mod" && i.state === "выключен").map((i) => i.name));

        // Сторонние файлы кладутся до перезапуска, scp отдельно от ssh.
        for (const p of plan) {
            if ((p.it.kind === "third" || p.it.kind === "own") && (p.a === "install" || p.a === "upgrade") && p.it.local) {
                const dest = p.a === "upgrade" && p.it.state === "выключен" ? D + p.it.files[0] : `${Q}/${p.it.file}`;
                if (p.a === "upgrade" && p.it.state === "выключен") await ssh(`mkdir -p ${q(dirname(dest))}`);
                await scp(p.it.local, dest);
                if (p.it.assets) {
                    await ssh(`rm -rf ${q(p.it.assetsDir)}; mkdir -p ${q(ASSETS)}`);
                    await scp(p.it.assets, p.it.assetsDir, true);
                }
                mem.log.push(`${p.a === "install" ? "поставлен" : "обновлён"} ${p.it.name}`);
            }
        }

        const trial = opts.trial !== false;
        // XOVI после применения работает, если останется хоть один включённый мод.
        const willOn = (it) => {
            const a = chosen[it.key];
            if (a === "disable" || a === "remove") return false;
            if (a === "enable" || a === "install") return true;
            return it.state === "включён" || it.state === "частично";
        };
        const start = [...mem.status.items.filter((i) => i.kind === "mod" || i.kind === "third" || i.kind === "own"), ...plan.filter((p) => p.it.kind === "catalog").map((p) => p.it)]
            .some(willOn);
        let script = "V=" + VELLUM + "\n";
        if (trial && start) script += ARM;
        if (del.length) script += `echo "@@LOG vellum del ${del.join(" ")}"; $V del ${del.map(q).join(" ")} 2>&1 </dev/null\n`;
        if (add.length) script += `echo "@@LOG vellum add ${add.join(" ")}"; $V add ${add.map(q).join(" ")} 2>&1 </dev/null\n`;
        if (upg.length) script += `echo "@@LOG vellum add -u ${upg.join(" ")}"; $V add -u ${upg.map(q).join(" ")} 2>&1 </dev/null\n`;
        for (const p of plan) {
            // Выключенные копии удалённого пакета Vellum не видит, их убираю сама.
            if (p.it.kind === "mod" && p.a === "remove") {
                script += p.it.files.map((f) => `rm -f ${q(D + f)}`).join("\n") + "\n";
            }
            if ((p.it.kind === "third" || p.it.kind === "own") && p.a === "remove") {
                script += p.it.files.map((f) => `rm -f ${q(f)} ${q(D + f)}`).join("\n") +
                    (p.it.assetsDir ? `\nrm -rf ${q(p.it.assetsDir)}` : "") + `\necho "@@LOG удалён ${p.it.name}"\n`;
            }
        }
        const r1 = await ssh(script, 300000);
        mem.log.push(...logLines(r1.out), ...shErrors(r1.err));

        // После Vellum список файлов мог поменяться: перечитываю статус и
        // раскладываю файлы так, как выбрано.
        await refresh(false);
        let moves = "";
        for (const it of mem.status.items) {
            if (it.kind !== "mod" && it.kind !== "third" && it.kind !== "own") continue;
            const a = chosen[it.key];
            let want = null;
            if (a === "enable" || a === "install") want = true;
            else if (a === "disable") want = false;
            else if (a === "upgrade" && it.kind === "mod") want = !wasOff.has(it.name);
            if (want !== null) moves += moveScript(it.files, want);
        }
        const anyOn = () => mem.status.items.some((i) => (i.kind === "mod" || i.kind === "third" || i.kind === "own") && i.state !== "выключен" && i.state !== "не стоит");
        moves += start ? XOVI_ON : XOVI_OFF;
        if (!trial && start) moves += DISARM("cancelled");
        const r2 = await ssh(moves, 60000);
        mem.log.push(...logLines(r2.out), ...shErrors(r2.err));
        const started = /XOVI запущен/.test(r2.out);
        if (start && !started) mem.log.push("ОШИБКА: XOVI не перезапустился, моды не применились");
        if (start && trial && started) mem.log.push(`проверка: ${TRIAL_SECONDS / 60} мин, без подтверждения моды выключатся сами`);

        const done = plan.map((p) => `${p.it.name} → ${ACTION_NAMES[p.a]}`);
        mem.choices = {};
        await new Promise((r) => setTimeout(r, 4000));
        await refresh(false);
        const groups = {};
        for (const p of plan) (groups[p.a] ??= []).push(p.it.name);
        mem.last = { at: new Date().toISOString(), done, groups, log: mem.log.slice(), anyOn: anyOn() };
        await saveChoices(session);
        const msg = [`[Моды Remarkable] Мастер применил: ${done.join("; ") || "только перезапуск"}.`,
            ...mem.log.map((l) => "- " + l),
            start && trial ? `Проверка на ${TRIAL_SECONDS / 60} мин: ждёт «Всё работает, оставить» на панели.` : ""].filter(Boolean);
        try { session?.send({ prompt: msg.join("\n") }).catch(() => {}); } catch { }
        return view();
    });
}

// Мод, которому нужен другой мод, без него не работает: включение тянет
// за собой то, что ему нужно, выключение - то, что нуждается в нём.
// Снятие отметки снимает и то, что было отмечено заодно.
function linkDeps(key, action, prev) {
    const mods = new Map((mem.status?.items ?? []).filter((i) => i.kind === "mod").map((i) => [i.name, i]));
    const it = [...mods.values()].find((i) => i.key === key);
    if (!it) return;
    const on = (m) => m.state === "включён" || m.state === "частично";
    const walk = (start, next, a, want) => {
        const seen = new Set([start.name]);
        const stack = [start];
        while (stack.length) {
            for (const n of next(stack.pop())) {
                const m = mods.get(n);
                if (!m || seen.has(n)) continue;
                seen.add(n);
                stack.push(m);
                if (want === null) { if (mem.choices[m.key] === a) delete mem.choices[m.key]; }
                else if (on(m) !== want && actionsFor(m).includes(a)) mem.choices[m.key] = a;
            }
        }
    };
    const needs = (m) => m.needs, users = (m) => m.requiredBy;
    if (action === "enable") walk(it, needs, "enable", true);
    else if (action === "disable" || action === "remove") walk(it, users, "disable", false);
    else if (!action && prev === "enable") walk(it, needs, "enable", null);
    else if (!action && (prev === "disable" || prev === "remove")) walk(it, users, "disable", null);
}

function notify(session, text) {
    try { session?.send({ prompt: `[Моды Remarkable] ${text}` }).catch(() => {}); } catch { }
}

const REBUILD = `touch /tmp/hashtab.running
setsid sh -c 'echo | ${X}/rebuild_hashtable >/tmp/hashtab.log 2>&1; . /etc/os-release; grep -q "Hashtab saved" /tmp/hashtab.log && echo "$IMG_VERSION" > ${X}/hashtab.os; systemctl start xochitl; rm -f /tmp/hashtab.running' </dev/null >/dev/null 2>&1 &
`;

export const actions = {
    async status({ session }) {
        await loadChoices(session);
        if (!mem.status && !mem.busy) await busy("читаю статус", () => refresh(false));
        const v = view();
        const s = v.status;
        return {
            os: s.os, xovi: s.xovi, trial: s.trial, hashtab: s.hashtab,
            mods: s.items.map((i) => ({ name: i.name, kind: i.kind, state: i.state, version: i.version, fresh: i.fresh, compatible: i.compatible, choice: i.choice })),
            last: v.last,
        };
    },
};

export const routes = {
    "/state": async ({ session }) => { await loadChoices(session); return view(); },
    "/refresh": async ({ session, body }) => {
        await loadChoices(session);
        await busy(body.fetch ? "проверяю обновления" : "читаю статус", async () => {
            await refresh(!!body.fetch);
            if (body.fetch) {
                mem.checked = { at: new Date().toISOString(), updates: mem.status.items.filter((i) => i.fresh).map((i) => i.name) };
            }
        }).catch(() => {});
        await saveChoices(session);
        return view();
    },
    "/choose": async ({ session, body }) => {
        if (mem.busy) return view();
        const prev = mem.choices[body.key];
        if (body.action) mem.choices[body.key] = body.action; else delete mem.choices[body.key];
        linkDeps(body.key, body.action, prev);
        await saveChoices(session);
        return view();
    },
    "/apply": async ({ session, body }) => {
        try { return await apply(session, { trial: body.trial !== false, start: body.start }); }
        catch (e) { mem.error = e.message; return view(); }
    },
    "/confirm": async ({ session }) => {
        await busy("снимаю страховку", async () => {
            await ssh(DISARM("confirmed"), 30000);
            await refresh(false);
        }).catch(() => {});
        return view();
    },
    "/xovi": async ({ session, body }) => {
        await busy(body.on ? "запускаю XOVI" : "останавливаю XOVI", async () => {
            await ssh(body.on ? (body.trial === false ? DISARM("cancelled") : ARM) + XOVI_ON : DISARM("cancelled") + XOVI_OFF, 60000);
            await new Promise((r) => setTimeout(r, 4000));
            await refresh(false);
        }).catch(() => {});
        notify(session, body.on ? "Мастер запустил XOVI." : "Мастер остановил XOVI: моды выключены.");
        return view();
    },
    "/choose-many": async ({ session, body }) => {
        if (mem.busy || !mem.status) return view();
        if (body.upgrade) {
            for (const it of mem.status.items) if (it.fresh) mem.choices[it.key] = "upgrade";
            await saveChoices(session);
            return view();
        }
        for (const it of mem.status.items) {
            if (it.kind !== "mod") continue;
            const a = body.on ? (it.state === "включён" ? null : "enable") : (it.state === "выключен" ? null : "disable");
            if (a && actionsFor(it).includes(a)) mem.choices[it.key] = a;
            else if (mem.choices[it.key] === "enable" || mem.choices[it.key] === "disable") delete mem.choices[it.key];
        }
        await saveChoices(session);
        return view();
    },
    "/reset": async ({ session }) => {
        if (!mem.busy) { mem.choices = {}; await saveChoices(session); }
        return view();
    },
    "/rebuild": async ({ session }) => {
        await busy("запускаю пересборку hashtab", async () => {
            await ssh(REBUILD, 30000);
            await new Promise((r) => setTimeout(r, 2000));
            await refresh(false);
        }).catch(() => {});
        notify(session, "Мастер запустил пересборку hashtab: на планшете нужен PIN.");
        return view();
    },
};
