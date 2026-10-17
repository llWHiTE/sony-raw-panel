# Changelog

## 0.8.0 — 2026-10-17

### Независимые профили и рассчитанные результаты

- Профили Sony/Adobe доступны в готовом сравнении. Меняется только выбранная ветка, без повторной проявки второй; повторный выбор того же профиля — no-op. Показанный проявщик, CUBE, геометрия и полный рабочий результат сохраняют согласованные настройки.
- Adobe-профиль обновляет частную базу XMP, повторно применяет текущий пресет и сохраняет приоритет CameraProfile/Look. Sony фиксирует независимую версию XML-рецепта, проверяет отсутствие неожиданной ручной правки и экспортирует только свою ветку. На JSX-ошибке собственные изменения откатываются, пользовательская работа не сбрасывается.
- Введён bounded дисковый кэш рассчитанных lossless 16-bit sRGB TIFF: Sony/Adobe preview и полный Sony. Ключ включает хеш RAW, семантический рецепт/эффективный XMP, установленные engine/profile dependencies, размеры и цвет; CUBE вынесен из ключа. Full Adobe остаётся встроенным RAW-смарт-объектом.
- Первичные проверки полные; повторные учитывают Windows ChangeTime и NTFS USN, а не только размер/mtime. Это покрывает быстрые одинаковые по размеру перезаписи с совпавшими временными метками; без USN используется повторный хеш содержимого. Повреждённые, недописанные и перенаправленные cache entries не используются. Изменённый dependency даёт промах, не старую обработку.
- Повторное открытие кэшированного профиля после собственной смены Sony-профиля проверяет последнюю сохранённую рабочую ревизию и возвращает нужный рецепт без нового экспорта. Собственная смена не выдаётся за ручную правку; настоящая ручная правка и чужая активная вкладка по-прежнему защищены.
- Лимит кэша начально 5 ГБ, настраивается; LRU не удаляет закреплённые результаты. Отдельная очистка derived images не затрагивает RAW-проекты/рецепты и не очищает Photoshop Undo. Cache failure не отменяет уже готовый результат.

### Очередь и фоновая подготовка

- Несколько RAW добавляются выбором, multi-drop или передачей из Проводника. Очередь хранит текущий кадр, порядок, статусы и параметры; предыдущий/следующий выбирается явно. Можно переставлять и удалять ожидающие записи, не удаляя файлы.
- Подготовленные проверенные копии переиспользуются по кадру/проявщику; один следующий RAW готовится автоматически. Очередь/готовность сохраняются, прерванный импорт не повторяется автоматически.
- Опционально готовится полный Sony TIFF текущего сравнения; выбор Sony присоединяется к готовому job и обычному recovery/ack, без второго экспорта. Смена Sony-рецепта инвалидирует pre-render, CUBE/Adobe-профиль — нет.
- Опционально готовится Sony-превью следующего кадра в кэш; Adobe спекулятивно не открывается в Photoshop во время ретуши. Оба затратных режима выключены по умолчанию.
- Планировщик сохраняет одну native-полосу: ручные задания выше полного текущего Sony, затем look-ahead, затем scan. Уже начатый экспорт не убивается; ожидающие задачи можно отменить/заменить. UI сообщает ожидание фоновой команды.
- Фоновые задания откладываются при ручной коррекции/изменённом RAW, диалогах, чужой вкладке, закрытом/свёрнутом Sony или другой активной программе. Не запускают Sony спекулятивно. Ручные настройки проверяются отдельным временным XML, не подменяя последнюю сохранённую версию проекта.

### Накладные задержки

