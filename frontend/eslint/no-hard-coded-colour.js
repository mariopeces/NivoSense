import path from "node:path";

// Every colour that is not in the tokens file must be listed in the baseline (colours that predate the tokens),
// value by value and file by file, so a new colour, a moved one or a swapped one fails, and a removed one
// must also leave the baseline.

// A colour function (matched to its balanced closing parenthesis) or a hex colour, also URL-encoded (%23) in data URIs.
const START =
  /(?<![a-z-])(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch|color-mix|color)\(|(?:#|%23)(?:[0-9a-f]{8}|[0-9a-f]{6}|[0-9a-f]{3,4})(?![0-9a-z_-])/gi;
const HEX_FRAGMENT = /(?:#|%23)[0-9a-f]{1,7}$/i;
const WORD =/(?<![\w-])[a-z]+(?![\w-])/gi;
const MAPLIBRE_COLOUR_EXPRESSIONS = new Set("rgb rgba hsl hsla".split(" "));
// Keys whose string values are colours: style objects and props, SVG and Recharts props, MapLibre paint properties.
const COLOUR_KEY = /colou?r|fill|stroke|background|border|outline|shadow|stop/i;
const MAPLIBRE_SETTERS = new Set(["setPaintProperty", "setLayoutProperty"]);
// CSS properties whose values hold names, not colours (a "snow" animation, a "Tan" font).
const CSS_NAME_PROPERTY = /^(animation|font|grid|transition|will-change|content|counter|quotes|list-style-type)/i;
const DIRECTIVE = /^\s*(eslint-disable(?:-next-line|-line)?|eslint-enable|eslint)(?:\s+([^\n]*?))?\s*(?:--|$)/s;

// CSS named colours (CSS Color 4). They are matched only where a value is a colour, because in prose they are
// ordinary words.
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

const normalise = (value) =>
  value
    .toLowerCase()
    .replace(/^%23/, "#")
    .replace(/\s*([,/])\s*/g, "$1")
    .replace(/\(\s+/g, "(")
    .replace(/\s+\)/g, ")")
    .replace(/\s+/g, " ")
    .replace(/'/g, '"');

function colourValues(text) {
  const values = [];
  START.lastIndex = 0;
  let match;
  while ((match = START.exec(text))) {
    let end = match.index + match[0].length;
    if (match[0].endsWith("(")) {
      let depth = 1;
      while (end < text.length && depth > 0) {
        if (text[end] === "(") depth += 1;
        if (text[end] === ")") depth -= 1;
        end += 1;
      }
      START.lastIndex = end;
    }
    values.push(normalise(text.slice(match.index, end)));
  }
  return values;
}

const namedColours = (text) => (text.match(WORD) ?? []).map((w) => w.toLowerCase()).filter((w) => NAMED.has(w));

// The text of a template literal whose interpolations are all literals (`#${"ff00ff"}`), else null.
function staticTemplate(node) {
  if (!node.expressions.every((e) => e.type === "Literal")) return null;
  return node.quasis.map((q, i) => (q.value.cooked ?? q.value.raw) + (node.expressions[i]?.value ?? "")).join("");
}

function keyName(node) {
  if (!node) return null;
  if (node.type === "Identifier" || node.type === "JSXIdentifier") return node.name;
  if (node.type === "Literal" && typeof node.value === "string") return node.value;
  if (node.type === "JSXNamespacedName") return node.name.name;
  return null;
}

// The property, prop or MapLibre paint key a string value is assigned to, through arrays, conditionals and
// template literals (MapLibre expressions and `cond ? "a" : "b"`).
function colourContextKey(node) {
  let current = node;
  for (let parent = node.parent; parent; current = parent, parent = parent.parent) {
    switch (parent.type) {
      case "Property":
        return parent.value === current ? keyName(parent.key) : null;
      case "JSXAttribute":
        return keyName(parent.name);
      case "AssignmentExpression":
        return parent.right === current && parent.left.type === "MemberExpression" ? keyName(parent.left.property) : null;
      case "CallExpression": {
        const method = parent.callee.type === "MemberExpression" ? keyName(parent.callee.property) : null;
        return MAPLIBRE_SETTERS.has(method) && parent.arguments[2] === current ? keyName(parent.arguments[1]) : null;
      }
      case "ConditionalExpression":
        if (parent.test === current) return null;
        break;
      case "JSXExpressionContainer":
      case "ArrayExpression":
      case "LogicalExpression":
      case "TemplateLiteral":
      case "BinaryExpression":
      case "TSAsExpression":
      case "TSSatisfiesExpression":
        break;
      default:
        return null;
    }
  }
  return null;
}

export default {
  meta: {
    type: "problem",
    docs: { description: "Ban colours outside the tokens file, except those listed in the baseline" },
    schema: [
      {
        type: "object",
        properties: {
          tokensFile: { type: "string" },
          baseline: { type: "object" },
          namedColoursAnywhere: { type: "boolean" },
        },
        additionalProperties: false,
      },
    ],
    messages: {
      colour: "Hard-coded colour {{value}}: define it in {{tokensFile}} and use the token.",
      stale:
        "The colour baseline lists {{value}} {{expected}} time(s) for this file but it appears {{found}}: " +
        "update colour-baseline.json.",
      directive: "Inline ESLint configuration cannot switch off {{rule}}.",
    },
  },
  create(context) {
    const { tokensFile, baseline = {}, namedColoursAnywhere = false } = context.options[0] ?? {};
    const sourceCode = context.sourceCode;
    const file = path.relative(context.cwd, context.filename).split(path.sep).join("/");
    const found = [];
    const add = (target, values) => {
      for (const value of values) found.push({ ...target, value });
    };

    const checkDirectives = () => {
      const comments = sourceCode.getAllComments ? sourceCode.getAllComments() : (sourceCode.comments ?? []);
      for (const comment of comments) {
        const match = DIRECTIVE.exec(comment.value);
        if (!match) continue;
        const rules = (match[2] ?? "").trim();
        const disablesAll = match[1].startsWith("eslint-disable") && rules === "";
        if (disablesAll || /(^|[\s,/])no-hard-coded-colour(?![\w-])/.test(rules)) {
          context.report({ loc: comment.loc, messageId: "directive", data: { rule: context.id } });
        }
      }
    };

    const finish = () => {
      checkDirectives();
      const allowed = baseline[file] ?? {};
      const counts = {};
      for (const { node, loc, value } of found) {
        counts[value] = (counts[value] ?? 0) + 1;
        if (counts[value] > (allowed[value] ?? 0)) {
          context.report({ node, loc, messageId: "colour", data: { value, tokensFile } });
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

    const checkString = (node, text) => {
      add({ node }, colourValues(text));
      if (namedColoursAnywhere) {
        if (NAMED.has(text.trim().toLowerCase())) add({ node }, [text.trim().toLowerCase()]);
        return;
      }
      const key = colourContextKey(node.type === "TemplateElement" ? node.parent : node);
      if (key && COLOUR_KEY.test(key)) add({ node }, namedColours(text));
    };

    const cssText = (node) => sourceCode.text.slice(node.loc.start.offset, node.loc.end.offset);

    return {
      // JavaScript and TypeScript
      Literal(node) {
        const inStaticTemplate = node.parent.type === "TemplateLiteral" && staticTemplate(node.parent) !== null;
        if (typeof node.value === "string" && !inStaticTemplate) checkString(node, node.value);
      },
      TemplateLiteral(node) {
        const text = staticTemplate(node);
        if (text !== null) checkString(node, text);
      },
      TemplateElement(node) {
        if (staticTemplate(node.parent) !== null) return;
        const text = node.value.cooked ?? node.value.raw;
        checkString(node, text);
        // A hex colour completed by an interpolation, as in `#ff${x}`.
        const fragment = node.tail ? null : HEX_FRAGMENT.exec(text);
        if (fragment && colourValues(fragment[0]).length === 0) add({ node }, [`${normalise(fragment[0])}\${}`]);
      },
      ArrayExpression(node) {
        const [head] = node.elements;
        if (head?.type === "Literal" && MAPLIBRE_COLOUR_EXPRESSIONS.has(String(head.value).toLowerCase())) {
          add({ node }, [normalise(sourceCode.getText(node))]);
        }
      },
      "Program:exit": finish,

      // CSS (CSSTree nodes from @eslint/css): every declaration value, custom properties included, and at-rule
      // preludes such as `@apply bg-[#...]`.
      Declaration(node) {
        const text = cssText(node);
        const value = text.slice(text.indexOf(":") + 1);
        add({ loc: node.loc }, colourValues(value));
        if (!CSS_NAME_PROPERTY.test(node.property)) {
          add({ loc: node.loc }, namedColours(value.replace(/var\([^)]*\)/g, "")));
        }
      },
      Atrule(node) {
        if (node.prelude) add({ loc: node.prelude.loc }, colourValues(cssText(node.prelude)));
      },
      "StyleSheet:exit": finish,
    };
  },
};
