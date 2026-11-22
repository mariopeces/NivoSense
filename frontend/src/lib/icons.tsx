import type { LucideIcon } from "lucide-react";

// The spec's one icon set: Lucide with a 1.75 px stroke at every size; 20 px in the rail, 16 px inline.
export function Icon({ icon: Glyph, size = 16 }: { icon: LucideIcon; size?: 16 | 20 }) {
  return <Glyph size={size} strokeWidth={1.75} absoluteStrokeWidth aria-hidden="true" focusable="false" />;
}
