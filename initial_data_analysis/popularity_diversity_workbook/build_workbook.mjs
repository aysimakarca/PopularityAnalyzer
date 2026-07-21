import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const root = path.resolve("../..");
const outputDir = path.resolve(".");

function parseCsv(text) {
  const rows = [];
  let row = [];
  let field = "";
  let quoted = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (quoted) {
      if (ch === '"' && text[i + 1] === '"') {
        field += '"';
        i++;
      } else if (ch === '"') {
        quoted = false;
      } else {
        field += ch;
      }
    } else if (ch === '"') {
      quoted = true;
    } else if (ch === ",") {
      row.push(field);
      field = "";
    } else if (ch === "\n") {
      row.push(field.replace(/\r$/, ""));
      rows.push(row);
      row = [];
      field = "";
    } else {
      field += ch;
    }
  }
  if (field.length || row.length) {
    row.push(field.replace(/\r$/, ""));
    rows.push(row);
  }
  const headers = rows.shift();
  return rows
    .filter((values) => values.some((value) => value !== ""))
    .map((values) => Object.fromEntries(headers.map((header, index) => [header, values[index] ?? ""])));
}

const spotifyRows = parseCsv(
  await fs.readFile(path.join(root, "spotify/spotify_dual_popularity_results.csv"), "utf8"),
);
const youtubeRows = parseCsv(
  await fs.readFile(path.join(root, "youtube_music/youtube_dual_popularity_results.csv"), "utf8"),
);
const selectedRows = parseCsv(
  await fs.readFile(path.join(root, "final_rank_based_playlist.csv"), "utf8"),
);

const youtubeById = new Map(youtubeRows.map((row) => [row.candidate_id, row]));
const pool = spotifyRows
  .map((spotify) => ({ spotify, youtube: youtubeById.get(spotify.candidate_id) }))
  .sort((a, b) => a.spotify.candidate_id.localeCompare(b.spotify.candidate_id));

if (pool.length !== 83 || selectedRows.length !== 30 || pool.some((row) => !row.youtube)) {
  throw new Error("Expected 83 joined pool rows and 30 selected rows");
}

function averageRanks(entries, valueGetter) {
  const ordered = entries
    .map((entry, index) => ({ index, value: valueGetter(entry) }))
    .sort((a, b) => a.value - b.value);
  const result = new Array(entries.length);
  let start = 0;
  while (start < ordered.length) {
    let end = start + 1;
    while (end < ordered.length && ordered[end].value === ordered[start].value) end++;
    const averageRank = ((start + 1) + end) / 2;
    for (let index = start; index < end; index++) result[ordered[index].index] = averageRank;
    start = end;
  }
  return result;
}

const spotifyRanks = averageRanks(pool, ({ spotify }) => Number(spotify.spotify_metric_value));
const youtubeRanks = averageRanks(pool, ({ youtube }) => Number(youtube.view_count));

function boundary(maxLower, minUpper) {
  return Math.sqrt((maxLower + 1) * (minUpper + 1)) - 1;
}

function observedRange(rows, valueField, tierField, tier) {
  const values = rows.filter((row) => row[tierField] === tier).map((row) => Number(row[valueField]));
  return { min: Math.min(...values), max: Math.max(...values) };
}

const spLow = observedRange(spotifyRows, "spotify_metric_value", "spotify_magnitude_tier", "Low");
const spMiddle = observedRange(spotifyRows, "spotify_metric_value", "spotify_magnitude_tier", "Middle");
const spHigh = observedRange(spotifyRows, "spotify_metric_value", "spotify_magnitude_tier", "High");
const ytLow = observedRange(youtubeRows, "view_count", "youtube_magnitude_tier", "Low");
const ytMiddle = observedRange(youtubeRows, "view_count", "youtube_magnitude_tier", "Middle");
const ytHigh = observedRange(youtubeRows, "view_count", "youtube_magnitude_tier", "High");

const spBoundary1 = boundary(spLow.max, spMiddle.min);
const spBoundary2 = boundary(spMiddle.max, spHigh.min);
const ytBoundary1 = boundary(ytLow.max, ytMiddle.min);
const ytBoundary2 = boundary(ytMiddle.max, ytHigh.min);

const workbook = Workbook.create();
const poolSheet = workbook.worksheets.add("Pool (83)");
const selectedSheet = workbook.worksheets.add("Selected Playlist (30)");
const trendSheet = workbook.worksheets.add("Trend Comparison");
const actualTrendSheet = workbook.worksheets.add("Actual Value Trends");
poolSheet.showGridLines = false;
selectedSheet.showGridLines = false;
trendSheet.showGridLines = false;
actualTrendSheet.showGridLines = false;

