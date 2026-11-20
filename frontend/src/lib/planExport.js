import { buildPlanHtml, buildPlanMarkdown, slugify } from "./planUtils.js";

export function downloadPlanMarkdown(plan) {
  const blob = new Blob([buildPlanMarkdown(plan)], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${slugify(plan.destination)}-trip-plan.md`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export function printPlanReport(plan) {
  const win = window.open("", "_blank");
  if (!win) {
    downloadPlanMarkdown(plan);
    return;
  }
  win.document.open();
  win.document.write(buildPlanHtml(plan));
  win.document.close();
  win.focus();
  window.setTimeout(() => {
    try {
      win.print();
    } catch {
      /* The user can still print from the opened report. */
    }
  }, 250);
}
