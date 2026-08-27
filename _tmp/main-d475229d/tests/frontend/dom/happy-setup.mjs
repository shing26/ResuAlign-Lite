import { Window } from "happy-dom";

/* Install browser globals BEFORE any app module that touches them at
 * import time (events.js reads localStorage at module scope). This
 * module must be the FIRST import of any DOM test that pulls in
 * events.js transitively (e.g. diff-editor.js). */
const window = new Window();
globalThis.window = window;
globalThis.document = window.document;
globalThis.localStorage = window.localStorage;