const colors = {
  navy: "#17324D",
  teal: "#0F6B6D",
  tealLight: "#DCEFEF",
  low: "#DDEBF7",
  middle: "#FFF2CC",
  high: "#E2F0D9",
  buffer: "#E7E6E6",
  white: "#FFFFFF",
  text: "#243447",
  line: "#C9D3DC",
  note: "#F3F6F8",
};

const poolHeaders = [
  "Candidate ID",
  "Artist",
  "Song",
  "Country",
  "Release year",
  "Subgenre",
  "Monthly listeners in Spotify",
  "Spotify average rank",
  "Spotify percentile (equation result)",
  "Spotify rank-based cluster",
  "Spotify log10 magnitude",
  "Spotify magnitude cluster",
  "Total views in YouTube",
  "YouTube average rank",
  "YouTube percentile (equation result)",
  "YouTube rank-based cluster",
  "YouTube log10 magnitude",
  "YouTube magnitude cluster",
  "Spotify URL",
  "YouTube URL",
  "Spotify measurement timestamp",
  "YouTube measurement timestamp",
];

poolSheet.getRange("A1:V1").merge();
poolSheet.getRange("A1").values = [["Popularity Evaluation — Full 83-Song Candidate Pool"]];
poolSheet.getRange("A2:V2").merge();
poolSheet.getRange("A2").values = [[
  "Compatibility edition: all derived results are stored as verified values so older Excel versions do not require unsupported functions. Equations remain documented at right.",
]];
poolSheet.getRange("A4:V4").values = [poolHeaders];

const poolValues = pool.map(({ spotify, youtube }, index) => [
  spotify.candidate_id,
  spotify.artist,
  spotify.title,
  spotify.country,
  Number(spotify.expected_year),
  spotify.style,
  Number(spotify.spotify_metric_value),
  spotifyRanks[index],
  Number(spotify.spotify_percentile),
  spotify.spotify_tier,
  Number(spotify.spotify_log10_popularity),
  spotify.spotify_magnitude_tier,
  Number(youtube.view_count),
  youtubeRanks[index],
  Number(youtube.youtube_percentile),
  youtube.youtube_tier,
  Number(youtube.youtube_log10_popularity),
  youtube.youtube_magnitude_tier,
  spotify.spotify_url,
  youtube.youtube_url,
  new Date(spotify.artist_monthly_listeners_captured_at),
  new Date(youtube.captured_at_utc),
]);
poolSheet.getRange("A5:V87").values = poolValues;

poolSheet.getRange("X1:AA1").merge();
poolSheet.getRange("X1").values = [["Calculation assumptions"]];
poolSheet.getRange("X2:Y4").values = [
  ["Candidate count (N)", 83],
  ["Percentile equation", "100 × (average rank − 0.5) / N"],
  ["Magnitude equation", "log10(raw popularity + 1)"],
];
poolSheet.getRange("X5:Z7").values = [
  ["Platform", "Low/Middle boundary", "Middle/High boundary"],
  ["Spotify", spBoundary1, spBoundary2],
  ["YouTube", ytBoundary1, ytBoundary2],
];
poolSheet.getRange("X9:AA9").merge();
poolSheet.getRange("X9").values = [["Rank-based bands"]];
poolSheet.getRange("X10:Y13").values = [
  ["Low", "Percentile ≤ 25"],
  ["Buffer", "25–37.5 and 62.5–75"],
  ["Middle", "37.5–62.5"],
  ["High", "Percentile ≥ 75"],
];

const poolTable = poolSheet.tables.add("A4:V87", true, "CandidatePoolTable");
poolTable.style = "TableStyleMedium2";
poolTable.showFilterButton = true;

const selectedHeaders = [
  "Playlist order",
  "Candidate ID",
  "Artist",
  "Song",
  "Country",
  "Release year",
  "Subgenre",
  "Monthly listeners in Spotify",
  "Spotify average rank",
  "Spotify percentile (equation result)",
  "Spotify rank-based cluster",
  "Spotify log10 magnitude",
  "Spotify magnitude cluster",
  "Total views in YouTube",
  "YouTube average rank",
  "YouTube percentile (equation result)",
  "YouTube rank-based cluster",
  "YouTube log10 magnitude",
  "YouTube magnitude cluster",
  "Cross-platform rank agreement",
  "Spotify URL",
  "YouTube URL",
  "Selection basis",
];

selectedSheet.getRange("A1:W1").merge();
selectedSheet.getRange("A1").values = [["Final Rank-Based 30-Song Research Playlist"]];
selectedSheet.getRange("A2:W2").merge();
selectedSheet.getRange("A2").values = [[
  "Selected from the 83-song pool with 10 Low, 10 Middle, and 10 High songs on each platform. Results are stored as values for legacy Excel compatibility.",
]];
selectedSheet.getRange("A4:W4").values = [selectedHeaders];

