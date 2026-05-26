const state = {
  data: null,
  hospitals: [],
  filtered: [],
};

const elements = {
  datasetYear: document.querySelector("#datasetYear"),
  totalCount: document.querySelector("#totalCount"),
  visibleCount: document.querySelector("#visibleCount"),
  keyword: document.querySelector("#keyword"),
  typeFilter: document.querySelector("#typeFilter"),
  regionFilter: document.querySelector("#regionFilter"),
  prefectureFilter: document.querySelector("#prefectureFilter"),
  participationFilter: document.querySelector("#participationFilter"),
  sortOrder: document.querySelector("#sortOrder"),
  resetFilters: document.querySelector("#resetFilters"),
  downloadCsv: document.querySelector("#downloadCsv"),
  noticeText: document.querySelector("#noticeText"),
  resultsBody: document.querySelector("#resultsBody"),
  emptyState: document.querySelector("#emptyState"),
  sourceList: document.querySelector("#sourceList"),
};

const prefectureOrder = [
  "北海道",
  "青森",
  "岩手",
  "宮城",
  "秋田",
  "山形",
  "福島",
  "茨城",
  "栃木",
  "群馬",
  "埼玉",
  "千葉",
  "東京",
  "神奈川",
  "新潟",
  "富山",
  "石川",
  "福井",
  "山梨",
  "長野",
  "岐阜",
  "静岡",
  "愛知",
  "三重",
  "滋賀",
  "京都",
  "大阪",
  "兵庫",
  "奈良",
  "和歌山",
  "鳥取",
  "島根",
  "岡山",
  "広島",
  "山口",
  "徳島",
  "香川",
  "愛媛",
  "高知",
  "福岡",
  "佐賀",
  "長崎",
  "熊本",
  "大分",
  "宮崎",
  "鹿児島",
  "沖縄",
];

const regionOrder = [
  "北海道",
  "東北",
  "関東",
  "中部",
  "近畿",
  "中国",
  "四国",
  "九州・沖縄",
];

function uniqueValues(items, key, preferredOrder = null) {
  const values = [...new Set(items.map((item) => item[key]))];
  if (!preferredOrder) {
    return values.sort((a, b) => a.localeCompare(b, "ja"));
  }
  return preferredOrder.filter((value) => values.includes(value));
}

function fillSelect(select, values) {
  values.forEach((value) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    select.append(option);
  });
}

function normalize(value) {
  return String(value ?? "").toLowerCase().normalize("NFKC").trim();
}

function getFilters() {
  return {
    keyword: normalize(elements.keyword.value),
    type: elements.typeFilter.value,
    region: elements.regionFilter.value,
    prefecture: elements.prefectureFilter.value,
    participation: elements.participationFilter.value,
    sortOrder: elements.sortOrder.value,
  };
}

function compareByPrefecture(a, b) {
  const prefDiff =
    prefectureOrder.indexOf(a.prefecture) - prefectureOrder.indexOf(b.prefecture);
  if (prefDiff !== 0) return prefDiff;
  if (a.type !== b.type) return a.type.localeCompare(b.type, "ja");
  return a.receptionNumber - b.receptionNumber;
}

function sortHospitals(items, sortOrder) {
  const sorted = [...items];
  if (sortOrder === "name") {
    sorted.sort((a, b) => a.name.localeCompare(b.name, "ja"));
  } else if (sortOrder === "number") {
    sorted.sort((a, b) => a.receptionNumber - b.receptionNumber);
  } else {
    sorted.sort(compareByPrefecture);
  }
  return sorted;
}

function filterHospitals() {
  const filters = getFilters();
  const filtered = state.hospitals.filter((hospital) => {
    const keywordTarget = normalize(
      `${hospital.name} ${hospital.prefecture} ${hospital.region} ${hospital.type} ${hospital.receptionNumber}`,
    );

    return (
      (!filters.keyword || keywordTarget.includes(filters.keyword)) &&
      (!filters.type || hospital.type === filters.type) &&
      (!filters.region || hospital.region === filters.region) &&
      (!filters.prefecture || hospital.prefecture === filters.prefecture) &&
      (!filters.participation ||
        String(hospital.matchingParticipation) === filters.participation)
    );
  });

  state.filtered = sortHospitals(filtered, filters.sortOrder);
  renderResults();
}

function createCell(text, className = "") {
  const cell = document.createElement("td");
  if (className) cell.className = className;
  cell.textContent = text;
  return cell;
}

function createHospitalCell(hospital) {
  const cell = document.createElement("td");
  const link = document.createElement("a");
  link.href = hospital.hospitalUrl;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  link.textContent = hospital.name;
  cell.append(link);
  return cell;
}

