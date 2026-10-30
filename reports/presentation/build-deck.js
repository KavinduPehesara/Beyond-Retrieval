/**
 * Beyond Retrieval - MSE907 Assessment 3 presentation (15 minutes).
 *
 * Every number on these slides comes from the project's own run directories
 * or from the Assessment 2 report; nothing is rounded up for effect.
 */

const path = require("path");
const pptxgen = require("pptxgenjs");

const SKILL = process.env.SKILL;
const FIGS = process.env.FIGS;
const OUT = process.env.OUT;

const { applyTheme } = require(path.join(SKILL, "scripts", "apply_theme.js"));

const THEME = {
  name: "Beyond Retrieval",
  headFontFace: "Cambria",
  bodyFontFace: "Calibri",
  colors: {
    dk1: "12302F",
    lt1: "FFFFFF",
    dk2: "0E3B38",
    lt2: "EDF3F1",
    accent1: "0E6E62",
    accent2: "4FA392",
    accent3: "C0643C",
    accent4: "7D9A94",
    accent5: "2A4F4B",
    accent6: "D4A843",
    hlink: "0E6E62",
    folHlink: "7D9A94",
  },
};

// Hex duplicates, for the options that refuse a scheme colour.
const HEX = {
  grid: "DDE7E4",
  shadow: "0E3B38",
  a1: "0E6E62",
  a2: "4FA392",
  a3: "C0643C",
  a6: "D4A843",
  mute: "7D9A94",
  ink: "12302F",
};

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.3 x 7.5
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
pres.author = "Kavindu Pehesara Gunawardena";
pres.company = "Yoobee College of Creative Innovation";
pres.subject = "MSE907 Assessment 3";
pres.title = "Beyond Retrieval";

const C = pres.SchemeColor;

const FOOTER = "Beyond Retrieval  ·  MSE907 Assessment 3  ·  K. P. Gunawardena  ·  270684416";

const chartAxis = {
  catAxisLabelColor: HEX.ink,
  catAxisLabelFontSize: 11,
  catAxisLabelFontFace: "+mn-lt",
  valAxisLabelColor: HEX.mute,
  valAxisLabelFontSize: 10,
  valAxisLabelFontFace: "+mn-lt",
  valGridLine: { color: HEX.grid, size: 1 },
  catGridLine: { style: "none" },
  showLegend: false,
  dataLabelColor: HEX.ink,
  dataLabelFontSize: 11,
  dataLabelFontFace: "+mn-lt",
  dataLabelFontBold: true,
};

/* ------------------------------------------------------------------ layouts */

pres.defineSlideMaster({
  title: "TITLE_DARK",
  background: { color: C.text2 },
  objects: [
    {
      placeholder: {
        options: { name: "title", type: "title", x: 0.9, y: 2.05, w: 11.5, h: 1.5, fontSize: 46, bold: true, color: C.background1, valign: "bottom", align: "left" },
        text: "",
      },
    },
    {
      placeholder: {
        options: { name: "body", type: "body", x: 0.92, y: 3.6, w: 10.6, h: 0.9, fontSize: 19, color: C.background2, valign: "top" },
        text: "",
      },
    },
  ],
});

pres.defineSlideMaster({
  title: "SECTION_DARK",
  background: { color: C.text2 },
  objects: [
    {
      placeholder: {
        options: { name: "title", type: "title", x: 0.9, y: 0.45, w: 11.5, h: 0.85, fontSize: 34, bold: true, color: C.background1, valign: "middle", align: "left" },
        text: "",
      },
    },
  ],
  slideNumber: { x: 12.5, y: 6.92, color: HEX.mute, fontFace: "+mn-lt", fontSize: 10 },
});

pres.defineSlideMaster({
  title: "CONTENT",
  background: { color: C.background1 },
  objects: [
    {
      placeholder: {
        options: { name: "title", type: "title", x: 0.6, y: 0.42, w: 12.1, h: 0.78, fontSize: 32, bold: true, color: C.text1, valign: "middle", align: "left" },
        text: "",
      },
    },
    { text: { text: FOOTER, options: { x: 0.6, y: 6.9, w: 9.5, h: 0.3, fontSize: 9, color: C.accent4, isTextBox: true, margin: 0, valign: "middle" } } },
  ],
  slideNumber: { x: 12.5, y: 6.92, color: HEX.mute, fontFace: "+mn-lt", fontSize: 10 },
});

pres.defineSlideMaster({
  title: "CHARTSLIDE",
  background: { color: C.background1 },
  objects: [
    {
      placeholder: {
        options: { name: "title", type: "title", x: 0.6, y: 0.42, w: 12.1, h: 0.78, fontSize: 32, bold: true, color: C.text1, valign: "middle", align: "left" },
        text: "",
      },
    },
    {
      placeholder: {
        options: { name: "chart", type: "chart", x: 0.6, y: 1.4, w: 7.5, h: 4.9, color: C.text1 },
        text: "",
      },
    },
    {
      placeholder: {
        options: { name: "body", type: "body", x: 8.4, y: 1.45, w: 4.3, h: 4.8, fontSize: 14, color: C.text1, valign: "top" },
        text: "",
      },
    },
    { text: { text: FOOTER, options: { x: 0.6, y: 6.9, w: 9.5, h: 0.3, fontSize: 9, color: C.accent4, isTextBox: true, margin: 0, valign: "middle" } } },
  ],
  slideNumber: { x: 12.5, y: 6.92, color: HEX.mute, fontFace: "+mn-lt", fontSize: 10 },
});

pres.defineSlideMaster({
  title: "IMAGE",
  background: { color: C.background1 },
  objects: [
    {
      placeholder: {
        options: { name: "title", type: "title", x: 0.6, y: 0.42, w: 12.1, h: 0.78, fontSize: 32, bold: true, color: C.text1, valign: "middle", align: "left" },
        text: "",
      },
    },
    {
      placeholder: {
        options: { name: "pic", type: "pic", x: 0.6, y: 1.4, w: 7.0, h: 5.09, color: C.text1 },
        text: "",
      },
    },
    {
      placeholder: {
        options: { name: "body", type: "body", x: 8.0, y: 1.45, w: 4.7, h: 4.9, fontSize: 14, color: C.text1, valign: "top" },
        text: "",
      },
    },
    { text: { text: FOOTER, options: { x: 0.6, y: 6.9, w: 9.5, h: 0.3, fontSize: 9, color: C.accent4, isTextBox: true, margin: 0, valign: "middle" } } },
  ],
  slideNumber: { x: 12.5, y: 6.92, color: HEX.mute, fontFace: "+mn-lt", fontSize: 10 },
});

