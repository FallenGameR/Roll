<#
.SYNOPSIS
    Known-word dictionary mapping individual Genre tag tokens (as found in
    the mp3 Genre id3 tag written by the annotation pipeline) to their
    category, so Get-Track can split the flat tag list into
    Intensity / Emotion / Scene / Game / Type buckets, plus a few
    pipeline meta-flags handled separately (see $script:RollGenreMetaTags).

.DESCRIPTION
    Derived from the original 6-category tagging scheme, then reshaped
    per user feedback: Place (location) and the old Scene (type of
    content) were merged into one broader Scene category, and Type was
    promoted from a single Effect-only flag to a multi-value bucket that
    also covers Vocals:
      - Intensity (energy):   Background, Tension, Combat, Crisis
      - Emotion:              Dread, Hostile, Haven, Tragic, Triumph,
                               Melancholy, Playful, Secrets, Divine,
                               Forbidden
      - Scene (place + type of content): Depths, Urban, Tavern, Lively,
                               Chase, Travel, Investigation, Anomaly
      - Game (source setting): Fantasy, Modern, SciFi
      - Type (production hint): Effect (soundboard/sfx), Vocals (has
                               singing/lyrics), Excluded (set aside from
                               the playable library, kept for reference)

    Tags not covered by this dictionary (i.e. Intro, Outro, Unsorted) are
    pipeline meta-flags outside the category scheme and are handled
    separately, not through this token->category map. New tags not in
    either place end up in the Unmatched bucket instead of being dropped
    or throwing. Extend this table as new tags show up in the library
    (re-run Get-Track and check for non-empty Unmatched).
#>
$script:RollGenreTaxonomy = @{
    # Intensity: energy/pacing role of the track in a scene.
    'Background' = 'Intensity'
    'Tension'    = 'Intensity'
    'Combat'     = 'Intensity'
    'Crisis'     = 'Intensity'

    # Emotion: чувство, которое трек вызывает. Список идёт от Эмоции.md:
    # это переживания слушателя, а не обстановка сцены и не её содержание.
    'Anger'      = 'Emotion'
    'Unease'     = 'Emotion'
    'Dread'      = 'Emotion'
    'Grief'      = 'Emotion'
    'Melancholy' = 'Emotion'
    'Guilt'      = 'Emotion'
    'Disgust'    = 'Emotion'
    'Awe'        = 'Emotion'
    'Curiosity'  = 'Emotion'
    'Tenderness' = 'Emotion'
    'Joy'        = 'Emotion'
    'Pride'      = 'Emotion'
    'Calm'       = 'Emotion'

    # Scene: где всё происходит и что это за сцена.
    'Depths'        = 'Scene'
    'Urban'         = 'Scene'
    'Tavern'        = 'Scene'
    'Court'         = 'Scene'
    'Ritual'        = 'Scene'
    'Shelter'       = 'Scene'
    'Wilds'         = 'Scene'
    'Ruins'         = 'Scene'
    'Sea'           = 'Scene'
    'Chase'         = 'Scene'
    'Travel'        = 'Scene'
    'Investigation' = 'Scene'
    'Anomaly'       = 'Scene'

    # Game: the source-material setting/era the track fits.
    'Fantasy' = 'Game'
    'Modern'  = 'Game'
    'SciFi'   = 'Game'

    # Type (production hint): роль самой записи - звуковой эффект,
    # наличие вокала, тема старта и финала кампании.
    'Effect'   = 'Type'
    'Vocals'   = 'Type'
    'Intro'    = 'Type'
    'Outro'    = 'Type'
}

<#
.SYNOPSIS
    Мета-флаги вне категорий: состояние трека в конвейере, а не свойство
    его звучания. Каждый становится отдельным булевым полем объекта
    Roll.MusicTrack, а не значением категории.

.DESCRIPTION
    Все три говорят об одном - берём ли мы трек в игру и что с ним
    делать дальше:

      Unsorted - подвешенное состояние. Либо ещё не слушали, либо
                 слушали и не решили; к игре допускается, в подборке
                 помечается звёздочкой.
      Excluded - отложен насовсем: слушать не хочется даже на пробу,
                 но пусть лежит на потом.
      Delete   - послушали, не понравилось; при ближайшей уборке уедет
                 в Music\Deleted.
#>
$script:RollGenreMetaTags = @('Delete', 'Excluded', 'Unsorted')

<#
.SYNOPSIS
    Canonical category order used when serializing a Roll.MusicTrack's
    parsed Genre categories back into the self-describing
    "Category:value1,value2" tag string (see ConvertTo-GenreTagString).
    Meta and Unmatched are appended last, in that order, when non-empty.
#>
$script:RollGenreCategoryOrder = @('Intensity', 'Emotion', 'Scene', 'Game', 'Type')

<#
.SYNOPSIS
    Что каждое значение означает на практике - одним абзацем, для
    подсказок в интерфейсе простановки тегов (Start-MusicTagger).

.DESCRIPTION
    Смысл значений разбирается в скилле music-picking, но скилл читает
    ассистент, а Мастеру за разметкой нужна подсказка под курсором.
    Тексты лежат здесь же, где сами значения, чтобы список и пояснения
    к нему не разъезжались.
