---
name: remarkable-mods
description: 'Моды на планшете Remarkable Paper Pro: как они устроены (XOVI, qmd, Vellum), как выключить все или часть, как вернуть сохранённый набор, где лежат копии модов. Use when installing, removing, disabling or restoring reMarkable mods, hunting a mod that misbehaves, or reading mod source.'
---

## Как устроено
На планшете два слоя:

- **Vellum** (`/home/root/.vellum/bin/vellum`) - пакетный менеджер, обёртка
  над apk. Ставит и обновляет моды, список заказанного - в
  `/home/root/.vellum/etc/apk/world`. В Windows у него есть окно,
  `C:\tools\RCU\reManager.exe`.
- **XOVI** подгружает моды в интерфейс (`xochitl`). Интерфейсный мод - один
  файл `.qmd` в `/home/root/xovi/exthome/qt-resource-rebuilder`: текстовая
  заплатка к QML интерфейса. Имена в ней - хеши, расшифровка в `hashtab`
  рядом. Расширения самого XOVI - `.so` в `/home/root/xovi/extensions.d`.

XOVI не вшит в систему. Скрипт `/home/root/xovi/start` монтирует tmpfs в
`/etc/systemd/system/xochitl.service.d` с `LD_PRELOAD` и перезапускает
интерфейс. После перезагрузки планшета интерфейс чистый; моды включает
тройное нажатие кнопки питания (служба `xovi-tripletap`) или тот же
`start` по SSH. Любой перезапуск интерфейса закрывает открытый документ.

Ходить по SSH: по кабелю `10.11.99.1`, по Wi-Fi - адрес пресета, пароль
один, из пресета RCU (`Tools\Remarkable\askpass.cmd`). Спящий планшет
не отвечает ни так, ни так.

Часы планшета и его журнал идут по UTC. Мастеру время называть в местном
поясе компьютера, а не в том, что напечатал `date` на планшете.

## Выключить и включить
Мастер управляет модами сам, с canvas `roll-mods` («Моды Remarkable»,
описан в `Tools\Editor\README.md`). Сессия на планшете ничего не включает,
не выключает и не ставит без его прямой просьбы: канвас и есть способ это
сделать. Пробу мода со страховкой тоже запускают оттуда, чтобы отсчёт был
виден Мастеру.

Канвас держит выключенные моды в `/home/root/xovi/disabled-mods` с полным
путём файла; старые папки `disabled`, `disabled-3.27` и `staging-3.29` -
ручные раскладки 26 ноября.

Руками, если канвас недоступен:
- **Все моды:** `umount -q /etc/systemd/system/xochitl.service.d;
  systemctl daemon-reload; systemctl restart xochitl`.
- **Вернуть все:** `/home/root/xovi/start`.
- **Отдельный мод на время:** перенести его `.qmd` в `/home/root/xovi/disabled`
  и выполнить `start`. Мод тапа по краю и прокрутки экрана - пара
  `_ingatellent.qmd` + папка `ingatellent`, переносить вместе.
- **Насовсем:** `vellum del <мод>`; вернуть - `vellum add <мод>`.

Проверка, что моды загружены: в `/proc/$(pidof xochitl)/environ` есть
`LD_PRELOAD=/home/root/xovi/xovi.so`.

## Набор 26 ноября 2026, до поиска гоустинга
Прошивка 3.27.3. Всё ниже было установлено и включено:

