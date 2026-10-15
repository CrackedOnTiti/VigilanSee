import { init, classModule, propsModule, attributesModule, h } from "snabbdom";
import logo from "./assets/logo.png";
import "./style.css";

const patch = init([classModule, propsModule, attributesModule]);

const DOCS_URL = "https://crackedontiti.github.io/VigilanSee/";
const REPO_URL = "https://github.com/CrackedOnTiti/VigilanSee";

const principles = [
  ["Server-side", "No client install and no kernel access."],
  ["Behavioral", "Detects patterns in how players act, for cheating and toxic behavior alike."],
  ["Game-agnostic", "You define the fields and scoring; we analyze what you send."],
];

function externalLink(sel, href, text) {
  return h(sel, { attrs: { href, target: "_blank", rel: "noopener noreferrer" } }, text);
}

function header() {
  return h("header.site-header", [
    h("a.brand", { attrs: { href: "/" } }, [
      h("img", { attrs: { src: logo, alt: "", width: 28, height: 28 } }),
      h("span", ["Vigilan", h("strong", "See")]),
    ]),
    h("nav", { attrs: { "aria-label": "Main" } }, [
      externalLink("a", DOCS_URL, "Documentation"),
      externalLink("a", REPO_URL, "GitHub"),
    ]),
  ]);
}

function welcome() {
  return h("section.panel.welcome", [
    h("h1", "Portal"),
    h(
      "p.lead",
      "VigilanSee is a server-side behavioral analysis service that works alongside existing anti-cheat systems."
    ),
    h("p", "This portal is where you will manage your games and follow player analysis. It is in early development."),
    h("div.actions", [
      externalLink("a.button.primary", DOCS_URL, "Read the documentation"),
      externalLink("a.button", REPO_URL, "View source"),
    ]),
  ]);
}

function about() {
  return h("aside.panel.about", [
    h("h2", "How it works"),
    h(
      "dl",
      principles.flatMap(([term, desc]) => [h("dt", term), h("dd", desc)])
    ),
  ]);
}

function view() {
  return h("div#app", [
    header(),
    h("main.layout", [welcome(), about()]),
    h("footer.site-footer", "VigilanSee · No bloat. No client. No compromise."),
  ]);
}

patch(document.getElementById("app"), view());