const poolDataById = new Map(
  pool.map(({ spotify, youtube }, index) => [
    spotify.candidate_id,
    {
      spotifyListeners: Number(spotify.spotify_metric_value),
      spotifyRank: spotifyRanks[index],
      spotifyPercentile: Number(spotify.spotify_percentile),
      spotifyRankTier: spotify.spotify_tier,
      spotifyLog: Number(spotify.spotify_log10_popularity),
      spotifyMagnitudeTier: spotify.spotify_magnitude_tier,
      youtubeViews: Number(youtube.view_count),
      youtubeRank: youtubeRanks[index],
      youtubePercentile: Number(youtube.youtube_percentile),
      youtubeRankTier: youtube.youtube_tier,
      youtubeLog: Number(youtube.youtube_log10_popularity),
      youtubeMagnitudeTier: youtube.youtube_magnitude_tier,
    },
  ]),
);
const selectedValues = selectedRows.map((row, index) => [
  index + 1,
  row.candidate_id,
  row.artist,
  row.title,
  row.country,
  Number(row.expected_year),
  row.style,
  poolDataById.get(row.candidate_id).spotifyListeners,
  poolDataById.get(row.candidate_id).spotifyRank,
  poolDataById.get(row.candidate_id).spotifyPercentile,
  poolDataById.get(row.candidate_id).spotifyRankTier,
  poolDataById.get(row.candidate_id).spotifyLog,
  poolDataById.get(row.candidate_id).spotifyMagnitudeTier,
  poolDataById.get(row.candidate_id).youtubeViews,
  poolDataById.get(row.candidate_id).youtubeRank,
  poolDataById.get(row.candidate_id).youtubePercentile,
  poolDataById.get(row.candidate_id).youtubeRankTier,
  poolDataById.get(row.candidate_id).youtubeLog,
  poolDataById.get(row.candidate_id).youtubeMagnitudeTier,
  poolDataById.get(row.candidate_id).spotifyRankTier === poolDataById.get(row.candidate_id).youtubeRankTier
    ? "Same tier"
    : "Adjacent tier",
  row.spotify_url,
  row.youtube_url,
  "Rank-based optimized selection",
]);
selectedSheet.getRange("A5:W34").values = selectedValues;

const selectedTable = selectedSheet.tables.add("A4:W34", true, "SelectedPlaylistTable");
selectedTable.style = "TableStyleMedium2";
selectedTable.showFilterButton = true;

selectedSheet.getRange("Y1:AA1").merge();
selectedSheet.getRange("Y1").values = [["Diversity summary"]];
selectedSheet.getRange("Y3:AA6").values = [
  ["Rank tier", "Spotify songs", "YouTube songs"],
  ["Low", selectedRows.filter((row) => row.spotify_selected_tier === "Low").length, selectedRows.filter((row) => row.youtube_selected_tier === "Low").length],
  ["Middle", selectedRows.filter((row) => row.spotify_selected_tier === "Middle").length, selectedRows.filter((row) => row.youtube_selected_tier === "Middle").length],
  ["High", selectedRows.filter((row) => row.spotify_selected_tier === "High").length, selectedRows.filter((row) => row.youtube_selected_tier === "High").length],
];

const selectedData = selectedRows.map((row) => poolDataById.get(row.candidate_id));
const countTier = (field, tier) => selectedData.filter((row) => row[field] === tier).length;

function quantileProfile(values, transform = (value) => Math.log10(value + 1)) {
  const sortedValues = values.map(transform).sort((a, b) => a - b);
  return Array.from({ length: 101 }, (_, percentile) => {
    const position = (percentile / 100) * (sortedValues.length - 1);
    const lower = Math.floor(position);
    const upper = Math.ceil(position);
    const fraction = position - lower;
    return sortedValues[lower] + (sortedValues[upper] - sortedValues[lower]) * fraction;
  });
}

const poolSpotifyValues = pool.map(({ spotify }) => Number(spotify.spotify_metric_value));
const selectedSpotifyValues = selectedData.map((row) => row.spotifyListeners);
const poolYoutubeValues = pool.map(({ youtube }) => Number(youtube.view_count));
const selectedYoutubeValues = selectedData.map((row) => row.youtubeViews);
const poolSpotifyProfile = quantileProfile(poolSpotifyValues);
const selectedSpotifyProfile = quantileProfile(selectedSpotifyValues);
const poolYoutubeProfile = quantileProfile(poolYoutubeValues);
const selectedYoutubeProfile = quantileProfile(selectedYoutubeValues);
const poolSpotifyActualProfile = quantileProfile(poolSpotifyValues, (value) => value);
const selectedSpotifyActualProfile = quantileProfile(selectedSpotifyValues, (value) => value);
const poolYoutubeActualProfile = quantileProfile(poolYoutubeValues, (value) => value);
const selectedYoutubeActualProfile = quantileProfile(selectedYoutubeValues, (value) => value);

