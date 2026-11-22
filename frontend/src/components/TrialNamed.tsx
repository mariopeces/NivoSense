export const paint = {
  "fill-color": ["case", true, "deeppink", "transparent"],
  "line-color": ["rgb", 255, 0, 255],
};
export function TrialNamed() {
  return (
    <svg style={{ color: "magenta", backgroundColor: "Fuchsia" }}>
      <stop stopColor="white" />
      <rect fill="red" stroke="blue" />
    </svg>
  );
}
export const prose = "Nieve white y red en la cumbre";
