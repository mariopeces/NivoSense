/** How the sub-basins are drawn: full on the Agua tab, only a thin outline of the domain elsewhere. */
export type BasinStyle = {
  /** Fill opacity; it also keeps the polygons clickable (a fill layer with opacity 0 still takes clicks). */
  fillOpacity: number;
  lineWidth: number;
  lineOpacity: number;
  haloOpacity: number;
  /** Selected basin highlight and click selection. */
  interactive: boolean;
};

export function basinStyle(section: string): BasinStyle {
  if (section === "agua") {
    return { fillOpacity: 0.12, lineWidth: 1.75, lineOpacity: 1, haloOpacity: 0.9, interactive: true };
  }
  return { fillOpacity: 0, lineWidth: 1, lineOpacity: 0.55, haloOpacity: 0.5, interactive: false };
}
