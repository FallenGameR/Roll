"use strict";

/*
  Клик по карточке таймлайна открывает сессию.

  Плагин simple-timeline рисует карточку ссылкой с классом internal-link и
  сам вешает на неё только предпросмотр при наведении. В обычной заметке
  клик по такой ссылке ловит Обсидиан, а в виде Bases (Timeline.md) ловить
  некому, и клик уходит в пустоту.

  Здесь один обработчик на весь документ: клик по ссылке внутри вида Bases
  этого плагина открывает файл из data-href. Ctrl/Cmd-клик открывает в новой
  вкладке. Блоки timeline-cal в заметках не трогаем: там клик работает и так.

  Файлы simple-timeline не правятся, обновление плагина патч не сносит.
*/

const { Plugin, Keymap } = require("obsidian");

module.exports = class TimelineLinks extends Plugin {
    onload() {
        this.registerDomEvent(document, "click", (evt) => {
            const target = evt.target;
            if (!(target instanceof Element)) return;
            const anchor = target.closest(".tl-bases-host a.tl-hover-anchor");
            if (!anchor) return;
            const path = anchor.getAttribute("data-href");
            if (!path) return;
            evt.preventDefault();
            evt.stopPropagation();
            this.app.workspace.openLinkText(path, "", Keymap.isModEvent(evt));
        }, { capture: true });
    }
};