- Убраны фиксированные 1 с после открытия RAW и 0,5 с после навигации Sony; ожидание проверяет правильную вкладку, доступность команды и фактическую папку. Poll начинается с 20 мс и ограничен backoff, вместо постоянных 250 мс.
- Preview использует ту же проверку завершённого TIFF writer, что полный экспорт: наличие файла само по себе не считается готовностью. После закрытия writer панель отдельно ждёт исчезновения штатного окна прогресса Sony — даже если оно уже показывает 100%, — прежде чем восстанавливать размеры экспорта; неожиданные диалоги не закрываются.
- JSX helpers загружаются по хешу версии в Photoshop один раз, а не перечитываются каждым запросом. Убран отдельный COM Version round-trip перед DoJavaScript; RPC reset и запрет автоматического replay сохранены.
- Scan редкий при скрытой панели/постороннем приложении и ниже ручных заданий. Добавлены stage timings проверки/копирования, рецепта/активации, cache/export и Adobe/COM.
- Замеры cold/miss/hit разделены в BENCHMARK.md. Ускорение повторного результата не выдаётся за ускорение самого RAW-движка; GPU-настройки, битность и геометрия не ухудшены.

### Windows и повседневная работа

- Компактный режим оставляет текущий кадр/очередь, основные действия, статус и время. Раскрытие восстанавливает порядок элементов и размер окна.
- Опциональная контекстная видимость скрывает панель поверх посторонних приложений и возвращает рядом с Photoshop/Sony; свои диалоги остаются частью панели, ручное скрытие не отменяется автоматически.
- Глобальные горячие клавиши через RegisterHotKey, отдельно включаемые/настраиваемые, с MOD_NOREPEAT, конфликтами и освобождением при выходе. Edit обновляет однозначную Photoshop-цель; Apply использует только известную начатую коррекцию; toggle доступен везде. Существующие локальные сочетания сохранены.
- «Отправить» устанавливает/удаляет только собственный пользовательский ярлык portable EXE. Нет регистрации ассоциаций, HKLM, автозагрузки и запроса администратора. Чужой одноимённый ярлык не заменяется. Установка не происходит автоматически при обновлении.
- CLI принимает Unicode/пробелы и несколько ARW. Повторный EXE передаёт bounded file-only IPC работающей панели той же data-папки; нет исполнения команд из сообщения, потери аргументов и подмены текущей работы. Диагностические CLI-режимы сохранены.
- Контекстное меню текущего кадра открывает оригинал/папку Sony-проекта, копирует путь и показывает RAW/project/revision/recipe. Photoshop-связь берётся из свежего состояния, не только из последнего добавленного файла.

### Иконка и оформление

- Добавлена оригинальная многоразмерная иконка 16–256 px, встроенная в EXE и Tk-окна; задан AppUserModelID для панели задач. Значок не копирует торговые логотипы Sony/Adobe.
- Скроллбар сделан узким, тёмным и без стрелок/светлой рамки. Кнопки получили приглушённые границы, плоские серые состояния и сохранённый клавиатурный фокус; синий акцент оставлен основному Apply. Queue-кнопки используют тот же стиль.
- Обновлены инструкции, changelog и раздельные измерения; добавлены cache/scheduler/queue/profile/Windows/UI-регрессии. Нативно проверены две камеры, профильные циклы, кэш, полный pre-render, look-ahead, защита ручных параметров, IPC, клавиши и компактный режим. SendTo тестируется только во временной папке.
- Главная страница кратко объясняет назначение проекта: максимально корректная Sony-проявка через оригинальный Imaging Edge с последующей ретушью в Photoshop. Обновлены быстрый старт, установка portable ZIP и пояснения по сохранности `data`.
- В поставку входят portable EXE/ZIP, инструкции, лицензии и SHA-256. Оригинальные ARW, проекты, установленные профили, локальные настройки и журналы не публикуются.

## 0.7.0 — 2026-10-17

### LUT прямо в готовом сравнении

