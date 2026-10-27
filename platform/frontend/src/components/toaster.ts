// Safe global toaster (Blueprint v5). Created lazily to avoid SSR/init issues.
// Blueprint's OverlayToaster defaults its DOM renderer to the legacy ReactDOM.render,
// which triggers "ReactDOM.render is no longer supported in React 18". We pass a
// React 18 createRoot-based domRenderer so it mounts the modern way (no warning).
import { OverlayToaster, Position, Intent } from "@blueprintjs/core";
import { createRoot } from "react-dom/client";

let _t: any = null;
async function get() {
  if (!_t) {
    _t = await OverlayToaster.createAsync(
      { position: Position.TOP },
      { domRenderer: (app, container) => createRoot(container).render(app) },
    );
  }
  return _t;
}
export const toast = {
  success: async (message: string) => (await get()).show({ message, intent: Intent.SUCCESS, icon: "tick" }),
  error: async (message: string) => (await get()).show({ message, intent: Intent.DANGER, icon: "error" }),
  info: async (message: string) => (await get()).show({ message, intent: Intent.PRIMARY, icon: "info-sign" }),
};
