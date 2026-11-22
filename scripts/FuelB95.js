// B95: minimum I/O, native medium widget; no polling or dependencies.
const url = "https://raw.githubusercontent.com/drew-1423/fuelb/main/reports/operations/widget_snapshot.json";
const every = 10800000; // 3 hours
const now = Date.now();
const fm = FileManager.local();
const file = fm.joinPath(fm.libraryDirectory(), "fuelb95-array.json");
const price = n => Number.isSafeInteger(n) && n > 0;
const valid = x => Array.isArray(x) && x.length === 3 &&
  (x[0] === null || price(x[0])) &&
  (x[1] === null || price(x[1])) &&
  (x[0] !== null || x[1] === null) &&
  Number.isSafeInteger(x[2]) && x[2] >= 0;

let data = null, checked = 0, offline = false;
if (fm.fileExists(file)) {
  try {
    const saved = JSON.parse(fm.readString(file));
    if (valid(saved)) {
      data = saved;
      checked = fm.modificationDate(file).getTime();
    }
  } catch (_) {}
}
if (!data || now - checked >= every) {
  try {
    const r = new Request(url);
    r.timeoutInterval = 8;
    const fresh = await r.loadJSON();
    if (!valid(fresh)) throw Error("Invalid feed");
    data = fresh;
    fm.writeString(file, JSON.stringify(data));
    checked = now;
  } catch (_) {
    offline = true;
  }
}

const w = new ListWidget();
w.backgroundColor = new Color("#000000");
w.setPadding(16, 17, 16, 17);
w.url = "https://fuelb95.streamlit.app/";
w.refreshAfterDate = new Date(offline ? now + every : Math.max(now + 60000, checked + every));
const white = Color.white();
function line(s, n, bold = false) {
  const t = w.addText(s);
  t.font = bold ? Font.boldSystemFont(n) : Font.mediumSystemFont(n);
  t.textColor = white;
  t.lineLimit = 1;
  t.minimumScaleFactor = 0.6;
}
const money = n => n.toLocaleString("en-US");
line("LEBANON FUEL B95", 13, true);
w.addSpacer(12);
if (data && price(data[0])) {
  line("CURRENT RECORDED PRICE", 10);
  line(money(data[0]) + " LBP", 23, true);
  w.addSpacer(8);
  line("PREDICTED PRICE", 10);
  if (price(data[1])) {
    line(money(data[1]) + " LBP", 23, true);
    w.addSpacer(8);
    const d = data[1] - data[0], sign = d > 0 ? "+" : "";
    line((d < 0 ? "▼ " : d > 0 ? "▲ " : "") +
      sign + money(d) + " LBP (" + sign +
      (100 * d / data[0]).toFixed(2) + "%)", 13, true);
  } else line("Forecast unavailable", 18, true);
} else line("Price unavailable", 18, true);
w.addSpacer();
line(offline ? "OFFLINE • SAVED DATA" :
  !data?.[2] || now - data[2] * 1000 > 43200000
    ? "OLD FORECAST • CHECK WEBSITE"
    : "RESEARCH FORECAST • LBP / 20L", 9);
Script.setWidget(w);
if (!config.runsInWidget) await w.presentMedium();
Script.complete();