| Мод | Версия | Файл |
|---|---|---|
| disable-infinite-scroll | 1.1.0-r6 | disableInfiniteScroll.qmd |
| faster-page-labels | 1.0.0-r0 | fasterPageLabels.qmd |
| faster-scroll-bar | 1.0.0-r0 | fasterScrollBar.qmd |
| filter-annotated-pages | 1.1.0-r0 | filterAnnotatedPages.qmd |
| fix-battery-indicator | 1.0.1-r2 | fixBatteryIndicator.qmd |
| ghostbuster | 1.0.0-r3 | ghostbuster.qmd |
| nav-history | 1.1.0-r0 | navHistory.qmd |
| scroll-screen-up-or-down | 1.0.1-r2 | ingatellent/scrollScreenUpOrDown.qmd |
| sort-templates-recent | 1.0.0-r0 | sortTemplatesRecent.qmd |
| tap-to-change-view-or-page | 1.0.1-r2 | ingatellent/tapToChangeViewOrPage.qmd |
| three-finger-swipe-to-reset-view | 1.0.1-r2 | threeFingerSwipeToResetView.qmd |
| touch-lock | 1.0.2-r3 | touchLock.qmd |
| librarian | 0.4.0-r0 | extensions.d/librarian.so |
| mount-utils | 1.2.0-r0 | команды mount-rw, mount-restore |
| tripletap | 1.1.0-r0 | служба xovi-tripletap |

Служебное: vellum 0.3.1-r0, vellum-bash-completion 3.0.3-r3, xovi 0.3.3-r2,
xovi-extensions 19.0.0-r3 (qt-command-executor, qt-resource-rebuilder,
xovi-message-broker 19.0.0-r1), remarkable-os 3.27.3.0-r0, rmpp 1.0.0-r0.

Вернуть этот набор: `vellum add` по списку модов, затем `/home/root/xovi/start`.
Точные старые версии Vellum уже может не отдавать, тогда встанут свежие;
сами файлы `.qmd` этих версий лежат в `Remarkable\mods` модуля.

## Перед обновлением прошивки
26 ноября Мастер включил автообновление, чтобы посмотреть, что нового, и
планшет сразу начал качать 3.29.1 (до этого было 3.27.3). Новая
прошивка ставится в запасной раздел и включается после перезагрузки,
поэтому до перезагрузки моды ещё можно убрать. Все `.qmd` (кроме
`hashtab`) и `librarian.so` перенесены в `/home/root/xovi/disabled-3.27`
(`qmd` и `ext`). В `extensions.d` остались только служебные
qt-resource-rebuilder, qt-command-executor и xovi-message-broker.

После обновления: `vellum check-os`, `vellum upgrade`, `vellum reenable`
(он же пересобирает `hashtab` под новую прошивку). Потом моды возвращать
по одному, начиная с тех, у кого Vellum показывает версию под новую
прошивку.

## Тикет в поддержку о гоустинге
26 ноября 2026, около 10:18, отправлен тикет через support.remarkable.com:
Contact → Send us an email → Technical issues and help. Сайт ответил
«Ticket Created!», номера на странице нет: он придёт письмом на
alex.kostikov@gmail.com.

- Модель Paper Pro, прошивка 3.29.1.1826, серийный номер RM05C004248035T
  (взят из `journalctl`, строка `serial :`).
- Суть: сильный зелёный и чёрный гоустинг на раннем Paper Pro, хуже на
  сложных PDF, след виден уже на экране PIN; стало хуже после обновлений,
  не прошло на 3.29.1. Спросили про ремонт или замену по гарантии или
  покрытию Connect. Про моды и режим разработчика не писали; если спросят,
  отвечать честно: включён, но гоустинг есть и на прошивке без модов.
- Приложено фото `remarkable-ghosting.jpg`: после ввода PIN поверх
  библиотеки остались «Enter passcode» и вся клавиатура. Оригинал из письма
  Мастера себе с темой «Ghosting».

Ответ поддержки: пока нет. Когда придёт, дописать сюда дату и суть.

## Копии модов
Расшифровка: `Remarkable\mods\decoded` — те же моды с именами вместо
хешей и шапкой «что делает» по-русски. Папка в `.gitignore`: в ней
открытым текстом куски кода прошивки, которые авторы модов прятали
хешами. Собирает её `Tools\Remarkable\decode-qmd.py <папка с hashtab>
<папка модов>`; заодно печатает хеши, которых нет в прошивке, — первая
проверка совместимости после обновления (но не последняя, см. выше).
Повторный прогон затирает шапки, их держать в копии.