pres.defineSlideMaster({
  title: "CLOSING_DARK",
  background: { color: C.text2 },
  objects: [
    {
      placeholder: {
        options: { name: "title", type: "title", x: 0.9, y: 0.7, w: 11.5, h: 1.0, fontSize: 38, bold: true, color: C.background1, valign: "middle", align: "left" },
        text: "",
      },
    },
  ],
  slideNumber: { x: 12.5, y: 6.92, color: HEX.mute, fontFace: "+mn-lt", fontSize: 10 },
});

/* ------------------------------------------------------------------ helpers */

function fit(file, maxW, maxH) {
  // addImage takes whatever w and h it is given and stretches to fill them,
  // so a figure redrawn at a different shape is silently distorted. The
  // numbers 7.0 x 5.09 were right for the old diagram and wrong by 5% for
  // the new one, which is why the box is measured rather than assumed.
  const head = require("fs").readFileSync(file).subarray(16, 24);
  const w = head.readUInt32BE(0);
  const h = head.readUInt32BE(4);
  const scale = Math.min(maxW / w, maxH / h);
  return { w: w * scale, h: h * scale };
}

let cardSeq = 0;

function card(slide, o) {
  cardSeq += 1;
  slide.addShape(pres.ShapeType.roundRect, {
    x: o.x,
    y: o.y,
    w: o.w,
    h: o.h,
    rectRadius: 0.08,
    fill: { color: o.dark ? C.accent5 : C.background2 },
    line: { color: o.dark ? C.accent5 : C.background2, width: 0 },
    objectName: "card" + cardSeq,
  });
}

function chip(slide, o) {
  cardSeq += 1;
  slide.addShape(pres.ShapeType.roundRect, {
    x: o.x,
    y: o.y,
    w: o.w,
    h: o.h || 0.34,
    rectRadius: 0.4,
    fill: { color: o.color },
    line: { color: o.color, width: 0 },
    objectName: "chip" + cardSeq,
  });
  slide.addText(o.text, {
    x: o.x,
    y: o.y,
    w: o.w,
    h: o.h || 0.34,
    fontSize: o.fontSize || 10,
    bold: true,
    color: C.background1,
    align: "center",
    valign: "middle",
    isTextBox: true,
    margin: 0,
    charSpacing: 0.6,
  });
}

function numDot(slide, o) {
  cardSeq += 1;
  slide.addShape(pres.ShapeType.ellipse, {
    x: o.x,
    y: o.y,
    w: 0.42,
    h: 0.42,
    fill: { color: o.color || C.accent1 },
    line: { color: o.color || C.accent1, width: 0 },
    objectName: "dot" + cardSeq,
  });
  slide.addText(String(o.n), {
    x: o.x,
    y: o.y,
    w: 0.42,
    h: 0.42,
    fontSize: 14,
    bold: true,
    color: C.background1,
    align: "center",
    valign: "middle",
    isTextBox: true,
    margin: 0,
  });
}

function stat(slide, o) {
  slide.addText(o.value, {
    x: o.x,
    y: o.y,
    w: o.w,
    h: o.h || 0.72,
    fontSize: o.fontSize || 40,
    bold: true,
    color: o.color || C.accent1,
    fontFace: "Cambria",
    isTextBox: true,
    margin: 0,
    valign: "middle",
  });
  if (o.label) {
    slide.addText(o.label, {
      x: o.x,
      y: o.y + (o.h || 0.72) - 0.02,
      w: o.w,
      h: o.labelH || 0.6,
      fontSize: 11,
      color: C.accent5,
      isTextBox: true,
      margin: 0,
      valign: "top",
    });
  }
}

function body(slide, text, o) {
  slide.addText(text, Object.assign({ fontSize: 13, color: C.text1, isTextBox: true, margin: 0, valign: "top", lineSpacingMultiple: 1.05 }, o));
}

function heading(slide, text, o) {
  slide.addText(text, Object.assign({ fontSize: 16, bold: true, color: C.accent5, fontFace: "Cambria", isTextBox: true, margin: 0, valign: "middle" }, o));
}

/* ======================================================= 1. title */

pres.addSection({ title: "Opening" });

let s = pres.addSlide({ masterName: "TITLE_DARK", sectionTitle: "Opening" });
s.addText("Beyond Retrieval", { placeholder: "title" });
s.addText("An LLM-supported tool for literature discovery and research gap suggestion", { placeholder: "body" });
s.addText(
  [
    { text: "Kavindu Pehesara Gunawardena  ·  270684416", options: { breakLine: true, bold: true } },
    { text: "MSE907 Industry-based Capstone Research Project  ·  Assessment 3", options: { breakLine: true } },
    { text: "Supervisor: Dr Helena Bahrami  ·  30 October 2026", options: { breakLine: true } },
    { text: "github.com/KavinduPehesara/Beyond-Retrieval", options: {} },
  ],
  { x: 0.92, y: 4.75, w: 7.6, h: 1.5, fontSize: 13, color: C.background2, isTextBox: true, margin: 0, lineSpacingMultiple: 1.25 }
);
s.addText("12,598 records  ·  6 systematic reviews  ·  101 run directories  ·  572 tests", {
  x: 0.92, y: 6.3, w: 11.5, h: 0.4, fontSize: 13, italic: true, color: C.accent6, isTextBox: true, margin: 0,
});
s.addNotes(
  "[0:00 — 0:28]\n\n" +
  "Good afternoon. I'm Kavindu Gunawardena, and this is Beyond Retrieval. It answers a research question with a ranked, screened set of papers, and it tells you whether other authors have already written that question down as an open gap.\n\n" +
  "Everything here was measured: twelve and a half thousand records, six reviews, a hundred and one stored runs. Every number on these slides has a directory behind it."
);

/* ======================================================= 2. two burdens */

pres.addSection({ title: "Literature and gaps" });

s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Literature and gaps" });
s.addText("Two burdens — and only one is being worked on", { placeholder: "title" });

card(s, { x: 0.6, y: 1.4, w: 5.9, h: 4.1 });
numDot(s, { x: 0.95, y: 1.78, n: 1 });
heading(s, "Screening", { x: 1.52, y: 1.78, w: 4.6, h: 0.42 });
body(s, "A review starts with thousands of candidates and ends with dozens. Every title and abstract is read by a person.", { x: 0.95, y: 2.45, w: 5.2, h: 0.95 });
stat(s, { x: 0.95, y: 3.72, w: 5.2, value: "2.8%", label: "of 12,598 records were eligible — 351 papers, across the six reviews in this corpus" });

