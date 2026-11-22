export const paint = {
  "fill-color": { type: "categorical", property: "k", default: "red", stops: [[1, "#00ff00"]] },
  "line-color": ["match", ["get", "k"], "a", "#ffffff", "salmon"],
  "circle-color": ["coalesce", ["get", "c"], "orchid"],
};