`Remarkable\mods` в корне Roll - файлы `.qmd` в том виде, как они стояли
на планшете 26 ноября: посмотреть, сравнить с обновлением, вернуть руками
(`scp -O` в папку qt-resource-rebuilder и `start`). Это чужой код под
GPL/MIT, авторы и лицензии - в шапке каждого файла. Свои моды, если
появятся, кладутся рядом в отдельную папку, а не правкой чужих: правку
чужого `.qmd` затрёт следующий `vellum upgrade`.

## GhostBuster Reloaded
Не из Vellum: github.com/pfjarschel/remarkable-paperpro-ghostbuster-reloaded,
копия в `Remarkable\mods\ghostbuster-reloaded`. Делает полное обновление
экрана сам: на перелистывание и переход по папкам (`page`), на настройки
(`settings`), после ластика (`eraser`), жест пятью пальцами (`global`; у нас
уже есть свой `ghostbuster.qmd` из Vellum с тем же жестом, второй не ставить).

Собран под прошивку 3.28.0.169. Совместимость с нашей проверяется так: все
числа `[[...]]` и `~&...&~` из `.qmd` должны найтись в `hashtab` планшета
(формат: 8 байт хеша big-endian, 4 байта длины, имя). На 3.27.3 сошлись
`page`, `eraser`, `global`; в `settings` нет одного хеша, его не ставить.

Совпадение хешей не гарантирует работу: на 3.27.3 `page` вешал интерфейс
сразу после ввода PIN, и экран PIN возвращался по кругу. Снят через
полчаса. Пробовать снова только на прошивке, под которую собран модуль.

26 ноября поставлен только `ghostbuster-page.qmd`: `scp -O` в папку
qt-resource-rebuilder и `start`. Перед этим папка целиком скопирована в
`/home/root/xovi/backup-2026-11-26`. Откат: удалить
`ghostbuster-page.qmd` и `start`. Ssh-сессия с `start` может не закрыться
сама; проверять по `pidof xochitl` и `LD_PRELOAD` в его environ.

Почему, скорее всего, вешал: мод зовёт `ghostBuster.forceClearNow(...)`,
метод встроенного объекта GhostBuster прошивки, и вставляет код после
строки `pageLabelTimer.restart();` в `DocumentView.qml`. Если в 3.27 нет
метода или строки, ломается сборка экрана библиотеки, а он грузится сразу
после PIN. Хеши такое не ловят.

### Пробовать новый мод только с автооткатом
Окирпичить так нельзя: моды лежат в `/home/root`, системный раздел не
меняется. Худшее — интерфейс падает по кругу. Перед пробой на планшете
заводится таймер, который сам снимает мод, если его не отменили:

```sh
Q=/home/root/xovi/exthome/qt-resource-rebuilder; M=ghostbuster-page.qmd
touch /tmp/mod-trial
END=$(( $(date +%s) + 180 ))
setsid sh -c "while [ \$(date +%s) -lt $END ]; do sleep 5; done; [ -f /tmp/mod-trial ] && mv $Q/$M /home/root/xovi/disabled/ && /home/root/xovi/start" </dev/null >/dev/null 2>&1 &
```

Срок считается по часам, а не одним `sleep 180`: планшет между касаниями
уходит в автосон, `sleep` во сне стоит, и трёхминутный таймер 26 ноября
опоздал больше чем на минуту. После сна цикл замечает, что срок вышел, и
откатывает сразу.

Затем мод кладётся и делается `start`. Мастер за три минуты проверяет вход
по PIN и пару страниц; если всё хорошо, `rm /tmp/mod-trial`, и таймер
ничего не делает. Не ответил, отвалился Wi-Fi, интерфейс в петле — через
три минуты мод уходит сам. Запасные пути: перезагрузка долгим нажатием
питания (после неё XOVI не стартует до тройного нажатия) и SSH по кабелю
на 10.11.99.1, который работает при любом состоянии интерфейса.