card(s, { x: 6.8, y: 1.4, w: 5.9, h: 4.1 });
numDot(s, { x: 7.15, y: 1.78, n: 2, color: C.accent3 });
heading(s, "Absence", { x: 7.72, y: 1.78, w: 4.6, h: 0.42 });
body(s, "What nobody has studied yet. Reading faster cannot answer it — the answer is in none of the papers you are reading.", { x: 7.15, y: 2.45, w: 5.2, h: 0.95 });
stat(s, { x: 7.15, y: 3.72, w: 5.2, value: "0 of 34", color: C.accent3, label: "review-tool features that address absence, across 21 tools surveyed by Bolaños et al. (2024)" });

body(s, "Automated screening has reported 95–100% recall since Cohen et al. (2006). Three recent papers say that number does not travel between corpora.", {
  x: 0.6, y: 5.85, w: 12.1, h: 0.75, fontSize: 15, italic: true, color: C.accent5,
});

s.addNotes(
  "[0:28 — 1:15]\n\n" +
  "The problem has two halves. Screening: a review starts with thousands of candidates and ends with dozens. Here, twelve and a half thousand records yielded three hundred and fifty-one eligible papers, and a human read every abstract.\n\n" +
  "The second burden is absence — the question nobody has answered. You cannot read your way to it, because the answer is in none of the papers in front of you. Bolaños surveyed twenty-one review tools against thirty-four features. Not one addressed absence.\n\n" +
  "And the screening half is less settled than it looks. Three recent papers say the published recall figures do not travel between corpora. So I tested all three."
);

/* ======================================================= 3. claims tested */

s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Literature and gaps" });
s.addText("Three published claims, tested against my own runs", { placeholder: "title" });

const claims = [
  {
    y: 1.4,
    verdict: "REPRODUCED",
    vcolor: C.accent1,
    claim: [
      { text: "Hida et al. (2026)\n", options: { bold: true } },
      { text: "LLM screening decisions vary run to run; inter-run Gwet AC2 between 0.55 and 1.0, best at temperature zero." },
    ],
    found: [
      { text: "Five cache-bypassed repeats on Nelson_2002: inter-run AC1 = ", options: {} },
      { text: "1.0", options: { bold: true, color: C.accent1 } },
      { text: " over 186 commonly verified records, verification rate steady at 50.5–50.8%. Their finding is not one vendor's inference stack.", options: {} },
    ],
  },
  {
    y: 3.0,
    verdict: "DID NOT HOLD",
    vcolor: C.accent3,
    claim: [
      { text: "Khraisha et al. (2024)\n", options: { bold: true } },
      { text: "GPT-4 sensitivity 0.42 on balanced data; accuracy should be best where prevalence is high." },
    ],
    found: [
      { text: "Across 0.8%–21.9% prevalence the unstable quantity is not accuracy, it is ", options: {} },
      { text: "verification rate: 35.6% to 94.8%", options: { bold: true, color: C.accent1 } },
      { text: " — and it does not track prevalence. Smid (1.0%) verifies at 91.7%; van der Valk (12.3%) at 39.3%.", options: {} },
    ],
  },
  {
    y: 4.6,
    verdict: "CONFIRMED",
    vcolor: C.accent1,
    claim: [
      { text: "Kusa et al. (2023)\n", options: { bold: true } },
      { text: "Effort-saving metrics are not comparable across reviews of differing prevalence." },
    ],
    found: [
      { text: "One unchanged BM25 baseline scores TNR@95 of ", options: {} },
      { text: "0.520 on Smid and 0.038 on Nelson", options: { bold: true, color: C.accent1 } },
      { text: " — a fourteen-fold spread from the corpus alone. So nothing in this project is ever pooled.", options: {} },
    ],
  },
];

claims.forEach((c) => {
  card(s, { x: 0.6, y: c.y, w: 12.1, h: 1.45 });
  chip(s, { x: 0.88, y: c.y + 0.24, w: 1.72, h: 0.32, color: c.vcolor, text: c.verdict, fontSize: 9 });
  body(s, c.claim, { x: 0.88, y: c.y + 0.7, w: 4.3, h: 0.65, fontSize: 12, color: C.accent5 });
  body(s, c.found, { x: 5.5, y: c.y + 0.22, w: 6.9, h: 1.05, fontSize: 13 });
});

s.addText("A claim is only reported here when a run directory on disk supports it.", {
  x: 0.6, y: 6.2, w: 12.1, h: 0.35, fontSize: 12, italic: true, color: C.accent4, isTextBox: true, margin: 0,
});

s.addNotes(
  "[1:15 — 2:12]\n\n" +
  "So this is my literature review, done as a test rather than a summary.\n\n" +
  "Hida reports that the same model changes its mind between runs. I reproduced it: five repeats with the cache off agreed perfectly, at temperature zero. Not one vendor's quirk.\n\n" +
  "Khraisha predicted accuracy would be best where prevalence is high. In my six reviews it was not. The quantity that moves is the verification rate — thirty-six to ninety-five per cent — and it does not follow prevalence. An accuracy figure published without a verification rate has a denominator that moves without telling you.\n\n" +
  "And Kusa's warning is confirmed outright. One unchanged BM25 baseline scores point five two on one review and point zero three eight on another — fourteen-fold, from the corpus alone. That is why nothing here is ever pooled."
);

/* ======================================================= 4. three gaps */

s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Literature and gaps" });
s.addText("Three gaps, and what happened to each", { placeholder: "title" });

const gaps = [
  {
    x: 0.6,
    n: 1,
    title: "Capability is demonstrated;\nopen, evaluated systems are not",
    status: "ADDRESSED",
    scolor: C.accent1,
    value: "101",
    label: "run directories, each carrying its configuration, metrics and commit hash",
    text: "Open licence, public repository, one interface over two commercial providers and a local model.",
  },
  {
    x: 4.78,
    n: 2,
    title: "Cost and reproducibility\nare uncharacterised",
    status: "MEASURED",
    scolor: C.accent1,
    value: "USD 0.13",
    label: "the entire two-vendor comparison; byte-identical metrics on repeat runs",
    text: "Reported as two properties: what a run costs, and whether a stored configuration reproduces it exactly.",
  },
  {
    x: 8.96,
    n: 3,
    title: "Absence is left\nunaddressed",
    status: "MEASURED, WITH A CAVEAT",
    scolor: C.accent3,
    value: "87.8%",
    label: "precision over 74 rated statements; recall 0.40–1.00 — precise, but it misses",
    text: "The tool suggests gaps the authors state themselves, and both halves of the score are reported.",
  },
];

