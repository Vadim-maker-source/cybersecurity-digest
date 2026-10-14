# Проверка интерфейса

Типизация: `npm run typecheck`. Production build: `npm run build`. Unicode/URL counter: `node --experimental-strip-types tests/counter.cjs`.

Браузерный E2E-сценарий выполнен на локальном экземпляре через инструмент управления браузером: вход, импорт fixtures, создание выпуска, переходы к источникам, настройкам и проверкам. После готовности проверяются письмо, пост, evidence, экспорт и мобильная ширина.

Для самостоятельного CI пакет @playwright/test установлен и зафиксирован. Установите Chromium через npx playwright install chromium и выполните npx playwright test. Сценарий: tests/editor.spec.ts. Пароль берётся из переменной `E2E_EDITOR_PASSWORD`, не записывается в test source и screenshots. Браузеры не устанавливаются в репозиторий автоматически.

Standalone suite подготовлен; исполнение указывается отдельно в отчёте. Trace выключен для защиты значений авторизации. Без E2E_EDITOR_PASSWORD результат skipped, а не passed.