- Список **LUT / XMP** остаётся доступным в готовом Sony/Adobe-сравнении. Новый выбор применяется в фоновом рабочем потоке; несовместимые действия блокируются только на время команды.
- CUBE → CUBE и CUBE → **Без LUT** изменяют только общий корректирующий слой Photoshop. Sony-экспорт и Adobe Camera Raw-декодирование не запускаются, исходные Sony/Adobe-слои не заменяются. Сохраняются документ, геометрия и показанный проявщик; лишние LUT-слои не накапливаются.
- Новый слой успешно создаётся до удаления старого. Ошибка JSX откатывает служебную операцию по истории; Python-состояние и выбор меняются только после успешного ответа. При ошибке интерфейс возвращает подпись последнего применённого эффекта.
- Последний успешно применённый LUT, включая отключение, переносится в полный Sony/Adobe-результат. Удаление библиотечной записи не уничтожает сохранённый снимок эффекта текущей операции.
- Ручная правка сравнения блокирует смену LUT вместо перезаписи возможной ретуши. Проверяются идентификатор служебного превью, известные слои, их количество, количество записей истории и ID текущего состояния истории — в том числе при заполненном лимите истории.
- Длительность команды показывается отдельно как **Смена LUT / XMP**. Восстановленное сравнение показывает свой фактический последний эффект.

### XMP без повторного Sony-экспорта

- XMP можно менять и отключать в том же сравнении. Обновляется только Adobe-слой с прежними проверками профиля, размеров и пропорций. Sony-слой и его рецепт остаются прежними.
- При переходе XMP → CUBE / None сначала восстанавливается Adobe без старого пресета. CUBE затем действует на обе ветки; XMP, как и раньше, действует только на Adobe.
- При создании сравнения сохраняется частный `adobe-base.xmp` с выбранными Adobe CameraProfile/Look. Новый XMP применяется к этой базе, а не поверх предыдущего пресета; зафиксированный профиль/Look имеет приоритет, прочие настройки нового пресета сохраняются.
- При ошибке обновления восстанавливается частный sidecar и сохраняется предыдущий Adobe-слой. Перенаправленные/жёстко связанные частные XMP не перезаписываются. Оригинальные RAW и пользовательские sidecar не меняются.
- Для восстановленных сравнений до 0.7.0 CUBE совместим; смена XMP требует нового сравнения, поскольку в старых данных нет зафиксированной базы. Базовый XMP удаляется только вместе с подтверждённо закрытым служебным превью по точному списку разрешённых имён.

### Безопасные оптимизации

- Добавлен ограниченный внутрипроцессный кэш валидации CUBE/XMP и подготовленных ICC, до 64 записей. Ключ учитывает путь, идентичность/размер и временные метки файла. Изменение файла инвалидирует кэш; первый запуск и восстановление после перезапуска выполняют проверки заново.
- Повреждённый/отсутствующий ICC пересоздаётся. Хеши снимков и защитные проверки оригиналов, геометрии и битности не отключены. Разбор/снимок/компиляция выбранного LUT больше не блокируют Tk-поток.
- Убраны отдельные повторные Photoshop `inspect` после построения и переключения сравнения: необходимая информация об истории возвращается основной командой.
- После применения Sony-профиля повторно используется уже сохранённый и проверенный рецепт вместо второго одинакового диалога Save Settings. Версии рецептов сохраняют независимые идентификаторы и контрольные суммы.
- Битность и разрешение ради скорости не снижались, JPEG-подмена и небезопасное параллельное управление приложениями не применяются. GPU-настройки Sony/Adobe не изменяются.
- Фактические замеры и ограничения опубликованы в [BENCHMARK.md](BENCHMARK.md). Быстрая смена CUBE не означает такого же ускорения первоначальной Sony-проявки.

### Очистка, проверки и документация