gaps.forEach((g) => {
  card(s, { x: g.x, y: 1.4, w: 3.74, h: 4.55 });
  numDot(s, { x: g.x + 0.3, y: 1.68, n: g.n, color: g.scolor });
  body(s, g.title, { x: g.x + 0.3, y: 2.22, w: 3.14, h: 0.9, fontSize: 15, bold: true, color: C.accent5, fontFace: "Cambria" });
  chip(s, { x: g.x + 0.3, y: 3.2, w: g.n === 3 ? 2.95 : 1.65, h: 0.3, color: g.scolor, text: g.status, fontSize: 8 });
  body(s, g.text, { x: g.x + 0.3, y: 3.65, w: 3.14, h: 0.95, fontSize: 12 });
  stat(s, { x: g.x + 0.3, y: 4.62, w: 3.14, value: g.value, fontSize: 30, h: 0.55, label: g.label });
});

s.addNotes(
  "[2:12 — 3:01]\n\n" +
  "Assessment One named three gaps. Here is what happened to each.\n\n" +
  "One: the field demonstrates capability but ships no open systems anyone can evaluate. Addressed — open licence, public repository, and every figure traced to one of a hundred and one run directories.\n\n" +
  "Two: cost and reproducibility are uncharacterised. Measured — thirteen cents for the whole comparison, and byte-identical metrics on repeat runs.\n\n" +
  "Three: absence is unaddressed. Measured, with a caveat. Precision is eighty-eight per cent over seventy-four rated statements; recall is between point four and one. It is precise, and it misses. I report both halves, because reporting only the precision is the kind of claim this project exists to argue against."
);


/* ======================================================= 5. built + questions */

pres.addSection({ title: "The system" });

s = pres.addSlide({ masterName: "IMAGE", sectionTitle: "The system" });
s.addText("What was built, and what it has to answer", { placeholder: "title" });
s.addImage(Object.assign({ placeholder: "pic", path: path.join(FIGS, "fig1.png") }, fit(path.join(FIGS, "fig1.png"), 7.0, 5.09)));

card(s, { x: 8.0, y: 1.4, w: 4.7, h: 2.95 });
chip(s, { x: 8.3, y: 1.66, w: 0.95, h: 0.3, color: C.accent1, text: "RQ1", fontSize: 10 });
body(s, "Can an LLM-supported review tool produce screening decisions a researcher can independently verify and rely on?", {
  x: 8.3, y: 2.04, w: 4.1, h: 0.8, fontSize: 13, bold: true, color: C.accent5, fontFace: "Cambria",
});
body(s, [
  { text: "Verifiable", options: { bold: true, color: C.accent1 } },
  { text: " — quote found verbatim, or withheld", options: { breakLine: true } },
  { text: "Accurate", options: { bold: true, color: C.accent1 } },
  { text: " — scored per review, never pooled", options: { breakLine: true } },
  { text: "Reproducible", options: { bold: true, color: C.accent1 } },
  { text: " — inter-run AC1 = 1.0", options: { breakLine: true } },
  { text: "Overridable", options: { bold: true, color: C.accent1 } },
  { text: " — overrides kept as labelled data", options: {} },
], { x: 8.3, y: 2.92, w: 4.1, h: 1.2, fontSize: 11, lineSpacingMultiple: 1.22 });

card(s, { x: 8.0, y: 4.55, w: 4.7, h: 1.94 });
chip(s, { x: 8.3, y: 4.8, w: 0.95, h: 0.3, color: C.accent3, text: "RQ2", fontSize: 10 });
body(s, "How much effort and cost does it remove at a fixed level of recall — and can it suggest the gaps authors state themselves?", {
  x: 8.3, y: 5.18, w: 4.1, h: 0.8, fontSize: 13, bold: true, color: C.accent5, fontFace: "Cambria",
});
body(s, "A missed paper costs far more than a false positive, so effort saved is only reported at 95% recall.", {
  x: 8.3, y: 5.98, w: 4.1, h: 0.45, fontSize: 11, italic: true, color: C.accent5,
});

s.addNotes(
  "[3:01 — 4:17]\n\n" +
  "This is the system as delivered, not as planned. Four layers: one page, an API, the domain logic in services, one adapter per external dependency.\n\n" +
  "The two boxes at the bottom are the point. The product imports nothing from the evaluation code. My supervisor asked what the six benchmark reviews were for in the product, and the honest answer was nothing: they are the test harness. So I rebuilt the interface as one page, and that separation is now enforced by tests. And everything funnels through the shaded box: the span verifier.\n\n" +
  "It has to answer two questions. The first is about trust, and I refuse to treat trust as an attitude you survey people about. It is four properties enforced in code, each carrying a number: verifiable, accurate, reproducible, overridable.\n\n" +
  "The second is practical — how much work this removes, at what cost, and whether it can find the gaps authors state themselves. A missed paper costs a reviewer far more than a false positive, so effort saved is only ever reported at ninety-five per cent recall.\n\n" +
  "[Only if asked — the counts on this diagram are read off the repository when it is drawn, so they cannot drift from what is actually there. Three of them had, before I made them count.]"
);

/* ======================================================= 6. SE principles */

s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "The system" });
s.addText("Software engineering principles, enforced in code", { placeholder: "title" });

const principles = [
  {
    x: 0.6, y: 1.4, w: 3.95, h: 2.25,
    head: "Separation of concerns",
    text: "The interface was rebuilt from six panels to one page in week 13. No service was modified. No measured figure moved.",
  },
  {
    x: 4.77, y: 1.4, w: 3.95, h: 2.25,
    head: "Interface segregation and DI",
    text: "One provider protocol behind Mock, ChatGPT, Gemini and Ollama. Services receive a provider; they never construct one.",
  },
  {
    x: 8.94, y: 1.4, w: 3.76, h: 2.25,
    head: "Fail fast, and name the failure",
    text: "The budget ceiling aborts a run rather than warning. A cached response whose fingerprint differs raises instead of serving stale data.",
  },
  {
    x: 0.6, y: 3.82, w: 6.06, h: 2.3,
    head: "Tests as executable design decisions",
    text: "572 tests. Some guard behaviour; a subset guards commitments — that ground truth can never reach a prompt, that ad-hoc records cannot enter the evaluation corpus, that three models screening one record produce three distinct cache entries. The mock provider lies 20% of the time on purpose, so the verification-failure path is exercised on every run.",
  },
  {
    x: 6.88, y: 3.82, w: 5.82, h: 2.3,
    head: "Reproducibility as an engineering property",
    text: "The metrics file is a pure function of configuration and corpus. Timestamps and commit hashes live in a separate run record, so two runs of one configuration produce byte-identical metrics — which makes reproducibility a thing you can test, not a thing you claim.",
  },
];