function renderResults() {
  const fragment = document.createDocumentFragment();
  state.filtered.forEach((hospital) => {
    const row = document.createElement("tr");
    row.append(
      createCell(hospital.prefecture),
      createHospitalCell(hospital),
      createCell(hospital.type),
      createCell(hospital.region),
    );

    const statusCell = document.createElement("td");
    statusCell.className = "status-cell";
    const status = document.createElement("span");
    status.className = hospital.matchingParticipation
      ? "status-badge"
      : "status-badge is-off";
    status.textContent = hospital.matchingParticipation ? "参加" : "不参加";
    statusCell.append(status);
    row.append(statusCell, createCell(hospital.receptionNumber, "number-cell"));
    fragment.append(row);
  });

  elements.resultsBody.replaceChildren(fragment);
  elements.visibleCount.textContent = state.filtered.length.toLocaleString("ja-JP");
  elements.emptyState.hidden = state.filtered.length > 0;
}

function renderSources() {
  const fragment = document.createDocumentFragment();
  state.data.sources.forEach((source) => {
    const item = document.createElement("li");
    const link = document.createElement("a");
    link.href = source.url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = source.label;
    item.append(link);
    fragment.append(item);
  });
  elements.sourceList.replaceChildren(fragment);
}

function resetPrefectureOptions(prefectures = state.hospitals.map((hospital) => hospital.prefecture)) {
  elements.prefectureFilter.replaceChildren(new Option("すべて", ""));
  fillSelect(
    elements.prefectureFilter,
    prefectureOrder.filter((prefecture) => prefectures.includes(prefecture)),
  );
}

function downloadCsv() {
  const header = [
    "年度",
    "都道府県",
    "地方",
    "病院名",
    "病院区分",
    "マッチング参加",
    "受付番号",
    "病院URL",
    "出典URL",
  ];
  const rows = state.filtered.map((hospital) => [
    hospital.year,
    hospital.prefecture,
    hospital.region,
    hospital.name,
    hospital.type,
    hospital.matchingParticipation ? "参加" : "不参加",
    hospital.receptionNumber,
    hospital.hospitalUrl,
    hospital.sourceUrl,
  ]);
  const csv = [header, ...rows]
    .map((row) =>
      row
        .map((value) => `"${String(value).replaceAll('"', '""')}"`)
        .join(","),
    )
    .join("\n");

  const blob = new Blob([`\ufeff${csv}`], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "jrmp-hospitals-2025.csv";
  link.click();
  URL.revokeObjectURL(url);
}

function resetFilters() {
  elements.keyword.value = "";
  elements.typeFilter.value = "";
  elements.regionFilter.value = "";
  resetPrefectureOptions();
  elements.prefectureFilter.value = "";
  elements.participationFilter.value = "";
  elements.sortOrder.value = "prefecture";
  filterHospitals();
}

function bindEvents() {
  [
    elements.keyword,
    elements.typeFilter,
    elements.regionFilter,
    elements.prefectureFilter,
    elements.participationFilter,
    elements.sortOrder,
  ].forEach((element) => {
    element.addEventListener("input", filterHospitals);
  });

  elements.regionFilter.addEventListener("input", () => {
    const selectedRegion = elements.regionFilter.value;
    const prefectures = selectedRegion
      ? state.hospitals
          .filter((hospital) => hospital.region === selectedRegion)
          .map((hospital) => hospital.prefecture)
      : state.hospitals.map((hospital) => hospital.prefecture);

    resetPrefectureOptions(prefectures);
    filterHospitals();
  });

  elements.resetFilters.addEventListener("click", resetFilters);
  elements.downloadCsv.addEventListener("click", downloadCsv);
}

async function init() {
  try {
    const response = await fetch("data/hospitals.json");
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    state.data = await response.json();
    state.hospitals = state.data.hospitals;
    elements.datasetYear.textContent = `${state.data.datasetYear}年度`;
    elements.totalCount.textContent = state.hospitals.length.toLocaleString("ja-JP");
    elements.noticeText.textContent = `${state.data.notice} データ生成日: ${state.data.generatedAt}`;

    fillSelect(elements.typeFilter, uniqueValues(state.hospitals, "type"));
    fillSelect(elements.regionFilter, uniqueValues(state.hospitals, "region", regionOrder));
    fillSelect(
      elements.prefectureFilter,
      uniqueValues(state.hospitals, "prefecture", prefectureOrder),
    );
    renderSources();
    bindEvents();
    filterHospitals();
  } catch (error) {
    elements.noticeText.textContent =
      "データの読み込みに失敗しました。GitHub Pagesではなくローカルファイルとして開いている場合は、簡易サーバー経由で表示してください。";
    console.error(error);
  }
}

init();
