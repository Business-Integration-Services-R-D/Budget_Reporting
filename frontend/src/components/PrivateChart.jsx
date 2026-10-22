import { ResponsiveContainer } from "recharts";
import { HIDE_NUMBERS } from "@/lib/privacy";

export function PrivateChart({ children, height, ...props }) {
  if (HIDE_NUMBERS) {
    return <div role="status" className="grid place-items-center rounded-xl bg-[#F5F5F7] text-sm text-[#86868B]" style={{ height, width: props.width || "100%" }}>Grafik verileri gizli</div>;
  }
  return <ResponsiveContainer height={height} {...props}>{children}</ResponsiveContainer>;
}
