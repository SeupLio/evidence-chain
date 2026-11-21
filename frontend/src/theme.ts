import { useEffect, useState } from "react";

export type Theme = "dark" | "light";

const KEY = "ec-theme";
const EVT = "ec-theme-change";

export function storedTheme(): Theme {
  try {
    return localStorage.getItem(KEY) === "light" ? "light" : "dark";
  } catch {
    return "dark";
  }
}

export function applyTheme(theme: Theme) {
  document.documentElement.dataset.theme = theme;
  document.documentElement.style.colorScheme = theme;
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute("content", theme === "light" ? "#f4f1e9" : "#07080a");
  try {
    localStorage.setItem(KEY, theme);
  } catch {
    /* 隐私模式下写入失败不影响本次切换 */
  }
}

export function useTheme() {
  const [theme, setTheme] = useState<Theme>(storedTheme);

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  useEffect(() => {
    const sync = () => setTheme(storedTheme());
    window.addEventListener(EVT, sync);
    return () => window.removeEventListener(EVT, sync);
  }, []);

  const toggle = () => {
    const next: Theme = theme === "dark" ? "light" : "dark";
    applyTheme(next);
    setTheme(next);
    window.dispatchEvent(new Event(EVT));
  };

  return { theme, toggle };
}
