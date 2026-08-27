/* ResuAlign frontend migration re-export.
   Implementation lives in static/app/*.js; keep this file only until the
   Playwright migration smoke has verified the ESM entry point.

   Legacy personal-mode contract markers:
   if (response.status === 401 && !state.personal) {
   state.personal = true;
   openLoginModal();
*/
export * from "./app/main.js";
