import { useEffect, useMemo, useRef } from "react";
import * as echarts from "echarts";
import { useTheme } from "../theme";

/*
 * 深色底上的图表配色在浅色主题里会「失焦」：白色网格线消失、荧光青柠发白。
 * 这里不改每个页面的 option，而是在 Chart 内统一做一次颜色映射，
 * 保证两种主题下图例、网格、趋势线都保持可读。
 */
function mapColor(src: string): string {
  if (src.includes("var(")) return src;
  let out = src;
  out = out.replace(/rgba\(\s*255\s*,\s*255\s*,\s*255\s*,/g, "rgba(26, 22, 16,");
  out = out.replace(/rgba\(\s*214\s*,\s*251\s*,\s*106\s*,/g, "rgba(79, 117, 0,");
  out = out.replace(/rgba\(\s*232\s*,\s*197\s*,\s*131\s*,/g, "rgba(137, 99, 26,");
  out = out.replace(/rgba\(\s*111\s*,\s*227\s*,\s*176\s*,/g, "rgba(12, 122, 78,");
  out = out.replace(/rgba\(\s*255\s*,\s*122\s*,\s*107\s*,/g, "rgba(190, 42, 31,");
  out = out.replace(/rgba\(\s*127\s*,\s*166\s*,\s*255\s*,/g, "rgba(44, 95, 191,");
  out = out.replace(/rgba\(\s*183\s*,\s*156\s*,\s*255\s*,/g, "rgba(106, 79, 201,");

  const hex: Record<string, string> = {
    "#d6fb6a": "#4f7500",
    "#e8c583": "#89631a",
    "#6fe3b0": "#0c7a4e",
    "#ff7a6b": "#be2a1f",
    "#8fa3c8": "#476b8f",
    "#8b93a1": "#6f6a60",
    "#8b93a0": "#6f6a60",
    "#5c6b80": "#6f6a60",
    "#5c636e": "#6f6a60",
    "#a3a9b4": "#5f584d",
    "#565d68": "#8b8376",
  };
  return hex[out.toLowerCase()] || out;
}

function lightOption(node: any): any {
  if (typeof node === "string") return mapColor(node);
  if (Array.isArray(node)) return node.map(lightOption);
  if (node && typeof node === "object") {
    const out: Record<string, any> = {};
    for (const [k, v] of Object.entries(node)) out[k] = lightOption(v);
    return out;
  }
  return node;
}

export default function Chart({
  option,
  height = 260,
  onEvents,
}: {
  option: any;
  height?: number;
  onEvents?: Record<string, (p: any) => void>;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const inst = useRef<echarts.ECharts | null>(null);
  const { theme } = useTheme();

  useEffect(() => {
    if (!ref.current) return;
    inst.current = echarts.init(ref.current, undefined, { renderer: "canvas" });
    const onResize = () => inst.current?.resize();
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      inst.current?.dispose();
      inst.current = null;
    };
  }, []);

  const themed = useMemo(() => (theme === "light" ? lightOption(option) : option), [option, theme]);

  useEffect(() => {
    if (!inst.current) return;
    inst.current.setOption(themed, true);
    if (onEvents) {
      Object.entries(onEvents).forEach(([evt, fn]) => inst.current?.off(evt).on(evt, fn as any));
    }
  }, [themed]);

  return <div ref={ref} style={{ width: "100%", height }} />;
}