principles.forEach((p, i) => {
  card(s, { x: p.x, y: p.y, w: p.w, h: p.h });
  numDot(s, { x: p.x + 0.28, y: p.y + 0.26, n: i + 1 });
  body(s, p.head, { x: p.x + 0.85, y: p.y + 0.26, w: p.w - 1.15, h: 0.45, fontSize: 15, bold: true, color: C.accent5, fontFace: "Cambria", valign: "middle" });
  body(s, p.text, { x: p.x + 0.28, y: p.y + 0.85, w: p.w - 0.56, h: p.h - 1.1, fontSize: 12.5 });
});

s.addNotes(
  "[4:17 — 5:15]\n\n" +
  "Which principles earned their place.\n\n" +
  "Separation of concerns. The proof is not the diagram — it is that I replaced six panels with one page, modified no service, and no measured figure moved.\n\n" +
  "Interface segregation: one provider protocol, four implementations — which is why adding a third vendor was a single class.\n\n" +
  "Fail fast. The budget ceiling aborts a run rather than warning me afterwards; a stale cache entry raises rather than serving.\n\n" +
  "Tests as design decisions: five hundred and seventy-two. A subset tests commitments — that ground truth can never reach a prompt — and the mock provider lies twenty per cent of the time on purpose, so the failure path runs on every pass.\n\n" +
  "And reproducibility: the metrics file is a pure function of configuration and corpus, which makes it testable rather than claimed."
);

/* ======================================================= 8. demo */

pres.addSection({ title: "Demonstration" });

s = pres.addSlide({ masterName: "SECTION_DARK", sectionTitle: "Demonstration" });
s.addText("The tool, end to end", { placeholder: "title" });

s.addShape(pres.ShapeType.roundRect, {
  x: 2.38, y: 1.5, w: 8.55, h: 4.81, rectRadius: 0.05,
  fill: { color: C.accent5 }, line: { color: C.accent2, width: 1.5, dashType: "dash" },
  objectName: "videoFrame",
});
s.addText("Demo recording goes here", {
  x: 2.38, y: 3.55, w: 8.55, h: 0.5, fontSize: 18, bold: true, color: C.accent2, align: "center", isTextBox: true, margin: 0,
});
s.addText("Insert > Video > This Device, then set it to start automatically and play full screen", {
  x: 2.38, y: 4.05, w: 8.55, h: 0.4, fontSize: 12, italic: true, color: C.accent4, align: "center", isTextBox: true, margin: 0,
});
s.addText("Question in  →  gap signal  →  ranked and screened papers, each with its quote  →  full text of the papers you choose  →  export", {
  x: 1.0, y: 6.45, w: 11.3, h: 0.4, fontSize: 13, color: C.background2, align: "center", isTextBox: true, margin: 0,
});

s.addNotes(
  "[5:15 — 7:19]  DEMO VIDEO, 1:45. Say the lead-in, start the video, stay quiet, then say the closing line.\n\n" +
  "LEAD-IN: \"Rather than describe the tool, let me show you two minutes of it.\"\n\n" +
  "CLOSING LINE: \"All of that runs over ChatGPT or Gemini — your choice at the top of the page — and the tool tells you what a run will cost before it starts.\"\n\n" +
  "--- Recording shot list (record to these beats, 1:45 total) ---\n\n" +
  "Beat 1 (0:00-0:20) — Type a plain research question. The system turns it into the inclusion rule the screening prompt will use, and shows that rule before it runs.\n\n" +
  "Beat 2 (0:20-0:55) — Ranked papers come back, each card carrying the sentence the judgement rests on. A paper whose quote could not be found verbatim is shown as a referral, not a decision. Each card also says whether the full text can be read, and where.\n\n" +
  "Beat 3 (0:55-1:20) — The gap signal: where authors state a gap in their own abstract, their words are quoted back.\n\n" +
  "Beat 4 (1:20-1:45) — Choose papers to read in full. Structured full text from Europe PMC, gaps quoted from the body and placed in their section, categorised fields and the publisher's own tables.\n\n" +
  "Beat 5 (1:45-2:00) — Export: summary, structured data, CSV tables and figures in one archive.\n\n" +
  "Before recording: close the .env file, the terminal and the editor; sign in beforehand so no credentials appear on screen."
);

/* ======================================================= 9. screening results */

pres.addSection({ title: "Results" });

s = pres.addSlide({ masterName: "CHARTSLIDE", sectionTitle: "Results" });
s.addText("Screening, per review — never pooled", { placeholder: "title" });

s.addChart(
  pres.ChartType.bar,
  [
    {
      name: "Verification rate",
      labels: ["Radjenović\n0.8%", "Smid\n1.0%", "van der Waal\n1.7%", "Menon\n7.6%", "van der Valk\n12.3%", "Nelson\n21.9%"],
      values: [35.6, 91.7, 39.3, 94.8, 39.3, 51.9],
    },
  ],
  Object.assign({}, chartAxis, {
    placeholder: "chart",
    barDir: "col",
    chartColors: [HEX.a1],
    showTitle: true,
    title: "Decisions the span verifier could substantiate (%)",
    titleColor: HEX.ink,
    titleFontSize: 13,
    titleFontFace: "+mn-lt",
    showValue: true,
    dataLabelPosition: "outEnd",
    dataLabelFormatCode: '0.0"%"',
    valAxisMaxVal: 100,
    valAxisMajorUnit: 25,
    barGapWidthPct: 55,
  })
);

s.addText(
  [
    { text: "The column nobody publishes\n", options: { bold: true, fontSize: 15, color: C.accent1, fontFace: "Cambria", breakLine: true } },
    { text: "A decision whose quote cannot be found is not a wrong prediction. It is a referral, and it is scored separately.\n\n", options: { breakLine: true } },
    { text: "Reviews are ordered by prevalence, left to right. The verification rate does not follow it.\n\n", options: { breakLine: true } },
    { text: "Where recall was computed: 0.925 on Radjenović, 0.906 on Nelson, 0.320 on van der Valk — which rises to 0.809 once withheld referrals are counted as the human would read them.\n\n", options: { breakLine: true } },
    { text: "Six reviews, 12,598 records, USD 0.00 for this arm.", options: { italic: true, color: C.accent5 } },
  ],
  { placeholder: "body", fontSize: 12.5 }
);

s.addNotes(
  "[7:19 — 8:12]\n\n" +
  "Here is the screening result, and why it is not one number.\n\n" +
  "The bars are the verification rate — the share of decisions whose supporting quote was actually found, word for word, in the record. The reviews are ordered by prevalence, and the rate plainly does not follow it.\n\n" +
  "This is the column almost nobody reports, and I think it is the most important one, because a decision whose quote cannot be found is not a wrong prediction. It is a referral back to the human.\n\n" +
  "Recall, where computed, is above point nine on two reviews and point three two on a third — which rises to point eight one once withheld referrals are counted the way a reviewer would actually read them."
);

/* ======================================================= 10. verifier */