trendSheet.getRange("A1:P1").merge();
trendSheet.getRange("A1").values = [["Popularity Trend Comparison — Pool vs Selected Playlist"]];
trendSheet.getRange("A2:P2").merge();
trendSheet.getRange("A2").values = [[
  "Method: sort songs from least to most popular, normalize position to percentiles (0–100), and compare log10(popularity + 1) curves. Similar curve shape indicates that the 30-song selection preserves the pool's overall popularity trend qualitatively.",
]];
trendSheet.getRange("A4:E4").values = [[
  "Normalized sorted percentile",
  "Spotify pool log10(monthly listeners + 1)",
  "Spotify selected log10(monthly listeners + 1)",
  "YouTube pool log10(total views + 1)",
  "YouTube selected log10(total views + 1)",
]];
trendSheet.getRange("A5:E105").values = Array.from({ length: 101 }, (_, index) => [
  index,
  poolSpotifyProfile[index],
  selectedSpotifyProfile[index],
  poolYoutubeProfile[index],
  selectedYoutubeProfile[index],
]);

const spotifyTrendChart = trendSheet.charts.add("line", {
  chartType: "line",
  title: "Spotify popularity trend: pool vs selected playlist",
  hasLegend: true,
});
const spotifyPoolSeries = spotifyTrendChart.series.add("83-song pool");
spotifyPoolSeries.categoryFormula = "'Trend Comparison'!$A$5:$A$105";
spotifyPoolSeries.formula = "'Trend Comparison'!$B$5:$B$105";
spotifyPoolSeries.fill = { type: "none" };
spotifyPoolSeries.line = { fill: colors.navy, style: "solid", width: 1.25 };
const spotifySelectedSeries = spotifyTrendChart.series.add("30-song selection");
spotifySelectedSeries.categoryFormula = "'Trend Comparison'!$A$5:$A$105";
spotifySelectedSeries.formula = "'Trend Comparison'!$C$5:$C$105";
spotifySelectedSeries.fill = { type: "none" };
spotifySelectedSeries.line = { fill: "#E07A24", style: "solid", width: 1.25 };
spotifyTrendChart.title = "Spotify popularity trend: pool vs selected playlist";
spotifyTrendChart.hasLegend = true;
spotifyTrendChart.xAxis = { axisType: "textAxis", tickLabelInterval: 10, numberFormatCode: "0" };
spotifyTrendChart.yAxis = { numberFormatCode: "0.0", min: 2, max: 8 };
spotifyTrendChart.xAxis.title.text = "Normalized sorted percentile (least to most popular)";
spotifyTrendChart.yAxis.title.text = "log10(monthly listeners + 1)";
spotifyTrendChart.setPosition("G4", "P20");

const youtubeTrendChart = trendSheet.charts.add("line", {
  chartType: "line",
  title: "YouTube popularity trend: pool vs selected playlist",
  hasLegend: true,
});
const youtubePoolSeries = youtubeTrendChart.series.add("83-song pool");
youtubePoolSeries.categoryFormula = "'Trend Comparison'!$A$5:$A$105";
youtubePoolSeries.formula = "'Trend Comparison'!$D$5:$D$105";
youtubePoolSeries.fill = { type: "none" };
youtubePoolSeries.line = { fill: colors.navy, style: "solid", width: 1.25 };
const youtubeSelectedSeries = youtubeTrendChart.series.add("30-song selection");
youtubeSelectedSeries.categoryFormula = "'Trend Comparison'!$A$5:$A$105";
youtubeSelectedSeries.formula = "'Trend Comparison'!$E$5:$E$105";
youtubeSelectedSeries.fill = { type: "none" };
youtubeSelectedSeries.line = { fill: "#E07A24", style: "solid", width: 1.25 };
youtubeTrendChart.title = "YouTube popularity trend: pool vs selected playlist";
youtubeTrendChart.hasLegend = true;
youtubeTrendChart.xAxis = { axisType: "textAxis", tickLabelInterval: 10, numberFormatCode: "0" };
youtubeTrendChart.yAxis = { numberFormatCode: "0.0", min: 2, max: 9 };
youtubeTrendChart.xAxis.title.text = "Normalized sorted percentile (least to most popular)";
youtubeTrendChart.yAxis.title.text = "log10(total views + 1)";
youtubeTrendChart.setPosition("G22", "P38");

