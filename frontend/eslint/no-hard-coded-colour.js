import path from "node:path";

// Every colour that is not in the tokens file must be listed in the baseline (colours that predate the tokens),
// value by value and file by file, so a new colour, a moved one or a swapped one fails, and a removed one
// must also leave the baseline.
const HEX = "#(?:[0-9a-f]{8}|[0-9a-f]{6}|[0-9a-f]{3,4})(?![0-9a-z_-])";
const FUNCTIONS = ["rgb", "rgba", "hsl", "hsla", "hwb", "lab", "lch", "oklab", "oklch", "color"];
const FUNCTION = `(?<![a-z-])(?:${FUNCTIONS.join("|")})\\([^()]*\\)`;
const IN_STRING = new RegExp(`${HEX}|${FUNCTION}`, "gi");

// CSS named colours (CSS Color 4), checked in CSS declaration values only: in TS strings they are ordinary words.
const NAMED = new Set(
  (
    "aliceblue antiquewhite aqua aquamarine azure beige bisque black blanchedalmond blue blueviolet brown burlywood " +
    "cadetblue chartreuse chocolate coral cornflowerblue cornsilk crimson cyan darkblue darkcyan darkgoldenrod darkgray " +
    "darkgreen darkgrey darkkhaki darkmagenta darkolivegreen darkorange darkorchid darkred darksalmon darkseagreen " +
    "darkslateblue darkslategray darkslategrey darkturquoise darkviolet deeppink deepskyblue dimgray dimgrey dodgerblue " +
    "firebrick floralwhite forestgreen fuchsia gainsboro ghostwhite gold goldenrod gray green greenyellow grey honeydew " +
    "hotpink indianred indigo ivory khaki lavender lavenderblush lawngreen lemonchiffon lightblue lightcoral lightcyan " +
    "lightgoldenrodyellow lightgray lightgreen lightgrey lightpink lightsalmon lightseagreen lightskyblue lightslategray " +
    "lightslategrey lightsteelblue lightyellow lime limegreen linen magenta maroon mediumaquamarine mediumblue " +
    "mediumorchid mediumpurple mediumseagreen mediumslateblue mediumspringgreen mediumturquoise mediumvioletred " +
    "midnightblue mintcream mistyrose moccasin navajowhite navy oldlace olive olivedrab orange orangered orchid " +
    "palegoldenrod palegreen paleturquoise palevioletred papayawhip peachpuff peru pink plum powderblue purple " +
    "rebeccapurple red rosybrown royalblue saddlebrown salmon sandybrown seagreen seashell sienna silver skyblue " +
    "slateblue slategray slategrey snow springgreen steelblue tan teal thistle tomato turquoise violet wheat white " +
    "whitesmoke yellow yellowgreen"
  ).split(" "),
);

const normalise = (value) => value.toLowerCase().replace(/\s*,\s*/g, ",").replace(/\s+/g, " ");

export default {
  meta: {
    type: "problem",
    docs: { description: "Ban colours outside the tokens file, except those listed in the baseline" },
    schema: [{ type: "object", properties: { tokensFile: { type: "string" }, baseline: { type: "object" } } }],
    messages: {
      colour: "Hard-coded colour {{value}}: define it in {{tokensFile}} and use the token.",
      stale:
        "The colour baseline lists {{value}} {{expected}} time(s) for this file but it appears {{found}}: " +
        "update colour-baseline.json.",
    },
  },
  create(context) {
    const { tokensFile, baseline = {} } = context.options[0] ?? {};
    const file = path.relative(context.cwd, context.filename).split(path.sep).join("/");
    const found = [];
    const collect = (node, text) => {
      for (const match of text.matchAll(IN_STRING)) found.push({ node, value: normalise(match[0]) });
    };
    const finish = () => {
      const allowed = { ...(baseline[file] ?? {}) };
      const counts = {};
      for (const { node, value } of found) {
        counts[value] = (counts[value] ?? 0) + 1;
        if (counts[value] > (allowed[value] ?? 0)) {
          context.report({ node, messageId: "colour", data: { value, tokensFile } });
        }
      }
      for (const [value, expected] of Object.entries(allowed)) {
        const seen = counts[value] ?? 0;
        if (seen < expected) {
          context.report({
            loc: { line: 1, column: 0 },
            messageId: "stale",
            data: { value, expected: String(expected), found: String(seen) },
          });
        }
      }
    };
    return {
      // JavaScript and TypeScript
      Literal(node) {
        if (typeof node.value === "string") collect(node, node.value);
      },
      TemplateElement(node) {
        collect(node, node.value.raw);
      },
      "Program:exit": finish,
      // CSS (CSSTree nodes from @eslint/css)
      Hash(node) {
        collect(node, `#${node.value}`);
      },
      Function(node) {
        if (FUNCTIONS.includes(node.name.toLowerCase())) {
          const { start, end } = node.loc;
          found.push({ node, value: normalise(context.sourceCode.text.slice(start.offset, end.offset)) });
        }
      },
      "Value Identifier"(node) {
        if (NAMED.has(node.name.toLowerCase())) found.push({ node, value: node.name.toLowerCase() });
      },
      "StyleSheet:exit": finish,
    };
  },
};
