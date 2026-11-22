import path from "node:path";

// Every colour that is not in the tokens file must be listed in the baseline (colours that predate the tokens),
// value by value and file by file, so a new colour, a moved one or a swapped one fails, and a removed one
// must also leave the baseline.

// A colour function (matched to its balanced closing parenthesis) or a hex colour, also URL-encoded (%23) in data URIs.
const START =
  /(?<![a-z-])(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch|color-mix|color)\(|(?:#|%23)(?:[0-9a-f]{8}|[0-9a-f]{6}|[0-9a-f]{3,4})(?![0-9a-z_-])/gi;
// Stands for a dynamic interpolation in a template literal's text.
const HOLE = "\uE000";
// A hex colour whose digits come (partly) from an interpolation: `#${x}`, `#ff${x}`.
const HEX_FRAGMENT = /(?:#|%23)[0-9a-f]{0,7}\uE000/gi;
const WORD = /(?<![\w-])[a-z]+(?![\w-])/gi;
const MAPLIBRE_COLOUR_EXPRESSIONS = new Set("rgb rgba hsl hsla".split(" "));
// Keys whose string values are or contain colours: style objects and props (colour shorthands and composites such
// as border, box-shadow, text-decoration, filter: drop-shadow(), column-rule), SVG and Recharts props, MapLibre paint
// properties, CSS custom properties.
const COLOUR_KEY = /colou?r|fill|stroke|background|border|outline|shadow|stop|decoration|filter|column-?rule|^--/i;
// Keys of a legacy MapLibre function object (`{ type, property, default, stops }`): their colours belong to the
// paint key that holds the object.
const LEGACY_FUNCTION_KEYS = new Set(["default", "stops"]);
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

// The text of a template literal with literal and nested template interpolations inlined (`#${"ff00ff"}`,
// `#${`ff00ff`}`) and every other interpolation replaced by HOLE.
function templateText(node) {
  return node.quasis
    .map((quasi, i) => {
      const expression = node.expressions[i];
      let inlined = "";
      if (expression?.type === "Literal") inlined = String(expression.value);
      else if (expression?.type === "TemplateLiteral") inlined = templateText(expression);
      else if (expression) inlined = HOLE;
      return (quasi.value.cooked ?? quasi.value.raw) + inlined;
    })
    .join("");
}

function keyName(node) {
  if (!node) return null;
  if (node.type === "Identifier" || node.type === "JSXIdentifier") return node.name;
  if (node.type === "Literal" && typeof node.value === "string") return node.value;
  if (node.type === "JSXNamespacedName") return node.name.name;
  // A computed key with a cast, as in `["--accent" as string]: ...` (React's style typing needs it).
  if (node.type === "TSAsExpression" || node.type === "TSSatisfiesExpression") return keyName(node.expression);
  return null;
}

// The property, prop or MapLibre paint key a string value is assigned to, through arrays, conditionals and
// template literals (MapLibre expressions and `cond ? "a" : "b"`).
function colourContextKey(node) {
  let current = node;
  for (let parent = node.parent; parent; current = parent, parent = parent.parent) {
    switch (parent.type) {
      case "Property":
        if (parent.value !== current) return null;
        if (LEGACY_FUNCTION_KEYS.has(keyName(parent.key)) && parent.parent.type === "ObjectExpression") {
          current = parent.parent;
          parent = current;
          break;
        }
        return keyName(parent.key);
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
      add({ node }, colourValues(text).map((value) => value.replaceAll(HOLE, "${}")));
      for (const fragment of text.matchAll(HEX_FRAGMENT)) {
        const digits = fragment[0].slice(0, -1);
        if (colourValues(digits).length === 0) add({ node }, [`${normalise(digits)}\${}`]);
      }
      if (namedColoursAnywhere) {
        if (NAMED.has(text.trim().toLowerCase())) add({ node }, [text.trim().toLowerCase()]);
        return;
      }
      const key = colourContextKey(node);
      if (key && COLOUR_KEY.test(key)) add({ node }, namedColours(text));
    };

    const cssText = (node) => sourceCode.text.slice(node.loc.start.offset, node.loc.end.offset);

    return {
      // JavaScript and TypeScript
      // Literals and templates interpolated into a template are checked as part of the outer template's text.
      Literal(node) {
        if (typeof node.value === "string" && node.parent.type !== "TemplateLiteral") checkString(node, node.value);
      },
      TemplateLiteral(node) {
        if (node.parent.type !== "TemplateLiteral") checkString(node, templateText(node));
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
          // Drop custom property names (`--red`), keep var() fallbacks (`var(--x, red)`).
          add({ loc: node.loc }, namedColours(value.replace(/--[\w-]+/g, "")));
        }
      },
      Atrule(node) {
        if (node.prelude) add({ loc: node.prelude.loc }, colourValues(cssText(node.prelude)));
      },
      "StyleSheet:exit": finish,
    };
  },
};