trendSheet.getRange("G40:P40").merge();
trendSheet.getRange("G40").values = [["Qualitative reading"]];
trendSheet.getRange("G41:P41").merge();
trendSheet.getRange("G41").values = [[
  "Spotify: the curves have the same broad increasing shape and converge at the upper endpoint; the selected curve is lower in part of the lower-middle range and slightly higher through part of the upper-middle range.",
]];
trendSheet.getRange("G42:P42").merge();
trendSheet.getRange("G42").values = [[
  `YouTube: the curves track closely through most percentiles, but the selection's upper tail ends at ${Math.max(...selectedData.map((row) => row.youtubeViews)).toLocaleString("en-US")} views versus ${Math.max(...pool.map(({ youtube }) => Number(youtube.view_count))).toLocaleString("en-US")} in the pool.`,
]];
trendSheet.getRange("G43:P43").merge();
trendSheet.getRange("G43").values = [[
  "Assessment is visual rather than based on a goodness-of-fit statistic. If matching the single extreme YouTube outlier is required, the playlist selection should be revised.",
]];

actualTrendSheet.getRange("A1:P1").merge();
actualTrendSheet.getRange("A1").values = [["Actual Popularity Values — Pool vs Selected Playlist"]];
actualTrendSheet.getRange("A2:P2").merge();
actualTrendSheet.getRange("A2").values = [[
  "These charts use untransformed monthly listeners and total views. Each set is sorted independently and linearly interpolated onto a shared 0–100% percentile grid only to align the 83-song and 30-song curves; extreme songs therefore compress most lower values near the baseline.",
]];
actualTrendSheet.getRange("A4:E4").values = [[
  "Normalized sorted percentile",
  "Spotify pool monthly listeners",
  "Spotify selected monthly listeners",
  "YouTube pool total views",
  "YouTube selected total views",
]];
actualTrendSheet.getRange("A5:E105").values = Array.from({ length: 101 }, (_, index) => [
  index,
  poolSpotifyActualProfile[index],
  selectedSpotifyActualProfile[index],
  poolYoutubeActualProfile[index],
  selectedYoutubeActualProfile[index],
]);

function addThinLineSeries(chart, name, categoryFormula, valueFormula, color) {
  const series = chart.series.add(name);
  series.categoryFormula = categoryFormula;
  series.formula = valueFormula;
  series.fill = { type: "none" };
  series.line = { fill: color, style: "solid", width: 1.25 };
  return series;
}

const spotifyActualChart = actualTrendSheet.charts.add("line", {
  chartType: "line",
  title: "Spotify actual monthly listeners: pool vs selected playlist",
  hasLegend: true,
});
addThinLineSeries(spotifyActualChart, "83-song pool", "'Actual Value Trends'!$A$5:$A$105", "'Actual Value Trends'!$B$5:$B$105", colors.navy);
addThinLineSeries(spotifyActualChart, "30-song selection", "'Actual Value Trends'!$A$5:$A$105", "'Actual Value Trends'!$C$5:$C$105", "#E07A24");
spotifyActualChart.title = "Spotify actual monthly listeners: pool vs selected playlist";
spotifyActualChart.hasLegend = true;
spotifyActualChart.xAxis = { axisType: "textAxis", tickLabelInterval: 10, numberFormatCode: "0" };
spotifyActualChart.yAxis = { numberFormatCode: "#,##0", min: 0 };
spotifyActualChart.xAxis.title.text = "Normalized sorted percentile (least to most popular)";
spotifyActualChart.yAxis.title.text = "Monthly listeners";
spotifyActualChart.setPosition("G4", "P20");

const youtubeActualChart = actualTrendSheet.charts.add("line", {
  chartType: "line",
  title: "YouTube actual total views: pool vs selected playlist",
  hasLegend: true,
});
addThinLineSeries(youtubeActualChart, "83-song pool", "'Actual Value Trends'!$A$5:$A$105", "'Actual Value Trends'!$D$5:$D$105", colors.navy);
addThinLineSeries(youtubeActualChart, "30-song selection", "'Actual Value Trends'!$A$5:$A$105", "'Actual Value Trends'!$E$5:$E$105", "#E07A24");
youtubeActualChart.title = "YouTube actual total views: pool vs selected playlist";
youtubeActualChart.hasLegend = true;
youtubeActualChart.xAxis = { axisType: "textAxis", tickLabelInterval: 10, numberFormatCode: "0" };
youtubeActualChart.yAxis = { numberFormatCode: "#,##0", min: 0 };
youtubeActualChart.xAxis.title.text = "Normalized sorted percentile (least to most popular)";
youtubeActualChart.yAxis.title.text = "Total views";
youtubeActualChart.setPosition("G22", "P38");

actualTrendSheet.getRange("G40:P40").merge();
actualTrendSheet.getRange("G40").values = [["How to read the actual-value charts"]];
actualTrendSheet.getRange("G41:P41").merge();
actualTrendSheet.getRange("G41").values = [[
  "The linear scale preserves the true magnitude differences. It is less useful for comparing the low and middle ranges because a few highly popular songs dominate the vertical axis.",
]];
actualTrendSheet.getRange("G42:P42").merge();
actualTrendSheet.getRange("G42").values = [[
  "Use these charts to assess absolute tail coverage, and the log10 charts to compare the distribution shape across the full popularity range.",
]];

