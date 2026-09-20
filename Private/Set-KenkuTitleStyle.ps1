<#
.SYNOPSIS
    Makes Kenku FM playlist cards show the location at the top and the
    scene at the bottom.

.DESCRIPTION
    New-Playlist puts a newline between the location name and the scene,
    but Kenku renders a title as a single text node with MUI's default
    white-space: normal, so the break collapses into a space. Enabling
    white-space: pre-line fixes the break, yet CSS alone can't push the
    two halves to opposite edges of the card: a lone text node is one
    anonymous box, so flex/grid alignment has nothing to distribute.

    So the patch also splits the title into two spans and turns the
    heading into a column flexbox with space-between. It runs from a
    MutationObserver because React re-renders the cards (on playback,
    search, edits) and would drop our spans; the observer rebuilds them
    whenever a title with a newline isn't in the split shape.

    There is no user stylesheet or plugin hook in Kenku, and anything
    injected over CDP dies with the window, so the code goes into the
    app's own player window HTML. The patch is idempotent, and since an
    app update replaces that file, New-Playlist re-applies it on every
    run instead of assuming it is still there.
#>
function Set-KenkuTitleStyle {
    param(
        [string]$Font,

        # Снимает патч и ничего не ставит взамен: нужно, чтобы сравнить
        # поведение плеера с оформлением и без него.
        [switch]$Disable
    )

    $ErrorActionPreference = 'Stop'

    $root = Join-Path $env:LOCALAPPDATA 'kenku-fm-win32-x64'
    $page = Get-ChildItem -LiteralPath $root -Filter 'index.html' -Recurse `
        -ErrorAction SilentlyContinue |
        Where-Object { $_.DirectoryName -like '*player_window*' } |
        Select-Object -First 1

    if (-not $page) {
        Write-Verbose "Kenku FM player window HTML not found, skipping patch"
        return
    }

    $html = Get-Content -LiteralPath $page.FullName -Raw

    # The chosen font lives in the patch itself, so a plain New-Playlist
    # run keeps it instead of resetting the look to Kenku's default.
    if (-not $Font -and $html -match 'data-roll-font="([^"]*)"') {
        $Font = $Matches[1]
    }

    # Цвет - фон приложения (#1e2231), затемнённый примерно вдвое: так
    # подпись читается на светлых картинках и не выбивается из палитры
    # Kenku.
    # Стиль вешается на пометку data-roll-title, которую скрипт ставит
    # только подписям поверх обложки: заголовки секций ("Playlists",
    # "Soundboards") - тоже h5 внутри MuiCard-root, и по классам их не
    # отличить, а хеши emotion-классов между версиями меняются.
    # Обводка рисуется вторым слоем того же текста в ::before, а не
    # набором копий в text-shadow: копиями пришлось бы закрывать диск
    # радиуса 6 с шагом в пиксель, то есть по сотне отрисовок текста на
    # каждую подпись, тогда как здесь их всего две.
    # Сам слой рисуется обычным текстом без -webkit-text-stroke, а
    # расширяется SVG-фильтром: feMorphology dilate раздувает силуэт
    # равномерно во все стороны, поэтому в отличие от text-stroke
    # (соединение углов "в ус") из острых стыков не вылетают длинные
    # шипы - они торчали хвостами у "к", "и", "й" и после порога
    # оставались прямоугольными выступами.
    # Дальше размытие плюс резкий порог по альфе (feColorMatrix)
    # скругляет квадратные углы, которые даёт прямоугольное ядро
    # dilate, оставляя край чётким.
    # Радиус - 5 пикселей: обводка расширяет глиф только наружу, а
    # внутренний просвет "П" при 24px шириной около восьми пикселей,
    # так что при меньшем радиусе в середине буквы просвечивает
    # картинка.
    # Слой уезжает под текст через z-index: -1, поэтому родителю нужен
    # свой контекст наложения (position: relative и z-index: 0) - иначе
    # обводка провалится под обложку карточки и станет не видна.
    # Ни текст, ни обводка не берутся предельными (#000 и #fff): на
    # пёстрой обложке такая пара рябит, поэтому цвета сведены к тёмному
    # сине-серому и приглушённому светлому.
    # Тень вешается на подпись целиком через filter: она обводит уже
    # готовый силуэт с обводкой, как у маркеров на картах.
    # Имя локации набирается мельче сцены: оно длиннее и в три строки
    # выглядит тяжелее самой обложки. Обводка под ним тоже тоньше -
    # иначе на мелких буквах она съедает просветы.
    $card = '.MuiTypography-h5[data-roll-title]'
    $rules = "$card{white-space:pre-line;color:#232a3d;" +
        '-webkit-font-smoothing:auto;font-weight:700;font-size:24px;' +
        'line-height:1.5;filter:drop-shadow(0 1px 2px rgba(0,0,0,.45));}' +
        "$card .roll-line{display:block;position:relative;z-index:0;}" +
        "$card .roll-line::before{content:attr(data-text);" +
        'position:absolute;left:0;top:0;width:100%;z-index:-1;' +
        'color:#e4e9f3;filter:url(#roll-goo);}' +
        "$card[data-roll-split]{display:flex;" +
        'flex-direction:column;justify-content:space-between;' +
        'align-self:stretch;height:100%;}' +
        "$card[data-roll-split] .roll-line:first-child{font-size:19px;}" +
        "$card[data-roll-split] .roll-line:first-child::before{" +
        'filter:url(#roll-goo-sm);}'
    if ($Font) {
        $rules += "$card{font-family:$Font;}"
    }
    $style = "<style id=`"roll-title-style`" data-roll-font=`"$Font`">" +
        $rules + '</style>'

    $script = @'
<script id="roll-title-script">
(() => {
  const split = () => {
    for (const title of document.querySelectorAll(
        ".MuiCard-root .MuiTypography-h5")) {
      // Подписи плейлистов лежат в абсолютном блоке поверх обложки, а
      // заголовки секций - нет; только по этому их и можно отличить.
      // getComputedStyle вызывает пересчёт лэйаута, поэтому ответ
      // запоминается на элементе: карточка не меняет своей природы.
      const holder = title.parentElement;
      if (!holder) continue;
      if (holder.dataset.rollHolder === undefined) {
        holder.dataset.rollHolder =
          getComputedStyle(holder).position === "absolute" ? "1" : "0";
        // Контейнер подписи растягивается на всю карточку - иначе
        // верхнюю половину подписи некуда прижать; однострочные
        // названия из-за этого прижимаются к низу вручную.
        if (holder.dataset.rollHolder === "1") holder.style.top = "0px";
      }
      if (holder.dataset.rollHolder !== "1") continue;
      title.dataset.rollTitle = "1";
      const text = title.getAttribute("data-roll-text") ?? title.textContent;
      const at = text.indexOf("\n");
      // Обводка рисуется вторым слоем в ::before, а тому нужен свой
      // элемент с текстом в data-text - поэтому в span заворачивается
      // и подпись без сцены, у которой делить нечего.
      const line = (value) => {
        const span = document.createElement("span");
        span.className = "roll-line";
        span.dataset.text = value;
        span.textContent = value;
        return span;
      };
      // React re-renders drop our spans but keep the element, so the
      // shape is re-checked instead of trusting a "done" flag.
      if (at < 0) {
        if (holder.style.alignItems !== "flex-end") {
          holder.style.alignItems = "flex-end";
        }
        if (title.firstElementChild?.className === "roll-line") continue;
        title.replaceChildren(line(text.trim()));
        continue;
      }
      if (title.dataset.rollSplit && title.children.length === 2) continue;
      title.setAttribute("data-roll-text", text);
      title.dataset.rollSplit = "1";
      title.replaceChildren(
        line(text.slice(0, at).trim()), line(text.slice(at).trim()));
    }
  };
  // Мутации идут пачками и во время воспроизведения не прекращаются,
  // поэтому проход откладывается до кадра отрисовки: иначе один и тот
  // же обход выполняется десятки раз в секунду и отнимает главный
  // поток у звука.
  let queued = false;
  const schedule = () => {
    if (queued) return;
    queued = true;
    requestAnimationFrame(() => { queued = false; split(); });
  };
  const start = () => {
    // Фильтр создаётся из скрипта, а не отдельным куском разметки,
    // чтобы снятие патча не пришлось делать в двух местах.
    if (!document.getElementById("roll-goo-svg")) {
      const svg = document.createElementNS(
        "http://www.w3.org/2000/svg", "svg");
      svg.id = "roll-goo-svg";
      svg.setAttribute("width", "0");
      svg.setAttribute("height", "0");
      svg.style.position = "absolute";
      // feMorphology раздувает силуэт равномерно, поэтому из острых
      // стыков не вылетают шипы, как у -webkit-text-stroke. Размытие
      // с резким порогом по альфе скругляет квадратные углы, которые
      // остаются от прямоугольного ядра dilate.
      const goo = (id, radius) =>
        '<filter id="' + id + '" x="-25%" y="-25%" ' +
        'width="150%" height="150%">' +
        '<feMorphology in="SourceGraphic" operator="dilate" radius="' +
        radius + '" result="d"/>' +
        '<feGaussianBlur in="d" stdDeviation="2" result="b"/>' +
        '<feColorMatrix in="b" type="matrix" values="' +
        '1 0 0 0 0  0 1 0 0 0  0 0 1 0 0  0 0 0 19 -9"/>' +
        '</filter>';
      svg.innerHTML = goo("roll-goo", 4) + goo("roll-goo-sm", 3);
      document.body.appendChild(svg);
    }
    split();
    // characterData не слушаем: счётчик времени тикает несколько раз в
    // секунду, а на форму заголовков это не влияет.
    new MutationObserver(schedule).observe(document.body,
      { subtree: true, childList: true });
  };
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
</script>
'@

    # Прежний патч снимается целиком, иначе смена шрифта не применится
    # и в файле копились бы дубли блоков.
    $clean = $html -replace '(?s)<style id="roll-title-style".*?</style>', '' `
        -replace '(?s)<script id="roll-title-script">.*?</script>', ''

    if ($Disable) {
        if ($clean -ne $html) {
            Set-Content -LiteralPath $page.FullName -Value $clean `
                -Encoding UTF8 -NoNewline
            Write-Verbose "Removed patch from $($page.FullName)"
        }
        return
    }

    $patched = $clean -replace '</body>', "$script</body>"
    $patched = $patched -replace '</head>', "$style</head>"

    if ($patched -eq $html) { return }

    Set-Content -LiteralPath $page.FullName -Value $patched -Encoding UTF8 -NoNewline
    Write-Verbose "Patched $($page.FullName)"
}
