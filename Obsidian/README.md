# Надстройки Обсидиана

Наши плагины и CSS-сниппеты для волтов: источник правды здесь, в волты
их ставит `Install-ObsidianKit`. Как писать свои и как вести каталог -
скилл `.github\skills\obsidian-plugins\SKILL.md`.

У всех самописных плагинов автор "Архивариус Бард" и русские имя и
описание, по ним они отличаются от магазинных в списке Community plugins.

## Как поставить

```powershell
Get-ObsidianKit                                   # весь каталог
Get-ObsidianKit -Vault 'C:\vaults\Новый волт'     # что из него уже стоит
Install-ObsidianKit -Vault 'C:\vaults\Новый волт' -Kit base, dnd -WhatIf
Install-ObsidianKit -Vault 'C:\vaults\Новый волт' -Kit base, dnd
```

Команда копирует файлы в `<волт>\.obsidian` и включает надстройки в
`community-plugins.json` и `appearance.json`. При запущенном Обсидиане
включение не трогает и печатает, что включить руками: открытый Обсидиан
перезаписывает эти файлы при выходе. Файл, который в волте новее, чем
здесь, не затирается без `-Force`. `data.json` плагинов не переносится.
Чужие плагины из колонки "Нужен" не ставятся, команда только
предупреждает, если их нет.

## Наборы

- `base` - любой волт;
- `dnd` - волт с Initiative Tracker и Fantasy Statblocks, разложенный как
  Рудники Фанделвера;
- `phandelver` - завязано на страницы и папки кампании.

## Плагины

| id | Набор | Имя | Что делает | Нужен |
|---|---|---|---|---|
| fold-properties-always | base | Свойства всегда свёрнуты | Шапка свойств свёрнута в редакторе, в чтении и во всплывающем предпросмотре | - |
| statblock-note-link | dnd | Ссылка из статблока на заметку | Ссылка на заметку монстра в макете статблока, чтобы открыть её из трекера | Fantasy Statblocks |
| combatant-pane-reuse | dnd | Одна панель Combatant | Трекер открывает статблок в уже открытой панели, а не плодит новые | Initiative Tracker |
| campaign-statblocks | dnd | Статблоки кампании | Макеты Монстр и Лист игрока с их стилями, которые не сносит обновление чужих плагинов | Fantasy Statblocks |
| party-initiative | dnd | Инициатива отряда | Инициатива всего отряда одной строкой; игроки из `Adventure/Players` | Initiative Tracker |
| timeline-links | dnd | Ссылки из таймлайна | Клик по карточке таймлайна в Bases открывает заметку | TTRPG Tools - Timeline |
| battlemap-links | phandelver | Ссылки с батлмапа | Токен на батлмапе открывает статблок, маркер боя запускает бой | Initiative Tracker, Excalidraw |
| chase-tracker | phandelver | Погоня | Код-блок `chase` по правилам погони кампании | Initiative Tracker |
| xge-difficulty | phandelver | Сложность боя по Занатару | Сложность боя в трекере по странице кампании вместо XP | Initiative Tracker |

## Сниппеты

| Имя | Набор | Что делает | Нужен |
|---|---|---|---|
| hide-all-properties-tab | base | Прячет вкладку All properties, которую Обсидиан пересоздаёт при запуске | - |
| hide-properties-in-popover | base | Убирает пустой блок свойств во всплывающем предпросмотре | - |
| fix-callout-boxes | base | Постоянная рамка, фон и шапка у стандартных callout'ов | - |
| fix-statblock-bold-contrast | dnd | Жирный текст в статблоке читается при тёмной теме | Fantasy Statblocks |
| statblock-live-preview | dnd | Статблок в редакторе тех же цветов, что в панели трекера | Fantasy Statblocks |
| tracker-panel-background | dnd | Панели трекера и статблоков на фоне темы | Initiative Tracker |
| zoommap-wide-only | dnd | Карта на всю ширину, текст обычной ширины | TTRPG Tools - Maps |
| zoommap-text-plate | dnd | Белая окантовка подписей на картах | TTRPG Tools - Maps |
| hide-properties-in-panel | phandelver | Прячет служебные свойства кампании в панели File properties | - |