#>
$script:RollGenreHelp = @{
    # Intensity - что происходит на сцене.
    'Background'    = 'Ровный фон под разговоры и осмотр, который можно крутить часами. Не требует внимания и не мешает говорить поверх.'
    'Tension'       = 'Нарастающее напряжение без драки: разведка, слежка, предчувствие беды. Что-то вот-вот случится, но пока не случилось.'
    'Combat'        = 'Рядовая схватка. Стычка, которую отряд ожидает выиграть, без веса финального боя.'
    'Crisis'        = 'Пик: босс, катастрофа, погоня на грани. Рядовой стычке это перебор - обесценивает настоящий финал.'

    # Emotion - что чувствует слушатель, а не что происходит на сцене.
    'Anger'         = 'Гнев, ярость, злость. Кипящая агрессия, готовность ударить - не обязательно бой, но всегда напор.'
    'Unease'        = 'Тревога, смутное беспокойство. Опасность есть, но она далеко и её не видно.'
    'Dread'         = 'Страх вблизи: угроза сильнее тебя и она рядом. Не синоним «опасно» - для зачистки, где агрессор сам отряд, не годится.'
    'Grief'         = 'Горе, скорбь, утрата. Что-то потеряно навсегда, и это уже случилось.'
    'Melancholy'    = 'Тихая грусть, тоска, сожаление. Мягче и пассивнее горя, без острой боли.'
    'Guilt'         = 'Вина, стыд, раскаяние. Сделал сам и теперь живёшь с этим.'
    'Disgust'       = 'Отвращение, брезгливость. Мерзкое, склизкое, гниющее - хочется отвернуться.'
    'Awe'           = 'Благоговение, трепет перед большим: божество, древность, мощь, от которой чувствуешь себя малым.'
    'Curiosity'     = 'Интерес, любопытство, азарт. Тянет разобраться, а не убежать.'
    'Tenderness'    = 'Нежность, любовь, преданность. Тепло к кому-то конкретному.'
    'Joy'           = 'Радость, веселье, облегчение, игривость. От тихой улыбки до балагана.'
    'Pride'         = 'Гордость, кураж, торжество. Перелом в свою пользу, победа, собственная сила.'
    'Calm'          = 'Покой, умиротворение, довольство. Ничто не угрожает и никуда не надо спешить.'

    # Scene - где происходит и что это за сцена.
    'Depths'        = 'Под землёй: пещеры, шахты, склепы, подземелья. Означает место, а не то, что за тобой крадутся.'
    'Urban'         = 'Город и жильё: улицы, кварталы, крепость изнутри, обжитое место.'
    'Tavern'        = 'Трактир и застолье: музыка, которую в мире играют живые музыканты.'
    'Court'         = 'Двор, приём, переговоры: власть, этикет, интрига в разговоре.'
    'Ritual'        = 'Храм, обряд, освящённое место: то, что делают с намерением и по правилам.'
    'Shelter'       = 'Убежище и привал: место, где отряд переводит дух и никто не гонится.'
    'Wilds'         = 'Дикая природа: лес, степь, горы, болото. Людей тут нет.'
    'Ruins'         = 'Развалины и брошенное: люди тут были и ушли, осталось то, что они построили.'
    'Sea'           = 'Море, река, корабль, порт: вода и всё, что с ней связано.'
    'Chase'         = 'Кого-то догоняют или от кого-то убегают: есть преследователь и цена промедления.'
    'Travel'        = 'Дорога между местами: переход по карте, обоз, долгий марш. Опасность может быть, но никто не гонится.'
    'Investigation' = 'Осмотр и поиск: следы, улики, разбор того, что здесь случилось.'
    'Anomaly'       = 'Место, где мир ведёт себя неправильно: искажение, запретная магия, чужеродное присутствие.'

    # Game - эпоха звучания, а не игра-источник.
    'Fantasy'       = 'Звучит как фэнтези: оркестр, акустика, хор, фолк. Тег означает разрешение брать трек в D&D, даже если он вынут из другого мира.'
    'Modern'        = 'Современное звучание: военное кино, нуар, живая ритм-секция, городская запись.'
    'SciFi'         = 'Электроника, синтезаторы, индустриальные текстуры, машинный гул.'

    # Type - роль самой записи.
    'Effect'        = 'Не музыка, а звук: разовый удар или петля антуража. В сцены Локация и Бой не попадает, живёт в Эффектах.'
    'Vocals'        = 'Есть пение или текст. Отвлекает при ролплее и начитке, в бою мешает меньше.'
    'Intro'         = 'Тема старта кампании. В локации не идёт.'
    'Outro'         = 'Тема финала кампании. В локации не идёт.'

    # Meta - состояние трека в конвейере.
    'Unsorted'      = 'Подвешенное состояние: либо ещё не слушали, либо слушали и не решили. К игре допускается, в подборке помечается звёздочкой. Любая оценка звёздами снимает эту метку.'
    'Excluded'      = 'Отложен на потом: применять на игре не хочется, слушать даже на пробу тоже. При ближайшей уборке уедет в Music\Excluded, тег останется висеть.'
    'Delete'        = 'Послушали, не понравилось. При ближайшей уборке уедет в Music\Deleted, а ссылки на него уйдут из подборок. Место дешевле сожаления, поэтому не удаление насовсем.'
}
