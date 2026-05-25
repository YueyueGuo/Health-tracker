/**
 * Heuristic: is the user currently typing in a form field?
 *
 * Used by detail-page keyboard handlers to avoid intercepting arrow-key
 * input that's meant for an editable element (e.g. text inputs, textareas,
 * `contenteditable` regions, custom comboboxes).
 */
export function isTypingTarget(target: EventTarget | null): boolean {
  if (!target || !(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
  if (target.isContentEditable) return true;
  const role = target.getAttribute("role");
  if (role === "textbox" || role === "combobox" || role === "searchbox") {
    return true;
  }
  return false;
}