- Включено локальное исправление 0.6.1, ранее не опубликованное отдельным релизом: стандартный Sony-запрос сохранения неизменённого служебного превью получает безопасный ответ **Нет** без ручного участия. Подробности защит — ниже; предупреждение перед глобальной очисткой Photoshop сохранено.
- Добавлены контроллерные, JSX и настоящие Tk-widget тесты смены CUBE/None, XMP-only обновления, отката, передачи последнего эффекта в оба full-size пути, кэш-инвалидации, повреждения ICC и безопасного удаления базового XMP.
- Нативные проверки Photoshop подтверждают изменение пикселей, чёрно-белый результат, отсутствие накопления слоёв, перенос LUT в полный Sony- и Adobe RAW-результат и неизменность оригинального ARW по SHA-256. Панель проверяется через реальные элементы Tk, а не только внутренние методы.
- README на главной странице, PANEL.md и PORTABLE.md обновлены: смена LUT в сравнении, разница CUBE/XMP, совместимость старых сравнений, кэш, измерения и безопасная замена EXE с сохранением `data`.
- В публичные исходники и EXE не включаются тестовые фотографии, рабочие проекты, локальные настройки, логи и установленные Adobe/Sony-профили.

## 0.6.1 — 2026-10-17 (локальное исправление, включено в релиз 0.7.0)

### Очистка без ручного запроса сохранения Sony

- Исправлено закрытие служебных Sony-превью при очистке кэша. Sony может оставлять вкладку помеченной изменённой даже после сохранения её параметров в отдельный XML, из-за чего прежняя очистка останавливалась на вопросе «Сохранить изменения в SonyRAW-….ARW?».
- После проверки частного RAW и семантического совпадения с сохранённым рецептом панель автоматически выбирает **Нет** в стандартном save-changes диалоге, созданном собственной командой закрытия. ARW не перезаписывается, XML-рецепт сохраняется.
- Проверяются процесс Sony, точное окно-владелец, тип/кнопки диалога, формулировка вопроса и имя конкретного служебного RAW. Общих нажатий Enter, Yes или «Нет для всех» нет.
- Если Sony переключил вкладку и предлагает сохранить другой RAW, закрытие отменяется кнопкой **Отмена**, а не подтверждается без сохранения. Изменённые по сравнению с рецептом превью не закрываются вообще.
- Уже существующие или неизвестные диалоги не подтверждаются автоматически. Рабочие снимки, активная коррекция и исходные файлы остаются защищены прежними проверками; предупреждение перед Photoshop ALLCACHES не удалено.
- Добавлены регрессионные тесты на стандартный вопрос, закрытие без вопроса, смену RAW, чужое окно, неизвестный вопрос и запрет закрытия обычного файла. Нативно воспроизведён именно Sony-запрос сохранения: неизменённые служебные вкладки закрываются без ручного участия, изменённая вкладка остаётся открытой без вопроса, исходный ARW не меняется по SHA-256.

## 0.6.0 — 2026-10-17

### Профили Adobe и Sony

- Добавлены отдельные списки **Профиль Adobe** и **Профиль Sony**. Профиль по умолчанию — **Camera Standard** для обоих проявщиков; последующие предпочтения сохраняются отдельно по модели камеры.
- Модель читается из TIFF/Exif выбранного ARW. Каталог Adobe строится из установленных Camera Raw DCP этой модели и Adobe Raw Look-профилей, а не из единого жёсткого списка для всех камер.
- Поддержаны Camera Standard / Camera ST, Adobe Color, Adobe Standard, Adobe Portrait, Camera Portrait / Camera PT и Camera Vivid / Camera VV. Остальные реально установленные варианты также появляются в списке. PT/VV не подменяются Adobe Portrait/Color.
- Adobe Color и Adobe Portrait записывают настоящий Camera Raw Look с UUID, параметрами, кривыми и установленной Look-таблицей. Одной строки CameraProfile/названия Look недостаточно; различия подтверждены по пикселям, а не только по подписи.
- Adobe-профиль и Look проверяются в метаданных результата Photoshop. Недоступный профиль не заменяется другим молча. При недостаточной поддержке камеры предлагается обновить Camera Raw.
- Sony-профили считываются из реального ComboBox Creative Style / Creative Look: используются его подписи и идентификаторы, а не одинаковые индексы для разных камер. Standard, Portrait, Vivid и другие варианты у A7R III отличаются от ST/PT/NT/VV/VV2/FL/IN/SH/BW/SE у A7R V.
- Наблюдённый Sony-каталог кэшируется отдельно по модели. Включены проверенные начальные каталоги A7R III и A7R V — это только подписи и идентификаторы, не файлы/алгоритмы профилей Sony.
- Для ещё неизвестной камеры до первого необходимого Sony-открытия предлагается только Camera Standard. Полный фактический список запоминается при этой проявке; дополнительного открытия ради списка нет. Каждый выбранный вариант проверяется в настоящем меню перед применением и затем в сохранённом XML-рецепте.

