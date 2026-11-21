import { Moon, Sun } from "./icons";
import { useTheme } from "../theme";

export default function ThemeToggle({ className = "" }: { className?: string }) {
  const { theme, toggle } = useTheme();
  const next = theme === "dark" ? "浅色" : "深色";
  return (
    <button
      type="button"
      className={"theme-toggle " + className}
      onClick={toggle}
      aria-label={`切换到${next}模式`}
      title={`切换到${next}模式`}
    >
      <span className="tt-ico">{theme === "dark" ? <Sun size={13} /> : <Moon size={13} />}</span>
      <span className="tt-label">{theme === "dark" ? "浅色" : "深色"}</span>
    </button>
  );
}