s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Results" });
s.addText("What the verifier buys, and why it fails", { placeholder: "title" });

card(s, { x: 0.6, y: 1.4, w: 5.95, h: 2.15 });
heading(s, "Turn the verifier off and recall rises", { x: 0.9, y: 1.62, w: 5.4, h: 0.4, fontSize: 15 });
body(s, [
  { text: "An exact replay of all 12,598 decisions without the gate: recall ", options: {} },
  { text: "+0.027 to +0.697", options: { bold: true, color: C.accent1 } },
  { text: " on every review. The price is volume — one review goes from ", options: {} },
  { text: "13 records to 451", options: { bold: true, color: C.accent3 } },
  { text: ", another from ", options: {} },
  { text: "141 to 3,953", options: { bold: true, color: C.accent3 } },
  { text: ". That is a trade, not a win, and I report it as one.", options: {} },
], { x: 0.9, y: 2.12, w: 5.4, h: 1.25, fontSize: 13 });

card(s, { x: 0.6, y: 3.75, w: 5.95, h: 2.35 });
heading(s, "It almost never invents a quote", { x: 0.9, y: 3.97, w: 5.4, h: 0.4, fontSize: 15 });
stat(s, { x: 0.9, y: 4.45, w: 2.5, value: "12", fontSize: 44, h: 0.72, label: "genuine fabrications in 5,909 failed attempts — 0.2%" });
stat(s, { x: 3.6, y: 4.45, w: 2.7, value: "97.8%", fontSize: 44, h: 0.72, color: C.accent3, label: "echoed the eligibility criteria back out of the prompt" });

s.addChart(
  pres.ChartType.bar,
  [
    {
      name: "Failures",
      labels: ["Echoed the criteria", "Stitched sentences", "Near paraphrase", "Fabricated", "Other"],
      values: [5778, 57, 53, 12, 9],
    },
  ],
  Object.assign({}, chartAxis, {
    x: 6.85, y: 1.4, w: 5.85, h: 4.7,
    barDir: "bar",
    chartColors: [HEX.a3],
    showTitle: true,
    title: "Why 5,909 verification attempts failed",
    titleColor: HEX.ink,
    titleFontSize: 13,
    titleFontFace: "+mn-lt",
    showValue: true,
    dataLabelPosition: "outEnd",
    dataLabelFormatCode: "#,##0",
    barGapWidthPct: 50,
    catAxisLabelFontSize: 12,
  })
);

s.addNotes(
  "[8:12 — 9:03]\n\n" +
  "Two results about the verifier, and the first is uncomfortable.\n\n" +
  "I replayed all twelve and a half thousand decisions with the gate switched off. Recall goes up on every single review — so the verifier costs me recall. What it buys is volume: thirteen records to read instead of four hundred and fifty-one. That is a trade, and I present it as one.\n\n" +
  "The second result changed how I describe this project. Of five thousand nine hundred verification failures, twelve were genuine fabrications. Ninety-eight per cent were the model echoing my own eligibility criteria back at me.\n\n" +
  "That is not a deceptive model — it is a measure of my prompt quality, which is far more useful to know."
);

/* ======================================================= 11. two AIs */

s = pres.addSlide({ masterName: "CHARTSLIDE", sectionTitle: "Results" });
s.addText("Three models, the same 418 records", { placeholder: "title" });

s.addChart(
  pres.ChartType.bar,
  [
    {
      name: "Gap statements flagged",
      labels: ["qwen2.5:7b\nlocal · USD 0.00", "Gemini\nUSD 0.112", "ChatGPT\nUSD 0.020"],
      values: [74, 125, 90],
    },
  ],
  Object.assign({}, chartAxis, {
    placeholder: "chart",
    barDir: "col",
    chartColors: [HEX.a1],
    showTitle: true,
    title: "Gap statements flagged in the same 418 abstracts",
    titleColor: HEX.ink,
    titleFontSize: 13,
    titleFontFace: "+mn-lt",
    showValue: true,
    dataLabelPosition: "outEnd",
    valAxisMaxVal: 150,
    valAxisMajorUnit: 50,
    barGapWidthPct: 80,
    catAxisLabelFontSize: 12,
  })
);

s.addText(
  [
    { text: "Agreement, per review: AC1 0.578 to 0.924\n", options: { bold: true, fontSize: 15, color: C.accent1, fontFace: "Cambria", breakLine: true } },
    { text: "Same spread, same cause as the BM25 result. Pooled into one figure it would be dominated by the easiest review — so it is not pooled.\n\n", options: { breakLine: true } },
    { text: "Same records, same prompt, same gate — and Gemini flags 69% more than the local model.\n\n", options: { breakLine: true } },
    { text: "Combining them: ", options: {} },
    { text: "both = 54", options: { bold: true } },
    { text: " (higher precision), ", options: {} },
    { text: "either = 145", options: { bold: true } },
    { text: " (nearly double the yield of one model alone). Which to prefer is a question only hand-rating can settle.\n\n", options: { breakLine: true } },
    { text: "Agreement measures consistency, not correctness. Two models can agree and both be wrong, and these share web-scale training data.", options: { italic: true, color: C.accent3 } },
  ],
  { placeholder: "body", fontSize: 12.5 }
);

s.addNotes(
  "[9:03 — 9:58]\n\n" +
  "This is the result my Assessment Two report had to call designed but unexecuted. It ran this week.\n\n" +
  "The same four hundred and eighteen records, the same prompt, the same gate, three models. The local model flags seventy-four. Gemini flags a hundred and twenty-five — sixty-nine per cent more. ChatGPT flags ninety, for two cents.\n\n" +
  "Agreement runs from point five eight to point nine two across the reviews — the same shape as the BM25 finding. Pooled, it would be dominated by whichever review was easiest. So it is not pooled.\n\n" +
  "The union of all three gives a hundred and forty-five instead of seventy-four. Tempting, since recall is my weakness — but I will not claim it is better until somebody hand-rates it. Agreement measures consistency, not correctness."
);

/* ======================================================= 12. ethics & legal */

pres.addSection({ title: "Ethics and culture" });

s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Ethics and culture" });
s.addText("Ethical and legal ground", { placeholder: "title" });