### Одинаковые настройки в превью и рабочем документе

- Профили обоих проявщиков фиксируются при запуске сравнения и сохраняются в его состоянии вместе с LUT. Полноразмерный выбор использует те же настройки, а не текущие глобальные списки панели.
- Выбранный Sony-стиль применяется перед первым экспортом и в сценарии **Сначала настроить в Sony**. Рабочая копия открывается с нужным профилем ещё до ручной коррекции.
- При повторной Sony-коррекции новый явно выбранный в панели профиль можно применить перед редактированием, не сбрасывая остальные параметры рецепта. Без явного нового выбора сохраняется стиль связанной версии проекта. Последующий Apply не переопределяет ручные изменения Sony глобальным профилем.
- Изменение профиля считается изменением рецепта. Неизменённый рецепт по-прежнему пропускает TIFF и замену смарт-объекта; ретушь и отдельный CUBE-слой сохраняются.
- Adobe-профиль/Look сохраняется внутри встроенного RAW-смарт-объекта для дальнейшего редактирования через Camera Raw. Глобальные списки не переписывают уже открытые Adobe-документы.
- Уточнён приоритет XMP: явно выбранный Adobe-профиль побеждает CameraProfile и конкурирующий Look пресета. Экспозиция, цветовые настройки и пользовательские кривые XMP сохраняются. Это намеренное отличие от 0.5.1; результат Sony To Leica может измениться при другом выбранном профиле.

### Добавление RAW и быстродействие

- Добавлена кнопка **Добавить RAW…**. Добавление/перетаскивание теперь отделено от **Открыть в Photoshop** и **Сравнить**: пользователь сначала видит модель и выбирает доступные профили.
- При добавлении не запускаются открытие фото в Sony/Photoshop, декодирование RAW или TIFF-экспорт. Читаются только небольшие метаданные и локальный каталог.
- Каталог Adobe сохраняется на диске по модели; изменения установленного набора/файлов инвалидируют кэш. Sony-списки повторно используются из наблюдённого каталога.
- После добавления в фоне готовится независимая проверенная копия для выбранного проявщика. Настройки профиля можно выбирать параллельно. Sony-открытие/сравнение повторно использует готовый проект; раннее нажатие ожидает уже начатую подготовку вместо параллельного копирования.
- Прямой Adobe-импорт может повторно использовать проверенную фоновую копию с проверкой её размера/mtime и сбросом только частного XMP, без второго копирования и полного хеширования при импорте.
- До выбора профиля не выполняется спекулятивная проявка. Не добавлен собственный GPU-движок и не изменяются глобальные настройки GPU Sony/Adobe: аппаратное ускорение остаётся под управлением самих приложений.
- В локальной нативной проверке первое чтение каталога A7R III заняло около **85 мс**, фоновая копия — около **0,10 с**. Это измерения конкретного диска/RAW, а не обещание пропорционального ускорения проявки.

### Интерфейс и исправление LUT

