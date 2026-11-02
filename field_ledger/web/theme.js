// Light or dark, set before the page draws: the person's choice (the board's toggle), else
// the phone's own setting, followed live. A plain script in <head>, not a module, so the
// page never flashes the wrong one first. tokens.css keys its night palette on data-theme.
const THEME_KEY = "field-ledger-theme";
const night = matchMedia("(prefers-color-scheme: dark)");

function chosenTheme() {
  try { return localStorage.getItem(THEME_KEY); } catch { return null; }   // private mode
}

function showTheme() {
  const choice = chosenTheme();
  document.documentElement.dataset.theme =
    choice === "light" || choice === "dark" ? choice : night.matches ? "dark" : "light";
}

showTheme();
night.addEventListener("change", showTheme);