selectedSheet.getRange("Y8:AA11").values = [
  ["Magnitude cluster", "Spotify songs", "YouTube songs"],
  ["Low", countTier("spotifyMagnitudeTier", "Low"), countTier("youtubeMagnitudeTier", "Low")],
  ["Middle", countTier("spotifyMagnitudeTier", "Middle"), countTier("youtubeMagnitudeTier", "Middle")],
  ["High", countTier("spotifyMagnitudeTier", "High"), countTier("youtubeMagnitudeTier", "High")],
];

function median(values) {
  const ordered = [...values].sort((a, b) => a - b);
  const middle = Math.floor(ordered.length / 2);
  return ordered.length % 2 ? ordered[middle] : (ordered[middle - 1] + ordered[middle]) / 2;
}

const selectedSpotify = selectedData.map((row) => row.spotifyListeners);
const selectedYoutube = selectedData.map((row) => row.youtubeViews);
const spotifyMin = Math.min(...selectedSpotify);
const youtubeMin = Math.min(...selectedYoutube);
const spotifyMax = Math.max(...selectedSpotify);
const youtubeMax = Math.max(...selectedYoutube);

selectedSheet.getRange("Y13:AA17").values = [
  ["Raw-count spread", "Spotify", "YouTube"],
  ["Minimum", spotifyMin, youtubeMin],
  ["Median", median(selectedSpotify), median(selectedYoutube)],
  ["Maximum", spotifyMax, youtubeMax],
  ["Maximum / minimum", spotifyMax / spotifyMin, youtubeMax / youtubeMin],
];

const scatter = selectedSheet.charts.add("scatter", {
  chartType: "scatter",
  title: "Selected songs span several orders of magnitude",
  hasLegend: false,
});
const scatterSeries = scatter.series.add("Selected songs");
scatterSeries.categoryFormula = "'Selected Playlist (30)'!$L$5:$L$34";
scatterSeries.formula = "'Selected Playlist (30)'!$R$5:$R$34";
scatterSeries.fill = colors.teal;
scatter.title = "Spotify vs YouTube popularity (log10 scale)";
scatter.hasLegend = false;
scatter.xAxis = { numberFormatCode: "0.0" };
scatter.yAxis = { numberFormatCode: "0.0" };
scatter.xAxis.title.text = "Spotify log10(monthly listeners + 1)";
scatter.yAxis.title.text = "YouTube log10(total views + 1)";
scatter.setPosition("Y19", "AG36");

function applyTierFormatting(sheet, rangeAddress) {
  const range = sheet.getRange(rangeAddress);
  range.conditionalFormats.add("containsText", { text: "Low", format: { fill: colors.low } });
  range.conditionalFormats.add("containsText", { text: "Middle", format: { fill: colors.middle } });
  range.conditionalFormats.add("containsText", { text: "High", format: { fill: colors.high } });
  range.conditionalFormats.add("containsText", { text: "Buffer", format: { fill: colors.buffer } });
}

function styleTitleAndNote(sheet, titleRange, noteRange) {
  sheet.getRange(titleRange).format = {
    fill: colors.navy,
    font: { bold: true, color: colors.white, size: 16 },
    verticalAlignment: "center",
  };
  sheet.getRange(titleRange).format.rowHeight = 30;
  sheet.getRange(noteRange).format = {
    fill: colors.note,
    font: { color: colors.text, italic: true, size: 10 },
    wrapText: true,
    verticalAlignment: "center",
  };
  sheet.getRange(noteRange).format.rowHeight = 32;
}

styleTitleAndNote(poolSheet, "A1:V1", "A2:V2");
styleTitleAndNote(selectedSheet, "A1:W1", "A2:W2");
styleTitleAndNote(trendSheet, "A1:P1", "A2:P2");
styleTitleAndNote(actualTrendSheet, "A1:P1", "A2:P2");

for (const [sheet, header] of [
  [poolSheet, "A4:V4"],
  [selectedSheet, "A4:W4"],
]) {
  sheet.getRange(header).format = {
    fill: colors.teal,
    font: { bold: true, color: colors.white, size: 10 },
    wrapText: true,
    horizontalAlignment: "center",
    verticalAlignment: "center",
    borders: { preset: "outside", style: "thin", color: colors.line },
  };
  sheet.getRange(header).format.rowHeight = 44;
}

poolSheet.getRange("X1:AA1").format = { fill: colors.navy, font: { bold: true, color: colors.white } };
poolSheet.getRange("X5:Z5").format = { fill: colors.teal, font: { bold: true, color: colors.white }, wrapText: true };
poolSheet.getRange("X9:AA9").format = { fill: colors.navy, font: { bold: true, color: colors.white } };
poolSheet.getRange("X2:Z13").format.borders = { preset: "outside", style: "thin", color: colors.line };
poolSheet.getRange("Y6:Z7").format.numberFormat = "#,##0";

