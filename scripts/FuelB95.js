// Lebanon Fuel B95 · medium Scriptable widget
// No libraries, polling loops, images or background timers.
const FEED = "https://raw.githubusercontent.com/drew-1423/fuelb/main/reports/operations/widget_snapshot.json";
const PERIOD = 3 * 60 * 60 * 1000;
const fm = FileManager.local();
const path = fm.joinPath(fm.libraryDirectory(), "fuelb95-widget.json");
const now = Date.now();

const isPrice = n => Number.isSafeInteger(n) && n > 0;
const valid = x => x?.v === 1 && typeof x.at === "string" &&
  (x.c === null || isPrice(x.c)) &&
  (x.p === null || isPrice(x.p)) &&
  (x.c !== null || x.p === null);

let data = null;
let fetched = 0;
let stale = false;

if (fm.fileExists(path)) {
  try {
    const saved = JSON.parse(fm.readString(path));
    if (valid(saved)) {
      data = saved;
      fetched = fm.modificationDate(path)?.getTime() || 0;
    }
  } catch (_) {}
}

if (!data || now - fetched >= PERIOD) {
  try {
    const request = new Request(FEED);
    request.timeoutInterval = 8;
    const latest = await request.loadJSON();
    if (!valid(latest)) throw Error("Invalid feed");
    data = latest;
    fm.writeString(path, JSON.stringify(data));
    fetched = Date.now();
  } catch (_) {
    stale = true;
  }
}

const widget = new ListWidget();
widget.backgroundColor = new Color("#000000");
widget.setPadding(16, 17, 16, 17);
widget.url = "https://fuelb95.streamlit.app/";
widget.refreshAfterDate = new Date(
  stale ? Date.now() + PERIOD : Math.max(Date.now() + 60000, fetched + PERIOD)
);

function text(value, size, bold = false) {
  const t = widget.addText(value);
  t.font = bold ? Font.boldSystemFont(size) : Font.mediumSystemFont(size);
  t.textColor = Color.white();
  t.lineLimit = 1;
  t.minimumScaleFactor = 0.6;
}

const money = n => n.toLocaleString("en-US");
text("LEBANON FUEL B95", 13, true);
widget.addSpacer(12);

if (data && isPrice(data.c)) {
  text("CURRENT RECORDED PRICE", 10);
  text(money(data.c) + " LBP", 23, true);
  widget.addSpacer(8);
  text("PREDICTED PRICE", 10);

  if (isPrice(data.p)) {
    text(money(data.p) + " LBP", 23, true);
    widget.addSpacer(8);
    const change = data.p - data.c;
    const sign = change > 0 ? "+" : "";
    const arrow = change < 0 ? "▼ " : change > 0 ? "▲ " : "";
    text(`${arrow}${sign}${money(change)} LBP (${sign}${(100 * change / data.c).toFixed(2)}%)`, 13, true);
  } else {
    text("Forecast unavailable", 18, true);
  }
} else {
  text("Price unavailable", 18, true);
}

widget.addSpacer();
const age = Date.now() - Date.parse(data?.at);
text(stale ? "OFFLINE • SAVED DATA" :
  !Number.isFinite(age) || age > 12 * 60 * 60 * 1000
    ? "OLD FORECAST • CHECK WEBSITE"
    : "RESEARCH FORECAST • LBP / 20L", 9);

Script.setWidget(widget);
if (!config.runsInWidget) await widget.presentMedium();
Script.complete();
