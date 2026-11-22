export function TrialShorthands() {
  return (
    <div
      style={{
        textDecoration: "underline red",
        columnRule: "1px solid teal",
        filter: "drop-shadow(0 0 2px navy)",
        backdropFilter: "drop-shadow(0 0 1px olive)",
        boxShadow: "0 0 4px black",
        caretColor: "lime",
        accentColor: "plum",
        ["--accent" as string]: "gold",
      }}
    />
  );
}