selectedSheet.getRange("Y1:AA1").format = { fill: colors.navy, font: { bold: true, color: colors.white } };
for (const address of ["Y3:AA3", "Y8:AA8", "Y13:AA13"]) {
  selectedSheet.getRange(address).format = { fill: colors.teal, font: { bold: true, color: colors.white }, wrapText: true };
}
for (const address of ["Y3:AA6", "Y8:AA11", "Y13:AA17"]) {
  selectedSheet.getRange(address).format.borders = { preset: "outside", style: "thin", color: colors.line };
}

applyTierFormatting(poolSheet, "J5:J87");
applyTierFormatting(poolSheet, "L5:L87");
applyTierFormatting(poolSheet, "P5:P87");
applyTierFormatting(poolSheet, "R5:R87");
applyTierFormatting(selectedSheet, "K5:K34");
applyTierFormatting(selectedSheet, "M5:M34");
applyTierFormatting(selectedSheet, "Q5:Q34");
applyTierFormatting(selectedSheet, "S5:S34");
applyTierFormatting(selectedSheet, "Y4:Y6");
applyTierFormatting(selectedSheet, "Y9:Y11");

poolSheet.getRange("G5:G87").format.numberFormat = "#,##0";
poolSheet.getRange("H5:H87").format.numberFormat = "0.00";
poolSheet.getRange("I5:I87").format.numberFormat = "0.00";
poolSheet.getRange("K5:K87").format.numberFormat = "0.000";
poolSheet.getRange("M5:M87").format.numberFormat = "#,##0";
poolSheet.getRange("N5:N87").format.numberFormat = "0.00";
poolSheet.getRange("O5:O87").format.numberFormat = "0.00";
poolSheet.getRange("Q5:Q87").format.numberFormat = "0.000";
poolSheet.getRange("U5:V87").format.numberFormat = "yyyy-mm-dd hh:mm";
poolSheet.getRange("S5:T87").format.font = { color: "#0563C1" };

selectedSheet.getRange("H5:H34").format.numberFormat = "#,##0";
selectedSheet.getRange("I5:I34").format.numberFormat = "0.00";
selectedSheet.getRange("J5:J34").format.numberFormat = "0.00";
selectedSheet.getRange("L5:L34").format.numberFormat = "0.000";
selectedSheet.getRange("N5:N34").format.numberFormat = "#,##0";
selectedSheet.getRange("O5:O34").format.numberFormat = "0.00";
selectedSheet.getRange("P5:P34").format.numberFormat = "0.00";
selectedSheet.getRange("R5:R34").format.numberFormat = "0.000";
selectedSheet.getRange("U5:V34").format.font = { color: "#0563C1" };
selectedSheet.getRange("Z14:AA16").format.numberFormat = "#,##0";
selectedSheet.getRange("Z17:AA17").format.numberFormat = "#,##0.0x";

trendSheet.getRange("A4:E4").format = {
  fill: colors.teal,
  font: { bold: true, color: colors.white, size: 10 },
  wrapText: true,
  horizontalAlignment: "center",
  verticalAlignment: "center",
};
trendSheet.getRange("A4:E4").format.rowHeight = 45;
trendSheet.getRange("A5:A105").format.numberFormat = "0";
trendSheet.getRange("B5:E105").format.numberFormat = "0.000";
trendSheet.getRange("A4:E105").format.borders = {
  insideHorizontal: { style: "thin", color: "#E4E9ED" },
  bottom: { style: "thin", color: colors.line },
};
trendSheet.getRange("A:A").format.columnWidthPx = 120;
trendSheet.getRange("B:E").format.columnWidthPx = 175;
trendSheet.getRange("F:F").format.columnWidthPx = 24;
trendSheet.getRange("G40:P40").format = { fill: colors.navy, font: { bold: true, color: colors.white } };
trendSheet.getRange("G41:P43").format = {
  fill: colors.note,
  font: { color: colors.text, size: 10 },
  wrapText: true,
  verticalAlignment: "center",
};
trendSheet.getRange("G41:P43").format.rowHeight = 34;
trendSheet.freezePanes.freezeRows(4);