const eth = [
  {
    x: 0.6, y: 1.4,
    head: "Collect as little as the job needs",
    text: "Google OpenID Connect, identity scope only. No password or third-party token is ever stored — just the stable subject id, verified email and display name. Sessions are stateless hashes that expire in 24 hours. A test asserts one account cannot read another's projects.",
  },
  {
    x: 6.75, y: 1.4,
    head: "A residual risk I name rather than hide",
    text: "The one-time sign-in ticket travels as a URL parameter. It is single-use, expires in 120 seconds and is bound to the originating browser — but it still lands in browser history. That is recorded as a residual risk, not written up as solved.",
  },
  {
    x: 0.6, y: 3.78,
    head: "Licensing, checked before use",
    text: "OpenAlex is CC0 and free to display. Europe PMC is queried only for its open-access subset. SYNERGY abstracts are not redistributable, so the data directory and raw model responses are never committed, and only opening sentences are quoted in the report.",
  },
  {
    x: 6.75, y: 3.78,
    head: "Ethics approval: an open risk, stated as one",
    text: "The usability study approval was planned for week 7 and has not been submitted. It blocks one thing — the exit test where a second person completes a query unassisted. It affects no measured result, because those are scored against a published benchmark, not against people.",
  },
];

eth.forEach((e, i) => {
  card(s, { x: e.x, y: e.y, w: 5.95, h: 2.25 });
  numDot(s, { x: e.x + 0.3, y: e.y + 0.26, n: i + 1, color: i === 3 ? C.accent3 : C.accent1 });
  body(s, e.head, { x: e.x + 0.87, y: e.y + 0.26, w: 4.8, h: 0.45, fontSize: 15, bold: true, color: C.accent5, fontFace: "Cambria", valign: "middle" });
  body(s, e.text, { x: e.x + 0.3, y: e.y + 0.85, w: 5.35, h: 1.25, fontSize: 12.5 });
});

s.addNotes(
  "[9:58 — 10:57]\n\n" +
  "Ethics is the part of this project I found hardest to be honest about. Four things.\n\n" +
  "Data minimisation: sign-in is identity scope only. No password or token is stored, and a test asserts that one account cannot read another's projects.\n\n" +
  "A residual risk I name rather than hide: the one-time sign-in ticket travels as a URL parameter. Single use and browser-bound — but it still lands in browser history.\n\n" +
  "Licensing was checked before use, and the details are on the slide.\n\n" +
  "And the one I would rather not have on a slide. The ethics application for the usability study was planned for week seven and has not been submitted. It is a live risk. It blocks the exit test with a second person, and no measured result — those are scored against a published benchmark, not against people."
);

/* ======================================================= 13. automation bias */

s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Ethics and culture" });
s.addText("Automation bias, and why a decision is withheld", { placeholder: "title" });

card(s, { x: 0.6, y: 1.4, w: 7.55, h: 2.55 });
heading(s, "Model confidence, across 23,148 decisions", { x: 0.95, y: 1.62, w: 6.9, h: 0.4, fontSize: 15 });
stat(s, { x: 0.95, y: 2.15, w: 3.3, value: "0.813", fontSize: 52, h: 0.85, label: "mean confidence when the quote WAS found in the source" });
stat(s, { x: 4.6, y: 2.15, w: 3.3, value: "0.798", fontSize: 52, h: 0.85, color: C.accent3, label: "mean confidence when the quote was NOT found" });

card(s, { x: 8.4, y: 1.4, w: 4.3, h: 2.55 });
body(s, "Fifteen thousandths apart.\n\nThe model is not less confident when it cannot substantiate itself. There is no threshold that separates the two cases — so a confidence score would be worse than useless here. It would look like a safeguard.", {
  x: 8.7, y: 1.7, w: 3.7, h: 1.95, fontSize: 13.5,
});

card(s, { x: 0.6, y: 4.15, w: 12.1, h: 1.95 });
heading(s, "So the design does the opposite of scoring", { x: 0.95, y: 4.38, w: 6.0, h: 0.4, fontSize: 15 });
body(s, "No confidence number is ever shown. A decision that cannot be substantiated is withheld and referred to the human, in their own queue, labelled as a referral rather than a prediction.", {
  x: 0.95, y: 4.92, w: 6.9, h: 1.0, fontSize: 13,
});
stat(s, { x: 8.4, y: 4.45, w: 1.9, value: "69.2%", fontSize: 30, h: 0.5, label: "of 13 dispositions were human overrides" });
stat(s, { x: 10.6, y: 4.45, w: 2.1, value: "13 / 13", fontSize: 30, h: 0.5, label: "of those overrides matched the recorded ground truth" });

s.addNotes(
  "[10:57 — 11:50]\n\n" +
  "This is the measurement I would keep if I could keep only one.\n\n" +
  "Automation bias is the risk that a researcher stops checking because the tool sounds sure. So I measured how sure it sounds. Across twenty-three thousand decisions, mean confidence when the quote was genuinely found was point eight one three. When no quote could be found at all, point seven nine eight.\n\n" +
  "Fifteen thousandths apart. No threshold separates them. So a confidence score here would not be a safeguard — it would look like one, which is worse.\n\n" +
  "The design does the opposite: no confidence number is ever shown, and a decision that cannot be substantiated is withheld and referred. Of thirteen dispositions, nine were human overrides — all thirteen matching ground truth."
);



/* ======================================================= 13. bias and culture */

s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Ethics and culture" });
s.addText("Bias and culture — one measured, one in the data", { placeholder: "title" });

const biases = [
  {
    y: 1.4, h: 1.5, head: "DISCIPLINARY", color: C.accent3, value: "7.6%",
    text: "Four extraction fields come from clinical trial reporting. In the software engineering review, sample size verified on 7.6% of records and study design on 36%.",
  },
  {
    y: 3.02, h: 1.5, head: "LANGUAGE", color: C.accent4, value: "EN",
    text: "The search path, the corpus and the prompts are English-only. Recorded as a limitation of the evaluation, not described as a design choice.",
  },
  {
    y: 4.64, h: 1.45, head: "SOURCE COVERAGE", color: C.accent4, value: "≈ half",
    text: "OpenAlex under-covers Chinese scholarship (Zheng et al., 2025). Only about half of indexed papers have a redistributable abstract — and the pipeline reads abstracts.",
  },
];

biases.forEach((b) => {
  card(s, { x: 0.6, y: b.y, w: 5.6, h: b.h });
  chip(s, { x: 0.9, y: b.y + 0.2, w: 2.0, h: 0.3, color: b.color, text: b.head, fontSize: 9 });
  s.addText(b.value, {
    x: 3.3, y: b.y + 0.13, w: 2.0, h: 0.44, fontSize: 22, bold: true, color: C.accent1,
    fontFace: "Cambria", align: "right", isTextBox: true, margin: 0, valign: "middle",
  });
  body(s, b.text, { x: 0.9, y: b.y + 0.64, w: 5.0, h: 0.75, fontSize: 11 });
});