- Оформление приближено к Adobe: нейтральные тёмно-серые поверхности, тёмные списки, компактные кнопки, синий акцент основного действия и тонкий индикатор. Нет тяжёлых визуальных эффектов и изменения размера окна для сравнения.
- Неактивные кнопки редактирования скрыты, когда ещё нет рабочего Sony-документа; добавленный файл, модель и фоновая подготовка видны отдельно от статуса Photoshop.
- В релиз включено локальное исправление 0.5.2: Color Lookup получает встроенный бинарный RGB device-link профиль вместе с CUBE-текстом. Ранее созданный слой мог существовать без реального эффекта.
- CUBE проверен для всех восьми комплектных LUT, отключения слоя, сохранения/повторного открытия PSD и Sony/Adobe preview/full. Старые слои не переписываются автоматически — требуется повторная загрузка CUBE в свойствах слоя или новый документ.

### Проверки, документация и обновление

- Добавлены тесты модели камеры, динамического каталога, кэш-инвалидации, настоящих Look Parameters, приоритета профиля над XMP, строгой JSX-проверки, независимых предпочтений камер, фоновой подготовки и передачи профиля в коррекцию.
- Нативно проверены шесть запрошенных Adobe-профилей в превью и полном RAW на A7R III/A7R V; Sony Standard/PT/VV в превью и полном размере; unchanged Apply; исходные ARW остались неизменными по SHA-256.
- Обновлены README на главной странице, PANEL.md и PORTABLE.md: порядок добавления RAW, профили, первая неизвестная камера, фоновые данные, LUT/XMP, GPU-ограничения и безопасное обновление.
- Обновление: закрыть старую панель, заменить EXE в прежней папке, **оставить data**. Фотографии, рабочие проекты, журналы, локальные пути и установленные файлы профилей Adobe/Sony не публикуются.

## 0.5.2 — 2026-10-17 (локальное исправление, включено в релиз 0.6.0)

- Fixed CUBE layers that were created but did not change the image: embed the RGB device-link ICC profile that Photoshop actually renders, alongside the original editable CUBE data.
- Compile profiles locally with 16-bit tables, correct CUBE/ICC channel ordering and per-channel input domains. No external dependencies or changes to the original RAW/LUT files.
- Verify cached profiles, regenerate missing/corrupt copies, and upgrade restored 0.5.1 operations when imported. Existing Photoshop layers are not silently rewritten; recreate the affected document or reload its CUBE through Photoshop Color Lookup.
- Added ICC structure, domain, cache and channel-order regression tests. Native verification measures merged RGB values for all eight bundled CUBE LUTs, identity/channel-swap controls, disabling the layer and PSD save/reopen persistence, instead of merely checking that a layer exists.

## 0.5.1 — 2026-10-17

- Fixed DSC04755 portrait orientation: source-relative output sizes now account for EXIF rotations 5–8 before Sony export. Both 100% and 50% comparisons retain the correct 5304:7952 aspect ratio.
- Adobe resizing is proportional only. Incompatible aspect ratios fail explicitly rather than stretching the image; at most a one-pixel canvas adjustment handles rounding.
- New projects record orientation-aware full output dimensions for both direct Sony import and comparison-to-full-size workflows.
- Added a unified **Очистить кэш** button: confirmed disk cache, identified unchanged Photoshop comparison documents, their unchanged Sony RAW tabs, then Photoshop `ALLCACHES`. A clear warning covers global undo-history/clipboard loss; **Больше не показывать** persists only after confirmation and can be re-enabled from the menu.
- Modified or unidentified previews, active work/recovery, user documents, RAW projects and recipes are retained. Sony preview closure verifies the saved recipe before unloading a tab and restores the prior active tab when possible.
- Added optional `.cube` Color Lookup layers to Sony/Adobe previews and final documents; default is **Без LUT** every launch. Local library supports importing and removing entries, including initial assets. Operation snapshots preserve a chosen look after library removal.
- Included eight user-supplied LUTs and `Sony To Leica.xmp` with explicit redistribution permission. XMP is an Adobe-only preset with its own profile/Look table, never misrepresented as a Sony recipe or Camera ST.
- Added the MIT source license for Alexey Storozhilov, separate creative-asset notices, original CPython/Windows/Tcl/Tk licenses and a runtime manifest. Creative assets/runtime are not relicensed under MIT.
- Expanded regression tests and native checks for rotated RAW, preview cleanup, LUT/XMP import, full-size output and warning preferences. Release includes this version-history file as an asset.