actualTrendSheet.getRange("A4:E4").format = {
  fill: colors.teal,
  font: { bold: true, color: colors.white, size: 10 },
  wrapText: true,
  horizontalAlignment: "center",
  verticalAlignment: "center",
};
actualTrendSheet.getRange("A4:E4").format.rowHeight = 45;
actualTrendSheet.getRange("A5:A105").format.numberFormat = "0";
actualTrendSheet.getRange("B5:E105").format.numberFormat = "#,##0";
actualTrendSheet.getRange("A4:E105").format.borders = {
  insideHorizontal: { style: "thin", color: "#E4E9ED" },
  bottom: { style: "thin", color: colors.line },
};
actualTrendSheet.getRange("A:A").format.columnWidthPx = 120;
actualTrendSheet.getRange("B:E").format.columnWidthPx = 175;
actualTrendSheet.getRange("F:F").format.columnWidthPx = 24;
actualTrendSheet.getRange("G40:P40").format = { fill: colors.navy, font: { bold: true, color: colors.white } };
actualTrendSheet.getRange("G41:P42").format = {
  fill: colors.note,
  font: { color: colors.text, size: 10 },
  wrapText: true,
  verticalAlignment: "center",
};
actualTrendSheet.getRange("G41:P42").format.rowHeight = 34;
actualTrendSheet.freezePanes.freezeRows(4);

poolSheet.freezePanes.freezeRows(4);
poolSheet.freezePanes.freezeColumns(3);
selectedSheet.freezePanes.freezeRows(4);
selectedSheet.freezePanes.freezeColumns(4);

const poolWidths = [70, 145, 210, 105, 80, 95, 135, 95, 130, 105, 105, 105, 125, 95, 130, 105, 105, 105, 210, 210, 135, 135];
poolWidths.forEach((width, index) => {
  poolSheet.getRangeByIndexes(0, index, 87, 1).format.columnWidthPx = width;
});
poolSheet.getRange("X:X").format.columnWidthPx = 175;
poolSheet.getRange("Y:Z").format.columnWidthPx = 135;
poolSheet.getRange("AA:AA").format.columnWidthPx = 20;

const selectedWidths = [70, 80, 145, 210, 105, 80, 95, 135, 95, 130, 105, 105, 105, 125, 95, 130, 105, 105, 105, 115, 210, 210, 150];
selectedWidths.forEach((width, index) => {
  selectedSheet.getRangeByIndexes(0, index, 36, 1).format.columnWidthPx = width;
});
selectedSheet.getRange("Y:Y").format.columnWidthPx = 145;
selectedSheet.getRange("Z:AA").format.columnWidthPx = 115;

poolSheet.getRange("A5:V87").format.font = { size: 10, color: colors.text };
selectedSheet.getRange("A5:W34").format.font = { size: 10, color: colors.text };
poolSheet.getRange("B5:F87").format.wrapText = false;
selectedSheet.getRange("C5:G34").format.wrapText = false;

const poolCheck = await workbook.inspect({
  kind: "table",
  range: "'Pool (83)'!A1:R12",
  include: "values,formulas",
  tableMaxRows: 12,
  tableMaxCols: 18,
});
console.log(poolCheck.ndjson);
const selectedCheck = await workbook.inspect({
  kind: "table",
  range: "'Selected Playlist (30)'!A1:AA17",
  include: "values,formulas",
  tableMaxRows: 17,
  tableMaxCols: 27,
});
console.log(selectedCheck.ndjson);
const trendCheck = await workbook.inspect({
  kind: "table",
  range: "'Trend Comparison'!A1:E12",
  include: "values,formulas",
  tableMaxRows: 12,
  tableMaxCols: 5,
});
console.log(trendCheck.ndjson);
const actualTrendCheck = await workbook.inspect({
  kind: "table",
  range: "'Actual Value Trends'!A1:E12",
  include: "values,formulas",
  tableMaxRows: 12,
  tableMaxCols: 5,
});
console.log(actualTrendCheck.ndjson);
const errorCheck = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 300 },
  summary: "final formula error scan",
});
console.log(errorCheck.ndjson);

const poolPreview = await workbook.render({ sheetName: "Pool (83)", range: "A1:AA22", scale: 1, format: "png" });
await fs.writeFile(path.join(outputDir, "pool_preview.png"), new Uint8Array(await poolPreview.arrayBuffer()));
const selectedPreview = await workbook.render({ sheetName: "Selected Playlist (30)", range: "A1:AG36", scale: 1, format: "png" });
await fs.writeFile(path.join(outputDir, "selected_preview.png"), new Uint8Array(await selectedPreview.arrayBuffer()));
const trendPreview = await workbook.render({ sheetName: "Trend Comparison", range: "A1:P44", scale: 1, format: "png" });
await fs.writeFile(path.join(outputDir, "trend_preview.png"), new Uint8Array(await trendPreview.arrayBuffer()));
const actualTrendPreview = await workbook.render({ sheetName: "Actual Value Trends", range: "A1:P43", scale: 1, format: "png" });
await fs.writeFile(path.join(outputDir, "actual_trend_preview.png"), new Uint8Array(await actualTrendPreview.arrayBuffer()));

const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(path.join(outputDir, "MCT_popularity_diversity_analysis.xlsx"));
console.log("Workbook exported successfully");