s.addChart(
  pres.ChartType.bar,
  [
    {
      name: "Gap-statement rate",
      labels: ["Radjenović\nsoftware", "Smid\nCS / stats", "Nelson\nmedicine", "van der Waal\nmedicine", "van der Valk\nmed / psych", "Menon\nmedicine"],
      values: [3.8, 10.0, 10.5, 20.7, 27.3, 52.2],
    },
  ],
  Object.assign({}, chartAxis, {
    x: 6.5, y: 1.4, w: 6.2, h: 3.5,
    barDir: "col",
    chartColors: [HEX.a2],
    showTitle: true,
    title: "Abstracts whose authors state a gap (%)",
    titleColor: HEX.ink,
    titleFontSize: 13,
    titleFontFace: "+mn-lt",
    showValue: true,
    dataLabelPosition: "outEnd",
    dataLabelFormatCode: '0.0"%"',
    dataLabelFontSize: 10,
    valAxisMaxVal: 60,
    valAxisMajorUnit: 20,
    barGapWidthPct: 55,
    catAxisLabelFontSize: 9,
  })
);

body(s, [
  { text: "Authors state a gap in under 4% of software engineering abstracts and 52% in one medical review. That is a house style, not a finding — and a tool reporting “no gaps found” on an SE corpus will be heard as reporting one.", options: { breakLine: true, paraSpaceAfter: 8 } },
  { text: "So: the schema must be configurable per discipline, every suggestion is shown beside its base rate, and the tool stays keyless, so it needs no institutional library.", options: { italic: true, color: C.accent5 } },
], { x: 6.5, y: 5.0, w: 6.2, h: 1.1, fontSize: 11.5 });

s.addNotes(
  "[11:50 — 13:39]\n\n" +
  "Three biases sit inside this system. I can quantify one, and I will not pretend I can quantify the other two.\n\n" +
  "The first is disciplinary, and it is mine. Four extraction fields come straight from clinical trial reporting conventions. Over the software engineering review, sample size verifies on under eight per cent of records. A tool presenting those fields as universal would under-serve everyone outside medicine invisibly, by returning blanks.\n\n" +
  "The second is language: English only. A limitation of the evaluation, not a design choice.\n\n" +
  "The third is source coverage. OpenAlex under-covers Chinese scholarship, and only about half of indexed papers have a redistributable abstract — which is what my pipeline reads. A paper without one is invisible here. That bias I built, and the honest response is to say so.\n\n" +
  "And culture is not a paragraph I added to satisfy a rubric. It is a variable sitting in my data. These bars are the share of abstracts whose authors state an open gap in their own words: under four per cent in software engineering, fifty-two per cent in one medical review. That is not a difference in how much research remains — it is a difference in what each field considers normal to write.\n\n" +
  "So if a software engineering researcher runs this and it reports no gaps found, the tool has reported a house style, and they will hear a finding. Three adaptations follow: a schema configurable per discipline, every suggestion shown beside that discipline's base rate, and a tool that stays keyless."
);

/* ======================================================= 14. close + what is open */

pres.addSection({ title: "Close" });

s = pres.addSlide({ masterName: "CLOSING_DARK", sectionTitle: "Close" });
s.addText("A decision you can check", { placeholder: "title" });

body(s, "The contribution is not that a model can screen papers. It is that a researcher can audit every decision it made, trace every figure to the run that produced it, and see the question nobody has answered yet — quoted in the words of the authors who asked it.", {
  x: 0.9, y: 1.78, w: 11.5, h: 0.95, fontSize: 16, color: C.background2,
});

const closers = [
  ["12,598", "records screened across six reviews, scored review by review and never pooled"],
  ["5,909", "unverifiable claims withheld — 12 fabricated, the rest my own prompt echoed back"],
  ["USD 0.13", "for the whole three-model comparison; every figure traces to a stored run"],
];
closers.forEach((c, i) => {
  const x = 0.9 + i * 3.95;
  card(s, { x: x, y: 2.85, w: 3.6, h: 1.75, dark: true });
  s.addText(c[0], { x: x + 0.3, y: 3.02, w: 3.0, h: 0.68, fontSize: 34, bold: true, color: C.accent6, fontFace: "Cambria", isTextBox: true, margin: 0, valign: "middle" });
  s.addText(c[1], { x: x + 0.3, y: 3.76, w: 3.0, h: 0.72, fontSize: 11, color: C.background2, isTextBox: true, margin: 0, valign: "top" });
});

card(s, { x: 0.9, y: 4.8, w: 11.5, h: 1.3, dark: true });
heading(s, "Still open — and not claimed", { x: 1.2, y: 4.98, w: 6.0, h: 0.35, fontSize: 14, color: C.background1 });
body(s, [
  { text: "The usability exit test, which needs ethics approval and a participant  ·  a manual pass over the 5,909 failure classifications  ·  precision for gaps read from full text  ·  tighter recall intervals.", options: { breakLine: true } },
  { text: "And ASReview still beats every retrieval strategy here, because it retrains on true labels as the reviewer works — the case for adaptive re-ranking.", options: { italic: true } },
], { x: 1.2, y: 5.38, w: 10.9, h: 0.65, fontSize: 11.5, color: C.background2 });

s.addText("github.com/KavinduPehesara/Beyond-Retrieval  ·  open licence  ·  101 run directories  ·  572 tests", {
  x: 0.9, y: 6.2, w: 11.5, h: 0.35, fontSize: 12, italic: true, color: C.accent2, isTextBox: true, margin: 0,
});
s.addText("Thank you — questions welcome", {
  x: 0.9, y: 6.6, w: 11.5, h: 0.45, fontSize: 17, bold: true, color: C.background1, isTextBox: true, margin: 0,
});

s.addNotes(
  "[13:39 — 15:01]\n\n" +
  "Four things are still open, and I would rather say them than have them found.\n\n" +
  "The usability exit test needs ethics approval and a participant. Until then the usability claim is withdrawn — not softened, withdrawn. The five thousand nine hundred failure classifications are automatic, and need a manual pass before I call them measured. Full-text extraction stays a demonstration. And the gap recall range supports a direction, not a number.\n\n" +
  "And the comparison that does not flatter me: ASReview beats every retrieval strategy I built, because it retrains on true labels as the reviewer works and mine rank once. That points straight at adaptive re-ranking, and it belongs in the report precisely because it is uncomfortable.\n\n" +
  "So the contribution is not that a model can screen papers. It is that a researcher can check it. Every decision carries the sentence it rests on, or it is withheld. Every figure traces to a run directory with its commit hash. And the question nobody has answered yet gets a first, measured attempt — quoted in the words of the authors who asked it.\n\n" +
  "Thank you. I am happy to take questions."
);

/* ------------------------------------------------------------------ write */

(async () => {
  await pres.writeFile({ fileName: OUT });
  await applyTheme(OUT, THEME);
  console.log("wrote " + OUT);
})();