## 0.5.0 — 2026-10-17

- Preview resolution is now 100%, 75%, 50% or a saved custom integer percentage (1–100%) of each source ARW's own usable width and height. Dimensions come from TIFF/Exif metadata, not a fixed camera resolution or Sony's last export settings.
- One comparison button starts the preview and then toggles Sony / Adobe; a single full-resolution action uses the currently shown engine.
- Opening, comparison and Apply durations remain visible after completion. Initial Sony preparation and the first Apply can be reported together, excluding manual adjustment time.
- Added **Отменить проявку** for pending/failed operations. Cancellation archives local recovery state without contacting Photoshop/Sony, deleting ready renders, or changing open documents.
- Photoshop host invalidates stale COM references after RPC/JSX errors and reconnects on the next explicit request. Mutating commands are never automatically replayed.
- Reworked the panel layout: no empty comparison placeholder, no forced window resizing, scrollable content for small windows, a fixed footer, contextual target selection and clearer error styling.
- Adobe preview decoding no longer uses the legacy medium-size cap for large percentage previews, avoiding upscaling a smaller decode.
- Added camera-independent dimension, percentage/preference, cancellation and comparison-state regressions. Native preview performance measurements are documented separately.

## 0.4.0 — 2026-10-17

Author: **Alexey Storozhilov**

Repository: https://github.com/llWHiTE/sony-raw-panel

### Workflow

- Added **Сначала настроить в Sony**. Open a private RAW copy in Sony, adjust it, then create the first Photoshop result only when **Применить** is pressed.
- Added semantic Sony-recipe comparison. Applying unchanged development settings skips TIFF export and Photoshop Smart Object replacement.
- Added a Sony / Adobe opening-engine selector. Adobe opens a full-resolution embedded RAW Smart Object with the Camera ST profile.
- Sony / Adobe comparisons support 1600 px, 3000 px and full resolution. Choosing an engine creates the full-resolution working result, independently of preview size.
- Existing retouch layers remain intact when the Sony Smart Object is updated.
- Temporary TIFFs are removed only after Photoshop confirms successful embedding. RAW copies and recipes remain available for future Sony adjustments.

### Portable application

- Added a single Windows x64 EXE containing its Python/Tk runtime; a separate Python installation is not required.
- Application paths are discovered from installed-app registrations and running programs. If discovery fails, launch Sony Edit / Photoshop manually and repeat discovery, or select their executable paths in the panel.
- Writable settings, projects and runtime files are stored in `data` beside the EXE.
- Added author credit, a GitHub link, an About dialog and a program-paths dialog.

### Verification

On the tested Windows 11 / Sony A7R V setup, the source workflow completed initial Sony preparation in 7.7 seconds, first Apply in 5.7 seconds, an unchanged Apply in 0.5 seconds, and a changed-exposure update in 4.4 seconds. These are observed timings, not guarantees for other computers or files.

Verified: original ARW hash unchanged, no TIFF before initial Apply, no render job for unchanged settings, successful update for changed settings, temporary TIFF cleanup, and full-resolution Adobe RAW Smart Object import.

### Limitations

- Requires separately installed Sony Imaging Edge Edit and Adobe Photoshop on Windows. These proprietary applications are not bundled.
- Sony mode embeds a 16-bit Sony-developed image, not a Sony RAW engine inside Camera Raw. Further Sony RAW adjustments use the retained project copy and recipe.
- The EXE is not code-signed; Windows SmartScreen may show a warning. Verify the SHA-256 checksum against the release asset.
- The GitHub repository and release exclude photographs, project data, caches, local application paths and credentials.
